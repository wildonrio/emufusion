"""Host-only lifecycle regression fixtures; not Android/GPU empirical proof.

Compile current production function bodies against instrumented window/Vulkan
stand-ins. Source contracts join the tested boundaries to the real call sites.
No device, private library, or graphics driver is used.
"""
import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
EDEN = ROOT / "engines/build/switch-src/eden/src"


def function(text, signature):
    start = text.index(signature)
    brace = text.index("{", start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


class EdenSurfaceLifecycleTest(unittest.TestCase):
    def compile_run(self, source, cpp=True):
        compiler = shutil.which("c++" if cpp else "cc")
        self.assertIsNotNone(compiler, "host compiler required; do not silently skip")
        with tempfile.TemporaryDirectory(prefix="eden-lifecycle-fixture-") as tmp:
            path = pathlib.Path(tmp) / ("fixture.cpp" if cpp else "fixture.c")
            path.write_text(source)
            binary = pathlib.Path(tmp) / "fixture"
            result = subprocess.run([compiler, "-std=c++20" if cpp else "-std=c11",
                                     "-pthread", str(path), "-o", str(binary)],
                                    text=True, capture_output=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(binary)], text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_real_jni_window_transaction_reference_counts(self):
        source = (ROOT / "unified-android/native/lucent_native_adapter_jni.c").read_text()
        bodies = "\n".join(function(source, sig) for sig in (
            "static bool bind_window(", "static bool bind_replacement_windows(",
            "static void release_replaced_windows(", "static void finish_window_binding(",
            "static void release_windows("))
        self.compile_run(r'''
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <stddef.h>
typedef struct { int refs; bool valid; } ANativeWindow;
typedef ANativeWindow* jobject;
typedef void JNIEnv;
typedef struct {
    ANativeWindow *primary_window, *lower_window;
    ANativeWindow *failed_previous_primary, *failed_previous_lower;
    bool window_binding_failed;
} lucent_adapter_jni_session;
static ANativeWindow* ANativeWindow_fromSurface(JNIEnv* env, jobject window) {
    if (!window->valid) return NULL;
    ++window->refs; return window;
}
static void ANativeWindow_release(ANativeWindow* window) {
    assert(window->refs > 0); --window->refs;
}
''' + bodies + r'''
int main(void) {
    ANativeWindow a={1,true}, b={1,true}, c={0,true}, d={0,true}, bad={0,false};
    lucent_adapter_jni_session session={&a,&b};
    ANativeWindow *old_a=NULL,*old_b=NULL;
    char error[128];
    assert(!bind_replacement_windows(NULL,&session,&bad,&d,&old_a,&old_b,error,sizeof(error)));
    assert(a.refs==1 && b.refs==1 && d.refs==0 && session.primary_window==&a);
    assert(!bind_replacement_windows(NULL,&session,&c,&bad,&old_a,&old_b,error,sizeof(error)));
    assert(c.refs==0 && a.refs==1 && b.refs==1 && session.lower_window==&b);
    assert(bind_replacement_windows(NULL,&session,&c,&d,&old_a,&old_b,error,sizeof(error)));
    assert(a.refs==1 && b.refs==1 && c.refs==1 && d.refs==1); // old alive during adapter call
    assert(session.primary_window==&c && session.lower_window==&d);
    release_replaced_windows(old_a,old_b);
    assert(a.refs==0 && b.refs==0);
    assert(bind_replacement_windows(NULL,&session,&c,NULL,&old_a,&old_b,error,sizeof(error)));
    assert(c.refs==2 && d.refs==1 && session.lower_window==NULL); // same window acquired first
    release_replaced_windows(old_a,old_b);
    assert(c.refs==1 && d.refs==0);
    release_replaced_windows(session.primary_window,session.lower_window);
    assert(c.refs==0);
    session=(lucent_adapter_jni_session){&a,&b}; a.refs=1; b.refs=1;
    assert(bind_replacement_windows(NULL,&session,&c,&d,&old_a,&old_b,error,sizeof(error)));
    finish_window_binding(&session,old_a,old_b,false);
    assert(a.refs==1 && b.refs==1 && c.refs==1 && d.refs==1 && session.window_binding_failed);
    assert(!bind_replacement_windows(NULL,&session,&a,&b,&old_a,&old_b,error,sizeof(error)));
    assert(a.refs==1 && b.refs==1 && c.refs==1 && d.refs==1); // bounded: no second failed pair
    release_windows(&session); // called only AFTER adapter destruction in JNI
    assert(a.refs==0 && b.refs==0 && c.refs==0 && d.refs==0);
}
''', cpp=False)

    def test_present_recreation_order_bounded_retry_and_failure_latch(self):
        source = (EDEN / "video_core/renderer_vulkan/vk_present_manager.cpp").read_text()
        bodies = "\n".join(function(source, sig) for sig in (
            "void PresentManager::CopyToSwapchain(", "void PresentManager::RecordPresentationFailure("))
        self.compile_run(r'''
#define __ANDROID__ 1
#define LOG_ERROR(...)
#include <atomic>
#include <cassert>
#include <mutex>
#include <vector>
using VkResult=int;
constexpr int VK_SUCCESS=0, VK_ERROR_SURFACE_LOST_KHR=-1, VK_ERROR_INITIALIZATION_FAILED=-2;
namespace vk { struct Exception { int result; explicit Exception(int r): result(r) {} int GetResult() const { return result; } }; }
std::vector<int> events;
bool swapchain_alive=true, surface_alive=true;
bool fail_create=false;
struct Frame { bool copy_submitted=false; };
struct Surface {
    void reset(){assert(!swapchain_alive); surface_alive=false;}
    Surface& operator=(int) { assert(!swapchain_alive); events.push_back(3); surface_alive=true; return *this; }
};
int CreateSurface(int,int) { assert(!surface_alive); if(fail_create) throw vk::Exception(-2); events.push_back(2); return 0; }
struct Device { int result=0; Device& GetLogical(){return *this;} int WaitIdle(){events.push_back(0); return result;} };
struct Scheduler { std::mutex submit_mutex; };
struct Swapchain { void RetireBeforeSurfaceReplacement(){assert(surface_alive); events.push_back(1); swapchain_alive=false;} };
struct Window { int GetWindowInfo(){return 0;} };
struct PresentManager {
    std::atomic<bool> surface_recreation_requested{false}; std::atomic<VkResult> presentation_failure{0};
    Scheduler scheduler; Device device; Swapchain swapchain; Surface surface; Window render_window; int instance=0;
    int copies=0, failure_copies=0, failure_code=-1; bool submit_before_failure=false;
    bool HasPresentationFailure() const { return presentation_failure.load()!=0; }
    void RecreateSwapchain(Frame*){assert(surface_alive); events.push_back(4); swapchain_alive=true;}
    void CopyToSwapchainImpl(Frame* frame){++copies; if(submit_before_failure) frame->copy_submitted=true; if(copies<=failure_copies) throw vk::Exception(failure_code); events.push_back(5);}
    void CopyToSwapchain(Frame*); void RecordPresentationFailure(VkResult);
};
''' + bodies + r'''
int main() {
    Frame frame;
    { PresentManager p; p.CopyToSwapchain(&frame); assert(p.copies==1 && !p.HasPresentationFailure()); }
    events.clear();
    { PresentManager p; p.failure_copies=1; p.CopyToSwapchain(&frame);
      assert(p.copies==2 && !p.HasPresentationFailure()); assert((events==std::vector<int>{0,1,2,3,4,5})); }
    events.clear();
    { PresentManager p; p.failure_copies=10; p.CopyToSwapchain(&frame);
      assert(p.copies==2 && p.HasPresentationFailure()); p.CopyToSwapchain(&frame); assert(p.copies==2);
      p.RecordPresentationFailure(-2); assert(p.presentation_failure.load()==-1); } // preserve first failure
    events.clear();
    { PresentManager p; p.failure_copies=1; fail_create=true; p.CopyToSwapchain(&frame);
      assert(p.copies==1 && p.presentation_failure.load()==-2 && !swapchain_alive);
      fail_create=false; p.CopyToSwapchain(&frame); assert(p.copies==1); }
    swapchain_alive=true; surface_alive=true; events.clear();
    { PresentManager p; p.surface_recreation_requested=true; p.CopyToSwapchain(&frame);
      assert(p.copies==1 && (events==std::vector<int>{0,1,2,3,4,5})); }
    events.clear();
    { PresentManager p; p.device.result=-2; p.surface_recreation_requested=true; p.CopyToSwapchain(&frame);
      assert(p.copies==0 && p.HasPresentationFailure() && swapchain_alive);
      assert((events==std::vector<int>{0})); } // failed idle cannot destroy live resources
    events.clear();
    { PresentManager p; p.submit_before_failure=true; p.failure_copies=1; p.CopyToSwapchain(&frame);
      assert(p.copies==1 && !p.HasPresentationFailure() && p.surface_recreation_requested);
      assert(events.empty()); // NEVER retry the consumed render_ready semaphore
      Frame fresh; p.CopyToSwapchain(&fresh);
      assert(p.copies==2 && (events==std::vector<int>{0,1,2,3,4,5})); }
    events.clear();
    { PresentManager p; Frame a,b; p.submit_before_failure=true; p.failure_copies=10;
      p.CopyToSwapchain(&a); assert(!p.HasPresentationFailure());
      p.CopyToSwapchain(&b); assert(p.HasPresentationFailure() && p.copies==2);
      p.CopyToSwapchain(&b); assert(p.copies==2); }
}
''')

    def test_gpu_owner_suspend_drain_order_and_failed_resume(self):
        source = (EDEN / "video_core/renderer_vulkan/renderer_vulkan.cpp").read_text()
        bodies = "\n".join(function(source, sig) for sig in (
            "bool RendererVulkan::SetPresentationSuspended(",
            "bool RendererVulkan::HasPresentationFailure("))
        self.compile_run(r'''
#define LOG_INFO(...)
#include <cassert>
#include <mutex>
#include <vector>
using VkResult=int; constexpr int VK_SUCCESS=0;
std::vector<int> events;
struct Scheduler {
    std::mutex submit_mutex;
    void WaitWorker(){assert(submit_mutex.try_lock()); submit_mutex.unlock(); events.push_back(1);}
};
struct Manager {
    bool failed=false;
    bool HasPresentationFailure() const {return failed;}
    void RequestSurfaceRecreation(){events.push_back(4);}
    void WaitPresent(){events.push_back(2);}
    void RecordPresentationFailure(int result){assert(result!=0); failed=true;}
};
struct Device { int result=0; Device& GetLogical(){return *this;} int WaitIdle(){events.push_back(3); return result;} };
struct RendererVulkan {
    std::mutex presentation_lifecycle_mutex; bool presentation_suspended=false;
    Scheduler scheduler; Manager present_manager; Device device;
    bool SetPresentationSuspended(bool); bool HasPresentationFailure() const;
};
''' + bodies + r'''
int main() {
    RendererVulkan r;
    assert(r.SetPresentationSuspended(true) && r.presentation_suspended);
    assert((events==std::vector<int>{1,2,3}));
    assert(r.SetPresentationSuspended(false) && !r.presentation_suspended && events.back()==4);
    events.clear(); r.device.result=-4;
    assert(!r.SetPresentationSuspended(true) && r.presentation_suspended && r.HasPresentationFailure());
    assert((events==std::vector<int>{1,2,3}));
    assert(!r.SetPresentationSuspended(false) && r.presentation_suspended);
    assert(events.size()==3); // no rearm, failure never cleared to manufacture recovery
}
''')

    def test_gpu_barrier_is_explicitly_woken_and_completed(self):
        source = (EDEN / "video_core/gpu.cpp").read_text()
        body = function(source, "    bool SetPresentationSuspended(bool suspended)")
        self.assertLess(body.index("RequestSyncOperation"), body.index("gpu_thread.TickGPU(is_async)"))
        self.assertLess(body.index("gpu_thread.TickGPU(is_async)"), body.index("WaitForSyncOperation(fence)"))

    def test_acquire_recreate_loop_and_empty_surface_fail_closed(self):
        source = (EDEN / "video_core/renderer_vulkan/vk_present_manager.cpp").read_text()
        body = function(source, "void PresentManager::CopyToSwapchainImpl(")
        self.assertNotIn("while (swapchain.AcquireNextImage())", body)
        self.assertIn("if (acquire_retry >= 1)", body)
        self.assertIn("throw vk::Exception(VK_ERROR_OUT_OF_DATE_KHR)", body)
        source = (EDEN / "video_core/renderer_vulkan/vk_swapchain.cpp").read_text()
        create = function(source, "void Swapchain::Create(")
        self.assertIn("throw vk::Exception(VK_ERROR_OUT_OF_DATE_KHR)", create)
        present = function(source, "void Swapchain::Present(")
        default = present[present.index("    default:"):]
        self.assertIn("vk::Check(result)", default)
        acquire = function(source, "bool Swapchain::AcquireNextImage(")
        out_of_date = acquire[acquire.index("case VK_ERROR_OUT_OF_DATE_KHR:"):]
        self.assertLess(out_of_date.index("return true"), out_of_date.index("case VK_ERROR_SURFACE_LOST_KHR:"))
        self.assertNotIn("return is_suboptimal", acquire)
        self.assertIn("return false;", acquire)

    def test_no_frame_allocation_while_suspended_or_failed(self):
        source = (EDEN / "video_core/renderer_vulkan/renderer_vulkan.cpp").read_text()
        body = function(source, "void RendererVulkan::Composite(")
        self.assertLess(body.index("presentation_lifecycle_mutex"), body.index("presentation_suspended"))
        self.assertLess(body.index("presentation_suspended || present_manager.HasPresentationFailure()"),
                        body.index("RenderAppletCaptureLayer"))
        self.assertLess(body.index("frame == nullptr"), body.index("blit_swapchain.DrawToFrame"))
        source = (EDEN / "video_core/renderer_vulkan/vk_present_manager.cpp").read_text()
        body = function(source, "Frame* PresentManager::GetRenderFrame(")
        self.assertLess(body.index("HasPresentationFailure()"), body.index("frame->present_done.Wait()"))

    def test_adapter_pause_rebind_stop_join_are_ordered(self):
        source = (ROOT / "engines/patches/eden-lucent-adapter.cpp").read_text()
        pause = function(source, "static void adapter_pause(")
        self.assertLess(pause.index("session.PauseEmulation()"), pause.index("SetPresentationSuspended(true)"))
        resume = function(source, "static void adapter_resume(")
        self.assertLess(resume.index("SetPresentationSuspended(false)"), resume.index("session.UnPauseEmulation()"))
        rebind = function(source, "static bool adapter_surface_recreated(")
        self.assertLess(rebind.index("SetPresentationSuspended(true)"), rebind.index("session.SetNativeWindow"))
        self.assertLess(rebind.index("session.SurfaceChanged()"), rebind.index("SetPresentationSuspended(false)"))
        stop = function(source, "static void adapter_stop(")
        self.assertLess(stop.index("SetPresentationSuspended(true)"), stop.index("session.UnPauseEmulation()"))
        self.assertNotIn("SetPresentationSuspended(false)", stop)
        self.assertLess(stop.index("engine->emulation_thread.join()"), stop.index("engine->window = nullptr"))
        self.assertIn("HasPresentationFailure()", function(source, "static bool adapter_run_frame("))

    def test_jni_failed_callback_retained_until_adapter_destroy(self):
        source = (ROOT / "unified-android/native/lucent_native_adapter_jni.c").read_text()
        for entry, result in (("nativeStart(", "started"), ("nativeSurfaceRecreated(", "rebound")):
            body = function(source, "Java_com_thorium_preview_NativeAdapterHost_" + entry)
            self.assertIn("finish_window_binding(session, old_primary, old_lower, " + result + ")", body)
        body = function(source, "Java_com_thorium_preview_NativeAdapterHost_nativeDestroy(")
        self.assertLess(body.index("lucent_native_adapter_destroy"), body.index("release_windows"))

    def test_session_shutdown_excludes_gpu_lifecycle_requests(self):
        source = (ROOT / "engines/patches/eden-lucent-adapter.cpp").read_text()
        for signature in ("static void adapter_pause(", "static void adapter_resume(",
                          "static bool adapter_surface_recreated(", "static bool adapter_run_frame("):
            body = function(source, signature)
            self.assertLess(body.index("presentation_api_mutex"), body.index("auto& session"))
        self.assertIn("std::scoped_lock lifecycle{engine->presentation_api_mutex};\n"
                      "            engine_session.ShutdownEmulation();", source)
        body = function(source, "static void adapter_stop(")
        self.assertLess(body.index("} // Never hold presentation_api_mutex"), body.index("engine->emulation_thread.join()"))


if __name__ == "__main__":
    unittest.main()
