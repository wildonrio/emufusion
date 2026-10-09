#!/usr/bin/env python3
"""Isolated coordinated guest-clock/audio/native-presentation candidate."""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
from build_eden_direct_pacing_trial import ROOT, TREE, BUILD, LLVM, NINJA, replace_once

DIRECT = ROOT/'engines/build/candidates/eden-direct-feedback-v2-2026-09-09'

def sources(trace_misses=False, dispatch_present=False):
    core_path=TREE/'src/core/core_timing.cpp'
    core=core_path.read_text()
    core=replace_once(core,'#include "common/cpu_features.h"\n#include "common/cpu_features.h"',
                      '#include "common/cpu_features.h"\n#include "eden_coupled_clock_native.h"')
    core=replace_once(core,'event.WaitFor(std::chrono::nanoseconds(wait_time));',
                      'event.WaitFor(std::chrono::nanoseconds(Lucent::Trial::g_coupled_clock.HostWaitNs(wait_time)));')
    core=replace_once(core,'is_multicore ? Common::g_wall_clock.GetCNTPCT()',
                      'is_multicore ? Common::WallClock::NSToCNTPCT(Lucent::Trial::GuestClockNs())')
    core=replace_once(core,'? Common::g_wall_clock.GetGPUTick()',
                      '? Common::WallClock::NSToGPUTick(Lucent::Trial::GuestClockNs())')
    core=replace_once(core,'? Common::g_wall_clock.GetTimeNS()',
                      '? std::chrono::nanoseconds{Lucent::Trial::GuestClockNs()}')
    core=replace_once(core,'? Common::g_wall_clock.GetTimeUS()',
                      '? std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::nanoseconds{Lucent::Trial::GuestClockNs()})')
    adapter_path=TREE/'src/android/app/src/main/jni/lucent_adapter.cpp'
    adapter=adapter_path.read_text()
    adapter=replace_once(adapter,'#include "video_core/renderer_base.h"',
                         '#include "video_core/renderer_base.h"\n#include "eden_coupled_clock_native.h"\n#include "eden_clocked_audio.h"')
    adapter=replace_once(adapter,'    ~LucentSinkStream() override = default;', '''    ~LucentSinkStream() override = default;
    size_t RenderClocked(std::span<s16> output, size_t frames,
                         AudioCore::Sink::OutputConsumption* observation) {
        return clocked_audio.Render(output.data(), frames, Lucent::Trial::g_coupled_clock.Rate(),
            [&](int16_t* destination, size_t count) {
                ProcessAudioOutAndRender(std::span<s16>{destination, count * kLucentChannels}, count, observation);
            });
    }
private:
    Lucent::Trial::ClockedStereoAudio clocked_audio;
public:''')
    adapter=replace_once(adapter,'output->ProcessAudioOutAndRender(pulled, kBlockFrames, &pull);\n                    observation.Pull(kBlockFrames,',
                         'const auto consumed = output->RenderClocked(pulled, kBlockFrames, &pull);\n                    observation.Pull(consumed,')
    adapter=replace_once(adapter,'    Lucent::SetPacedVsyncHz(0.0);','''    Lucent::Trial::g_coupled_clock.Reset();
    Lucent::Trial::g_coupled_clock_allowed.store(Settings::values.use_multi_core.GetValue());
    Lucent::SetPacedVsyncHz(0.0);''')
    adapter=replace_once(adapter,'    Lucent::SetFgPresentation(enabled);','''    Lucent::SetFgPresentation(enabled);
    if (enabled) Lucent::Trial::g_coupled_clock.SetRate(1.0, Lucent::Trial::RawGuestClockNs);''')
    adapter=replace_once(adapter,'    return Lucent::SetPacedVsyncHz(hz);','''    // This trial owns a coherent guest clock; do not also alter the VI period.
    if (hz != 0.0) return false;
    return Lucent::SetPacedVsyncHz(0.0);''')
    adapter=replace_once(adapter,'''    return LUCENT_NATIVE_TIMING_BASE_CLOCK_CORRECTION |
           LUCENT_NATIVE_TIMING_SUBMISSION_TIMESTAMPS;''','''    // Display feedback owns this isolated trial's coordinated clock. The
    // external paced-video setter rejects nonzero requests, so do not advertise
    // that independently callable correction capability to the Java host.
    return LUCENT_NATIVE_TIMING_SUBMISSION_TIMESTAMPS;''')
    adapter=replace_once(adapter,'                // Bracket the clock read.', '''                LOG_INFO(Audio_Sink, "Coupled clock TRIAL guestRate={:.9f} sourceFrames={} outputFrames={}",
                         Lucent::Trial::g_coupled_clock.Rate(), observation.stream_frames, observation.mixed_frames);
                // Bracket the clock read.''')
    producer_path=TREE/'src/core/hle/service/nvnflinger/buffer_queue_producer.cpp'
    producer=replace_once(producer_path.read_text(),'#include "common/cpu_features.h"',
                          '#include "common/cpu_features.h"\n#include "eden_coupled_clock_native.h"')
    producer=replace_once(producer,'Common::g_wall_clock.GetTimeNS().count()', 'Lucent::Trial::GuestClockNs()')
    swap_path=TREE/'src/video_core/renderer_vulkan/vk_swapchain.cpp'
    recorded=json.loads((DIRECT/'source-identity.json').read_text())
    assert hashlib.sha256(swap_path.read_bytes()).hexdigest()==recorded['originalSourceSha256']
    swap=(DIRECT/'vk_swapchain.cpp').read_text()
    assert hashlib.sha256(swap.encode()).hexdigest()==recorded['trialSourceSha256']
    swap=replace_once(swap,'#include "eden_direct_present_pacer.h"',
                      '#include "eden_direct_present_pacer.h"\n#include "eden_coupled_clock_native.h"')
    swap=replace_once(swap,'    if (!supported || !proc) return;',
                      '    Lucent::Trial::ResetDisplayClock();\n    if (!supported || !proc) return;')
    swap=replace_once(swap,'void TrialDirectDestroy(VkSwapchainKHR swapchain) {',
                      'void TrialDirectDestroy(VkSwapchainKHR swapchain) {\n    Lucent::Trial::ResetDisplayClock();')
    swap=replace_once(swap,'    if (result != VK_SUCCESS && result != VK_INCOMPLETE) {',
                      '    if (result != VK_SUCCESS && result != VK_INCOMPLETE) {\n        Lucent::Trial::ResetDisplayClock();')
    swap=replace_once(swap,'    const auto target = state.pacer.Schedule(id, now, composition_period);', '''    if (!state.pacer.HasRecentFeedback(id, now)) {
        Lucent::Trial::ResetDisplayClock();
    } else if (id % 240 == 0) {
        if (Settings::values.use_speed_limit.GetValue() && Settings::SpeedLimit() == 100)
            Lucent::Trial::ObserveDisplayClock(state.pacer.RefreshNs());
        else
            Lucent::Trial::g_coupled_clock.SetRate(1.0, Lucent::Trial::RawGuestClockNs);
    }
    const auto target = state.pacer.Schedule(id, now, composition_period);''')
    swap=replace_once(swap,'guestClockChanged=false','guestClockPolicy=coupled-trial')
    if trace_misses:
        swap=replace_once(swap,'#include "eden_coupled_clock_native.h"',
                          '#include "eden_coupled_clock_native.h"\n#include "eden_missed_present_trace.h"')
        swap=replace_once(swap,'    Lucent::Trial::DirectPresentPacer pacer;',
                          '    Lucent::Trial::DirectPresentPacer pacer;\n    Lucent::Trial::MissedPresentTrace trace;')
        swap=replace_once(swap,'uint32_t id, uint64_t now, int64_t composition_period) {',
                          'uint32_t id, uint64_t now, int64_t composition_period, const lucent_source_composition_v1* source) {')
        swap=replace_once(swap,'    auto& state = it->second;',
                          '    auto& state = it->second;\n    state.trace.Submit(id, now, composition_period, source);')
        swap=replace_once(swap,'        if (t.presentID < id) state.pacer.Feedback(t.presentID, t.actualPresentTime, now);',
                          '        if (t.presentID < id) { state.trace.Feedback(t, now); state.pacer.Feedback(t.presentID, t.actualPresentTime, now); }')
        swap=replace_once(swap,'Lucent::g_last_composition_period_ns.load(std::memory_order_relaxed));\n        lucent_present_times.sType',
                          'Lucent::g_last_composition_period_ns.load(std::memory_order_relaxed), source_image);\n        lucent_present_times.sType')
    result=[(core_path,core,'src/core/libcore.a'),(producer_path,producer,'src/core/libcore.a'),
            (adapter_path,adapter,None),(swap_path,swap,'src/video_core/libvideo_core.a')]
    if dispatch_present:
        present_path=TREE/'src/video_core/renderer_vulkan/vk_present_manager.cpp'
        present=replace_once(present_path.read_text(),'''            frame_cv.notify_one();
        });
    } else {
        scheduler.WaitWorker();''','''            frame_cv.notify_one();
        });
        // The render submission was already dispatched by Flush. Publish this
        // following callback now, in FIFO order, rather than leaving it in a
        // fresh command chunk until unrelated guest work happens to dispatch.
        // No extra GPU submit or wait; render_ready still guards the image copy.
        scheduler.DispatchWork();
    } else {
        scheduler.WaitWorker();''')
        result.append((present_path,present,'src/video_core/libvideo_core.a'))
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--trace-misses',action='store_true')
    p.add_argument('--dispatch-present',action='store_true')
    p.add_argument('--dispatch-only',action='store_true',help='Isolate callback publication on the unchanged native clock/presenter')
    args=p.parse_args();out=args.output_dir.resolve()
    if out.exists():p.error('output exists')
    subprocess.run(['python3',str(ROOT/'engines/tools/apply_eden_timing_patch.py')],check=True)
    if args.dispatch_only and args.trace_misses:p.error('dispatch-only excludes timing instrumentation')
    generated=sources(args.trace_misses,args.dispatch_present or args.dispatch_only)
    if args.dispatch_only:
        generated=[entry for entry in generated if entry[0].name=='vk_present_manager.cpp']
    out.mkdir(parents=True)
    manifest=[];objects=[]
    for name in ([] if args.dispatch_only else ['eden_coupled_clock.h','eden_coupled_clock_native.h','eden_clocked_audio.h','eden_direct_present_pacer.h']):
        shutil.copyfile(Path(__file__).with_name(name),out/name)
    if args.trace_misses:
        shutil.copyfile(Path(__file__).with_name('eden_missed_present_trace.h'),out/'eden_missed_present_trace.h')
    for original,text,archive in generated:
        copy=out/original.name;copy.write_text(text)
        manifest.append({'path':str(original.relative_to(TREE)),
            'originalSha256':hashlib.sha256(original.read_bytes()).hexdigest(),
            'trialSha256':hashlib.sha256(copy.read_bytes()).hexdigest()})
        obj=out/(original.name+'.o');objects.append((original,obj,archive))
        subprocess.run(['python3',str(ROOT/'engines/diagnostics/compile_spurs_trace.py'),
            '--commands',str(BUILD/'compile_commands.json'),'--output',str(obj),'--without-trace',
            '--source-suffix',str(original.relative_to(TREE/'src')),'--source-copy',str(copy)],check=True)
    (out/'source-identity.json').write_text(json.dumps(manifest,indent=2))
    line=subprocess.check_output([str(NINJA),'-t','commands','yuzu-android'],cwd=BUILD,text=True).splitlines()[-1]
    tokens=shlex.split(line)
    assert tokens[:2]==[':','&&'] and tokens[-2:]==['&&',':'];tokens=tokens[2:-2]
    assert not any(t in ['&&',';','|','>'] for t in tokens)
    for token in sorted(set(a for _,_,a in objects if a)):
        old=BUILD/token;new=out/Path(token).name;shutil.copyfile(old,new)
        members=subprocess.check_output([str(LLVM/'llvm-ar'),'t',str(old)],text=True).splitlines()
        replacements={obj.name:obj for _,obj,a in objects if a==token}
        assert all(members.count(n)==1 for n in replacements)
        subprocess.run([str(LLVM/'llvm-ar'),'r',str(new),*[str(v) for v in replacements.values()]],check=True)
        subprocess.run([str(LLVM/'llvm-ranlib'),str(new)],check=True)
        assert subprocess.check_output([str(LLVM/'llvm-ar'),'t',str(new)],text=True).splitlines()==members
        for member in members:
            actual=subprocess.check_output([str(LLVM/'llvm-ar'),'p',str(new),member])
            expected=replacements[member].read_bytes() if member in replacements else subprocess.check_output([str(LLVM/'llvm-ar'),'p',str(old),member])
            assert actual==expected,member
        print(token,'unchanged members:',len(members)-len(replacements),flush=True)
        assert tokens.count(token)==1;tokens[tokens.index(token)]=str(new)
    direct='src/android/app/src/main/jni/CMakeFiles/yuzu-android.dir/lucent_adapter.cpp.o'
    if not args.dispatch_only:
        assert tokens.count(direct)==1;tokens[tokens.index(direct)]=str(out/'lucent_adapter.cpp.o')
    dep='--dependency-file=src/android/app/src/main/jni/CMakeFiles/yuzu-android.dir/link.d'
    assert tokens.count(dep)==1;tokens[tokens.index(dep)]='--dependency-file='+str(out/'link.d')
    tokens[tokens.index('-o')+1]=str(out/'libeden.unstripped.so')
    subprocess.run(tokens,cwd=BUILD,check=True)
    final=out/'liblucent_native_adapter_eden.so'
    subprocess.run([str(LLVM/'llvm-strip'),'--strip-all','-o',str(final),str(out/'libeden.unstripped.so')],check=True)
    for entry in manifest:
        assert hashlib.sha256((TREE/entry['path']).read_bytes()).hexdigest()==entry['originalSha256']
    print('Candidate',final,'SHA256',hashlib.sha256(final.read_bytes()).hexdigest(),flush=True)

if __name__=='__main__':main()
