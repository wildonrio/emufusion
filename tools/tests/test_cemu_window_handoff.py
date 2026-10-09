"""Compile the actual Cemu window handoff against a recording Vulkan boundary.

Checks ownership/ordering, not driver correctness; device sleep/wake remains required.
"""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TREE = Path(json.loads((ROOT / "engines/cemu-source-lock.json").read_text())["core"]["stagedTree"])
SOURCE = (TREE / "src/Cafe/HW/Latte/Renderer/Vulkan/VulkanRenderer.cpp").read_text()


def function(name):
    start = SOURCE.index("void VulkanRenderer::" + name + "(")
    brace = SOURCE.index("{", start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (SOURCE[end] == "{") - (SOURCE[end] == "}")
        end += 1
    return SOURCE[start:end]


class CemuWindowHandoffTest(unittest.TestCase):
    def test_real_handoff_defers_gpu_work_to_consumer(self):
        compiler = shutil.which("clang++")
        self.assertIsNotNone(compiler)
        harness = r'''
#include <atomic>
#include <cassert>
#include <memory>
#include <mutex>
#include <thread>
#include <vector>
struct ANativeWindow { int width, height; };
int ANativeWindow_getWidth(ANativeWindow* w) { return w->width; }
int ANativeWindow_getHeight(ANativeWindow* w) { return w->height; }
struct Vector2i { int x, y; };
namespace WindowSystem {
struct Handle { std::atomic<void*> surface{nullptr}; };
struct Info {
 Handle canvas_main, canvas_pad;
 std::atomic_bool pad_open{false};
 std::atomic_int width{}, height{}, phys_width{}, phys_height{};
 std::atomic_int pad_width{}, pad_height{}, phys_pad_width{}, phys_pad_height{};
} info;
Info& GetWindowInfo() { return info; }
void GetWindowPhysSize(int& x, int& y) { x = info.phys_width; y = info.phys_height; }
void GetPadWindowPhysSize(int& x, int& y) { x = info.phys_pad_width; y = info.phys_pad_height; }
}
enum class LogType { Force };
template<class... T> void cemuLog_log(T...) {}
struct Chain {
 void* window;
 bool surfaceWasLost = false;
 Vector2i size;
 bool UsesAndroidWindow(void* w) const { return window == w; }
 struct Extent { int width, height; };
 Extent getExtent() const { return {size.x, size.y}; }
};
struct VulkanRenderer {
 std::mutex m_androidWindowMutex;
 std::atomic_bool m_lucentManagedWindows{false};
 std::unique_ptr<Chain> m_mainSwapchainInfo, m_padSwapchainInfo;
 std::vector<bool> calls;
 std::thread::id owner = std::this_thread::get_id();
 void PublishAndroidWindows(ANativeWindow*, ANativeWindow*);
 void RefreshAndroidWindows();
 void InitializeSurface(Vector2i size, bool main) {
  assert(std::this_thread::get_id() == owner);
  auto& chain = main ? m_mainSwapchainInfo : m_padSwapchainInfo;
  auto& info = WindowSystem::info;
  chain = std::make_unique<Chain>(Chain{(main ? info.canvas_main : info.canvas_pad).surface.load(), false, size});
  calls.push_back(main);
 }
 void RecreateSwapchain(bool main) {
  auto& chain = main ? m_mainSwapchainInfo : m_padSwapchainInfo;
  assert(chain && chain->surfaceWasLost);
  Vector2i size;
  if (main) WindowSystem::GetWindowPhysSize(size.x, size.y);
  else WindowSystem::GetPadWindowPhysSize(size.x, size.y);
  InitializeSurface(size, main);
 }
};
''' + function("PublishAndroidWindows") + function("RefreshAndroidWindows") + r'''
int main() {
 VulkanRenderer r;
 ANativeWindow tv{1920,1080}, pad{1240,1080}, tv2{1920,1080}, pad2{1240,1080};
 auto publish = [&](ANativeWindow* t, ANativeWindow* p) {
  std::thread adapter([&] { r.PublishAndroidWindows(t,p); });
  adapter.join(); // must not wait for a future graphics acquire while paused
 };
 publish(&tv,&pad);
 assert(r.calls.empty());
 r.RefreshAndroidWindows();
 assert(r.calls.size() == 2);
 publish(&tv,&pad); r.RefreshAndroidWindows();
 assert(r.calls.size() == 2); // repeated callbacks are not new VkSurfaces
 publish(&tv2,nullptr);
 assert(r.calls.size() == 2); // no GPU work from adapter thread
 r.RefreshAndroidWindows();
 assert(r.calls.size() == 3 && r.calls.back());
 assert(r.m_padSwapchainInfo->window == &pad); // retain old VkSurface ownership
 assert(!WindowSystem::info.pad_open);
 publish(&tv2,&pad2); r.RefreshAndroidWindows();
 assert(r.calls.size() == 4 && !r.calls.back());
 assert(r.m_padSwapchainInfo->window == &pad2);
 r.m_mainSwapchainInfo->surfaceWasLost = true;
 publish(&tv2,&pad2); r.RefreshAndroidWindows();
 assert(r.calls.size() == 4); // lost same queue waits for replacement, not a worker
}
'''
        with tempfile.TemporaryDirectory(prefix="cemu-window-handoff-") as temp:
            source = Path(temp) / "test.cpp"
            source.write_text(harness)
            binary = Path(temp) / "test"
            subprocess.run([compiler, "-std=c++20", "-pthread", str(source), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True, timeout=5)

    def test_adapter_rebind_never_replaces_live_swapchains(self):
        adapter = (ROOT / "engines/patches/cemu-lucent-adapter.cpp").read_text()
        rebind = adapter.split("static bool adapter_surface_recreated(", 1)[1].split("static void adapter_stop(", 1)[0]
        self.assertIn("renderer->PublishAndroidWindows", rebind)
        self.assertNotIn("renderer->InitializeSurface", rebind)
        self.assertNotIn("renderer->StopUsingPadAndWait", rebind)
        acquire = SOURCE.split("bool VulkanRenderer::AcquireNextSwapchainImage(", 1)[1].split("void VulkanRenderer::RecreateSwapchain(", 1)[0]
        self.assertLess(acquire.index("RefreshAndroidWindows();"), acquire.index("if (chain && chain->surfaceWasLost) return false;"))
        self.assertLess(acquire.index("if (chain && chain->surfaceWasLost) return false;"), acquire.index("UpdateSwapchainProperties("))


if __name__ == "__main__":
    unittest.main()
