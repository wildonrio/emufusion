"""Actual proof-fence timestamp and completion methods; not device timing proof."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

from tools.tests.test_lsfg_surface_callback_diagnostics import declaration

ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / "unified-android/lsfg-qualification-native"


class LsfgProofCompletionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = (NATIVE / "owned_vulkan_host.cpp").read_text()
        header = (NATIVE / "owned_vulkan_host.hpp").read_text()
        structs = "\n".join(declaration(header, signature, True) for signature in (
            "struct LiveRequest {", "struct Completion {"))
        structs += "\n" + "\n".join(declaration(source, signature, True) for signature in (
            "struct ImportedImage {", "enum class LiveSlotState {", "struct LiveSlot {"))
        methods = "\n".join(declaration(source, signature) for signature in (
            "std::optional<Completion> pollSurfaceCompletion(",
            "LiveSlot* findSurfaceSlot(uint64_t presentId, LiveSlotState state)",
            "uint64_t proofFenceTimestamp(LiveSlot& slot)"))
        fixture = r'''
#include <algorithm>
#include <array>
#include <cassert>
#include <cstdint>
#include <fcntl.h>
#include <iostream>
#include <memory>
#include <optional>
#include <poll.h>
#include <stdexcept>
#include <string>
#include <unistd.h>
using VkResult=int;using VkCommandBuffer=int;using VkFence=int;using VkSemaphore=int;
using VkImage=int;using VkDeviceMemory=int;using VkBuffer=int;
constexpr int VK_SUCCESS=0,VK_NOT_READY=1,VK_NULL_HANDLE=0;
struct AHardwareBuffer {int refs=1;};
struct VkExtent2D {uint32_t width=0,height=0;};
struct VkPastPresentationTimingGOOGLE {
    uint32_t presentID;uint64_t desiredPresentTime,actualPresentTime,earliestPresentTime,presentMargin;
};
void requireSuccess(int status,const char* message){if(status!=VK_SUCCESS)throw std::runtime_error(message);}
struct sync_fence_info {int status=1;uint64_t timestamp_ns=999;};
struct sync_file_info {int status=1;uint32_t num_fences=2;std::array<sync_fence_info,2> children;};
struct sync_file_info configured;
bool missingInfo=false;int infoCalls=0,infoFrees=0;
struct sync_file_info* sync_file_info(int){
    infoCalls++;return missingInfo?nullptr:new struct sync_file_info(configured);
}
void sync_file_info_free(struct sync_file_info* info){infoFrees++;delete info;}
const sync_fence_info* sync_get_fence_info(struct sync_file_info* info){return info->children.data();}
bool openFd(int fd){return fd>=0 && ::fcntl(fd,F_GETFD)>=0;}
struct Fixture {
''' + structs + r'''
    std::array<LiveSlot,3> live_{};
    bool fatal_=false;int device_=1,analyses=0,captures=0;
    AHardwareBuffer left,right;ImportedImage leftImage,rightImage;
    int originalFd=-1,writerFd=-1;
    struct Device {
        int status=VK_SUCCESS,calls=0;
        int vkGetFenceStatus(int device,int fence){assert(device==1 && fence==7);calls++;return status;}
    } deviceFunctions_;
    Fixture(){
        configured={};missingInfo=false;infoCalls=infoFrees=0;
        auto& slot=live_[1];slot.state=LiveSlotState::SurfaceProofQueued;
        slot.request.left=&left;slot.request.right=&right;
        slot.request.presentId=4371;slot.request.physicalPresentTimeNs=2000;
        slot.request.desiredPresentTimeNs=1800;slot.request.completionDeadlineNs=1000;
        slot.request.sessionEpoch=4;slot.request.presentationEpoch=15;
        slot.gpuStartNs=123;slot.presentFence=7;slot.wsiPresentId=4371;
        leftImage.buffer=&left;rightImage.buffer=&right;
        slot.sourceLeft=&leftImage;slot.sourceRight=&rightImage;
        slot.fullCaptureId=99;slot.privateProofPrepared=false;
        slot.proofMapped=&left;slot.proofInitialized=true;
        int pipeFds[2];assert(::pipe(pipeFds)==0);
        originalFd=pipeFds[0];writerFd=pipeFds[1];slot.proofTimestampSyncFd=originalFd;
        signal();
    }
    ~Fixture(){if(openFd(originalFd))::close(originalFd);if(openFd(writerFd))::close(writerFd);}
    void signal(){const char byte='x';assert(::write(writerFd,&byte,1)==1);}
    void makePending(){char byte;assert(::read(originalFd,&byte,1)==1);}
    void owned()const{
        const auto& slot=live_[1];
        assert(left.refs==1 && right.refs==1);
        assert(slot.request.left==&left && slot.request.right==&right);
        assert(slot.sourceLeft==&leftImage && slot.sourceRight==&rightImage);
        assert(slot.proofMapped==&left && slot.proofInitialized && slot.fullCaptureId==99);
        assert(slot.request.presentId==4371 && slot.gpuStartNs==123);
        assert(slot.request.completionDeadlineNs==1000);
    }
    Completion analyzeCompletion(LiveSlot& slot,const VkPastPresentationTimingGOOGLE& physical){
        analyses++;assert(physical.actualPresentTime==slot.request.physicalPresentTimeNs);
        return Completion{.presentId=slot.request.presentId,
            .actualPresentTimeNs=physical.actualPresentTime,.gpuCompletionNs=slot.gpuCompletionObservedNs};
    }
    void completeTripletCapture(LiveSlot&,const Completion&){captures++;}
''' + methods + r'''
    std::optional<Completion> poll(){return pollSurfaceCompletion(4371,1800,1500,2000);}
};
template<typename F> std::string error(F operation){
    try{operation();}catch(const std::runtime_error& e){return e.what();}
    throw std::logic_error("expected production rejection");
}
void late(){
    for(bool generated:{false,true}){
        Fixture f;f.live_[1].request.generated=generated;
        configured.children[0].timestamp_ns=900;configured.children[1].timestamp_ns=1001;
        const auto message=error([&]{f.poll();});
        assert(message.find("SurfaceControl proof missed its immutable completion deadline")!=std::string::npos);
        for(const auto& field:std::array<std::string,5>{"presentId=4371","gpuCompletionNs=1001",
                "completionDeadlineNs=1000","gpuStartNs=123",generated?"generated=1":"generated=0"})
            assert(message.find(field)!=std::string::npos);
        assert(f.fatal_ && f.analyses==0 && f.captures==0);
        assert(f.live_[1].state==Fixture::LiveSlotState::SurfaceProofQueued);
        assert(f.live_[1].gpuCompletionObservedNs==1001);
        assert(f.live_[1].proofTimestampSyncFd==-1 && !openFd(f.originalFd));
        assert(infoCalls==1 && infoFrees==1);f.owned();
        const int calls=f.deviceFunctions_.calls;
        assert(error([&]{f.poll();}).find("quarantined")!=std::string::npos);
        assert(f.deviceFunctions_.calls==calls);f.owned();
    }
}
void ontime(){
    for(uint64_t signal:{999ULL,1000ULL}){
        Fixture f;configured.children[0].timestamp_ns=signal;
        configured.children[1].timestamp_ns=900;
        const auto completion=f.poll();
        assert(completion && completion->gpuCompletionNs==signal && completion->actualPresentTimeNs==2000);
        assert(!f.fatal_ && f.analyses==1 && f.captures==1);
        assert(f.live_[1].state==Fixture::LiveSlotState::SurfaceDeliveredAwaitingRelease);
        assert(f.live_[1].proofTimestampSyncFd==-1 && !openFd(f.originalFd));f.owned();
        // Completion is not buffer retirement or permission to count twice.
        assert(error([&]{f.poll();}).find("unknown SurfaceControl completion identity")!=std::string::npos);
        assert(f.analyses==1 && f.captures==1);f.owned();
    }
}
void not_ready(){
    Fixture f;f.deviceFunctions_.status=VK_NOT_READY;
    assert(!f.poll() && !f.poll());
    assert(!f.fatal_ && f.analyses==0 && f.captures==0 && infoCalls==0);
    assert(f.live_[1].state==Fixture::LiveSlotState::SurfaceProofQueued);
    assert(f.live_[1].gpuCompletionObservedNs==0 && openFd(f.originalFd));f.owned();
    f.deviceFunctions_.status=VK_SUCCESS;assert(f.poll());f.owned();
}
void invalid(){
    for(int kind=0;kind<9;kind++){
        Fixture f;
        if(kind==0)f.live_[1].proofTimestampSyncFd=-1;
        if(kind==1)f.makePending();
        if(kind==2)missingInfo=true;
        if(kind==3)configured.status=0;
        if(kind==4)configured.num_fences=0;
        if(kind==5)configured.children[1].status=-1;
        if(kind==6)configured.children[1].timestamp_ns=0;
        if(kind==7)f.deviceFunctions_.status=-4;
        const auto message=error([&]{
            if(kind==8)f.pollSurfaceCompletion(4371,1801,1500,2000);else f.poll();
        });
        assert(!message.empty() && f.analyses==0 && f.captures==0);
        // These preexisting validation exceptions precede the explicit late-
        // timestamp fatal latch. The caller makes runtime failure terminal.
        assert(!f.fatal_ && f.live_[1].gpuCompletionObservedNs==0);
        assert(f.live_[1].state==Fixture::LiveSlotState::SurfaceProofQueued);
        assert(openFd(f.originalFd));f.owned();
        if(kind==8)assert(f.deviceFunctions_.calls==0 && infoCalls==0);
    }
}
void cached_private(){
    for(uint64_t signal:{0ULL,999ULL,1000ULL,1001ULL}){
        Fixture f;auto& slot=f.live_[1];slot.privateProofPrepared=true;
        // Private readiness already consumed this exact proof FD. Completion
        // must use the saved kernel signal, never poll-now or a second read.
        slot.gpuCompletionObservedNs=f.proofFenceTimestamp(slot);
        assert(slot.proofTimestampSyncFd==-1 && !openFd(f.originalFd));
        slot.gpuCompletionObservedNs=signal; // includes corrupted-cache guards
        missingInfo=true;const auto calls=infoCalls;
        if(signal==999 || signal==1000){
            const auto result=f.poll();assert(result && result->gpuCompletionNs==signal);
            assert(!f.fatal_ && f.analyses==1);
        }else{
            error([&]{f.poll();});assert(f.fatal_ && f.analyses==0);
            assert(slot.state==Fixture::LiveSlotState::SurfaceProofQueued);
        }
        assert(infoCalls==calls);f.owned();
    }
}
int main(int argc,char** argv){
    assert(argc==2);std::string name=argv[1];
    if(name=="late")late();else if(name=="ontime")ontime();
    else if(name=="pending")not_ready();else if(name=="invalid")invalid();
    else if(name=="cached_private")cached_private();else assert(false);
    std::cout<<"PASS "<<name<<'\n';
}
'''
        compiler = shutil.which("c++")
        if compiler is None:
            raise AssertionError("C++ compiler required")
        cls.temporary = tempfile.TemporaryDirectory(prefix="lsfg-proof-completion-")
        cls.addClassCleanup(cls.temporary.cleanup)
        directory = Path(cls.temporary.name)
        unit = directory / "fixture.cpp"
        unit.write_text(fixture)
        cls.binary = directory / "fixture"
        result = subprocess.run([compiler, "-std=c++20", "-Wall", "-Wextra", "-Werror",
                                 "-g", "-O1", "-fsanitize=address,undefined", str(unit),
                                 "-o", str(cls.binary)], capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    def case(self, name):
        env = dict(os.environ, ASAN_OPTIONS="detect_leaks=0:abort_on_error=1",
                   UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")
        result = subprocess.run([str(self.binary), name], capture_output=True,
                                text=True, timeout=10, env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS " + name, result.stdout)

    def test_on_target_physical_present_cannot_hide_late_gpu_proof(self):
        self.case("late")

    def test_kernel_signal_at_or_before_deadline_succeeds_without_retiring_buffers(self):
        self.case("ontime")

    def test_not_ready_retains_exact_slot_and_proof_fd(self):
        self.case("pending")

    def test_invalid_or_missing_proof_never_becomes_a_success(self):
        self.case("invalid")

    def test_private_cached_kernel_signal_is_reused_and_still_deadline_checked(self):
        self.case("cached_private")


if __name__ == "__main__":
    unittest.main(verbosity=2)
