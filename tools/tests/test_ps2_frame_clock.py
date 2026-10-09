"""Execute the candidate's actual pacing and throttle-switch functions.

This verifies ownership/handoff behavior, not Android performance or audio.
"""
import hashlib
import json
import os
import tarfile
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = None

def function(text, name):
    start = text.index(name)
    opening = text.index('{', start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]

class FrontendClockTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global SOURCE
        lock = json.loads((ROOT/'engines/armsx2-source-lock.json').read_text())
        archive = Path(os.environ.get('ARMSX2_SOURCE_ARCHIVE', str(
            ROOT/'engines/build/sources'/('armsx2-' + lock['core']['commit'] + '.tar.gz'))))
        if not archive.is_file():
            raise unittest.SkipTest('Set ARMSX2_SOURCE_ARCHIVE to the pinned cached archive')
        digest = hashlib.sha256()
        with archive.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        assert digest.hexdigest() == lock['core']['archiveSha256']
        cls.fixture = tempfile.TemporaryDirectory(prefix='ps2-source-clock-')
        cls.addClassCleanup(cls.fixture.cleanup)
        SOURCE = Path(cls.fixture.name)
        paths = {
            'pcsx2-libretro/Main.cpp', 'pcsx2-libretro/CMakeLists.txt',
            'platforms/android/app/src/main/cpp/CMakeLists.txt',
            'pcsx2/VMManager.cpp', 'pcsx2/GS/Renderers/Vulkan/VKLibretro.cpp',
            'pcsx2/GS/Renderers/Vulkan/VKLibretro.h',
            'pcsx2/GS/Renderers/Vulkan/GSDeviceVK.cpp',
            'pcsx2/GS/Renderers/Vulkan/GSDeviceVK.h'}
        with tarfile.open(archive, 'r:gz') as bundle:
            for member in bundle:
                relative = member.name.partition('/')[2]
                if relative in paths:
                    destination = SOURCE/relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(bundle.extractfile(member).read())
        assert all((SOURCE/path).is_file() for path in paths)
        cls.baseline_vk = (SOURCE/'pcsx2/GS/Renderers/Vulkan/VKLibretro.cpp').read_text()
        for patch in lock['patches']:
            path = ROOT/patch['path']
            assert hashlib.sha256(path.read_bytes()).hexdigest() == patch['sha256']
            subprocess.run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(path)],
                           cwd=SOURCE, check=True, capture_output=True)

    def test_descriptor_cache_is_reset_only_after_the_existing_frame_fence(self):
        renderer = (SOURCE/'pcsx2/GS/Renderers/Vulkan/GSDeviceVK.cpp').read_text()
        cache = (SOURCE/'pcsx2/GS/Renderers/Vulkan/FrameDescriptorBatchCache.h').read_text()
        self.assertIn('MAX_FRAME_TEXTURE_SETS = 8192;', renderer)
        self.assertIn('Capacity = 8192;', cache)
        activation = function(renderer, 'void GSDeviceVK::ActivateCommandBuffer')
        self.assertLess(activation.index('WaitForCommandBufferCompletion(index)'),
                        activation.index('vkResetDescriptorPool'))
        self.assertLess(activation.index('vkResetDescriptorPool'),
                        activation.index('resources.descriptor_batches.Reset()'))
        self.assertIn('else\n\t\t\tresources.descriptor_batches.Reset();', activation)
        self.assertNotIn('EMUFUSION_DESCRIPTOR_QA', renderer)
        self.assertNotIn('s_descriptor_qa', renderer)
        self.assertEqual(3, renderer.count('UseInputAttachmentDescriptors()'))

    def test_early_consumer_regression_fails_old_and_passes_patched_source(self):
        for patched, text in ((False, self.baseline_vk), (True,
                (SOURCE/'pcsx2/GS/Renderers/Vulkan/VKLibretro.cpp').read_text())):
            state = text[text.index('static std::mutex s_frame_mutex;'):text.index('\n\tvoid Shutdown()')]
            code = r'''
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <future>
#include <mutex>
using u64 = uint64_t;
constexpr int VK_NULL_HANDLE = 0;
struct Frame {int image = 0;};
''' + state + r'''
int main() {
 using namespace std::chrono_literals;
 SetPacing(true);
 Frame frame;
 auto result = std::async(std::launch::async, [&] {return ConsumeFrame(&frame);});
 bool waited = result.wait_for(10ms) == std::future_status::timeout;
 AbortPacing();
 result.wait();
 return waited ? 0 : 42;
}
'''
            with self.subTest(patched=patched), tempfile.TemporaryDirectory() as temp:
                unit = Path(temp)/'regression.cpp'
                unit.write_text(code)
                binary = Path(temp)/'regression'
                subprocess.run(['clang++','-std=c++17','-pthread',str(unit),'-o',str(binary)],check=True)
                result = subprocess.run([str(binary)],timeout=5)
                self.assertEqual(result.returncode, 0 if patched else 42)

    def test_actual_handoff_and_clock_ownership(self):
        vk = (SOURCE/'pcsx2/GS/Renderers/Vulkan/VKLibretro.cpp').read_text()
        vm = (SOURCE/'pcsx2/VMManager.cpp').read_text()
        state = vk[vk.index('static std::mutex s_frame_mutex;'):vk.index('\n\tvoid Shutdown()')]
        throttle = function(vm, 'void VMManager::Internal::Throttle()')
        # Exercise the exact new early-return path, while representing the
        # unchanged sleep-based limiter with an observable fallback counter.
        prefix = throttle[:throttle.index('\n\tif (s_target_speed')]
        code = r'''
#include <cassert>
#include <atomic>
#include <condition_variable>
#include <cstdint>
#include <future>
#include <mutex>
#include <thread>
#include <chrono>
using u64 = uint64_t;
constexpr int VK_NULL_HANDLE = 0;
namespace VKLibretro {
bool Active = false;
struct Frame { int image = 0; };
''' + state + r'''
}
int resets = 0, pauses = 0, fallbacks = 0;
void ResetFrameLimiter() { ++resets; }
namespace PerformanceMetrics { void AdpfPauseFrameWork() { ++pauses; } }
namespace VMManager::Internal { void Throttle(); }
''' + prefix + r'''
++fallbacks;
}
int main() {
 using namespace std::chrono_literals;
 using namespace VKLibretro;
 SetPacing(true);
 VMManager::Internal::Throttle(); // standalone path must keep its limiter
 assert(fallbacks == 1 && resets == 0);
 Active = true;
 VMManager::Internal::Throttle();
#ifdef ENABLE_VULKAN
 assert(resets == 1 && pauses == 1 && fallbacks == 1);
#else
 assert(resets == 0 && pauses == 0 && fallbacks == 2);
#endif
 AbortPacing();
 assert(!IsPacing());
 VMManager::Internal::Throttle(); // abort/snapshot must restore local pacing
#ifdef ENABLE_VULKAN
 assert(fallbacks == 2);
#else
 assert(fallbacks == 3);
#endif
 SetPacing(true);
 std::atomic<bool> returned{false};
 auto producer = std::async(std::launch::async, [&] {
   PublishFrame(Frame{1}); returned = true;
 });
 Frame frame;
 auto deadline = std::chrono::steady_clock::now() + 2s;
 while (!ConsumeFrame(&frame)) {
   assert(std::chrono::steady_clock::now() < deadline);
   std::this_thread::yield();
 }
 assert(frame.image == 1);
 assert(producer.wait_for(2s) == std::future_status::ready);
 assert(returned && !ConsumeFrame(&frame));
 // Repeated content still has an independent frame handoff, not a skip.
 auto repeat = std::async(std::launch::async, [&] { PublishFrame(Frame{1}); });
 deadline = std::chrono::steady_clock::now() + 2s;
 while (!ConsumeFrame(&frame)) {
   assert(std::chrono::steady_clock::now() < deadline);
   std::this_thread::yield();
 }
 assert(repeat.wait_for(2s) == std::future_status::ready);
 auto pending = std::async(std::launch::async, [&] { PublishFrame(Frame{2}); });
 AbortPacing(); // shutdown must release a producer without consumption
 assert(pending.wait_for(2s) == std::future_status::ready);
 assert(ConsumeFrame(&frame));
 SetPacing(true);
 // A frontend deadline may beat the asynchronous GS by a few milliseconds.
 // Do not treat that as a consumed guest frame and replay stale video/audio.
 auto early = std::async(std::launch::async, [&] { return ConsumeFrame(&frame); });
 assert(early.wait_for(10ms) == std::future_status::timeout);
 auto next = std::async(std::launch::async, [&] { PublishFrame(Frame{3}); });
 assert(early.wait_for(2s) == std::future_status::ready && early.get());
 assert(frame.image == 3 && next.wait_for(2s) == std::future_status::ready);
 auto waiting = std::async(std::launch::async, [&] { return ConsumeFrame(&frame); });
 assert(waiting.wait_for(10ms) == std::future_status::timeout);
 AbortPacing();
 assert(waiting.wait_for(50ms) == std::future_status::ready && !waiting.get());
 SetPacing(true);
 auto wait_begin = std::chrono::steady_clock::now();
 assert(!ConsumeFrame(&frame)); // a failed renderer cannot park UI forever
 auto spent = std::chrono::steady_clock::now() - wait_begin;
 assert(spent >= 50ms && spent < 1s);
 AbortPacing();
}
'''
        with tempfile.TemporaryDirectory(prefix='ps2-clock-test-') as temp:
            src = Path(temp)/'test.cpp'
            src.write_text(code)
            for enabled in (False, True):
                with self.subTest(vulkan=enabled):
                    binary = Path(temp)/('test-vk' if enabled else 'test-no-vk')
                    subprocess.run(['clang++', '-std=c++17', '-pthread',
                                    *(['-DENABLE_VULKAN'] if enabled else []),
                                    str(src), '-o', str(binary)], check=True)
                    subprocess.run([str(binary)], check=True, timeout=10)

    def test_every_guest_vblank_retains_a_handoff(self):
        main = (SOURCE/'pcsx2-libretro/Main.cpp').read_text()
        self.assertIn('SetBoolValue("EmuCore/GS", "SkipDuplicateFrames", false)', main)
        self.assertIn('SetBoolValue("EmuCore/GS", "VsyncEnable", false)', main)
        self.assertNotIn('params.start_unlimited = true', main)

if __name__ == '__main__':
    unittest.main()
