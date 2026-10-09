"""Replay actual loss-return and base flip code with controlled scheduling.

This checks request consumption, not real Vulkan resource synchronization.
"""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "engines/build/sources/aps3e-b5ae1af50d5e2f3b705506e7380a4504e086840b/app/src/main/cpp/rpcs3/rpcs3/Emu/RSX"
GEN = ROOT / "engines/diagnostics/prepare_flip_retirement.py"
spec = importlib.util.spec_from_file_location("flip_retirement", GEN)
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)

PREFIX = r'''
#include <cassert>
unsigned get_system_time() { return 1; }
struct { void Pause() {} } Emu;
struct Bits {
    unsigned value = 0;
    unsigned operator&(unsigned b) const { return value & b; }
    void clear(unsigned b) { value &= ~b; }
};
namespace rsx {
constexpr unsigned display_interrupt = 1;
struct display_flip_info_t { bool emu_flip; };
using display_flip_info = display_flip_info_t;
struct thread {
    struct flip_request { enum { emu_requested=1, native_ui=2, any=3 }; };
    Bits m_eng_interrupt_mask{1}, async_flip_requested;
    struct { unsigned sampled_frames=0; } performance_counters;
    unsigned m_pause_after_x_flips=0, last_host_flip_timestamp=0;
    void flip(const display_flip_info_t&);
};
}
struct VKGSRender : rsx::thread {
    bool surface_lost=false, swapchain_unavailable=false;
    unsigned reinitializations=0;
    void reinitialize_swapchain() { ++reinitializations; }
    void lost(const rsx::display_flip_info_t& info);
};
'''
SUFFIX = r'''
int main() {
    VKGSRender renderer;
    renderer.async_flip_requested.value = 3;
    const rsx::display_flip_info_t game{true};
    // handle_emu_flip notifies once after the backend returns, even on loss.
    renderer.lost(game);
    unsigned notifications = 1;
    // do_local_task replays any still-pending emulation request.
    if (renderer.async_flip_requested & rsx::thread::flip_request::emu_requested) {
        renderer.rsx::thread::flip(game);
        ++notifications;
    }
    if (notifications != 1) return 10;
    assert(renderer.reinitializations == 1);
    assert(renderer.surface_lost && renderer.swapchain_unavailable);
    assert(renderer.performance_counters.sampled_frames == 1);
    assert(renderer.async_flip_requested.value == 2); // leave native UI pending
    renderer.lost({false});
    assert(renderer.async_flip_requested.value == 0);
    assert(renderer.performance_counters.sampled_frames == 1);
    assert(renderer.m_eng_interrupt_mask.value == 0);
}
'''


@unittest.skipUnless((SRC / "VK/VKPresent.cpp").is_file(), "local source absent")
class FlipRetirementTest(unittest.TestCase):
    def test_retained_patch_matches_exact_tested_candidate_without_source_writes(self):
        original = (SRC / "VK/VKPresent.cpp").read_bytes()
        relative = Path("app/src/main/cpp/rpcs3/rpcs3/Emu/RSX/VK/VKPresent.cpp")
        patch = ROOT / "engines/patches/aps3e-acquire-loss-flip-retirement.patch"
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / relative
            target.parent.mkdir(parents=True)
            target.write_bytes(original)
            subprocess.run(["git", "apply", str(patch)], cwd=temporary, check=True)
            self.assertEqual(generator.prepare(original).encode(), target.read_bytes())
            subprocess.run(["git", "apply", "--reverse", str(patch)],
                           cwd=temporary, check=True)
            self.assertEqual(original, target.read_bytes())
        self.assertEqual(original, (SRC / "VK/VKPresent.cpp").read_bytes())

    def test_only_expected_return_changes_and_drift_rejected(self):
        old = (SRC / "VK/VKPresent.cpp").read_bytes()
        new = generator.prepare(old)
        self.assertEqual(old.decode(), new.replace(generator.NEW, generator.OLD, 1))
        with self.assertRaises(ValueError):
            generator.prepare(old + b"\n")

    def test_existing_output_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "existing.cpp"
            output.write_text("other agent code")
            result = subprocess.run(["python3", str(GEN), "--source", str(SRC / "VK/VKPresent.cpp"),
                                     "--output", str(output)], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(output.read_text(), "other agent code")

    @unittest.skipUnless(shutil.which("c++"), "compiler absent")
    def test_real_loss_branch_and_base_flip_old_replays_new_consumes(self):
        old = (SRC / "VK/VKPresent.cpp").read_bytes()
        thread = (SRC / "RSXThread.cpp").read_text()
        start = thread.index("\tvoid thread::flip(const display_flip_info_t& info)")
        end = thread.index("\n\tvoid thread::check_zcull_status", start)
        base = "namespace rsx {\n" + thread[start:end] + "\n}\n"
        with tempfile.TemporaryDirectory() as temporary:
            for name, text, expected in (("old", old.decode(), 10), ("new", generator.prepare(old), 0)):
                start = text.index("            case VK_ERROR_SURFACE_LOST_KHR:")
                end = text.index("\t\tcase VK_ERROR_OUT_OF_DATE_KHR:", start)
                body = text[start:end].split(":", 1)[1]
                source = Path(temporary) / (name + ".cpp")
                binary = Path(temporary) / name
                source.write_text(PREFIX + base + "void VKGSRender::lost(const rsx::display_flip_info_t& info) {\n"
                                  + "(void)info;\n" + body + "}\n" + SUFFIX)
                subprocess.run(["c++", "-std=c++20", "-Wall", "-Wextra", "-Werror", "-fno-exceptions",
                                "-fsanitize=address,undefined", str(source), "-o", str(binary)], check=True)
                self.assertEqual(subprocess.run([str(binary)]).returncode, expected)


if __name__ == "__main__":
    unittest.main()
