"""Execute production SurfaceControl scheduling with controlled platform leaves.

These are synthetic host regressions, NOT Android physical timing qualification.
The worker, transaction construction, rejection and callback bodies are extracted
unchanged. Only clocks, OS scheduling, condition waiting and Android APIs are
controlled. A recorded 4.681771 ms apply duration is injected, not measured here.
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
    masked = re.sub(r'''//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])' ''',
                    lambda match: " " * len(match.group()), source,
                    flags=re.S | re.X)
    depth = 0
    for index in range(opening, len(masked)):
        if masked[index] == "{":
            depth += 1
        elif masked[index] == "}":
            depth -= 1
            if not depth:
                end = index + 1
                if semicolon:
                    assert source[end] == ";"
                    end += 1
                return source[start:end]
    raise AssertionError("unterminated production declaration: " + signature)


class SurfaceEarlySubmissionTest(unittest.TestCase):
    @classmethod
    def build_source(cls):
        native = (NATIVE / "owned_surface_control_presenter.cpp").read_text()
        header = (NATIVE / "owned_surface_control_presenter.hpp").read_text()
        structs = "\n".join(declaration(native, signature, True) for signature in (
            "struct Pending {", "struct SharedState {", "struct CallbackContext {",
            "struct CommitCallbackContext {"))
        # A deterministic OS condition-variable leaf: never sleep a real thread.
        structs = structs.replace("std::condition_variable scheduledCondition;",
                                  "ControlledCondition scheduledCondition;")
        structs += "\n" + declaration(header, "struct FrameTimeline {", True)
        constants = "\n".join(re.findall(
            r"static constexpr [^;]+;", native[native.index("class OwnedSurface"): 
                                                  native.index("struct Pending {")]))
        methods = "\n".join(declaration(native, signature) for signature in (
            "void timedApplyWorkerMain()", "void applyScheduled(uint64_t presentId)",
            "void rejectScheduled(uint64_t presentId, const char* reason,",
            "static void onComplete(void* opaque, ASurfaceTransactionStats* stats)",
            "std::vector<uint64_t> takeUnavailablePresentFences()",
            "uint64_t recordCommitDispatch(uint64_t presentId,",
            "static void onCommit(void* opaque, ASurfaceTransactionStats*) noexcept",
            "void logMissingFenceCommitLocked(const Pending& row)",
            "void recordDispatchFailureLocked(Pending& row, const char* reason) noexcept",
            "void throwIfDispatchFailedLocked() const",
            "void logApplyTimingTail(const Pending& row)"))
        source = r'''
#include <algorithm>
#include <array>
#include <atomic>
#include <cassert>
#include <cerrno>
#include <chrono>
#include <condition_variable>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <deque>
#include <fcntl.h>
#include <functional>
#include <iostream>
#include <map>
#include <memory>
#include <mutex>
#include <optional>
#include <stdexcept>
#include <string>
#include <unistd.h>
#include <vector>

uint64_t clockNs=0, cpuNs=100, injectedApplyNs=0, injectedCpuNs=17;
uint64_t timelineLookupCostNs=0,createDelayOnceNs=0;
std::function<void()> onCreate;
std::vector<std::string> logs;
struct ControlledCondition {
    bool* closing=nullptr;
    unsigned waits=0, timedWaits=0;
    void notify_all() {}
    template<class Lock,class Predicate> void wait(Lock&,Predicate ready) {
        ++waits;
        if(!ready()) {assert(closing); *closing=true;}
        assert(ready());
    }
    template<class Lock,class Time,class Predicate>
    bool wait_until(Lock&,const Time&,Predicate) {
        ++timedWaits;
        throw std::runtime_error("unexpected artificial deadline-opening wait");
    }
};
struct FixtureCpuSet {};
#define cpu_set_t FixtureCpuSet
#define CPU_ZERO(p) ((void)(p))
#define CPU_SET(cpu,p) ((void)(cpu),(void)(p))
#define pthread_self() 0
#define pthread_setname_np(thread,name) ((void)(thread),(void)(name),0)
#define setpriority(which,who,priority) ((void)(which),(void)(who),(void)(priority),0)
#define getpriority(which,who) ((void)(which),(void)(who),-10)
#define sched_setaffinity(pid,size,set) ((void)(pid),(void)(size),(void)(set),0)
#ifndef PRIO_PROCESS
#define PRIO_PROCESS 0
#endif
constexpr int ANDROID_LOG_WARN=1,ANDROID_LOG_ERROR=2;
int __android_log_print(int,const char*,const char* format,...) {
    char text[2048];va_list args;va_start(args,format);
    std::vsnprintf(text,sizeof(text),format,args);va_end(args);
    logs.emplace_back(text);return 0;
}
struct AHardwareBuffer {int references=1;};
void AHardwareBuffer_release(AHardwareBuffer* buffer){assert(buffer->references>0);--buffer->references;}
struct ASurfaceControl {int references=1;};
void ASurfaceControl_release(ASurfaceControl* surface){assert(surface->references>0);--surface->references;}
struct ARect {int left,top,right,bottom;};
using AVsyncId=int64_t;
constexpr int ASURFACE_TRANSACTION_VISIBILITY_SHOW=1;
struct ASurfaceTransactionStats {int64_t latch=-1;int present=-1;int previousRelease=-1;};
int64_t ASurfaceTransactionStats_getLatchTime(ASurfaceTransactionStats* s){return s->latch;}
int ASurfaceTransactionStats_getPresentFenceFd(ASurfaceTransactionStats* s){return s->present;}
int ASurfaceTransactionStats_getPreviousReleaseFenceFd(ASurfaceTransactionStats* s,ASurfaceControl*){
    return s->previousRelease;
}
using Callback=void(*)(void*,ASurfaceTransactionStats*);
struct ASurfaceTransaction {
    ASurfaceControl* surface=nullptr;
    AHardwareBuffer* buffer=nullptr;
    int acquire=-2,visibility=0,z=0,transform=-1;
    ARect source{},destination{};
    bool geometry=false,backpressure=false,explicitDesired=false;
    int64_t vsync=0,desired=0;
    void* opaque=nullptr;
    Callback callback=nullptr;
    void* commitOpaque=nullptr;
    Callback commitCallback=nullptr;
};
std::vector<ASurfaceTransaction> applied;
std::vector<int> platformAcquireFds;
unsigned creates=0,deletes=0;
bool createFails=false;
bool openFd(int fd){return fd>=0 && ::fcntl(fd,F_GETFD)>=0;}
int newFd(){int fds[2];assert(::pipe(fds)==0);::close(fds[1]);return fds[0];}
ASurfaceTransaction* ASurfaceTransaction_create(){
    ++creates;clockNs+=createDelayOnceNs;createDelayOnceNs=0;
    if(onCreate){const auto callback=onCreate;onCreate=nullptr;callback();}
    return createFails?nullptr:new ASurfaceTransaction;
}
void ASurfaceTransaction_delete(ASurfaceTransaction* t){++deletes;delete t;}
void ASurfaceTransaction_setBuffer(ASurfaceTransaction* t,ASurfaceControl* s,AHardwareBuffer* b,int fd){
    assert(t->acquire==-2);assert(fd==-1 || openFd(fd));
    t->surface=s;t->buffer=b;t->acquire=fd;
    if(fd>=0)platformAcquireFds.push_back(fd);
}
void ASurfaceTransaction_setGeometry(ASurfaceTransaction* t,ASurfaceControl*,ARect s,ARect d,int transform){
    t->source=s;t->destination=d;t->transform=transform;t->geometry=true;
}
void ASurfaceTransaction_setVisibility(ASurfaceTransaction* t,ASurfaceControl*,int value){t->visibility=value;}
void ASurfaceTransaction_setZOrder(ASurfaceTransaction* t,ASurfaceControl*,int value){t->z=value;}
void ASurfaceTransaction_setDesiredPresentTime(ASurfaceTransaction* t,int64_t value){
    t->desired=value;t->explicitDesired=true;
}
void ASurfaceTransaction_setOnComplete(ASurfaceTransaction* t,void* opaque,Callback callback){
    t->opaque=opaque;t->callback=callback;
}
void ASurfaceTransaction_setOnCommit(ASurfaceTransaction* t,void* opaque,Callback callback){
    t->commitOpaque=opaque;t->commitCallback=callback;
}
void ASurfaceTransaction_apply(ASurfaceTransaction* t){
    assert(t->callback && t->opaque && t->buffer && t->backpressure);
    applied.push_back(*t);clockNs+=injectedApplyNs;cpuNs+=injectedCpuNs;
}
struct Fixture {
    using Impl=Fixture;
''' + constants + "\n" + structs + r'''
    std::array<AHardwareBuffer,16> buffers;
    ASurfaceControl surface;
    std::shared_ptr<SharedState> state_=std::make_shared<SharedState>();
    ASurfaceControl* surface_=&surface;
    std::mutex applyMutex_;
    std::atomic<bool> timedApplyStop_{false};
    uint64_t lastSubmittedPresentId_=0;
    ARect source_{0,0,1280,720},destination_{0,0,1920,1080};
    std::map<uint64_t,FrameTimeline> timelines;
    std::vector<int> inputFds;
    void (*setOnCommit_)(ASurfaceTransaction*,void*,Callback)=ASurfaceTransaction_setOnCommit;
    Fixture(){
        assert(applied.empty() && platformAcquireFds.empty());
        clockNs=0;cpuNs=100;injectedApplyNs=0;injectedCpuNs=17;
        timelineLookupCostNs=0;createDelayOnceNs=0;onCreate=nullptr;
        creates=deletes=0;createFails=false;logs.clear();
        state_->scheduledCondition.closing=&state_->closing;
        state_->commitObservationAvailable=true;
    }
    ~Fixture(){
        // Android callback leaf supplies UNKNOWN, never fabricated scanout.
        for(auto& transaction:applied){
            ASurfaceTransactionStats unknown;
            if(transaction.commitOpaque){
                transaction.commitCallback(transaction.commitOpaque,&unknown);
                transaction.commitOpaque=nullptr;
            }
            if(transaction.opaque)transaction.callback(transaction.opaque,&unknown);
            transaction.opaque=nullptr;
        }
        applied.clear();
        for(int fd:platformAcquireFds){assert(openFd(fd));::close(fd);}
        platformAcquireFds.clear();state_.reset();
        assert(surface.references==1);
    }
    static uint64_t monotonicNs(){return clockNs;}
    static uint64_t diagnosticMonotonicNs() noexcept {return clockNs;}
    static uint64_t threadCpuNs(){return cpuNs;}
    static void acquireSurface_(ASurfaceControl* s){++s->references;}
    static void setBackPressure_(ASurfaceTransaction* t,ASurfaceControl*,bool value){t->backpressure=value;}
    static void setFrameTimelineLeaf(ASurfaceTransaction* t,AVsyncId value){t->vsync=value;}
    void (*setFrameTimeline_)(ASurfaceTransaction*,AVsyncId)=setFrameTimelineLeaf;
    std::optional<FrameTimeline> nativeFrameTimeline(uint64_t vsync){
        clockNs+=timelineLookupCostNs;
        const auto found=timelines.find(vsync);
        return found==timelines.end()?std::nullopt:std::optional<FrameTimeline>(found->second);
    }
    int add(uint64_t id,uint64_t deadline,bool queue=true){
        Pending row;row.presentId=id;row.frameTimelineVsyncId=id+10000;
        row.frameTimelineDeadlineNs=deadline;
        row.frameTimelineExpectedNs=deadline+10'333'333;
        row.desiredPresentTimeNs=row.frameTimelineExpectedNs-2'000'000;
        row.frameTimelineRefreshDurationNs=8'333'333;
        row.buffer=&buffers.at(state_->pending.size());++row.buffer->references;
        row.acquireFenceFd=newFd();inputFds.push_back(row.acquireFenceFd);
        timelines.emplace(row.frameTimelineVsyncId,FrameTimeline{
                row.frameTimelineVsyncId,row.frameTimelineExpectedNs,deadline});
        state_->pending.emplace(id,row);if(queue)state_->scheduled.push_back(id);
        return row.acquireFenceFd;
    }
''' + methods + r'''
};
constexpr uint64_t DEADLINE=1'000'000'000,OUTLIER=4'681'771;
void assertIdentity(const Fixture::Pending& before,const Fixture::Pending& after){
    assert(before.presentId==after.presentId);
    assert(before.frameTimelineVsyncId==after.frameTimelineVsyncId);
    assert(before.frameTimelineExpectedNs==after.frameTimelineExpectedNs);
    assert(before.frameTimelineDeadlineNs==after.frameTimelineDeadlineNs);
    assert(before.desiredPresentTimeNs==after.desiredPresentTimeNs);
    assert(before.buffer==after.buffer);
}
void assertTransaction(const Fixture& f,const ASurfaceTransaction& t,const Fixture::Pending& before){
    assert(t.vsync==static_cast<int64_t>(before.frameTimelineVsyncId));
    // An explicit timestamp disables Android 13's frame-timeline early-frame
    // gate AND pending-buffer backpressure. Preserve the exact vsync token and
    // leave the new transaction automatically timestamped for this path.
    assert(before.frameTimelineVsyncId!=0 && !t.explicitDesired && t.desired==0);
    assert(t.buffer==before.buffer && t.surface==f.surface_);
    assert(t.geometry && t.source.right==1280 && t.source.bottom==720);
    assert(t.destination.right==1920 && t.destination.bottom==1080 && t.transform==0);
    assert(t.backpressure && t.visibility==ASURFACE_TRANSACTION_VISIBILITY_SHOW && t.z==1);
    const auto* callback=static_cast<const Fixture::CallbackContext*>(t.opaque);
    assert(callback->presentId==before.presentId);
}
void ready_slack_and_legacy_control(){
    {
        Fixture f;const int fd=f.add(3742,DEADLINE,false);
        clockNs=DEADLINE-2'000'000;injectedApplyNs=OUTLIER;
        f.applyScheduled(3742); // Actual apply at the old opening time.
        const auto& row=f.state_->pending.at(3742);
        assert(row.transactionApplyEndNs==DEADLINE+2'681'771);
        assert(row.acquireFenceFd==-1 && openFd(fd) && !row.submissionRejected);
        assert(row.buffer->references==2 && f.state_->scheduledRejected==0);
        assert(!row.physicalDelivered && f.state_->completed==0);
    }
    {
        Fixture f;const int fd=f.add(3742,DEADLINE);
        const auto original=f.state_->pending.at(3742);
        clockNs=DEADLINE-8'000'000;injectedApplyNs=OUTLIER;
        f.timedApplyWorkerMain();
        const auto& row=f.state_->pending.at(3742);
        assert(row.workerDequeueNs==DEADLINE-8'000'000);
        assert(row.transactionApplyStartNs==DEADLINE-8'000'000);
        assert(row.transactionApplyEndNs==DEADLINE-3'318'229);
        assert(row.transactionApplyCpuEndNs-row.transactionApplyCpuStartNs==injectedCpuNs);
        assert(row.transactionApplyEndNs<original.desiredPresentTimeNs);
        assert(f.state_->scheduledCondition.timedWaits==0);
        assert(applied.size()==1 && creates==1 && deletes==1);
        assertIdentity(original,row);assertTransaction(f,applied.front(),original);
        assert(applied.front().acquire==fd && openFd(fd) && row.acquireFenceFd==-1);
        assert(!row.physicalDelivered && !row.callbackReceived && f.state_->completed==0);
        assert(f.state_->scheduledRejected==0);
    }
}
void fifo_and_exact_future_bounds(){
    Fixture f;f.add(1,DEADLINE-100'000'000,false); // Existing older, nonscheduled ownership.
    for(uint64_t id=10;id<=12;++id)f.add(id,DEADLINE+(id-10)*16'666'666);
    clockNs=DEADLINE-8'000'000;injectedApplyNs=OUTLIER;
    f.timedApplyWorkerMain();assert(applied.size()==3);
    for(size_t index=0;index<applied.size();++index){
        const uint64_t id=10+index;const auto& row=f.state_->pending.at(id);
        const auto* callback=static_cast<const Fixture::CallbackContext*>(applied[index].opaque);
        assert(callback->presentId==id);
        assert(callback->previousPresentId==(index==0?0:id-1));
        assert(applied[index].commitCallback && applied[index].commitOpaque);
        assert(row.commitObservationSerial==index+1);
        assert(row.predecessorPresentId==(index==0?0:id-1));
        assert(row.predecessorCommitSnapshotKnown==(index!=0));
        assert(!row.predecessorCommitObservedAtDispatch);
        assertTransaction(f,applied[index],row);
        assert(row.transactionApplyEndNs<row.frameTimelineDeadlineNs);
        assert(row.transactionApplyEndNs<row.desiredPresentTimeNs);
        assert(!row.physicalDelivered && row.acquireFenceFd==-1);
    }
    assert(f.lastSubmittedPresentId_==12 && f.state_->scheduled.empty());
    assert(f.state_->pending.at(1).acquireFenceFd>=0);
    assert(f.state_->pending.at(1).transactionApplyStartNs==0);
    assert(f.state_->pending.at(10).nextDispatchPresentId==11);
    assert(!f.state_->pending.at(10).commitObservedAtNextDispatch);
}
void rejected_before_transfer(const std::string& scenario){
    Fixture f;const int fd=f.add(1,DEADLINE);f.add(2,DEADLINE+20'000'000);
    auto& first=f.state_->pending.at(1);const auto original=first;
    clockNs=DEADLINE-8'000'000;
    std::string reason;
    if(scenario=="expired"){clockNs=DEADLINE+1;reason="deadline-expired";}
    else if(scenario=="exact"){clockNs=DEADLINE;reason="deadline-expired";}
    else if(scenario=="expected"){++f.timelines.at(first.frameTimelineVsyncId).expectedPresentationTimeNs;reason="expected-revised";}
    else if(scenario=="deadline"){++f.timelines.at(first.frameTimelineVsyncId).deadlineNs;reason="deadline-revised";}
    else if(scenario=="zero-refresh"){first.frameTimelineRefreshDurationNs=0;reason="refresh-invalid";}
    else if(scenario=="overflow-refresh"){first.frameTimelineRefreshDurationNs=UINT64_MAX;reason="refresh-invalid";}
    else if(scenario=="lookup-expiry"){timelineLookupCostNs=8'000'001;reason="deadline-expired-at-apply";}
    else if(scenario=="create-exact"){createDelayOnceNs=8'000'000;reason="deadline-expired-at-handoff";}
    else if(scenario=="create-late"){createDelayOnceNs=8'000'001;reason="deadline-expired-at-handoff";}
    else if(scenario=="handoff-expected"){
        onCreate=[&]{++f.timelines.at(first.frameTimelineVsyncId).expectedPresentationTimeNs;};
        reason="timeline-revised-at-handoff";
    }
    else if(scenario=="handoff-deadline"){
        onCreate=[&]{++f.timelines.at(first.frameTimelineVsyncId).deadlineNs;};
        reason="timeline-revised-at-handoff";
    }
    else assert(false);
    f.timedApplyWorkerMain();
    assert(first.submissionRejected && first.released && !first.physicalDelivered);
    assert(first.transactionApplyStartNs==0 && first.acquireFenceFd==-1 && !openFd(fd));
    assertIdentity(original,first);
    const unsigned expectedCreates=scenario.starts_with("create-") ||
            scenario.starts_with("handoff-") ? 2 : 1;
    assert(applied.size()==1 && creates==expectedCreates && deletes==expectedCreates);
    const auto* callback=static_cast<const Fixture::CallbackContext*>(applied.front().opaque);
    assert(callback->presentId==2 && callback->previousPresentId==0);
    assert(f.state_->scheduledRejected==1 && f.state_->completed==0);
    assert(std::any_of(logs.begin(),logs.end(),[&](const std::string& text){return text.find("reason="+reason)!=std::string::npos;}));
}
void missing_rolling_token_is_not_relabelled(){
    Fixture f;f.add(1,DEADLINE);const auto original=f.state_->pending.at(1);
    f.timelines.clear();clockNs=DEADLINE-8'000'000;injectedApplyNs=OUTLIER;
    f.timedApplyWorkerMain();
    assert(applied.size()==1 && f.state_->scheduledRejected==0);
    assertIdentity(original,f.state_->pending.at(1));assertTransaction(f,applied.front(),original);
}
void unknown_callback_is_not_a_present(){
    Fixture f;f.add(1,DEADLINE);clockNs=DEADLINE-8'000'000;
    f.timedApplyWorkerMain();assert(applied.size()==1);
    auto& transaction=applied.front();ASurfaceTransactionStats unknown;
    transaction.callback(transaction.opaque,&unknown);transaction.opaque=nullptr;
    const auto& row=f.state_->pending.at(1);
    assert(row.callbackReceived && row.rawCallbackLatchTimeNs==-1 && row.presentFenceFd==-1);
    assert(!row.physicalDelivered && row.latchTimeNs==0 && f.state_->completed==0);
    assert(f.takeUnavailablePresentFences()==std::vector<uint64_t>{1});
    assert(f.takeUnavailablePresentFences().empty());
    assert(!row.physicalDelivered && f.state_->completed==0 && f.state_->dropped==0);
}
void already_expired_at_apply_and_tokenless_boundary(){
    {
        Fixture f;const int fd=f.add(1,DEADLINE,false);clockNs=DEADLINE;
        f.applyScheduled(1);
        assert(applied.empty() && creates==0 && !openFd(fd));
        assert(f.state_->pending.at(1).submissionRejected && f.lastSubmittedPresentId_==0);
    }
    {
        Fixture f;f.add(1,DEADLINE,false);auto& row=f.state_->pending.at(1);
        row.frameTimelineVsyncId=0;row.frameTimelineDeadlineNs=0;
        row.frameTimelineExpectedNs=0;row.desiredPresentTimeNs=DEADLINE+30'000'000;
        clockNs=DEADLINE;f.applyScheduled(1);
        assert(applied.size()==1 && applied.front().vsync==0);
        assert(applied.front().explicitDesired);
        assert(applied.front().desired==static_cast<int64_t>(row.desiredPresentTimeNs));
        assert(!row.submissionRejected && !row.physicalDelivered);
    }
}
void bounded_diagnostics_keep_identity_and_unknown_cpu(){
    Fixture f;const int fd=f.add(1,DEADLINE,false);
    auto& row=f.state_->pending.at(1);
    const auto identity=row;
    row.enqueueNs=DEADLINE-9'000'000;
    row.workerDequeueNs=DEADLINE-8'100'000;
    row.applyLockAcquiredNs=DEADLINE-8'000'100;
    row.transactionApplyStartNs=0;row.transactionApplyEndNs=10;
    f.logApplyTimingTail(row);assert(logs.empty());
    row.transactionApplyStartNs=100;row.transactionApplyEndNs=99;
    f.logApplyTimingTail(row);assert(logs.empty());
    row.transactionApplyStartNs=DEADLINE-8'000'000;
    row.transactionApplyEndNs=row.transactionApplyStartNs+
            Fixture::kApplyTailDiagnosticThresholdNs-1;
    f.logApplyTimingTail(row);assert(logs.empty());
    row.transactionApplyEndNs=row.transactionApplyStartNs+OUTLIER;
    row.transactionApplyCpuStartNs=100;row.transactionApplyCpuEndNs=117;
    f.logApplyTimingTail(row);assert(logs.size()==1);
    assert(logs.back().find("presentId=1 vsyncId=10001")!=std::string::npos);
    assert(logs.back().find("expectedNs="+std::to_string(identity.frameTimelineExpectedNs))!=std::string::npos);
    assert(logs.back().find("deadlineNs="+std::to_string(DEADLINE))!=std::string::npos);
    assert(logs.back().find("driverDesiredNs="+std::to_string(identity.desiredPresentTimeNs))!=std::string::npos);
    assert(logs.back().find("enqueueNs="+std::to_string(row.enqueueNs))!=std::string::npos);
    assert(logs.back().find("dequeueNs="+std::to_string(row.workerDequeueNs))!=std::string::npos);
    assert(logs.back().find("lockAcquiredNs="+std::to_string(row.applyLockAcquiredNs))!=std::string::npos);
    assert(logs.back().find("wallNs=4681771 cpuKnown=1 cpuNs=17 deadlineCrossed=0")!=std::string::npos);
    // Even a tiny wall interval is logged when it crosses the exact deadline.
    row.transactionApplyStartNs=DEADLINE-1;row.transactionApplyEndNs=DEADLINE+1;
    row.transactionApplyCpuStartNs=0;row.transactionApplyCpuEndNs=17;
    f.logApplyTimingTail(row);assert(logs.size()==2);
    assert(logs.back().find("wallNs=2 cpuKnown=0 cpuNs=0 deadlineCrossed=1")!=std::string::npos);
    row.transactionApplyCpuStartNs=100;row.transactionApplyCpuEndNs=99;
    f.logApplyTimingTail(row);assert(logs.size()==3);
    assert(logs.back().find("cpuKnown=0 cpuNs=0")!=std::string::npos);
    // Invalid CPU evidence is diagnostic only; no physical status is upgraded.
    for(int index=0;index<100;++index)f.logApplyTimingTail(row);
    assert(logs.size()==Fixture::kMaximumApplyTailLogs && logs.size()==12);
    assert(f.state_->applyTailLogs==12 && f.state_->completed==0 && f.state_->dropped==0);
    assertIdentity(identity,row);
    assert(!row.callbackReceived && !row.physicalDelivered && !row.released);
    assert(!row.unavailableReported && !row.submissionRejected && row.presentFenceFd==-2);
    assert(row.acquireFenceFd==fd && openFd(fd) && row.buffer->references==2);
    assert(row.transactionApplyStartNs==DEADLINE-1 && row.transactionApplyEndNs==DEADLINE+1);
    assert(row.transactionApplyCpuStartNs==100 && row.transactionApplyCpuEndNs==99);
    assert(applied.empty() && creates==0 && deletes==0 && f.lastSubmittedPresentId_==0);
}
void optional_commit_observation_unavailable(){
    Fixture f;f.setOnCommit_=nullptr;f.state_->commitObservationAvailable=false;
    f.add(1,DEADLINE);const auto original=f.state_->pending.at(1);
    clockNs=DEADLINE-8'000'000;f.timedApplyWorkerMain();
    assert(applied.size()==1 && !applied.front().commitCallback && !applied.front().commitOpaque);
    const auto& row=f.state_->pending.at(1);assertIdentity(original,row);
    assertTransaction(f,applied.front(),row);
    assert(row.commitObservationSerial==0 && !row.commitCallbackObserved);
    assert(f.state_->nextCommitObservationSerial==0 && !row.physicalDelivered);
    assert(!row.submissionRejected && f.state_->scheduledRejected==0);
    f.logMissingFenceCommitLocked(row); // Observation unavailable is explicit, not false commit evidence.
    assert(logs.size()==1 && logs.back().find("serial=0 available=0")!=std::string::npos);
}
int main(int argc,char** argv){
    assert(argc==2);const std::string name=argv[1];
    if(name=="slack")ready_slack_and_legacy_control();
    else if(name=="fifo")fifo_and_exact_future_bounds();
    else if(name=="missing-token")missing_rolling_token_is_not_relabelled();
    else if(name=="unknown")unknown_callback_is_not_a_present();
    else if(name=="apply-boundary")already_expired_at_apply_and_tokenless_boundary();
    else if(name=="diagnostics")bounded_diagnostics_keep_identity_and_unknown_cpu();
    else if(name=="no-commit-api")optional_commit_observation_unavailable();
    else rejected_before_transfer(name);
    std::cout<<"PASS synthetic-host "<<name<<'\n';
}
'''
        return source

    @classmethod
    def setUpClass(cls):
        source = cls.build_source()
        compiler = shutil.which("c++")
        if compiler is None:
            raise AssertionError("C++ compiler is required")
        cls.temporary = tempfile.TemporaryDirectory(prefix="lsfg-early-submission-")
        cls.addClassCleanup(cls.temporary.cleanup)
        directory = Path(cls.temporary.name)
        unit = directory / "fixture.cpp"
        unit.write_text(source)
        cls.binary = directory / "fixture"
        result = subprocess.run([
            compiler, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-g", "-O1",
            "-fsanitize=address,undefined", str(unit), "-o", str(cls.binary),
        ], capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    def run_case(self, name):
        env = dict(os.environ, ASAN_OPTIONS="detect_leaks=0:abort_on_error=1",
                   UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")
        result = subprocess.run([str(self.binary), name], capture_output=True,
                                text=True, timeout=10, env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS synthetic-host " + name, result.stdout)

    def test_recorded_apply_outlier_uses_early_ready_slack_without_retiming(self):
        self.run_case("slack")

    def test_actual_worker_and_apply_keep_fifo_bounds_geometry_and_acquire_ownership(self):
        self.run_case("fifo")

    def test_optional_commit_api_absence_does_not_change_admission_or_handoff(self):
        self.run_case("no-commit-api")

    def test_exact_and_expired_deadlines_reject_before_android_transfer(self):
        for name in ("exact", "expired"):
            with self.subTest(name=name):
                self.run_case(name)

    def test_revised_expected_and_deadline_reject_without_relabelling_or_wedging_fifo(self):
        for name in ("expected", "deadline"):
            with self.subTest(name=name):
                self.run_case(name)

    def test_invalid_refresh_rejects_before_android_transfer(self):
        for name in ("zero-refresh", "overflow-refresh"):
            with self.subTest(name=name):
                self.run_case(name)

    def test_expiry_between_worker_preflight_and_apply_rechecks_before_transfer(self):
        self.run_case("lookup-expiry")

    def test_transaction_creation_delay_expiring_at_or_after_deadline_rejects_before_handoff(self):
        for name in ("create-exact", "create-late"):
            with self.subTest(name=name):
                self.run_case(name)

    def test_timeline_revised_during_transaction_creation_rejects_before_handoff(self):
        for name in ("handoff-expected", "handoff-deadline"):
            with self.subTest(name=name):
                self.run_case(name)

    def test_absent_rolling_token_keeps_original_admitted_identity(self):
        self.run_case("missing-token")

    def test_actual_unknown_callback_does_not_turn_early_submission_into_physical_success(self):
        self.run_case("unknown")

    def test_apply_boundary_rejects_expired_token_and_preserves_tokenless_driver_bound(self):
        self.run_case("apply-boundary")

    def test_actual_tail_diagnostics_bound_logs_preserve_identity_and_mark_unknown_cpu(self):
        self.run_case("diagnostics")


if __name__ == "__main__":
    unittest.main()
