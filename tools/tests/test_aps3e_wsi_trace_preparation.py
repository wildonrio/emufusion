"""Validate isolated WSI logging without treating it as runtime qualification."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from tools.tests.test_aps3e_present_surface_lost import SOURCE, PREFIX, SUFFIX

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "engines/diagnostics/prepare_wsi_trace.py"
spec = importlib.util.spec_from_file_location("wsi_trace_preparation", SCRIPT)
TRACE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(TRACE)


class WsiTracePreparationTest(unittest.TestCase):
    def test_rejects_unreviewed_source(self):
        with self.assertRaisesRegex(ValueError, "source changed"):
            TRACE.instrument(b"another agent's source changes")

    @unittest.skipUnless(SOURCE.is_file(), "local aPS3e source absent")
    def test_driver_operations_not_duplicated_and_timeout_logs_only_on_change(self):
        original = SOURCE.read_bytes()
        generated = TRACE.instrument(original)
        for operation in ("_vkDeviceWaitIdle(", "m_swapchain->present(",
                          "m_swapchain->acquire_next_swapchain_image(",
                          "m_swapchain->create(", "m_swapchain->init(",
                          "vk::wait_for_fence("):
            self.assertEqual(original.decode().count(operation), generated.count(operation), operation)
        self.assertIn("if (status != lucent_last_acquire_result)", generated)
        for stage in ("reinit.enter", "reinit.submit.begin", "reinit.submit.end",
                      "reinit.cleanup.begin", "reinit.cleanup.end", "reinit.idle.begin",
                      "reinit.idle.end", "reinit.surface.begin", "reinit.surface.end",
                      "reinit.swapchain.begin", "reinit.swapchain.end", "reinit.swapchain.failed",
                      "reinit.resize-wait.begin", "reinit.resize-wait.end", "reinit.exit",
                      "present.call.begin", "present.call.end", "acquire.begin",
                      "acquire.result", "acquire.complete", "flip.enter"):
            self.assertIn('"' + stage, generated)
        self.assertEqual(original, SOURCE.read_bytes())

    @unittest.skipUnless(SOURCE.is_file(), "local aPS3e source absent")
    def test_cli_never_overwrites_existing_output(self):
        with tempfile.TemporaryDirectory(prefix="wsi-trace-refusal-") as directory:
            output = Path(directory) / "existing.cpp"
            output.write_text("preserve this file")
            result = subprocess.run([sys.executable, "-B", str(SCRIPT), "--source", str(SOURCE),
                                     "--output", str(output)], capture_output=True, text=True)
            self.assertNotEqual(0, result.returncode)
            self.assertEqual("preserve this file", output.read_text())

    @unittest.skipUnless(SOURCE.is_file() and shutil.which("c++"), "local source/compiler absent")
    def test_instrumented_present_handler_keeps_all_existing_result_controls(self):
        generated = TRACE.instrument(SOURCE.read_bytes())
        start = generated.index("void VKGSRender::present(")
        end = generated.index("void VKGSRender::advance_queued_frames()", start)
        with tempfile.TemporaryDirectory(prefix="wsi-trace-behavior-") as directory:
            source, binary = Path(directory) / "test.cpp", Path(directory) / "test"
            source.write_text("#include <initializer_list>\n#define LUCENT_WSI_EVENT(...) ((void)0)\n"
                              + PREFIX + generated[start:end] + SUFFIX)
            subprocess.run(["c++", "-std=c++20", "-Wall", "-Wextra", "-Werror", str(source),
                            "-o", str(binary)], check=True)
            self.assertEqual(0, subprocess.run([str(binary)]).returncode)


if __name__ == "__main__":
    unittest.main()
