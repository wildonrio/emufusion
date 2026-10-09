import importlib.util
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "surface_capture", ROOT / "unified-android/tools/capture_surface_latency.py")
capture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(capture)


class CaptureTests(unittest.TestCase):
    def test_remote_shell_preserves_exact_layer(self):
        for layer in ("EmuFusion LSFG owned output#36049", "a 'quoted'; $(false) layer"):
            command = capture.latency_command("adb", "427c87b2", layer)
            self.assertEqual(command[:4], ["adb", "-s", "427c87b2", "shell"])
            self.assertEqual(shlex.split(command[4]),
                             ["dumpsys", "SurfaceFlinger", "--latency", layer])

    def test_empty_and_pending_histories_fail(self):
        for raw in ("", "8333333\n", "8333333\n0 0 0\n",
                    "8333333\n1 9223372036854775807 1\n"):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                capture.inspect_history(raw)

    def test_invalid_rows_break_intervals_without_bridging(self):
        result = capture.inspect_history(
            "8333333\n1 100 1\n2 200 2\n0 0 0\n3 10000 3\n4 10100 4\n")
        self.assertEqual(result["adjacent_intervals"], 2)
        self.assertEqual(result["max_interval_ns"], 100)
        self.assertEqual(result["qualification"], "NOT_ASSESSED")

    def test_malformed_or_reversed_histories_fail(self):
        for raw in ("8333333\n1 2\n", "8333333\n1 100 1\n2 100 2\n",
                    "8333333\n1 200 1\n2 100 2\n"):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                capture.inspect_history(raw)

    def test_failed_capture_is_preserved_and_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "raw.txt"
            def runner(command, **kwargs):
                self.assertEqual(len(command), 5)
                self.assertEqual(kwargs["timeout"], 15)
                return subprocess.CompletedProcess(command, 0, "8333333\n", "")
            with self.assertRaises(ValueError):
                capture.capture("adb", "serial", "layer", output, runner)
            self.assertEqual(output.read_text(), "8333333\n")
            with self.assertRaises(FileExistsError):
                capture.capture("adb", "serial", "layer", output, runner)
