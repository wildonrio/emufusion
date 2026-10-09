"""Startup driver-bound regressions; these tests do not certify device timing."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / "unified-android/lsfg-qualification-native"


class LsfgStartupPresentTimingTest(unittest.TestCase):
    def test_build_gate_accepts_driver_bound_but_rejects_old_tokenless_substitution(self):
        # Uncommitted, build-Mac-only input (see tools/run_ci_tests.py).
        for needed in (ROOT / "experiments/lsfg-vulkan-android-inprocess/tools/verify_owned_wsi_setup_source.py",):
            if not needed.exists():
                self.skipTest("local-only input absent: " + str(needed))
        gate = ROOT / "experiments/lsfg-vulkan-android-inprocess/tools/verify_owned_wsi_setup_source.py"
        import sys
        with tempfile.TemporaryDirectory(prefix="lsfg-driver-gate-") as temporary:
            directory = Path(temporary)
            for name in ("owned_vulkan_host.cpp", "owned_surface_control_presenter.cpp",
               "lsfg_qualification_jni.cpp", "continuous_inference.hpp", "CMakeLists.txt"):
                shutil.copyfile(NATIVE / name, directory / name)
            command = [sys.executable, str(gate), "--native-dir", str(directory)]
            passed = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(passed.returncode, 0, passed.stdout + passed.stderr)
            native = directory / "lsfg_qualification_jni.cpp"
            text = native.read_text()
            first, rest = text.split("dispatchReadySurfaceSubmission(Host*", 1)
            rest = rest.replace("submission->desiredPresentTimeNs,",
                                "submission->physicalPresentTimeNs,", 1)
            native.write_text(first + "dispatchReadySurfaceSubmission(Host*" + rest)
            rejected = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("driver-request bound", rejected.stderr)

    def test_compiled_driver_bound_and_recorded_scan_boundary_regression(self):
        compiler = shutil.which("c++")
        self.assertIsNotNone(compiler)
        with tempfile.TemporaryDirectory(prefix="lsfg-startup-timing-") as temporary:
            executable = Path(temporary) / "surface_present_timing_test"
            result = subprocess.run([
                compiler, "-std=c++20", "-Wall", "-Wextra", "-Werror",
                "-fsanitize=address,undefined", "-I", str(NATIVE),
                str(NATIVE / "tests/surface_present_timing_test.cpp"),
                "-o", str(executable),
            ], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(executable)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_tokenless_pipeline_preserves_requested_driver_bound_and_identity(self):
        native = (NATIVE / "lsfg_qualification_jni.cpp").read_text()
        pipeline = native.split("dispatchReadySurfaceSubmission(Host*", 1)[1].split(
            "void logSurfaceTimingDiagnostic", 1)[0]
        call = pipeline.split("surfacePresenter->present(", 1)[1].split(
            "if (!accepted)", 1)[0]
        self.assertIn("submission->desiredPresentTimeNs,", call)
        self.assertNotIn("submission->physicalPresentTimeNs", call)
        host = (NATIVE / "owned_vulkan_host.cpp").read_text()
        expected = host.split("const uint64_t expectedSurfaceDesiredNs =", 1)[1].split(
            "const VkResult fenceStatus", 1)[0]
        self.assertIn("slot->request.desiredPresentTimeNs;", expected)
        self.assertNotIn("slot->request.physicalPresentTimeNs", expected)
        self.assertIn("desiredPresentTimeNs != expectedSurfaceDesiredNs", expected)

    def test_startup_targets_stay_immutable_and_fenceless_evidence_stays_failed(self):
        native = (NATIVE / "lsfg_qualification_jni.cpp").read_text()
        test = native.split("void runBoundedSurfaceControlSelfTest", 1)[1].split(
            "void runBoundedLiveSurfaceControlSelfTest", 1)[0]
        self.assertIn("startupDriverPresentTimeNs(firstPhysical)", test)
        self.assertIn("startupDriverPresentTimeNs(secondPhysical)", test)
        self.assertIn("1, firstDriverDesired", test)
        self.assertIn("2, secondDriverDesired", test)
        self.assertIn("firstNormalizedActual, firstPhysical, intervalTolerance", test)
        self.assertIn("secondNormalizedActual, secondPhysical, intervalTolerance", test)
        self.assertIn("intervalError <= intervalTolerance", test)
        self.assertIn("presentId=\" + std::to_string(unavailable.front())", native)
        self.assertIn('"startup-live-pair"', native)
        self.assertIn('"startup-live-cadence"', native)
        presenter = (NATIVE / "owned_surface_control_presenter.cpp").read_text()
        self.assertIn("if (reported == 4) break;", presenter)
        self.assertIn('\\"presentFenceFd\\":', presenter)
        self.assertIn('\\"applyEndNs\\":', presenter)


if __name__ == "__main__":
    unittest.main()
