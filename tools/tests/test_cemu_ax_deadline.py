"""Exercise the actual AXOut_update with a deterministic delayed mixer.

These scheduling checks do not substitute for a device audio recording.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class CemuAxDeadlineTest(unittest.TestCase):
    def test_pending_mix_does_not_consume_an_unsubmitted_audio_period(self):
        tree = Path(json.loads((ROOT / "engines/cemu-source-lock.json").read_text())
                    ["core"]["stagedTree"])
        source = Path(os.environ.get("CEMU_AX_TEST_SOURCE",
            str(tree / "src/Cafe/OS/libs/snd_core/ax_out.cpp"))).read_text()
        begin = source.index("\tvoid AXOut_update()")
        end = source.index("{", begin) + 1
        depth = 1
        while depth:
            depth += (source[end] == "{") - (source[end] == "}")
            end += 1
        body = source[begin:end]
        harness = r'''
#include <chrono>
#include <shared_mutex>
#include <memory>
#include <cassert>
#include <cstdio>
using Clock=std::chrono::steady_clock;
Clock::time_point simulated;
auto now_cached() { return simulated; }
struct IAudioAPI { static constexpr int kBlockCount=24;
 bool NeedAdditionalBlocks() { return false; } };
std::shared_mutex g_audioMutex;
std::unique_ptr<IAudioAPI> g_tvAudio, g_padAudio;
constexpr int AX_FRAMES_PER_GROUP=4;
namespace snd_core {
bool initialized=true;
unsigned numQueuedFramesSndGeneric=0, processed=0;
long long due=0,lastDispatch=-1000000,shortestInterval=1000000;
bool isInitialized() {return initialized;}
unsigned getNumProcessedFrames() { return processed; }
void AXOut_updateDevicePlayState(bool) {}
void AXIst_QueueFrame() {
 assert(processed==numQueuedFramesSndGeneric); // Never two outstanding mixes.
 auto us=std::chrono::duration_cast<std::chrono::microseconds>(simulated.time_since_epoch()).count();
 shortestInterval=std::min(shortestInterval,us-lastDispatch);
 lastDispatch=us;
 // One in eight mixes takes 5ms. The average load is easily sustainable.
 due=us+((numQueuedFramesSndGeneric%8)==7?5000:500);
}
''' + body + r'''
}
int main() {
 using namespace snd_core;
 for(long long us=0;us<=2000000;us+=100) {
  simulated=Clock::time_point(std::chrono::microseconds(us));
  if(processed!=numQueuedFramesSndGeneric && us>=due) ++processed;
  AXOut_update();
 }
 std::printf("dispatched=%u expected~667 min_spacing_us=%lld\n",
             numQueuedFramesSndGeneric,shortestInterval);
 assert(shortestInterval>=1700); // Retain existing catch-up CPU fairness.
 assert(numQueuedFramesSndGeneric>=664 && numQueuedFramesSndGeneric<=668);
 // Long disabled interval must not build unbounded catch-up debt.
 initialized=false;
 for(long long us=2000100;us<=5000000;us+=100) {
  simulated=Clock::time_point(std::chrono::microseconds(us));
  if(processed!=numQueuedFramesSndGeneric && us>=due) ++processed;
  AXOut_update();
 }
 unsigned before=numQueuedFramesSndGeneric;
 initialized=true;
 simulated+=std::chrono::microseconds(3000);
 AXOut_update();
 assert(numQueuedFramesSndGeneric<=before+1);
}
'''
        with tempfile.TemporaryDirectory(prefix="cemu-ax-deadline-") as directory:
            path=Path(directory)
            (path / "test.cpp").write_text(harness)
            build=subprocess.run([shutil.which("clang++"), "-std=c++20", "-O1",
                "-fsanitize=address,undefined", str(path / "test.cpp"),
                "-o", str(path / "test")],capture_output=True,text=True,timeout=60)
            self.assertEqual(build.returncode,0,build.stdout+build.stderr)
            run=subprocess.run([str(path / "test")],capture_output=True,text=True,timeout=15)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)


if __name__ == "__main__":
    unittest.main()
