"""Execute the actual local present() handler with controlled Vulkan results.

Mocks cover error dispatch and image bookkeeping, not real GPU synchronization.
Neither this test nor a successful compile proves Android sleep/resume recovery.
"""
import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
REL = Path("app/src/main/cpp/rpcs3/rpcs3/Emu/RSX/VK/VKPresent.cpp")
SOURCE = ROOT / "engines/build/sources/aps3e-b5ae1af50d5e2f3b705506e7380a4504e086840b" / REL
PATCH = ROOT / "engines/patches/aps3e-present-surface-lost.patch"

PREFIX = r'''
#include <cassert>
#define ensure(x) assert(x)
using s64 = long long;
constexpr unsigned umax = ~0u;
enum VkResult { VK_SUCCESS, VK_SUBOPTIMAL_KHR, VK_ERROR_OUT_OF_DATE_KHR,
                VK_ERROR_SURFACE_LOST_KHR, OTHER_ERROR };
struct Logger { template<typename... T> void error(T...) {} } rsx_log;
struct Commands { int count = 0; void flush() { ++count; } };
struct Swapchain {
    VkResult result; int calls = 0;
    VkResult present(int, unsigned) { ++calls; return result; }
};
namespace vk { struct frame_context_t {
    unsigned present_image = 1; int present_wait_semaphore = 0;
    Commands* swap_command_buffer;
}; }
struct VKGSRender {
    Swapchain* m_swapchain;
    bool swapchain_unavailable = false, surface_lost = false;
    void present(vk::frame_context_t*);
};
'''
SUFFIX = r'''
int main() {
    for (auto result : {VK_SUCCESS, VK_SUBOPTIMAL_KHR, VK_ERROR_OUT_OF_DATE_KHR,
                        VK_ERROR_SURFACE_LOST_KHR, OTHER_ERROR}) {
        Commands commands;
        Swapchain swapchain{result};
        VKGSRender renderer{&swapchain};
        vk::frame_context_t context{1, 0, &commands};
        renderer.present(&context);
        if (renderer.surface_lost != (result == VK_ERROR_SURFACE_LOST_KHR)) return 10;
        if (renderer.swapchain_unavailable != (result != VK_SUCCESS && result != VK_SUBOPTIMAL_KHR)) return 11;
        if (context.present_image != umax || commands.count != 1 || swapchain.calls != 1) return 12;
        // A previously unavailable surface must not be presented a second time.
        context.present_image = 2;
        renderer.swapchain_unavailable = true;
        renderer.present(&context);
        if (swapchain.calls != 1 || context.present_image != umax || commands.count != 2) return 13;
    }
}
'''


@unittest.skipUnless(SOURCE.is_file() and shutil.which("c++"), "local aPS3e source/compiler absent")
class PresentSurfaceLostTest(unittest.TestCase):
    def test_real_handler_old_fails_new_passes_and_patch_preserves_source(self):
        original = SOURCE.read_bytes()
        with tempfile.TemporaryDirectory(prefix="aps3e-present-regression-") as directory:
            work = Path(directory)
            copy = work / REL
            copy.parent.mkdir(parents=True)
            copy.write_bytes(original)
            subprocess.run(["git", "apply", "--reverse", str(PATCH)], cwd=work, check=True)
            old = copy.read_bytes()
            self.assertEqual("8c9d17286276f1f506be0c16676a4a838de02442e3d70746543d6e292a073372",
                             hashlib.sha256(old).hexdigest())
            subprocess.run(["git", "apply", str(PATCH)], cwd=work, check=True)
            self.assertEqual(original, copy.read_bytes())
            for name, source, expected in (("old", old, 10), ("new", original, 0)):
                text = source.decode()
                start = text.index("void VKGSRender::present(")
                end = text.index("void VKGSRender::advance_queued_frames()", start)
                program = work / (name + ".cpp")
                binary = work / name
                program.write_text("#include <initializer_list>\n" + PREFIX + text[start:end] + SUFFIX)
                subprocess.run(["c++", "-std=c++20", "-Wall", "-Wextra", "-Werror",
                                str(program), "-o", str(binary)], check=True)
                self.assertEqual(expected, subprocess.run([str(binary)]).returncode)
        self.assertEqual(original, SOURCE.read_bytes())


if __name__ == "__main__":
    unittest.main()
