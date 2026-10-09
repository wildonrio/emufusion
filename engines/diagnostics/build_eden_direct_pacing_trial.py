#!/usr/bin/env python3
"""Compile/link one isolated Switch presentation candidate; no normal outputs edited."""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
TREE = ROOT / 'engines/build/switch-src/eden'
BUILD = TREE / 'build-android'
SDK = Path('/Users/tyleryoung/Library/Android/sdk')
NINJA = SDK / 'cmake/3.22.1/bin/ninja'
LLVM = Path('/Users/tyleryoung/Code/cemu/Cemu-0.5/android-sdk/ndk/28.2.13676358/toolchains/llvm/prebuilt/darwin-x86_64/bin')

INTEGRATION = r'''
#ifdef __ANDROID__
namespace {
struct TrialDirectState {
    Lucent::Trial::DirectPresentPacer pacer;
    PFN_vkGetPastPresentationTimingGOOGLE query{};
};
std::mutex trial_direct_mutex;
std::unordered_map<VkSwapchainKHR, TrialDirectState> trial_direct_states;
void TrialDirectCreate(VkDevice device, VkSwapchainKHR swapchain,
                       PFN_vkGetDeviceProcAddr proc, bool supported) {
    if (!supported || !proc) return;
    const auto refresh = reinterpret_cast<PFN_vkGetRefreshCycleDurationGOOGLE>(
            proc(device, "vkGetRefreshCycleDurationGOOGLE"));
    const auto query = reinterpret_cast<PFN_vkGetPastPresentationTimingGOOGLE>(
            proc(device, "vkGetPastPresentationTimingGOOGLE"));
    VkRefreshCycleDurationGOOGLE cycle{};
    if (!refresh || !query || refresh(device, swapchain, &cycle) != VK_SUCCESS) return;
    std::scoped_lock lock{trial_direct_mutex};
    TrialDirectState state;
    if (!state.pacer.Configure(cycle.refreshDuration)) return;
    state.query = query;
    trial_direct_states.insert_or_assign(swapchain, state);
    LOG_INFO(Render_Vulkan, "Direct pacing TRIAL refreshDurationNs={}", cycle.refreshDuration);
}
void TrialDirectDestroy(VkSwapchainKHR swapchain) {
    std::scoped_lock lock{trial_direct_mutex};
    trial_direct_states.erase(swapchain);
}
uint64_t TrialDirectTarget(VkDevice device, VkSwapchainKHR swapchain,
                           uint32_t id, uint64_t now, int64_t composition_period) {
    std::scoped_lock lock{trial_direct_mutex};
    auto it = trial_direct_states.find(swapchain);
    if (it == trial_direct_states.end()) return 0;
    auto& state = it->second;
    // Fixed bounded storage. VK_INCOMPLETE is valid partial timing delivery;
    // returned timings are consumed only once by the Vulkan implementation.
    std::array<VkPastPresentationTimingGOOGLE, 32> timings{};
    uint32_t count = static_cast<uint32_t>(timings.size());
    const auto result = state.query(device, swapchain, &count, timings.data());
    if (result != VK_SUCCESS && result != VK_INCOMPLETE) {
        trial_direct_states.erase(it);
        return 0;
    }
    count = std::min(count, static_cast<uint32_t>(timings.size()));
    for (uint32_t i = 0; i < count; ++i) {
        const auto& t = timings[i];
        if (t.presentID < id) state.pacer.Feedback(t.presentID, t.actualPresentTime, now);
    }
    const auto target = state.pacer.Schedule(id, now, composition_period);
    if (id == 1 || id % 240 == 0)
        LOG_INFO(Render_Vulkan, "Direct pacing TRIAL id={} targetNs={} refreshNs={:.3f} samples={} resets={} periodNs={} guestClockChanged=false",
                 id, target, state.pacer.RefreshNs(), state.pacer.Samples(), state.pacer.Resets(), composition_period);
    return target;
}
} // namespace
#endif
'''

def replace_once(source, old, new):
    if source.count(old) != 1:
        raise RuntimeError('source context changed: ' + old[:100])
    return source.replace(old, new, 1)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    out = args.output_dir.resolve()
    if out.exists(): parser.error('output already exists')
    subprocess.run(['python3', str(ROOT/'engines/tools/apply_eden_timing_patch.py')], check=True)
    source = TREE/'src/video_core/renderer_vulkan/vk_swapchain.cpp'
    original = source.read_text()
    changed = replace_once(original, '#include <vector>', '#include <vector>\n#include <mutex>\n#include <unordered_map>\n#include "eden_direct_present_pacer.h"')
    changed = replace_once(changed, 'namespace Vulkan {', 'namespace Vulkan {\n' + INTEGRATION)
    changed = replace_once(changed, '    extent = swapchain_ci.imageExtent;', '''#ifdef __ANDROID__
    TrialDirectCreate(*device.GetLogical(), *swapchain,
                      device.GetDispatchLoader().vkGetDeviceProcAddr, device.HasLucentDisplayTiming());
#endif
    extent = swapchain_ci.imageExtent;''')
    changed = replace_once(changed, '    swapchain.reset();', '''#ifdef __ANDROID__
    TrialDirectDestroy(*swapchain);
#endif
    swapchain.reset();''')
    # Off uses existing images on the native surface; no FG source records.
    changed = replace_once(changed, '    if (source_image && Lucent::UsesFgPresentation()) {', '''    if (device.HasLucentDisplayTiming() && !Lucent::UsesFgPresentation()) {
        lucent_present_time.presentID = static_cast<u32>(submission_sequence);
        lucent_present_time.desiredPresentTime = TrialDirectTarget(
                *device.GetLogical(), *swapchain, static_cast<u32>(submission_sequence), now_ns,
                Lucent::g_last_composition_period_ns.load(std::memory_order_relaxed));
        lucent_present_times.sType = VK_STRUCTURE_TYPE_PRESENT_TIMES_INFO_GOOGLE;
        lucent_present_times.swapchainCount = 1;
        lucent_present_times.pTimes = &lucent_present_time;
        present_next = &lucent_present_times;
    }
    if (source_image && Lucent::UsesFgPresentation()) {''')
    out.mkdir(parents=True)
    copy = out/'vk_swapchain.cpp'
    copy.write_text(changed)
    shutil.copyfile(Path(__file__).with_name('eden_direct_present_pacer.h'), out/'eden_direct_present_pacer.h')
    (out/'source-identity.json').write_text(json.dumps({'originalSourceSha256':hashlib.sha256(original.encode()).hexdigest(),
        'trialSourceSha256':hashlib.sha256(changed.encode()).hexdigest()},indent=2))
    # Prove that the normal linked engine still strips to the installed baseline.
    base = BUILD/'src/android/app/src/main/jni/libyuzu-android.so'
    subprocess.run([str(LLVM/'llvm-strip'),'--strip-all','-o',str(out/'baseline.so'),str(base)],check=True)
    baseline_sha = hashlib.sha256((out/'baseline.so').read_bytes()).hexdigest()
    if baseline_sha != '13462144097fa0b11a5ed73e198e68ffe9b9e77ef2678c53dbb6ee5a46d758a9':
        raise RuntimeError('normal engine differs from installed baseline: ' + baseline_sha)
    obj = out/'vk_swapchain.cpp.o'
    subprocess.run(['python3',str(ROOT/'engines/diagnostics/compile_spurs_trace.py'),
        '--commands',str(BUILD/'compile_commands.json'),'--output',str(obj),'--without-trace',
        '--source-suffix','/renderer_vulkan/vk_swapchain.cpp','--source-copy',str(copy)],check=True)
    old = BUILD/'src/video_core/libvideo_core.a'
    archive = out/'libvideo_core.a'
    shutil.copyfile(old,archive)
    members = subprocess.check_output([str(LLVM/'llvm-ar'),'t',str(old)],text=True).splitlines()
    assert members.count(obj.name) == 1
    subprocess.run([str(LLVM/'llvm-ar'),'r',str(archive),str(obj)],check=True)
    subprocess.run([str(LLVM/'llvm-ranlib'),str(archive)],check=True)
    assert subprocess.check_output([str(LLVM/'llvm-ar'),'t',str(archive)],text=True).splitlines() == members
    for member in members:
        actual = subprocess.check_output([str(LLVM/'llvm-ar'),'p',str(archive),member])
        expected = obj.read_bytes() if member == obj.name else subprocess.check_output([str(LLVM/'llvm-ar'),'p',str(old),member])
        assert actual == expected, member
    print('Unchanged archive members:',len(members)-1,flush=True)
    line = subprocess.check_output([str(NINJA),'-t','commands','yuzu-android'],cwd=BUILD,text=True).splitlines()[-1]
    tokens = shlex.split(line)
    assert tokens[:2] == [':','&&'] and tokens[-2:] == ['&&',':']
    tokens = tokens[2:-2]
    assert not any(t in ['&&',';','|','>'] for t in tokens)
    dep = '--dependency-file=src/android/app/src/main/jni/CMakeFiles/yuzu-android.dir/link.d'
    assert tokens.count(dep) == 1
    tokens[tokens.index(dep)] = '--dependency-file=' + str(out/'link.d')
    token = 'src/video_core/libvideo_core.a'
    assert tokens.count(token) == 1
    tokens[tokens.index(token)] = str(archive)
    tokens[tokens.index('-o')+1] = str(out/'libeden.unstripped.so')
    subprocess.run(tokens,cwd=BUILD,check=True)
    final = out/'liblucent_native_adapter_eden.so'
    subprocess.run([str(LLVM/'llvm-strip'),'--strip-all','-o',str(final),str(out/'libeden.unstripped.so')],check=True)
    assert source.read_text() == original
    print('Candidate:',final,'SHA256:',hashlib.sha256(final.read_bytes()).hexdigest(),flush=True)

if __name__ == '__main__': main()
