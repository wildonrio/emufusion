"""Exercise actual Cemu title/pause methods with initialization held at a barrier."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tools.tests.test_native_adapter_retirement_completion import member

ROOT = Path(__file__).resolve().parents[2]
TREE = Path(json.loads((ROOT / 'engines/cemu-source-lock.json').read_text())['core']['stagedTree'])
SOURCE = TREE / 'src/Cafe/CafeSystem.cpp'

HARNESS = r'''
#include <atomic>
#include <cassert>
#include <chrono>
#include <condition_variable>
#include <cstdio>
#include <mutex>
#include <thread>
#include <vector>
using namespace std::chrono_literals;
std::mutex initMutex;
std::condition_variable initCv;
bool initEntered=false,initAllowed=false;
std::atomic<int> activeThreads{0},suspended{0},effectivePauses{0},effectiveResumes{0},schedulerStarts{0};
void PPCTimer_waitForInit(){}
namespace WindowSystem{void NotifyGameLoaded(){}}
enum class CPUMode{MulticoreRecompiler};
namespace ActiveSettings{CPUMode GetCPUMode(){return CPUMode::MulticoreRecompiler;}}
namespace LaunchSettings{bool ForceMultiCoreInterpreter(){return false;}bool ForceInterpreter(){return false;}}
struct Module{void TitleStart(){}};
void cemu_initForGame(){
    std::unique_lock lock(initMutex);initEntered=true;initCv.notify_all();
    assert(initCv.wait_for(lock,3s,[]{return initAllowed;}));
    activeThreads=5;
}
namespace coreinit{
void SuspendActiveThreads(){if(activeThreads){suspended+=activeThreads.load();effectivePauses++;}}
void ResumeActiveThreads(){if(activeThreads){suspended-=activeThreads.load();effectiveResumes++;}}
void OSSchedulerBegin(int count){assert(count==3);schedulerStarts++;}
}
namespace CafeSystem{
std::vector<Module*> s_iosuModules;
bool sSystemRunning=false,sTitlePaused=false,sTitleThreadsReady=false;
std::mutex sTitlePauseMutex;
// PRODUCTION_METHODS
}
void waitForScheduler(){
    auto deadline=std::chrono::steady_clock::now()+3s;
    while(!schedulerStarts&&std::chrono::steady_clock::now()<deadline)std::this_thread::yield();
    assert(schedulerStarts==1);
}
void startHeld(){
    using namespace CafeSystem;
    initEntered=false;initAllowed=false;activeThreads=0;suspended=0;
    effectivePauses=0;effectiveResumes=0;schedulerStarts=0;sSystemRunning=false;
    sTitlePaused=false;sTitleThreadsReady=false;
    LaunchForegroundTitle();
    std::unique_lock lock(initMutex);
    assert(initCv.wait_for(lock,3s,[]{return initEntered;}));
}
void allowInit(){std::lock_guard lock(initMutex);initAllowed=true;initCv.notify_all();}
int main(){
    using namespace CafeSystem;
    for(int i=0;i<40;i++){
        startHeld();
        PauseTitle();PauseTitle();
        allowInit();waitForScheduler();
        if(suspended!=5){
            std::fputs("startup pause did not suspend newly created guest threads\n",stderr);
            return 1;
        }
        assert(effectivePauses==1);
        ResumeTitle();ResumeTitle();
        assert(suspended==0&&effectiveResumes==1);

        startHeld();PauseTitle();ResumeTitle();allowInit();waitForScheduler();
        assert(suspended==0&&effectivePauses==0&&effectiveResumes==0);

        startHeld();allowInit();waitForScheduler();
        assert(suspended==0);
        PauseTitle();PauseTitle();assert(suspended==5&&effectivePauses==1);
        ResumeTitle();ResumeTitle();assert(suspended==0&&effectiveResumes==1);

        startHeld();std::thread concurrentPause([]{PauseTitle();});
        allowInit();concurrentPause.join();waitForScheduler();
        assert(suspended==5&&effectivePauses==1);
        ResumeTitle();assert(suspended==0&&effectiveResumes==1);
    }
    std::puts("160 Cemu startup/pause/resume interleavings passed");
}
'''


class CemuStartPauseTests(unittest.TestCase):
    def execute(self, source):
        signatures = ['\tvoid _LaunchTitleThread()', '\tvoid LaunchForegroundTitle()',
                      '\tvoid PauseTitle()', '\tvoid ResumeTitle()']
        text = HARNESS.replace('// PRODUCTION_METHODS', '\n'.join(member(source, s) for s in signatures))
        with tempfile.TemporaryDirectory(prefix='emufusion-cemu-pause-') as temporary:
            path = Path(temporary)
            (path / 'test.cpp').write_text(text)
            build = subprocess.run([shutil.which('clang++'), '-std=c++20', '-O1',
                '-fsanitize=address,undefined', str(path / 'test.cpp'), '-o', str(path / 'test')],
                capture_output=True, text=True, timeout=60)
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            return subprocess.run([str(path / 'test')], capture_output=True, text=True, timeout=20)

    def test_pause_is_applied_after_guest_thread_initialization(self):
        result = self.execute(SOURCE.read_text())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('160 Cemu startup/pause/resume interleavings passed', result.stdout)

    def test_missing_readiness_reconciliation_reproduces_lost_pause(self):
        source = SOURCE.read_text()
        block = ('\t\t{\n\t\t\tstd::lock_guard pauseLock(sTitlePauseMutex);\n'
                 '\t\t\tsTitleThreadsReady = true;\n\t\t\tif (sTitlePaused)\n'
                 '\t\t\t\tcoreinit::SuspendActiveThreads();\n\t\t}\n')
        self.assertEqual(source.count(block), 1)
        result = self.execute(source.replace(block, '', 1))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('startup pause did not suspend newly created guest threads', result.stderr)


if __name__ == '__main__':
    unittest.main()
