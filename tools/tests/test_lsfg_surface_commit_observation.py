"""Compile actual commit-observation methods; no Android timing qualification.

Platform clocks/logging and already-tested release-fence polling are controlled
leaves. Commit callbacks never provide simulated physical or release evidence.
"""
from pathlib import Path
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / "unified-android/lsfg-qualification-native/owned_surface_control_presenter.cpp"


def declaration(source, signature, semicolon=False):
    start = source.index(signature)
    opening = source.index("{", start)
    masked = re.sub(r'''//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])' ''',
                    lambda match: " " * len(match.group()), source, flags=re.S | re.X)
    depth = 0
    for index in range(opening, len(masked)):
        if masked[index] == "{":
            depth += 1
        elif masked[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1 + int(semicolon)]
    raise AssertionError(signature)


class SurfaceCommitObservationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        native = NATIVE.read_text()
        structs = "\n".join(declaration(native, item, True) for item in (
            "struct Pending {", "struct SharedState {", "struct CommitCallbackContext {"))
        constants = "\n".join(re.findall(r"static constexpr [^;]+;",
                                         native[native.index("class OwnedSurface"):
                                                native.index("struct Pending {")]))
        methods = "\n".join(declaration(native, item) for item in (
            "static uint64_t diagnosticMonotonicNs() noexcept",
            "uint64_t recordCommitDispatch(uint64_t presentId,",
            "static void onCommit(void* opaque, ASurfaceTransactionStats*) noexcept",
            "void logMissingFenceCommitLocked(const Pending& row)",
            "std::vector<uint64_t> takeUnavailablePresentFences()",
            "void throwIfDispatchFailedLocked() const",
            "void retire(uint64_t presentId)",
            "static void closeAndRelease(Pending& row)"))
        source = r'''
#include <cassert>
#include <condition_variable>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <deque>
#include <iostream>
#include <map>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <time.h>
#include <unistd.h>
#include <vector>
uint64_t nowNs=1;int clockMode=0;
int controlledClockGettime(clockid_t id,timespec* result){
    assert(id==CLOCK_MONOTONIC);
    result->tv_sec=nowNs/1'000'000'000;result->tv_nsec=nowNs%1'000'000'000;
    if(clockMode==1)return -1;
    if(clockMode==2)result->tv_sec=-1;
    if(clockMode==3)result->tv_nsec=-1;
    if(clockMode==4)result->tv_nsec=1'000'000'000;
    if(clockMode==5)result->tv_sec=INT64_MAX;
    return 0;
}
#define clock_gettime controlledClockGettime
struct AHardwareBuffer {unsigned releases=0;};
void AHardwareBuffer_release(AHardwareBuffer* b){++b->releases;}
struct ASurfaceTransactionStats {}; // No getters: a fence query cannot compile.
constexpr int ANDROID_LOG_ERROR=1;
std::vector<std::string> logs;
int __android_log_print(int,const char*,const char* format,...){
    char buffer[2048];va_list args;va_start(args,format);
    const int count=std::vsnprintf(buffer,sizeof(buffer),format,args);va_end(args);
    assert(count>=0 && count<1024);logs.emplace_back(buffer);return count;
}
struct Fixture {
''' + constants + "\n" + structs + r'''
    std::shared_ptr<SharedState> state_=std::make_shared<SharedState>();
    void add(uint64_t id){Pending row;row.presentId=id;state_->pending.emplace(id,row);}
    void pollReleaseFencesLocked(){} // No release inferred from a commit.
    uint64_t dispatch(uint64_t id,uint64_t previous){add(id);return recordCommitDispatch(id,previous);}
    void commit(uint64_t id,uint64_t serial){
        onCommit(new CommitCallbackContext{state_,id,serial},nullptr);
    }
    void retireProven(uint64_t id){
        // Test setup provides independent completed/released evidence.
        auto& row=state_->pending.at(id);row.physicalDelivered=true;row.released=true;retire(id);
    }
''' + methods + r'''
};
void no_physical_authority(const Fixture& f,uint64_t id){
    const auto& row=f.state_->pending.at(id);
    assert(!row.callbackReceived && !row.physicalDelivered && !row.released);
    assert(row.presentFenceFd==-2 && row.releaseFenceFd==-2 && row.acquireFenceFd==-2);
    assert(!row.submissionRejected && f.state_->callbacks==0 && f.state_->completed==0);
}
void exact_before_and_after(){
    Fixture f;nowNs=10;const auto a=f.dispatch(4294967295ULL,0);
    assert(a==1 && !f.state_->pending.at(4294967295ULL).predecessorCommitSnapshotKnown);
    nowNs=20;f.commit(4294967295ULL,a);no_physical_authority(f,4294967295ULL);
    nowNs=30;const auto b=f.dispatch(1,4294967295ULL);
    const auto& next=f.state_->pending.at(1);const auto& previous=f.state_->pending.at(4294967295ULL);
    assert(b==2 && next.predecessorCommitSnapshotKnown);
    assert(next.predecessorPresentId==4294967295ULL && next.predecessorCommitObservedAtDispatch);
    assert(next.predecessorCommitObservedNs==20 && next.dispatchObservedNs==30);
    assert(previous.nextDispatchPresentId==1 && previous.nextDispatchObservedNs==30);
    assert(previous.commitObservedAtNextDispatch && previous.commitObservedNsAtNextDispatch==20);
    nowNs=40;const auto c=f.dispatch(2,1);
    assert(c==3 && !f.state_->pending.at(2).predecessorCommitObservedAtDispatch);
    assert(f.state_->pending.at(2).predecessorCommitSnapshotKnown);
    nowNs=50;f.commit(1,b);
    assert(f.state_->pending.at(1).commitCallbackObservedNs==50);
    assert(!f.state_->pending.at(1).commitObservedAtNextDispatch);
    assert(f.state_->pending.at(1).commitObservedNsAtNextDispatch==0);
    assert(!f.state_->pending.at(2).predecessorCommitObservedAtDispatch); // Frozen snapshot.
    assert(!f.state_->lastCommitCallbackObserved && f.state_->lastCommitPresentId==2);
    no_physical_authority(f,1);no_physical_authority(f,2);assert(logs.empty());
}
void wrong_duplicate_and_reused_ids(){
    Fixture f;nowNs=10;const auto serial=f.dispatch(9,0);
    f.commit(8,serial);f.commit(9,serial+1);f.commit(9,0);
    assert(f.state_->unmatchedCommitCallbacks==3 && f.state_->commitCallbacks==0);
    f.commit(9,serial);nowNs=20;f.commit(9,serial);
    assert(f.state_->commitCallbacks==1 && f.state_->duplicateCommitCallbacks==1);
    assert(f.state_->pending.at(9).commitCallbackObservedNs==10);
    f.retireProven(9);const auto fresh=f.dispatch(9,9);
    assert(fresh!=serial);f.commit(9,serial);
    assert(!f.state_->pending.at(9).commitCallbackObserved && !f.state_->lastCommitCallbackObserved);
    assert(f.state_->unmatchedCommitCallbacks==4);
    f.commit(9,fresh);no_physical_authority(f,9);
    assert(f.state_->commitCallbacks==2);
}
void retirement_and_shutdown(){
    Fixture f;nowNs=10;const auto a=f.dispatch(1000001,0);
    f.retireProven(1000001);nowNs=20;f.commit(1000001,a);
    assert(f.state_->lastCommitCallbackObserved && f.state_->lastCommitCallbackObservedNs==20);
    f.dispatch(1,1000001);
    assert(f.state_->pending.at(1).predecessorCommitSnapshotKnown);
    assert(f.state_->pending.at(1).predecessorCommitObservedAtDispatch);
    const auto serial=f.state_->pending.at(1).commitObservationSerial;
    auto* callback=new Fixture::CommitCallbackContext{f.state_,1,serial};
    f.state_->closing=true;auto keep=f.state_;std::weak_ptr<Fixture::SharedState> weak=keep;
    f.state_.reset();Fixture::onCommit(callback,nullptr);
    assert(keep->commitCallbacksAfterClose==1 && !keep->pending.at(1).commitCallbackObserved);
    assert(!keep->pending.at(1).released && !keep->pending.at(1).physicalDelivered);
    keep.reset();assert(weak.expired()); // Callback held only bounded shared state, not presenter.
}
void unknown_clock_and_exhaustion(){
    for(int mode=1;mode<=5;++mode){
        Fixture f;clockMode=mode;const auto serial=f.dispatch(1,0);f.commit(1,serial);
        assert(f.state_->pending.at(1).commitCallbackObserved);
        assert(f.state_->pending.at(1).commitCallbackObservedNs==0);
        assert(f.state_->pending.at(1).dispatchObservedNs==0);
        no_physical_authority(f,1);
    }
    clockMode=0;Fixture f;f.state_->nextCommitObservationSerial=UINT64_MAX;
    assert(f.dispatch(1,0)==0);f.commit(1,0);
    assert(!f.state_->pending.at(1).commitCallbackObserved && f.state_->commitCallbacks==0);
}
void bounded_storage_and_missing_fence_logs(){
    Fixture f;uint64_t previous=0;
    for(uint64_t id=1;id<=10000;++id){
        nowNs=id;const auto serial=f.dispatch(id,previous);f.commit(id,serial);
        f.retireProven(id);previous=id;
        assert(f.state_->pending.empty() && f.state_->scheduled.empty());
    }
    assert(f.state_->commitCallbacks==10000 && logs.empty());
    for(uint64_t id=10001;id<=10020;++id){
        nowNs=id;f.dispatch(id,previous);previous=id;
        auto& row=f.state_->pending.at(id);row.callbackReceived=true;row.presentFenceFd=-1;
    }
    assert(f.takeUnavailablePresentFences().size()==20);
    assert(logs.size()==12 && f.state_->commitDiagnosticLogs==12);
    assert(logs.front().find("presentId=10001 serial=10001")!=std::string::npos);
    assert(logs.front().find("predecessor=10000 predecessorKnown=1 predecessorObserved=1")!=std::string::npos);
    assert(logs.front().find("next=10002 nextDispatchNs=10002 observedAtNext=0")!=std::string::npos);
    assert(f.takeUnavailablePresentFences().empty() && logs.size()==12);
    assert(f.state_->completed==0 && f.state_->dropped==0);
    assert(!f.state_->pending.at(10001).physicalDelivered && !f.state_->pending.at(10001).released);
}
int main(int argc,char** argv){
    assert(argc==2);const std::string test=argv[1];
    if(test=="exact")exact_before_and_after();
    else if(test=="wrong")wrong_duplicate_and_reused_ids();
    else if(test=="lifetime")retirement_and_shutdown();
    else if(test=="unknown")unknown_clock_and_exhaustion();
    else if(test=="bounded")bounded_storage_and_missing_fence_logs();
    else assert(false);
    std::cout<<"PASS "<<test<<'\n';
}
'''
        compiler = shutil.which("c++")
        if not compiler:
            raise AssertionError("C++ compiler required")
        cls.temporary = tempfile.TemporaryDirectory(prefix="lsfg-commit-observation-")
        cls.addClassCleanup(cls.temporary.cleanup)
        unit = Path(cls.temporary.name) / "fixture.cpp"
        unit.write_text(source)
        cls.binary = Path(cls.temporary.name) / "fixture"
        result = subprocess.run([compiler, "-std=c++20", "-Wall", "-Wextra", "-Werror",
                                 "-g", "-O1", "-fsanitize=address,undefined", str(unit),
                                 "-o", str(cls.binary)], capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    def test_actual_commit_observations(self):
        for scenario in ("exact", "wrong", "lifetime", "unknown", "bounded"):
            with self.subTest(scenario=scenario):
                result = subprocess.run([str(self.binary), scenario], capture_output=True,
                                        text=True, timeout=20, env={**os.environ,
                                        "ASAN_OPTIONS": "detect_leaks=" +
                                        ("0" if sys.platform == "darwin" else "1") +
                                        ":abort_on_error=1",
                                        "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"})
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
