"""Execute actual presenter ownership boundaries with faulted platform leaves.

Reuses the controlled worker/Android scaffold, not simulated production methods.
Faults are synthetic. These tests do not qualify Android timing or driver behavior.
"""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

import test_lsfg_surface_early_submission as early
from test_lsfg_surface_early_submission import declaration, NATIVE


class SurfaceApplyOwnershipTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        native = (NATIVE / "owned_surface_control_presenter.cpp").read_text()
        header = (NATIVE / "owned_surface_control_presenter.hpp").read_text()
        source = early.SurfaceEarlySubmissionTest.build_source().split("int main(int argc,char** argv)")[0]
        source = source.replace("#include <optional>", "#include <optional>\n#include <poll.h>\n#include <sstream>")
        source = source.replace("uint64_t clockNs=0,", "bool failAfterCreate=false, failGeometry=false, failEndClock=false, throwAfterApply=false;\n"
                                "bool callbackInApply=false, failInitialClock=false, failPreApplyClock=false;\n"
                                "bool failMap=false, failQueue=false;\nsize_t failAtAppliedCount=1;\nstd::function<void()> duringApply;\nuint64_t clockNs=0,")
        source = source.replace("void AHardwareBuffer_release(",
                                "void AHardwareBuffer_acquire(AHardwareBuffer* b){++b->references;}\nvoid AHardwareBuffer_release(")
        source = source.replace("bool geometry=false,backpressure=false,explicitDesired=false;", "bool geometry=false,backpressure=false,explicitDesired=false,wasApplied=false;")
        source = source.replace("void ASurfaceTransaction_delete(ASurfaceTransaction* t){++deletes;delete t;}", r'''
void ASurfaceTransaction_delete(ASurfaceTransaction* t){
    ++deletes;
    if(!t->wasApplied && t->acquire>=0){
        assert(openFd(t->acquire));::close(t->acquire);
        const auto item=std::find(platformAcquireFds.begin(),platformAcquireFds.end(),t->acquire);
        assert(item!=platformAcquireFds.end());platformAcquireFds.erase(item);
    }
    delete t;
}
''')
        source = source.replace("t->source=s;t->destination=d;", "if(failGeometry)throw std::runtime_error(\"geometry leaf fault after transfer\");\n    t->source=s;t->destination=d;")
        source = source.replace("applied.push_back(*t);clockNs+=injectedApplyNs;cpuNs+=injectedCpuNs;", r'''
    t->wasApplied=true;applied.push_back(*t);
    if(callbackInApply){
        ASurfaceTransactionStats stats{static_cast<int64_t>(clockNs+10),newFd(),-1};
        applied.back().callback(applied.back().opaque,&stats);applied.back().opaque=nullptr;
    }
    if(duringApply)duringApply();
    clockNs+=injectedApplyNs;cpuNs+=injectedCpuNs;
    if(throwAfterApply)throw std::runtime_error("apply accepted then leaf fault");
''')
        source = source.replace("static uint64_t monotonicNs(){return clockNs;}", r'''
    static uint64_t monotonicNs(){
        if(failInitialClock || (failPreApplyClock && !platformAcquireFds.empty() && applied.empty()) ||
                (failAfterCreate && creates>0 && platformAcquireFds.empty()) ||
                (failEndClock && applied.size()>=failAtAppliedCount))throw std::runtime_error("clock leaf fault");
        return clockNs;
    }
''')
        source = source.replace("static uint64_t diagnosticMonotonicNs() noexcept {return clockNs;}",
                                "static uint64_t diagnosticMonotonicNs() noexcept {return failEndClock && applied.size()>=failAtAppliedCount?0:clockNs;}")
        # Android sync-file leaves. A signaled FD is independent test evidence;
        # callbacks themselves never fabricate a physical timestamp.
        sync = r'''
struct sync_fence_info {int status=1;uint64_t timestamp_ns=1'020'000'000;};
struct sync_file_info {int status=1;uint32_t num_fences=1;sync_fence_info child;};
struct sync_file_info* sync_file_info(int){return new struct sync_file_info;}
void sync_file_info_free(struct sync_file_info* value){delete value;}
const sync_fence_info* sync_get_fence_info(struct sync_file_info* value){return &value->child;}
'''
        containers = r'''
template<class K,class V>struct ControlledMap:std::map<K,V>{
    template<class... A>auto emplace(A&&... args){
        if(failMap)throw std::bad_alloc();
        return std::map<K,V>::emplace(std::forward<A>(args)...);
    }
};
template<class V>struct ControlledDeque:std::deque<V>{
    void push_back(const V& value){if(failQueue)throw std::bad_alloc();std::deque<V>::push_back(value);}
};
'''
        source = source.replace("struct Fixture {", sync + containers + "\nstruct Fixture {")
        source = source.replace("std::map<uint64_t, Pending> pending;", "ControlledMap<uint64_t, Pending> pending;")
        source = source.replace("std::deque<uint64_t> scheduled;", "ControlledDeque<uint64_t> scheduled;")
        methods = "\n".join(declaration(native, signature) for signature in (
            "bool present(AHardwareBuffer* buffer, int acquireFenceFd,",
            "void rollback(uint64_t presentId, int acquireFenceFd)",
            "static void closeAndRelease(Pending& row)",
            "std::optional<Completion> pollCompletion()", "bool isReleased(uint64_t presentId)",
            "void retire(uint64_t presentId)", "void pollReleaseFencesLocked()"))
        source = source.replace("};\nconstexpr uint64_t DEADLINE", "\n" +
                declaration(header, "struct Completion {", True) + r'''
    static uint64_t absoluteDifference(uint64_t a,uint64_t b){return a>=b?a-b:b-a;}
    template<class... T>bool rejectImmediate(T...){return false;}
    std::string diagnosticJsonLocked() const{return "controlled diagnostic serialization";}
''' + methods + "\n};\nconstexpr uint64_t DEADLINE")
        source += r'''
template<class F>void mustThrow(F fn){bool threw=false;try{fn();}catch(const std::exception&){threw=true;}assert(threw);}
void assertHeld(Fixture& f,uint64_t id,int acquired){
    const auto& row=f.state_->pending.at(id);
    assert(!row.submissionRejected && !row.physicalDelivered && !row.released);
    assert(row.acquireFenceFd==-1 && openFd(acquired) && row.buffer->references==2);
    assert(f.state_->scheduledRejected==0 && f.state_->completed==0 && f.state_->dropped==0);
}
void post_apply(bool early,bool throwingApi){
    Fixture f;const int fd=f.add(1,DEADLINE);const int queuedFd=f.add(2,DEADLINE+20'000'000);
    callbackInApply=early;failEndClock=!throwingApi;throwAfterApply=throwingApi;
    clockNs=DEADLINE-8'000'000;
    f.timedApplyWorkerMain();assert(applied.size()==1);assertHeld(f,1,fd);
    assert(f.state_->scheduled.size()==1 && openFd(queuedFd)); // No later dispatch after terminal failure.
    mustThrow([&]{f.takeUnavailablePresentFences();}); // Explicit terminal status, not a forged drop.
    mustThrow([&]{f.pollCompletion();}); // Cannot stall forever on applyEnd0.
    if(!early){
        ASurfaceTransactionStats stats{static_cast<int64_t>(clockNs+10),newFd(),-1};
        applied.front().callback(applied.front().opaque,&stats);applied.front().opaque=nullptr;
    }
    const int present=f.state_->pending.at(1).presentFenceFd;
    assert(present>=0 && openFd(present));
    mustThrow([&]{f.pollCompletion();});assert(openFd(present));assertHeld(f,1,fd);
    assert(!f.isReleased(1)); // Unknown last-buffer release stays unknown.
    assert(!f.state_->pending.at(1).physicalDelivered);mustThrow([&]{f.retire(1);});
    assert(deletes==creates); // Applied transaction object, not its owned callbacks, was destroyed.
    failEndClock=false;const int newInput=newFd();
    mustThrow([&]{f.present(&f.buffers[3],newInput,3,DEADLINE+40'000'000,0,0,0,0);});
    assert(!openFd(newInput) && f.buffers[3].references==1 && f.state_->pending.count(3)==0);
}
void tokenless_rollback(){
    Fixture f;AHardwareBuffer& buffer=f.buffers[0];const int fd=newFd();
    failEndClock=true;callbackInApply=true;clockNs=DEADLINE;
    mustThrow([&]{f.present(&buffer,fd,1,DEADLINE+30'000'000,0,0,0,0);});
    assert(f.state_->pending.count(1)==1 && buffer.references==2);
    assertHeld(f,1,fd);assert(f.state_->pending.at(1).callbackReceived);
    assert(openFd(f.state_->pending.at(1).presentFenceFd));
    mustThrow([&]{f.pollCompletion();});assert(deletes==creates);
}
void before_apply_cancel(bool afterTransfer){
    Fixture f;const int fd=f.add(1,DEADLINE);
    failGeometry=afterTransfer;failAfterCreate=!afterTransfer;
    clockNs=DEADLINE-8'000'000;f.timedApplyWorkerMain();
    const auto& row=f.state_->pending.at(1);
    assert(applied.empty() && row.submissionRejected && row.released && !row.physicalDelivered);
    assert(!openFd(fd) && f.surface.references==1 && row.buffer->references==2);
    assert(deletes==creates && f.lastSubmittedPresentId_==0);
    assert(f.takeUnavailablePresentFences()==std::vector<uint64_t>{1});
}
void callback_before_successful_return(){
    Fixture f;f.add(1,DEADLINE);callbackInApply=true;clockNs=DEADLINE-8'000'000;
    duringApply=[&]{assert(f.state_->pending.at(1).callbackReceived);assert(!f.pollCompletion());};
    f.timedApplyWorkerMain();duringApply=nullptr;
    assert(f.pollCompletion().has_value());assert(f.state_->completed==1);
}
void older_completed_release_after_failure(){
    Fixture f;f.add(10,DEADLINE,false);clockNs=DEADLINE-8'000'000;
    f.applyScheduled(10);
    ASurfaceTransactionStats prior{static_cast<int64_t>(clockNs+10),newFd(),-1};
    applied.front().callback(applied.front().opaque,&prior);applied.front().opaque=nullptr;
    assert(f.pollCompletion().has_value());
    AHardwareBuffer* priorBuffer=f.state_->pending.at(10).buffer;
    const int failedFd=f.add(11,DEADLINE+20'000'000);
    failEndClock=true;failAtAppliedCount=2;callbackInApply=true;clockNs+=20'000'000;
    f.timedApplyWorkerMain();assert(applied.size()==2);
    mustThrow([&]{f.pollCompletion();});
    assert(f.isReleased(10) && f.state_->pending.at(10).releaseCallbackPresentId==11);
    f.retire(10);assert(f.state_->pending.count(10)==0 && priorBuffer->references==1);
    assert(!f.isReleased(11) && openFd(failedFd));
    assert(!f.state_->pending.at(11).physicalDelivered && f.state_->completed==1);
}
void cancelled_preapply_clock_has_no_dispatch_snapshot(){
    Fixture f;f.add(1,DEADLINE);clockNs=DEADLINE-8'000'000;failPreApplyClock=true;
    f.timedApplyWorkerMain();
    assert(applied.empty() && f.state_->pending.at(1).transactionCancelled);
    assert(f.state_->pending.at(1).submissionRejected && f.lastSubmittedPresentId_==0);
    assert(f.state_->pending.at(1).commitObservationSerial==0);
    assert(f.state_->nextCommitObservationSerial==0 && f.state_->lastCommitPresentId==0);
    assert(f.surface.references==1 && deletes==creates);
}
void enqueue_failure(const std::string& name){
    Fixture f;clockNs=DEADLINE-8'000'000;const int fd=newFd();
    failInitialClock=name=="enqueue-clock";failMap=name=="enqueue-map";failQueue=name=="enqueue-queue";
    mustThrow([&]{f.present(&f.buffers[0],fd,1,DEADLINE+8'333'333,
            10001,DEADLINE+10'333'333,DEADLINE,8'333'333);});
    assert(f.buffers[0].references==1 && f.state_->pending.empty() && f.state_->scheduled.empty());
    assert(!openFd(fd));
    assert(applied.empty() && f.surface.references==1);
}
void false_and_validation_fd_contract(){
    Fixture f;clockNs=DEADLINE;const int declined=newFd();
    assert(!f.present(&f.buffers[0],declined,1,DEADLINE+8'333'333,
            10001,DEADLINE+10'333'333,DEADLINE,8'333'333));
    assert(openFd(declined));::close(declined);
    const int invalid=newFd();
    mustThrow([&]{f.present(nullptr,invalid,1,DEADLINE+30'000'000,0,0,0,0);});
    assert(!openFd(invalid) && f.state_->pending.empty() && f.buffers[0].references==1);
}
void worker_preflight_clock_failure(){
    Fixture f;const int fd=f.add(1,DEADLINE);clockNs=DEADLINE-8'000'000;
    failInitialClock=true;f.timedApplyWorkerMain();
    const auto& row=f.state_->pending.at(1);
    assert(row.submissionRejected && row.released && !row.physicalDelivered && !row.dispatchFailed);
    assert(!openFd(fd) && creates==0 && applied.empty() && f.state_->dispatchFailurePresentId==0);
}
int main(int argc,char** argv){
    assert(argc==2);const std::string name=argv[1];
    if(name=="post-clock-late")post_apply(false,false);
    else if(name=="post-clock-early")post_apply(true,false);
    else if(name=="apply-throw-late")post_apply(false,true);
    else if(name=="apply-throw-early")post_apply(true,true);
    else if(name=="tokenless")tokenless_rollback();
    else if(name=="pre-transfer")before_apply_cancel(false);
    else if(name=="post-transfer-pre-apply")before_apply_cancel(true);
    else if(name=="success-early")callback_before_successful_return();
    else if(name=="older-release")older_completed_release_after_failure();
    else if(name=="preapply-clock")cancelled_preapply_clock_has_no_dispatch_snapshot();
    else if(name=="fd-contract")false_and_validation_fd_contract();
    else if(name=="worker-clock")worker_preflight_clock_failure();
    else if(name.starts_with("enqueue-"))enqueue_failure(name);
    else assert(false);
    std::cout<<"PASS ownership "<<name<<'\n';
}
'''
        cls.temporary = tempfile.TemporaryDirectory(prefix="lsfg-apply-ownership-")
        cls.addClassCleanup(cls.temporary.cleanup)
        unit = Path(cls.temporary.name) / "fixture.cpp"
        unit.write_text(source)
        cls.binary = unit.with_suffix("")
        result = subprocess.run([shutil.which("c++"), "-std=c++20", "-Wall", "-Wextra", "-Werror",
                                 "-g", "-O1", "-fsanitize=address,undefined", str(unit),
                                 "-o", str(cls.binary)], capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    def test_actual_apply_ownership_faults(self):
        for scenario in ("post-clock-late", "post-clock-early", "apply-throw-late", "apply-throw-early",
                         "tokenless", "pre-transfer", "post-transfer-pre-apply", "success-early", "older-release",
                         "preapply-clock", "enqueue-clock", "enqueue-map", "enqueue-queue", "fd-contract", "worker-clock"):
            with self.subTest(scenario=scenario):
                result = subprocess.run([str(self.binary), scenario], capture_output=True, text=True,
                                        timeout=10, env={**os.environ,
                                        "ASAN_OPTIONS": "detect_leaks=0:abort_on_error=1",
                                        "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"})
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
