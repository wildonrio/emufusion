import importlib.util
import json
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "unified-android" / "tools" / "verify_runtime_return_evidence.py"
SPEC = importlib.util.spec_from_file_location("runtime_return_evidence", TOOL)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class RuntimeReturnEvidenceTest(unittest.TestCase):
    def test_activity_start_and_resume_are_release_failures(self):
        log = """
E/ActivityTaskManager: START u0 {act=com.thorium.preview.LAUNCH_INTERNAL_GAME cmp=com.thorium.preview/org.pegasus_frontend.android.MainActivity}
I/LucentInWindow: In-window route accepted engine=mesen system=nes
I/ActivityThread: performResumeActivity com.thorium.preview displayId 0
I/LucentInWindow: Returned to Lucent immediately in same window engine=mesen system=nes latencyMs=1
"""
        result = MODULE.audit(log, {"return-01.png": "Nintendo menu"})
        self.assertFalse(result.passed)
        self.assertEqual(result.activity_launch_count, 1)
        self.assertEqual(result.lifecycle_resume_count, 1)
        self.assertTrue(any("ActivityTaskManager START" in error
                            for error in result.errors))

    def test_visible_splash_overrules_fast_host_marker(self):
        log = (
            "I/LucentInWindow: Returned to Lucent immediately in same window "
            "engine=mesen system=nes latencyMs=1\n"
        )
        result = MODULE.audit(log, {
            "return-01.png": "gameplay",
            "return-02.png": "LUCENT POWERED BY PEGASUS",
        })
        self.assertFalse(result.passed)
        self.assertEqual(result.host_return_latencies_ms, (1,))
        self.assertEqual(result.visible_reset_frames, ("return-02.png",))
        self.assertTrue(any("despite host latency marker min=1ms" in error
                            for error in result.errors))

    def test_receiver_route_with_clean_frames_passes(self):
        log = """
I/LucentLaunchReceiver: received launch
I/LucentInWindow: In-window route accepted engine=mesen system=nes
I/LucentInWindow: Returned to Lucent immediately in same window engine=mesen system=nes latencyMs=7
"""
        result = MODULE.audit(log, {
            "return-01.png": "Nintendo Entertainment System 10-Yard Fight",
            "return-02.png": "Nintendo Entertainment System 1943",
        }, visible_return_upper_bounds_ms=(23,))
        self.assertTrue(result.passed, result.errors)

    def test_missing_return_marker_is_not_inferred_from_clean_screen(self):
        result = MODULE.audit(
            "I/LucentInWindow: In-window route accepted engine=mesen system=nes",
            {"return-01.png": "Nintendo menu"},
        )
        self.assertFalse(result.passed)
        self.assertIn("no in-window return marker was captured", result.errors)

    def test_host_or_visible_latency_over_five_hundred_ms_fails(self):
        host = MODULE.audit(
            "Returned to Lucent immediately in same window latencyMs=501",
            {"return.png": "SYSTEM VIEW"},
            visible_return_upper_bounds_ms=(20,),
        )
        self.assertTrue(any("in-process" in error for error in host.errors))
        visible = MODULE.audit(
            "Returned to Lucent immediately in same window latencyMs=5",
            {"return.png": "SYSTEM VIEW"},
            visible_return_upper_bounds_ms=(501,),
        )
        self.assertTrue(any("composed-pixel" in error
                            for error in visible.errors))

    def test_expected_apk_sha256_is_required_on_the_command_line(self):
        completed = subprocess.run(
            [sys.executable, str(TOOL), "/nonexistent"],
            capture_output=True, text=True,
        )
        self.assertEqual(2, completed.returncode)
        self.assertIn("--expected-apk-sha256", completed.stderr)

    def test_evidence_identity_binding_fails_closed(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        evidence = Path(temporary.name)
        with self.assertRaises(SystemExit) as caught:
            MODULE.require_apk_identity(evidence, "ab" * 32)
        self.assertIn("records no APK identity", str(caught.exception))
        (evidence / "results.json").write_text(
            json.dumps({"apkSha256": "cd" * 32}), encoding="utf-8",
        )
        with self.assertRaises(SystemExit) as caught:
            MODULE.require_apk_identity(evidence, "ab" * 32)
        self.assertIn("never transfers across SHAs", str(caught.exception))
        MODULE.require_apk_identity(evidence, "cd" * 32)

    def test_stored_pass_cannot_hide_stored_splash_ocr(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "results.json"
        path.write_text(json.dumps({
            "complete": True,
            "counts": {"PASS": 1, "FAIL": 0},
            "systems": [{"titles": [{"heldStop": {
                "hostReturnLatencyMs": 3,
                "interstitialOcr": [{
                    "path": "/evidence/megadrive-return-02.png",
                    "ocr": "G<_ LUCENT",
                }],
            }}]}],
        }), encoding="utf-8")
        ocr, latencies, reports = MODULE.stored_result_evidence(path)
        self.assertEqual(ocr, {"megadrive-return-02.png": "G<_ LUCENT"})
        self.assertEqual(latencies, (3,))
        self.assertEqual(reports, ())
        result = MODULE.audit(
            "I/LucentInWindow: Returned to Lucent immediately in same window "
            "latencyMs=3",
            ocr,
        )
        self.assertFalse(result.passed)
        self.assertEqual(result.visible_reset_frames,
                         ("megadrive-return-02.png",))

    def test_visible_video_report_is_recomputed_from_winscope_mp4(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        evidence = Path(temporary.name)
        timestamps = [10_000_000_000, 10_010_000_000, 10_020_000_001]
        video = evidence / "gc-return-visible.mp4"
        video.write_bytes(
            b"prefix" + MODULE.return_video.WINSC0PE_V2_MAGIC +
            struct.pack("<IqI", 2, 0, len(timestamps)) +
            struct.pack(f"<{len(timestamps)}Q", *timestamps) + b"suffix"
        )
        reports = ({
            "method": "screenrecord-winscope-v2-device-clock-upper-bound",
            "thresholdLowerBoundElapsedNs": 10_000_000_000,
            "firstMenuFrameIndex": 2,
            "firstMenuElapsedNs": 10_020_000_001,
            "visibleReturnLatencyUpperBoundMs": 21,
            "videoPath": "/old/path/gc-return-visible.mp4",
        },)
        bounds, errors = MODULE.validate_visible_video_reports(evidence, reports)
        self.assertEqual(bounds, (21,))
        self.assertEqual(errors, ())
        forged = (dict(reports[0], visibleReturnLatencyUpperBoundMs=1),)
        bounds, errors = MODULE.validate_visible_video_reports(evidence, forged)
        self.assertEqual(bounds, ())
        self.assertTrue(any("upward-rounded" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
