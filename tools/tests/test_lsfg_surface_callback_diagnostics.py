"""Execute real callback/poll/retirement methods with controlled Android leaves.

These host checks cover callback ordering and observability. They do not qualify
Android fence behavior, physical cadence, or buffer correctness on a real device.
"""
from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / "unified-android/lsfg-qualification-native"


def declaration(source, signature, semicolon=False):
    start = source.index(signature)
    opening = source.index("{", start)
    masked = re.sub(r"""//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])'""",
                    lambda match: " " * len(match.group()), source, flags=re.S)
    depth = 0
    for index in range(opening, len(masked)):
        if masked[index] == "{":
            depth += 1
        elif masked[index] == "}":
            depth -= 1
            if depth == 0:
                end = index + 1
                if semicolon:
                    assert source[end] == ";"
                    end += 1
                return source[start:end]
    raise AssertionError("unterminated production declaration: " + signature)


class SurfaceCallbackDiagnosticTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        native = (NATIVE / "owned_surface_control_presenter.cpp").read_text()
        header = (NATIVE / "owned_surface_control_presenter.hpp").read_text()
        structs = "\n".join(declaration(native, signature, True) for signature in (
            "struct Pending {", "struct SharedState {", "struct CallbackContext {"))
        structs += "\n" + declaration(header, "struct Completion {", True)
        methods = "\n".join(declaration(native, signature) for signature in (
            "std::string diagnosticJsonLocked() const",
            "static void onComplete(void* opaque, ASurfaceTransactionStats* stats)",
            "std::optional<Completion> pollCompletion()",
            "std::vector<uint64_t> takeUnavailablePresentFences()",
            "void throwIfDispatchFailedLocked() const",
            "bool isReleased(uint64_t presentId)", "void retire(uint64_t presentId)",
            "static void closeAndRelease(Pending& row)", "void pollReleaseFencesLocked()"))
        source = r'''
#include <algorithm>
#include <cassert>
#include <condition_variable>
#include <cstdint>
#include <deque>
#include <fcntl.h>
#include <iostream>
#include <map>
#include <memory>
#include <mutex>
#include <optional>
#include <poll.h>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unistd.h>
#include <vector>
struct AHardwareBuffer {int releases=0;};
void AHardwareBuffer_release(AHardwareBuffer* buffer){++buffer->releases;}
struct ASurfaceControl {int releases=0;};
void ASurfaceControl_release(ASurfaceControl* surface){++surface->releases;}
struct ASurfaceTransactionStats {int64_t latch;int present;int previousRelease;};
int64_t ASurfaceTransactionStats_getLatchTime(ASurfaceTransactionStats* stats){return stats->latch;}
int ASurfaceTransactionStats_getPresentFenceFd(ASurfaceTransactionStats* stats){return stats->present;}
int ASurfaceTransactionStats_getPreviousReleaseFenceFd(ASurfaceTransactionStats* stats,ASurfaceControl*){
    return stats->previousRelease;
}
struct sync_fence_info {int status=1;uint64_t timestamp_ns=200;};
struct sync_file_info {int status=1;uint32_t num_fences=1;sync_fence_info child;};
struct sync_file_info* sync_file_info(int){return new struct sync_file_info;}
void sync_file_info_free(struct sync_file_info* info){delete info;}
const sync_fence_info* sync_get_fence_info(struct sync_file_info* info){return &info->child;}
int newFd(){int fds[2];assert(::pipe(fds)==0);::close(fds[1]);return fds[0];}
bool openFd(int fd){return ::fcntl(fd,F_GETFD)>=0;}
struct Fixture {
''' + structs + r'''
    std::shared_ptr<SharedState> state_=std::make_shared<SharedState>();
    ASurfaceControl surface;
    void logMissingFenceCommitLocked(const Pending&) {} // Dedicated commit fixture tests the real logger.
    void add(uint64_t id){
        Pending row;
        row.presentId=id;row.desiredPresentTimeNs=150;
        row.frameTimelineVsyncId=id+1000;row.frameTimelineExpectedNs=200;
        row.frameTimelineDeadlineNs=120;row.transactionApplyStartNs=100;
        row.transactionApplyEndNs=101;
        state_->pending.emplace(id,row);
    }
    void callback(uint64_t id,uint64_t previous,int64_t latch,int present=-1,int release=-1){
        ASurfaceTransactionStats stats{latch,present,release};
        onComplete(new CallbackContext{state_,&surface,id,previous},&stats);
    }
''' + methods + r'''
};
template<typename F> void throws(F operation){
    bool caught=false;try{operation();}catch(const std::runtime_error&){caught=true;}assert(caught);
}
void raw_values_never_invent_physical(){
    for(const int64_t raw:std::vector<int64_t>{INT64_MIN,-1,0,123}){
        Fixture f;f.add(1);f.add(2);
        f.callback(1,0,raw);
        f.callback(2,1,124,newFd());
        const auto& row=f.state_->pending.at(1);
        assert(row.rawCallbackLatchTimeNs==raw);
        assert(row.latchTimeNs==(raw>0?static_cast<uint64_t>(raw):0));
        assert(row.callbackReceived && row.presentFenceFd==-1);
        assert(row.releaseCallbackPresentId==2 && row.released);
        assert(!f.pollCompletion()); // newer valid callback cannot overtake unknown1
        const auto unknown=f.takeUnavailablePresentFences();
        assert(unknown==std::vector<uint64_t>{1});
        assert(f.takeUnavailablePresentFences().empty());
        assert(!f.pollCompletion());
        assert(!row.physicalDelivered && row.unavailableReported);
        assert(f.state_->completed==0 && f.state_->dropped==0);
        throws([&]{f.retire(1);}); // release alone is not physical evidence
        const auto json=f.diagnosticJsonLocked();
        assert(json.find("\"rawCallbackLatchNs\":"+std::to_string(raw))!=std::string::npos);
        assert(json.find("\"unavailableReported\":1")!=std::string::npos);
    }
}
void positive_gate_unchanged(){
    for(const int64_t raw:std::vector<int64_t>{INT64_MIN,-1,0}){
        Fixture f;f.add(1);const int fd=newFd();f.callback(1,0,raw,fd);
        throws([&]{f.pollCompletion();});
        assert(f.state_->pending.at(1).rawCallbackLatchTimeNs==raw);
        assert(!f.state_->pending.at(1).physicalDelivered && openFd(fd));
        assert(f.state_->completed==0);
    }
    Fixture f;f.add(1);const int fd=newFd();f.callback(1,0,123,fd);
    const auto completion=f.pollCompletion();
    assert(completion && completion->presentId==1 && completion->latchTimeNs==123);
    assert(completion->actualPresentTimeNs==200 && completion->rawPresentFenceTimeNs==200);
    assert(f.state_->pending.at(1).rawCallbackLatchTimeNs==123);
    assert(f.state_->completed==1 && !openFd(fd));
}
void release_ownership_is_separate(){
    Fixture f;f.add(1);f.add(2);
    int pipeFds[2];assert(::pipe(pipeFds)==0);
    const int acquire=newFd();f.state_->pending.at(1).acquireFenceFd=acquire;
    f.callback(1,0,-1);
    f.callback(2,1,123,newFd(),pipeFds[0]);
    auto& previous=f.state_->pending.at(1);const auto& current=f.state_->pending.at(2);
    assert(current.callbackPreviousPresentId==1 && current.callbackPreviousReleaseFenceFd==pipeFds[0]);
    assert(previous.releaseCallbackPresentId==2 && previous.releaseFenceFd==pipeFds[0]);
    assert(!previous.released && openFd(acquire));
    assert(!f.isReleased(1));
    const auto pending=f.diagnosticJsonLocked();
    assert(pending.find("\"releaseCallbackPresentId\":2")!=std::string::npos);
    assert(pending.find("\"releaseFenceFd\":"+std::to_string(pipeFds[0]))!=std::string::npos);
    assert(pending.find("\"acquireFenceFd\":"+std::to_string(acquire))!=std::string::npos);
    const char byte='x';assert(::write(pipeFds[1],&byte,1)==1);
    assert(f.isReleased(1) && previous.released && !openFd(pipeFds[0]));
    assert(previous.releaseFenceFd==-1 && previous.releaseCallbackPresentId==2);
    assert(current.callbackPreviousReleaseFenceFd==pipeFds[0]); // unowned historical numeric copy
    assert(!f.pollCompletion() && f.state_->completed==0);
    assert(openFd(acquire));
    ::close(pipeFds[1]);
}
void callback_duplicates_do_not_rewrite_raw_or_ownership(){
    Fixture f;f.add(1);f.add(2);
    f.callback(1,0,-1);
    const int release=newFd();f.callback(2,1,123,newFd(),release);
    const int discardedPresent=newFd(),discardedRelease=newFd();
    f.callback(2,1,999,discardedPresent,discardedRelease);
    const auto& current=f.state_->pending.at(2);
    const auto& previous=f.state_->pending.at(1);
    assert(current.rawCallbackLatchTimeNs==123 && current.latchTimeNs==123);
    assert(current.callbackPreviousReleaseFenceFd==release);
    assert(previous.releaseCallbackPresentId==2 && previous.releaseFenceFd==release);
    assert(!openFd(discardedPresent) && !openFd(discardedRelease) && openFd(release));
    assert(f.state_->callbacks==2 && f.surface.releases==3);
}
void callback_before_apply_returns_retains_fence(){
    Fixture f;f.add(1);
    auto& row=f.state_->pending.at(1);
    row.transactionApplyStartNs=0;row.transactionApplyEndNs=0;
    const int present=newFd();
    f.callback(1,0,123,present);
    assert(row.callbackReceived && row.presentFenceFd==present && openFd(present));
    assert(!f.pollCompletion());
    assert(f.takeUnavailablePresentFences().empty());
    assert(!row.physicalDelivered && f.state_->completed==0 && openFd(present));
    throws([&]{f.retire(1);});
    // Actual apply bookkeeping is published only when the call returns.
    row.transactionApplyStartNs=100;row.transactionApplyEndNs=101;
    const auto completed=f.pollCompletion();
    assert(completed && completed->presentId==1 && completed->actualPresentTimeNs==200);
    assert(row.physicalDelivered && f.state_->completed==1 && !openFd(present));
}
void invalid_timestamp_reports_exact_failed_predicate(){
    Fixture f;f.add(1);auto& row=f.state_->pending.at(1);
    row.transactionApplyEndNs=124;
    const int present=newFd();f.callback(1,0,99,present);
    bool caught=false;
    try{f.pollCompletion();}catch(const std::runtime_error& error){
        caught=true;const std::string message=error.what();
        assert(message.find("presentId=1 physicalTimestampNs=200")!=std::string::npos);
        assert(message.find("missingLatch=0 presentBeforeLatch=0 missingApplyStart=0")!=std::string::npos);
        assert(message.find("applyEndBeforeStart=0 latchBeforeApplyStart=1 latchBeforeApplyReturn=1")!=std::string::npos);
        assert(message.find("\"rawCallbackLatchNs\":99")!=std::string::npos);
        assert(message.find("\"applyEndNs\":124")!=std::string::npos);
    }
    assert(caught && !row.physicalDelivered && f.state_->completed==0 && openFd(present));
}
void remaining_raw_order_guards_still_reject(){
    for(int scenario=0;scenario<4;++scenario){
        Fixture f;f.add(1);auto& row=f.state_->pending.at(1);
        int64_t latch=123;
        if(scenario==0)row.transactionApplyStartNs=0;
        if(scenario==1)row.transactionApplyEndNs=99;
        if(scenario==2)latch=0;
        if(scenario==3)latch=201; // positive present fence remains 200
        const int present=newFd();f.callback(1,0,latch,present);
        throws([&]{f.pollCompletion();});
        assert(!row.physicalDelivered && !row.released && openFd(present));
        assert(f.state_->completed==0);
    }
}
void asynchronous_latch_and_present_may_precede_apply_return(){
    // SurfaceFlinger is asynchronous. Userspace can be descheduled after IPC
    // while the compositor latches and even presents before apply returns.
    for(const uint64_t applyEnd:std::vector<uint64_t>{123,124,201}){
        Fixture f;f.add(1);auto& row=f.state_->pending.at(1);
        row.transactionApplyEndNs=applyEnd;
        const int present=newFd();f.callback(1,0,123,present);
        const auto completion=f.pollCompletion();
        assert(completion && completion->presentId==1);
        assert(completion->latchTimeNs==123 && completion->actualPresentTimeNs==200);
        assert(completion->transactionApplyStartNs==100);
        assert(completion->transactionApplyEndNs==applyEnd);
        assert(row.physicalDelivered && f.state_->completed==1 && !openFd(present));
        // A present fence is not a release fence: do not recycle this buffer.
        assert(!row.released && !f.isReleased(1));
        throws([&]{f.retire(1);});
    }
}
void bounded_diagnostic_does_not_mutate(){
    Fixture f;for(uint64_t id=1;id<=7;++id)f.add(id);
    f.callback(1,0,123,newFd());assert(f.pollCompletion());
    f.callback(2,1,-1);
    for(int repetition=0;repetition<3;++repetition){
        const auto json=f.diagnosticJsonLocked();
        assert(json.find("\"presentId\":1,")==std::string::npos);
        for(int id=2;id<=5;++id)assert(json.find("\"presentId\":"+std::to_string(id)+",")!=std::string::npos);
        assert(json.find("\"presentId\":6,")==std::string::npos);
        assert(json.find("\"presentId\":7,")==std::string::npos);
        assert(json.size()<4096);
        assert(f.state_->pending.at(2).rawCallbackLatchTimeNs==-1);
        assert(!f.state_->pending.at(2).unavailableReported);
        assert(!f.state_->pending.at(2).physicalDelivered);
        assert(f.state_->completed==1 && f.state_->dropped==0 && f.state_->callbacks==2);
    }
}
int main(int argc,char** argv){
    assert(argc==2);const std::string name=argv[1];
    if(name=="raw")raw_values_never_invent_physical();
    else if(name=="gate")positive_gate_unchanged();
    else if(name=="release")release_ownership_is_separate();
    else if(name=="duplicate")callback_duplicates_do_not_rewrite_raw_or_ownership();
    else if(name=="callback-before-return")callback_before_apply_returns_retains_fence();
    else if(name=="predicate-diagnostic")invalid_timestamp_reports_exact_failed_predicate();
    else if(name=="async-latch")asynchronous_latch_and_present_may_precede_apply_return();
    else if(name=="raw-order-guards")remaining_raw_order_guards_still_reject();
    else if(name=="bounded")bounded_diagnostic_does_not_mutate();
    else assert(false);
    std::cout<<"PASS "<<name<<'\n';
}
'''
        compiler = shutil.which("c++")
        if compiler is None:
            raise AssertionError("C++ compiler is required")
        cls.temporary = tempfile.TemporaryDirectory(prefix="lsfg-callback-diagnostic-")
        cls.addClassCleanup(cls.temporary.cleanup)
        output = Path(cls.temporary.name)
        unit = output / "fixture.cpp"
        unit.write_text(source)
        cls.binary = output / "fixture"
        result = subprocess.run([compiler, "-std=c++20", "-Wall", "-Wextra", "-Werror",
                                 "-g", "-O1", "-fsanitize=address,undefined",
                                 str(unit), "-o", str(cls.binary)], capture_output=True,
                                text=True, timeout=60)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    def run_case(self, name):
        env = dict(os.environ, ASAN_OPTIONS="detect_leaks=0:abort_on_error=1",
                   UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")
        result = subprocess.run([str(self.binary), name], capture_output=True,
                                text=True, timeout=10, env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS " + name, result.stdout)

    def test_signed_latch_and_missing_fence_never_invent_physical_success(self):
        self.run_case("raw")

    def test_existing_positive_latch_gate_is_unchanged(self):
        self.run_case("gate")

    def test_callback_before_apply_return_keeps_fence_and_waits_for_bookkeeping(self):
        self.run_case("callback-before-return")

    def test_invalid_timestamp_reports_exact_predicate_and_retains_ownership(self):
        self.run_case("predicate-diagnostic")

    def test_compositor_latch_and_present_can_precede_userspace_apply_return(self):
        self.run_case("async-latch")

    def test_other_raw_timestamp_guards_retain_failed_fences(self):
        self.run_case("raw-order-guards")

    def test_output_release_and_raw_callback_are_distinct_ownership(self):
        self.run_case("release")

    def test_duplicate_callback_cannot_rewrite_raw_or_release_identity(self):
        self.run_case("duplicate")

    def test_four_row_diagnostic_bound_and_no_state_mutation(self):
        self.run_case("bounded")

    def test_live_missing_fence_remains_fatal_not_a_recovery_branch(self):
        jni = (NATIVE / "lsfg_qualification_jni.cpp").read_text()
        branch = jni.split("if (!unavailable.empty()) {", 1)[1].split(
            "    auto physical =", 1)[0]
        self.assertIn("throw emufusion::lsfg::PresentFenceUnavailable", branch)
        self.assertNotIn("markDropped(", branch)
        self.assertNotIn("dropSurfacePresentation(", branch)
        self.assertNotIn("retire(", branch)


if __name__ == "__main__":
    unittest.main(verbosity=2)
