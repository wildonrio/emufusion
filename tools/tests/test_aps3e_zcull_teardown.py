"""Exercise source-derived ZCULL ownership with missing/throwing exit callbacks.

This is a host ownership regression, not a Vulkan or device Quick Resume pass.
"""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "engines/build/sources/aps3e-b5ae1af50d5e2f3b705506e7380a4504e086840b/app/src/main/cpp/rpcs3/rpcs3/Emu/RSX/VK/VKGSRender.cpp"
GEN = ROOT / "engines/diagnostics/prepare_zcull_teardown.py"
spec = importlib.util.spec_from_file_location("zcull_teardown", GEN)
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)

PREFIX = r'''
#include <cassert>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>
int control_destructions = 0;
int throw_stage = 0;
namespace rsx::reports {
struct ZCULL_control {
    std::vector<int> pending = std::vector<int>(16, 42);
    virtual ~ZCULL_control() { ++control_destructions; }
};
}
struct GSRender {
    std::unique_ptr<rsx::reports::ZCULL_control> zcull_ctrl;
    virtual ~GSRender() = default;
    void on_exit() { if (throw_stage == 1) throw std::runtime_error("exit"); }
};
namespace vk {
void destroy_pipe_compiler() {
    if (throw_stage == 2) throw std::runtime_error("compiler exit");
}
}
struct VKGSRender : GSRender, rsx::reports::ZCULL_control {
    ~VKGSRender() override;
    void on_exit();
    void bind();
};
'''
SUFFIX = r'''
int main(int argc, char** argv) {
    assert(argc == 2);
    const std::string mode = argv[1];
    {
        VKGSRender renderer;
        if (mode == "owned") {
            renderer.zcull_ctrl = std::make_unique<rsx::reports::ZCULL_control>();
        } else if (mode != "uninitialized") {
            renderer.bind();
            if (mode != "skipped") {
                throw_stage = mode == "throw_gs" ? 1 : mode == "throw_compiler" ? 2 : 0;
                try { renderer.on_exit(); } catch (const std::runtime_error&) {}
            }
        }
    }
    assert(control_destructions == (mode == "owned" ? 2 : 1));
}
'''


@unittest.skipUnless(SRC.is_file(), "local aPS3e source absent")
class ZcullTeardownTest(unittest.TestCase):
    def test_exact_narrow_change_and_drift_rejection(self):
        old = SRC.read_bytes()
        self.assertEqual(generator.prepare(old).replace(generator.NEW, generator.OLD, 1), old.decode())
        with self.assertRaises(ValueError):
            generator.prepare(old + b"\n")

    def test_refuses_existing_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "candidate.cpp"
            output.write_text("other agent code")
            result = subprocess.run(["python3", str(GEN), "--source", str(SRC),
                                     "--output", str(output)], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(output.read_text(), "other agent code")

    @unittest.skipUnless(shutil.which("c++"), "compiler absent")
    def test_source_ownership_old_fails_interrupted_exit_new_passes(self):
        old = SRC.read_bytes()
        with tempfile.TemporaryDirectory() as temporary:
            for label, text in (("old", old.decode()), ("new", generator.prepare(old))):
                start = text.index(generator.OLD)
                end = text.index("\tif (m_device == VK_NULL_HANDLE)", start)
                # Stop before GPU work; preserve actual destructor-entry ownership.
                destructor = text[start:end] + "}\n"
                start = text.index("void VKGSRender::on_exit()")
                end = text.index("\nvoid VKGSRender::clear_surface", start)
                on_exit = text[start:end]
                bind = "zcull_ctrl.reset(static_cast<::rsx::reports::ZCULL_control*>(this));"
                self.assertEqual(text.count(bind), 1)
                source = Path(temporary) / (label + ".cpp")
                binary = Path(temporary) / label
                source.write_text(PREFIX + destructor + on_exit
                                  + "void VKGSRender::bind() {" + bind + "}\n" + SUFFIX)
                subprocess.run(["c++", "-std=c++20", "-Wall", "-Wextra", "-Werror",
                                "-fsanitize=address,undefined", str(source), "-o", str(binary)], check=True)
                for mode in ("normal", "skipped", "throw_gs", "throw_compiler", "owned", "uninitialized"):
                    with self.subTest(candidate=label, mode=mode):
                        result = subprocess.run([str(binary), mode], capture_output=True, text=True)
                        if label == "old" and mode in ("skipped", "throw_gs", "throw_compiler"):
                            self.assertNotEqual(result.returncode, 0)
                            self.assertIn("AddressSanitizer", result.stderr)
                        else:
                            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(SRC.read_bytes(), old)


if __name__ == "__main__":
    unittest.main()
