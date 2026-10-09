"""Host fault injection of production cutoff/retirement bodies, not GPU evidence.

Android/Vulkan/sync leaves are instrumented stand-ins. The visible submission
prefix is verbatim production; its unchanged GPU-submit tail is a sentinel.
No timing deadline, pixel quality, or device qualification is inferred here.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / "unified-android/lsfg-qualification-native"


def body(text, signature):
    start = text.index(signature)
    opening = text.index("{", start)
    depth, end = 1, opening + 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


class LsfgCutoffRetirementTest(unittest.TestCase):
    def compile_run(self, source):
        compiler = shutil.which("c++")
        self.assertIsNotNone(compiler)
        with tempfile.TemporaryDirectory(prefix="lsfg-cutoff-fixture-") as temporary:
            root = Path(temporary)
            unit = root / "fixture.cpp"
            unit.write_text(source)
            binary = root / "fixture"
            result = subprocess.run([compiler, "-std=c++20", "-Wall", "-Wextra", "-Werror",
                                     "-fsanitize=address,undefined", str(unit), "-o", str(binary)],
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_actual_two_cutoffs_fence_ownership_timeout_and_bounded_diagnostics(self):
        native = (NATIVE / "owned_vulkan_host.cpp").read_text()
        header = (NATIVE / "owned_vulkan_host.hpp").read_text()
        types = "\n".join(body(header, signature) + ";" for signature in (
            "struct LiveRequest", "struct SurfaceSubmission", "struct Completion"))
        types += "\n" + "\n".join(body(native, signature) + ";" for signature in (
            "enum class LiveSlotState", "struct LiveSlot {", "struct DropDrainObservation"))
        methods = "\n".join(body(native, signature) for signature in (
            "DropDrainObservation observeDropDrain(", "void logSurfaceCutoffDrop(",
            "void markSurfaceCutoffDrop(", "std::optional<Completion> pollDroppedSurfacePresentation()",
            "uint64_t oldestPendingSurfacePresentId() const", "void resetLiveSlotStorage(",
            "void resetTimeline("))
        submission_prefix = body(native, "std::optional<SurfaceSubmission> pollSurfaceSubmission()")
        submission_prefix = submission_prefix.split("        try {", 1)[0] + r'''
        ++surfaceSubmits;
        slot.state=LiveSlotState::SurfaceProofQueued;
        return SurfaceSubmission{.presentId=slot.request.presentId};
    }
'''
        source = r'''
#include <algorithm>
#include <array>
#include <cassert>
#include <cerrno>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <map>
#include <memory>
#include <optional>
#include <poll.h>
#include <stdexcept>
#include <string>
#include <vector>
using VkResult=int; using VkCommandBuffer=int; using VkFence=int; using VkSemaphore=int;
using VkImage=int; using VkDeviceMemory=int; using VkBuffer=int; using AHardwareBuffer=int;
constexpr int VK_SUCCESS=0,VK_NOT_READY=1,VK_NULL_HANDLE=0;
constexpr uint64_t kDroppedDrainTimeoutNs=1000000000ULL,kCutoffDiagnosticRequestLimit=8;
struct ImportedImage {};
uint64_t clockNs=100;
uint64_t monotonicNs(){return clockNs;}
void requireSuccess(int status,const char*){if(status!=VK_SUCCESS)throw std::runtime_error("device failure");}
struct Fence {
    int pollStatus=1,pollError=EBADF,infoError=0,events=POLLIN,status=1,childStatus=1;
    uint32_t count=1;uint64_t signalNs=98;int closes=0;
};
std::map<int,Fence> fds;
std::map<int,int> vkFences;
extern "C" int poll(pollfd* p,nfds_t count,int timeout){
    assert(count==1 && timeout==0);auto& f=fds.at(p->fd);assert(f.closes==0);
    p->revents=f.events;errno=f.pollError;return f.pollStatus;
}
extern "C" int close(int fd){++fds.at(fd).closes;assert(fds.at(fd).closes==1);return 0;}
struct sync_fence_info {int status;uint64_t timestamp_ns;};
struct sync_file_info {int status;uint32_t num_fences;sync_fence_info child;};
// GCC reads "new struct X{...}" as a type definition; name the type once.
typedef struct sync_file_info SyncFileInfo;
struct sync_file_info* sync_file_info(int fd){const auto& f=fds.at(fd);
    if(f.infoError!=0){errno=f.infoError;return nullptr;}
    return new SyncFileInfo{f.status,f.count,{f.childStatus,f.signalNs}};}
void sync_file_info_free(struct sync_file_info* info){delete info;}
const sync_fence_info* sync_get_fence_info(struct sync_file_info* info){return &info->child;}
std::vector<std::string> logs;
void log(const char* format,...){char line[4096];va_list args;va_start(args,format);
    int size=vsnprintf(line,sizeof(line),format,args);va_end(args);
    assert(size>0 && static_cast<size_t>(size)<sizeof(line));logs.emplace_back(line);}
#define LOGE(...) log(__VA_ARGS__)
''' + body(native, "struct ReadyFenceObservation") + ";\n" + body(native, "ReadyFenceObservation observeReadyFence(") + r'''
struct Fixture {
''' + types + r'''
    std::array<LiveSlot,3> live_{};
    bool fatal_=false,surfaceCutoffQuarantineLogged_=false,advanceOnReady=false;
    int device_=1,surfaceSubmits=0;uint32_t pendingPresentations_=0;
    uint64_t surfaceCutoffDrops_=0,surfaceCutoffRetired_=0,presentationEpoch_=1;
    struct Device {int vkGetFenceStatus(int,int fence){return vkFences.at(fence);}} deviceFunctions_;
    struct Writer {int discards=0;void discard(uint64_t,const char*){++discards;}} writer;
    Writer* tripletWriter_=&writer;
    void retireAbandonedCopies(){}
    bool readyFdSignaled(LiveSlot& slot){
        bool result=observeReadyFence(slot.readySyncFd).ready;
        if(advanceOnReady)clockNs=100;
        return result;
    }
''' + methods + "\n" + submission_prefix + r'''
    LiveSlot& admit(uint32_t index,uint64_t id,uint64_t deadline=100){
        LiveSlot& slot=live_[index];assert(slot.state==LiveSlotState::Idle);
        slot.state=LiveSlotState::AwaitingReady;
        slot.request=LiveRequest{.presentId=id,.physicalPresentTimeNs=deadline+20,
            .desiredPresentTimeNs=deadline+10,.completionDeadlineNs=deadline,
            .refreshDurationNs=8,.compositorFrameTimelineVsyncId=1000+id,
            .compositorFrameTimelineExpectedNs=deadline+20,
            .compositorFrameTimelineDeadlineNs=deadline,.sessionEpoch=4,.presentationEpoch=5,
            .leftSequence=20,.rightSequence=21,.leftTimestampNs=20,.rightTimestampNs=40,
            .contentTimestampNs=20};
        slot.copyFence=1+index*2;slot.presentFence=2+index*2;
        slot.readySyncFd=11+index;slot.sourceLeft=reinterpret_cast<ImportedImage*>(1);
        slot.sourceRight=reinterpret_cast<ImportedImage*>(2);++pendingPresentations_;
        fds[slot.readySyncFd]=Fence{};vkFences[slot.copyFence]=VK_SUCCESS;
        vkFences[slot.presentFence]=VK_NOT_READY;return slot;
    }
};
void reset(){fds.clear();vkFences.clear();logs.clear();clockNs=100;}
int main(){
    // Already-ready output polled at the cutoff is still a DROP, not a late
    // submission or a deadline reanchor. Preserve exact ID, role and epoch.
    reset();{
        Fixture f;auto& old=f.admit(0,7);f.admit(1,8,200);
        assert(!f.pollSurfaceSubmission());assert(!f.fatal_ && old.cutoffBranch==1);
        assert(old.readySyncFd==11 && fds[11].closes==0 && f.oldestPendingSurfacePresentId()==7);
        assert(!f.pollSurfaceSubmission() && f.surfaceSubmits==0); // New request cannot pass barrier.
        auto row=f.pollDroppedSurfacePresentation();assert(row && row->dropped && row->presentId==7);
        assert(row->actualPresentTimeNs==0 && row->earliestPresentTimeNs==0 && row->gpuCompletionNs==0);
        assert(row->desiredPresentTimeNs==110 && row->refreshDurationNs==8);
        assert(f.pendingPresentations_==1 && f.surfaceCutoffDrops_==1 && f.surfaceCutoffRetired_==1);
        assert(fds[11].closes==1 && old.state==Fixture::LiveSlotState::Idle && old.sourceLeft==nullptr);
        assert(!f.pollDroppedSurfacePresentation() && f.pendingPresentations_==1); // No double decrement.
        assert(logs[0].find("presentId=7 sessionEpoch=4 presentationEpoch=5 generated=0")!=std::string::npos);
        assert(logs[0].find("kernelSignalKnown=1 kernelSignalNs=98 physicalSubmitted=0")!=std::string::npos);
        f.resetTimeline(99);assert(f.surfaceCutoffDrops_==1 && f.surfaceCutoffRetired_==1);
        auto next=f.pollSurfaceSubmission();assert(next && next->presentId==8 && f.surfaceSubmits==1);
    }
    // Second cutoff branch: zero-poll began on time but returned at cutoff.
    reset();{
        Fixture f;auto& s=f.admit(0,1);clockNs=99;f.advanceOnReady=true;
        assert(!f.pollSurfaceSubmission() && s.cutoffBranch==2 && !f.fatal_);
        assert(f.pollDroppedSurfacePresentation()->presentId==1 && f.surfaceSubmits==0);
    }
    // Busy copy/output retains the FD, source references and slot. No wait or
    // metadata-only drop can let Java close the Images while GPU work runs.
    reset();{
        Fixture f;auto& s=f.admit(0,1);vkFences[1]=VK_NOT_READY;fds[11].pollStatus=0;
        assert(!f.pollSurfaceSubmission());f.resetTimeline(6);
        assert(!f.pollDroppedSurfacePresentation() && !f.fatal_ && f.pendingPresentations_==1);
        assert(s.sourceLeft!=nullptr && s.readySyncFd==11 && fds[11].closes==0 && s.request.presentationEpoch==5);
        clockNs=180;vkFences[1]=VK_SUCCESS;fds[11].pollStatus=1;fds[11].signalNs=175;
        assert(f.pollDroppedSurfacePresentation()->presentId==1 && fds[11].closes==1);
    }
    // Generated private proof needs its actual submitted presentFence as well
    // as the ready FD/copy fence; a reset fence on an endpoint does not.
    reset();{
        Fixture f;auto& s=f.admit(0,1);s.privateProofPrepared=true;s.request.generated=true;
        s.request.contentTimestampNs=30;s.fullCaptureId=9;s.proofTimestampSyncFd=31;fds[31]=Fence{};
        assert(!f.pollSurfaceSubmission());assert(!f.pollDroppedSurfacePresentation());
        assert(f.writer.discards==0 && fds[11].closes==0 && fds[31].closes==0);
        vkFences[2]=VK_SUCCESS;auto row=f.pollDroppedSurfacePresentation();assert(row && row->dropped);
        assert(f.writer.discards==1 && fds[11].closes==1 && fds[31].closes==1);
    }
    // Sentinel is explicit already-ready, not an invented kernel timestamp.
    reset();{
        Fixture f;auto& s=f.admit(0,1);s.readySyncFd=-1;
        assert(!f.pollSurfaceSubmission());assert(f.pollDroppedSurfacePresentation());
        assert(logs[0].find("kernelSignalKnown=0 kernelSignalNs=0")!=std::string::npos);
    }
    // Valid signaled empty/missing-time information proves readiness only;
    // it is not an unknown/error fence and never supplies a fabricated time.
    for(int missing=0;missing<2;++missing){reset();Fixture f;f.admit(0,1);
        if(missing==0)fds[11].count=0;else fds[11].signalNs=0;
        assert(!f.pollSurfaceSubmission());assert(f.pollDroppedSurfacePresentation() && !f.fatal_);
        assert(logs[0].find("outputReady=1 kernelSignalKnown=0 kernelSignalNs=0")!=std::string::npos);
    }
    // EINTR/EAGAIN do not imply a lost device or prove readiness. Return to
    // the owner immediately, retain all dependencies, then zero-poll again.
    for(int transient=0;transient<4;++transient){reset();Fixture f;f.admit(0,1);
        if(transient<2){fds[11].pollStatus=-1;fds[11].pollError=transient==0?EINTR:EAGAIN;}
        else fds[11].infoError=transient==2?EINTR:EAGAIN;
        assert(!f.pollSurfaceSubmission() && !f.pollDroppedSurfacePresentation() && !f.fatal_);
        assert(fds[11].closes==0 && logs[0].find("outputReady=-1")!=std::string::npos);
        fds[11].pollStatus=1;fds[11].infoError=0;
        assert(f.pollDroppedSurfacePresentation() && fds[11].closes==1);
    }
    // An already-submitted compositor rejection still waits for proof, never
    // changes to the new pre-submit state or manufactures a physical time.
    reset();{
        Fixture f;auto& s=f.admit(0,1);s.state=Fixture::LiveSlotState::SurfaceDroppedAwaitingProof;
        assert(!f.pollDroppedSurfacePresentation());vkFences[2]=VK_SUCCESS;
        auto row=f.pollDroppedSurfacePresentation();assert(row && row->dropped && row->actualPresentTimeNs==0);
        assert(f.surfaceCutoffDrops_==0 && f.surfaceCutoffRetired_==0);
    }
    // Every unknown/error completion is fatal and retains the exact slot.
    for(int failure=0;failure<9;++failure){reset();Fixture f;auto& s=f.admit(0,1);
        if(failure==0)fds[11].pollStatus=-1;
        if(failure==1)fds[11].events=POLLNVAL;
        if(failure==2)fds[11].status=-1;
        if(failure==3)fds[11].status=0;
        if(failure==4)fds[11].childStatus=0;
        if(failure==5)fds[11].events=POLLERR;
        if(failure==6)fds[11].infoError=EINVAL;
        if(failure==7)vkFences[1]=-4;
        if(failure==8){s.privateProofPrepared=true;vkFences[2]=-4;}
        try{f.pollSurfaceSubmission();assert(false);}catch(const std::runtime_error&){}
        assert(f.fatal_ && s.state==Fixture::LiveSlotState::SurfaceDroppedAwaitingReady);
        assert(f.pendingPresentations_==1 && fds[11].closes==0 && s.sourceLeft!=nullptr);
        try{f.pollDroppedSurfacePresentation();assert(false);}catch(const std::runtime_error&){}
    }
    // Stuck work hits a separate fixed drain watchdog, not a relaxed visible
    // deadline. It cannot be cleared by a presentation epoch reset.
    reset();{
        Fixture f;auto& s=f.admit(0,1);fds[11].pollStatus=0;f.pollSurfaceSubmission();f.resetTimeline(100);
        clockNs=100+kDroppedDrainTimeoutNs-1;assert(!f.pollDroppedSurfacePresentation());
        clockNs++;try{f.pollDroppedSurfacePresentation();assert(false);}catch(const std::runtime_error&){}
        assert(f.fatal_ && f.pendingPresentations_==1 && fds[11].closes==0 && s.sourceLeft!=nullptr);
        assert(logs.back().find("stage=quarantine")!=std::string::npos);
    }
    // Logs cap at eight exact pairs, while lifetime failure/retirement totals
    // keep increasing and every reused slot receives a fresh request identity.
    reset();{
        Fixture f;
        for(uint64_t id=1;id<=32;++id){f.admit(0,id);assert(!f.pollSurfaceSubmission());
            auto row=f.pollDroppedSurfacePresentation();assert(row && row->presentId==id);
            assert(f.pendingPresentations_==0);f.resetTimeline(id+5);}
        assert(logs.size()==16 && f.surfaceCutoffDrops_==32 && f.surfaceCutoffRetired_==32);
        assert(f.oldestPendingSurfacePresentId()==0);
    }
}
'''
        self.compile_run(source)

    def test_actual_jni_join_keeps_old_physical_and_old_drop_ahead_of_new_rows(self):
        native = (NATIVE / "lsfg_qualification_jni.cpp").read_text()
        function = body(native, "progressLiveSurfacePipeline(Host* host,")
        dispatch = body(native, "void dispatchReadySurfaceSubmission(Host* host)")
        self.compile_run(r'''
#include <cassert>
#include <cstdint>
#include <deque>
#include <map>
#include <memory>
#include <optional>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>
namespace emufusion::lsfg {
struct PresentFenceUnavailable:std::runtime_error{using std::runtime_error::runtime_error;};
struct OwnedVulkanHost {
    struct Completion {bool dropped=false;uint64_t presentId=0;};
    struct Submission {uint32_t slotIndex=0;void* buffer=nullptr;int proofReadySyncFd=-1;
        uint64_t presentId=0,desiredPresentTimeNs=0,physicalPresentTimeNs=0,
        compositorFrameTimelineVsyncId=0,compositorFrameTimelineExpectedNs=0,
        compositorFrameTimelineDeadlineNs=0,refreshDurationNs=0;};
    std::set<uint64_t> pending;std::deque<Completion> drops;
    std::deque<Submission> submissions;unsigned submissionPolls=0;
    uint64_t rejected=0;
    std::optional<Submission> pollSurfaceSubmission(){++submissionPolls;
        if(submissions.empty())return std::nullopt;
        auto row=submissions.front();submissions.pop_front();return row;}
    void retireSurfacePresentation(uint64_t){}
    void dropSurfacePresentation(uint64_t id){assert(!rejected);rejected=id;}
    std::optional<Completion> pollDroppedSurfacePresentation(){if(drops.empty())return std::nullopt;
        auto row=drops.front();drops.pop_front();pending.erase(row.presentId);return row;}
    uint64_t oldestPendingSurfacePresentId(){return pending.empty()?0:*pending.begin();}
    std::optional<Completion> pollSurfaceCompletion(uint64_t id,uint64_t,uint64_t,uint64_t){
        pending.erase(id);return Completion{false,id};}
};
struct OwnedSurfaceControlPresenter {
    struct Completion {uint64_t presentId=0,actualPresentTimeNs=0,desiredPresentTimeNs=0,latchTimeNs=0;};
    std::deque<Completion> physical;
    bool isReleased(uint64_t){return false;}void retire(uint64_t){}
    bool accept=true;unsigned presents=0;void* buffer=nullptr;int fd=-2;
    std::vector<uint64_t> presented;
    bool present(void* b,int f,uint64_t id,uint64_t desired,uint64_t token,
                 uint64_t expected,uint64_t deadline,uint64_t period){
        ++presents;buffer=b;fd=f;presented={id,desired,token,expected,deadline,period};return accept;}
    std::vector<uint64_t> takeUnavailablePresentFences(){return {};}
    std::string diagnosticJson(){return "fixture";}
    std::optional<Completion> pollCompletion(){if(physical.empty())return std::nullopt;
        auto row=physical.front();physical.pop_front();return row;}
};
}
using Native=emufusion::lsfg::OwnedVulkanHost;using Presenter=emufusion::lsfg::OwnedSurfaceControlPresenter;
struct Host {
    std::unique_ptr<Native> ownedVulkan=std::make_unique<Native>();
    std::unique_ptr<Presenter> surfacePresenter=std::make_unique<Presenter>();
    std::set<uint64_t> deliveredAwaitingRelease;
    std::map<uint64_t,Native::Completion> droppedCompletions;
    std::map<uint64_t,Presenter::Completion> physicalCompletions;
    uint64_t selfTestPresentFenceOffsetNs=0;
    struct Timing {struct Request {uint64_t presentId,physicalTargetNs,driverDesiredNs,vsyncId,tokenExpectedNs,tokenDeadlineNs;};
        unsigned count=0;uint32_t slot=0;Request request{};
        void submitted(uint32_t s,Request r){++count;slot=s;request=r;}} timingDiagnostics;
};
std::vector<int> closedFds;
int close(int fd){closedFds.push_back(fd);return 0;}
uint64_t normalizedPhysicalPresentTime(uint64_t raw,uint64_t offset){return raw+offset;}
void logSurfaceTimingDiagnostic(Host*,const char*,const Presenter::Completion&,bool,const Native::Completion*,bool){}
''' + dispatch + r'''
std::optional<Native::Completion>
''' + function + r'''
int main(){
    // The dispatch-only call runs before Java ledger commit. It preserves all
    // exact request fields and must not consume any physical/drop completion.
    for(bool accepted:{false,true}) for(bool token:{false,true}) {
        Host h;int buffer=9;
        Native::Submission row{2,&buffer,71,101,900,1000,
            token?uint64_t{42}:0,1000,800,100};
        h.ownedVulkan->submissions.push_back(row);
        h.surfacePresenter->physical.push_back({99,500,450,480});
        h.ownedVulkan->drops.push_back({true,98});
        h.surfacePresenter->accept=accepted;closedFds.clear();
        dispatchReadySurfaceSubmission(&h);
        assert(h.surfacePresenter->presents==1 && h.surfacePresenter->buffer==&buffer);
        assert(h.surfacePresenter->fd==71);
        assert((h.surfacePresenter->presented==std::vector<uint64_t>{101,900,
            token?uint64_t{42}:0,1000,800,token?uint64_t{100}:0}));
        assert(h.surfacePresenter->physical.size()==1 && h.ownedVulkan->drops.size()==1);
        assert(h.physicalCompletions.empty() && h.droppedCompletions.empty());
        if(accepted){assert(closedFds.empty() && h.ownedVulkan->rejected==0);
            assert(h.timingDiagnostics.count==1 && h.timingDiagnostics.slot==2);
            assert(h.timingDiagnostics.request.physicalTargetNs==1000 &&
                   h.timingDiagnostics.request.driverDesiredNs==900);}
        else{assert(closedFds==std::vector<int>{71} && h.ownedVulkan->rejected==101);
            assert(h.timingDiagnostics.count==0);}
        dispatchReadySurfaceSubmission(&h); // no duplicate submission
        assert(h.surfacePresenter->presents==1 && h.ownedVulkan->submissionPolls==2);
    }
    {Host h;h.ownedVulkan->pending={7,8};h.ownedVulkan->drops.push_back({true,8});
        assert(!progressLiveSurfacePipeline(&h));assert(h.droppedCompletions.count(8)==1);
        h.surfacePresenter->physical.push_back({7,100,90,95});
        auto first=progressLiveSurfacePipeline(&h);assert(first && !first->dropped && first->presentId==7);
        auto second=progressLiveSurfacePipeline(&h);assert(second && second->dropped && second->presentId==8);
        assert(!progressLiveSurfacePipeline(&h));}
    {Host h;h.ownedVulkan->pending={7,8};h.surfacePresenter->physical.push_back({8,100,90,95});
        assert(!progressLiveSurfacePipeline(&h));assert(h.physicalCompletions.count(8)==1);
        h.ownedVulkan->drops.push_back({true,7});
        auto first=progressLiveSurfacePipeline(&h);assert(first && first->dropped && first->presentId==7);
        auto second=progressLiveSurfacePipeline(&h);assert(second && !second->dropped && second->presentId==8);}
    // Self-test/live IDs need not form a guessed contiguous sequence. Ordering
    // is tied to actual outstanding requests, not an inferred next integer.
    {Host h;h.ownedVulkan->pending={1000000};h.ownedVulkan->drops.push_back({true,1000000});
        auto row=progressLiveSurfacePipeline(&h);assert(row && row->presentId==1000000);}
}
''')

    def test_scope_guards_and_existing_java_drop_contract(self):
        native = (NATIVE / "owned_vulkan_host.cpp").read_text()
        submission = body(native, "std::optional<SurfaceSubmission> pollSurfaceSubmission()")
        self.assertEqual(submission.count("markSurfaceCutoffDrop("), 2)
        self.assertLess(submission.index("markSurfaceCutoffDrop("), submission.index("recordSurfaceProof(slot)"))
        reset = body(native, "void resetTimeline(")
        self.assertNotIn("surfaceCutoff", reset)
        self.assertNotIn("resetLiveSlotStorage", reset)
        physical = body(native, "std::optional<Completion> pollSurfaceCompletion(")
        self.assertIn("fatal_ = true;", physical)
        self.assertIn("SurfaceControl proof missed its immutable completion deadline", physical)
        self.assertNotIn("markSurfaceCutoffDrop", physical)
        retired = body(native, "std::optional<Completion> pollDroppedSurfacePresentation()")
        self.assertLess(retired.index("observeDropDrain"), retired.index("resetLiveSlotStorage"))
        self.assertNotIn("actualPresentTimeNs =", retired)
        jni = (NATIVE / "lsfg_qualification_jni.cpp").read_text()
        enqueue = jni.split("Java_com_thorium_preview_game_NativeLsfgBridge_enqueue(", 1)[1].split(
            'extern "C"', 1)[0]
        self.assertLess(enqueue.index("droppedCompletions.size() >= kSlotCount"),
                        enqueue.index("activatePrivatePrepared("))
        self.assertIn("completion->dropped ? 0 :", jni)
        java = (ROOT / "unified-android/qualification-src/com/thorium/preview/game/LsfgPresentationTransport.java").read_text()
        self.assertIn("if (raw[2] == 0L)", java)
        self.assertIn("PresentationEvent.dropped(", java)


if __name__ == "__main__":
    unittest.main()
