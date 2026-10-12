import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "unified-android" / "tools" / "verify_n64_stop_race_evidence.py"
SPEC = importlib.util.spec_from_file_location("n64_stop_race_evidence", TOOL)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class N64StopRaceEvidenceTest(unittest.TestCase):
    def test_818_r2_surface_race_fails_despite_2ms_return(self):
        result = MODULE.audit("""
I/EmuFusionInWindow: Exit to Lucent invoked engine=mupen64plus-next system=n64 reason=thor-stop-hold
E/BufferQueueProducer: dequeueBuffer: BufferQueue has been abandoned
E/EmuFusionPhase2Engine: Renderer stopped engine=mupen64plus-next system=n64
E/EmuFusionPhase2Engine: java.lang.IllegalStateException: Android EGL swap failed (0x300d)
I/EmuFusionInWindow: Returned to Lucent immediately in same window engine=mupen64plus-next system=n64 latencyMs=2
E/EmuFusionInWindow: Engine session error engine=mupen64plus-next system=n64 message=Lucent could not protect Quick Resume.
E/EmuFusionInWindow: java.lang.IllegalStateException: engine state vault is not ready
W/EmuFusionInWindow: Exit checkpoint failed after library return
E/libEGL: call to OpenGL ES API with no current context
""")
        self.assertFalse(result.passed)
        self.assertEqual(result.return_latencies_ms, (2,))
        self.assertGreaterEqual(result.surface_race_count, 3)
        self.assertGreaterEqual(result.session_error_count, 2)
        self.assertGreaterEqual(result.save_failure_count, 2)

    def test_clean_background_commit_after_instant_return_passes(self):
        result = MODULE.audit("""
I/EmuFusionInWindow: Exit to Lucent invoked engine=mupen64plus-next system=n64 reason=thor-stop-hold
I/EmuFusionInWindow: Returned to Lucent immediately in same window engine=mupen64plus-next system=n64 latencyMs=3
I/EmuFusionPhase2Engine: Committed Quick Resume before stop engine=mupen64plus-next commit=f275caf
I/EmuFusionInWindow: Exit checkpoint finished after library return engine=mupen64plus-next system=n64
""")
        self.assertTrue(result.passed, result.errors)

    def test_fast_return_without_commit_fails_closed(self):
        result = MODULE.audit("""
I/EmuFusionInWindow: Exit to Lucent invoked engine=mupen64plus-next system=n64
I/EmuFusionInWindow: Returned to Lucent immediately in same window engine=mupen64plus-next system=n64 latencyMs=1
""")
        self.assertFalse(result.passed)
        self.assertTrue(any("Quick Resume commit" in error
                            for error in result.errors))

    def test_commit_before_visible_return_is_rejected(self):
        result = MODULE.audit("""
I/EmuFusionInWindow: Exit to Lucent invoked engine=mupen64plus-next system=n64
I/EmuFusionPhase2Engine: Committed Quick Resume before stop engine=mupen64plus-next
I/EmuFusionInWindow: Returned to Lucent immediately in same window engine=mupen64plus-next system=n64 latencyMs=40
I/EmuFusionInWindow: Exit checkpoint finished after library return engine=mupen64plus-next system=n64
""")
        self.assertFalse(result.passed)
        self.assertTrue(any("exit ordering" in error for error in result.errors))

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
            json.dumps({"exactInstall": {"installedSha256": "cd" * 32}}),
            encoding="utf-8",
        )
        with self.assertRaises(SystemExit) as caught:
            MODULE.require_apk_identity(evidence, "ab" * 32)
        self.assertIn("never transfers across SHAs", str(caught.exception))
        MODULE.require_apk_identity(evidence, "CD" * 32)

    def test_slow_return_is_not_hidden_by_successful_commit(self):
        result = MODULE.audit("""
I/EmuFusionInWindow: Exit to Lucent invoked engine=mupen64plus-next system=n64
I/EmuFusionInWindow: Returned to Lucent immediately in same window engine=mupen64plus-next system=n64 latencyMs=120
I/EmuFusionPhase2Engine: Committed Quick Resume before stop engine=mupen64plus-next
I/EmuFusionInWindow: Exit checkpoint finished after library return engine=mupen64plus-next system=n64
""")
        self.assertFalse(result.passed)
        self.assertTrue(any("exceeded 50ms" in error for error in result.errors))


if __name__ == "__main__":
    unittest.main()
