"""Run the real TCL ring wait with a delayed GPU and guest submissions."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]


class CemuRingAudioFairnessTest(unittest.TestCase):
    def test_gpu_backpressure_services_guest_without_stale_ring_space(self):
        tree=Path(json.loads((ROOT / "engines/cemu-source-lock.json").read_text())
                  ["core"]["stagedTree"])
        source=Path(os.environ.get("CEMU_TCL_TEST_SOURCE",
                    str(tree / "src/Cafe/OS/libs/TCL/TCL.cpp"))).read_text()
        begin=source.index("\tvoid TCLWaitForRBSpace(")
        end=source.index("\n\t// this function assumes",begin)
        harness=r'''
#include <atomic>
#include <cassert>
#include <cstdint>
using uint32=uint32_t;
using uint32be=uint32;
constexpr uint32 TCL_RING_BUFFER_SIZE=4096;
std::atomic<uint32> tclRingBufferA_readIndex{0}, tclRingBufferA_writeIndex{0};
struct CPU {unsigned coreInterruptMask=1;} cpu;
CPU* PPCInterpreter_getCurrentInstance(){return &cpu;}
bool locked=false;
bool __OSHasSchedulerLock(){return locked;}
unsigned pauses=0,yields=0;
void _mm_pause(){
 ++pauses;
 assert(pauses<4096); // Original tight wait fails here without yielding.
 if(!cpu.coreInterruptMask || locked) tclRingBufferA_readIndex=100;
}
void PPCCore_switchToScheduler(){
 assert(cpu.coreInterruptMask && !locked);
 ++yields;
 // GPU progresses and another guest producer also submits while switched.
 tclRingBufferA_writeIndex=40;
 tclRingBufferA_readIndex=yields==1?60:100;
}
''' + source[begin:end] + r'''
int main(){
 TCLWaitForRBSpace(32); assert(yields==0 && pauses==0);
 tclRingBufferA_writeIndex=4080;
 TCLWaitForRBSpace(32);
 assert(yields==2); // Must reread the writer after switching, not cache 4080.
 assert(tclRingBufferA_readIndex-tclRingBufferA_writeIndex>=33);
 cpu.coreInterruptMask=0; pauses=yields=0;
 tclRingBufferA_readIndex=0;tclRingBufferA_writeIndex=4080;
 TCLWaitForRBSpace(32);assert(yields==0);
 cpu.coreInterruptMask=1;locked=true;pauses=yields=0;
 tclRingBufferA_readIndex=0;tclRingBufferA_writeIndex=4080;
 TCLWaitForRBSpace(32);assert(yields==0);
}
'''
        with tempfile.TemporaryDirectory(prefix="cemu-ring-fairness-") as directory:
            path=Path(directory)
            (path / "test.cpp").write_text(harness)
            build=subprocess.run([shutil.which("clang++"), "-std=c++20", "-O1",
                "-fsanitize=address,undefined",str(path / "test.cpp"),
                "-o",str(path / "test")],capture_output=True,text=True,timeout=60)
            self.assertEqual(build.returncode,0,build.stdout+build.stderr)
            run=subprocess.run([str(path / "test")],capture_output=True,text=True,timeout=10)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)


if __name__=="__main__":
    unittest.main()
