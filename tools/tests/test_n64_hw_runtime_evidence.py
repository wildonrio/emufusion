import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "unified-android" / "tools" / "verify_n64_hw_runtime_evidence.py"
SPEC = importlib.util.spec_from_file_location("n64_hw_runtime_evidence", TOOL)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class N64HardwareRuntimeEvidenceTest(unittest.TestCase):
    def test_00616_style_gl_rejection_fails_closed(self):
        result = MODULE.audit("""
I/EmuFusionInWindow: In-window route accepted engine=mupen64plus-next system=n64
I/LucentNativeHost: core library loaded path=liblucent_core_mupen64plus_next.so
I/LucentNativeHost: retro_load_game begin path=game.z64 needFullpath=0
E/LucentLibretroCore: mupen64plus: libretro frontend doesn't have OpenGL support
E/EmuFusionPhase2Engine: Renderer stopped engine=mupen64plus-next system=n64
E/EmuFusionPhase2Engine: java.lang.IllegalStateException: core rejected game content
""")
        self.assertFalse(result.passed)
        self.assertTrue(result.negotiation_rejected)
        self.assertTrue(any("SET_HW_RENDER" in error for error in result.errors))
        self.assertEqual(result.presented_frame_count, 0)

    def test_core_load_alone_is_never_a_pass(self):
        result = MODULE.audit("""
I/EmuFusionInWindow: In-window route accepted engine=mupen64plus-next system=n64
I/LucentNativeHost: core library loaded path=liblucent_core_mupen64plus_next.so
""")
        self.assertFalse(result.passed)
        self.assertIn("retro_load_game never completed", result.errors)
        self.assertTrue(any("acceptance marker" in error
                            for error in result.errors))

    def test_complete_negotiated_gpu_path_passes(self):
        result = MODULE.audit("""
I/EmuFusionInWindow: In-window route accepted engine=mupen64plus-next system=n64
I/LucentNativeHost: hardware render request accepted context=OPENGLES3 cacheContext=1
I/LucentNativeHost: retro_load_game complete
I/LucentLibretroCore: mupen64plus: context_reset()
I/LucentGlesBackend: pre-swap pixels sequence=1 policy=2 path=2 window=1,2,3,255 frontend=0,0,0,0 fbo=0
""")
        self.assertTrue(result.passed, result.errors)
        self.assertEqual(result.hardware_contexts, ("OPENGLES3",))
        self.assertEqual(result.context_reset_count, 1)
        self.assertEqual(result.presented_frame_count, 1)

    def make_evidence(self, **contents) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        evidence = Path(temporary.name)
        for name, payload in contents.items():
            path = evidence / name.replace("__", ".")
            if isinstance(payload, (dict, list)):
                path.write_text(json.dumps(payload), encoding="utf-8")
            else:
                path.write_text(payload, encoding="utf-8")
        return evidence

    def test_expected_apk_sha256_is_required_on_the_command_line(self):
        completed = subprocess.run(
            [sys.executable, str(TOOL), "/nonexistent"],
            capture_output=True, text=True,
        )
        self.assertEqual(2, completed.returncode)
        self.assertIn("--expected-apk-sha256", completed.stderr)

    def test_evidence_without_recorded_identity_fails_closed(self):
        evidence = self.make_evidence()
        with self.assertRaises(SystemExit) as caught:
            MODULE.require_apk_identity(evidence, "ab" * 32)
        self.assertIn("records no APK identity", str(caught.exception))

    def test_evidence_from_a_different_apk_sha_is_rejected(self):
        evidence = self.make_evidence(
            results__json={"expectedSha256": "cd" * 32},
        )
        with self.assertRaises(SystemExit) as caught:
            MODULE.require_apk_identity(evidence, "ab" * 32)
        self.assertIn("never transfers across SHAs", str(caught.exception))

    def test_matching_results_json_identity_passes(self):
        for record in (
            {"apkSha256": "AB" * 32},
            {"expectedSha256": "ab" * 32},
            {"exactInstall": {"installedSha256": "ab" * 32}},
            {"exactInstall": {"candidateSha256": "ab" * 32}},
        ):
            evidence = self.make_evidence(results__json=record)
            MODULE.require_apk_identity(evidence, "ab" * 32)

    def test_installed_base_sha256_marker_file_binds_identity(self):
        evidence = self.make_evidence(
            **{"installed-base-sha256__txt": ("ab" * 32) + "  base.apk\n"},
        )
        MODULE.require_apk_identity(evidence, "AB" * 32)
        with self.assertRaises(SystemExit):
            MODULE.require_apk_identity(evidence, "cd" * 32)

    def test_malformed_expected_hash_is_rejected(self):
        evidence = self.make_evidence(results__json={"apkSha256": "ab" * 32})
        with self.assertRaises(SystemExit) as caught:
            MODULE.require_apk_identity(evidence, "not-a-sha")
        self.assertIn("64-digit hex", str(caught.exception))

    def test_zero_sequence_is_not_presented_frame_proof(self):
        result = MODULE.audit("""
I/EmuFusionInWindow: In-window route accepted engine=mupen64plus-next system=n64
I/LucentNativeHost: hardware render accepted context=OPENGLES3
I/LucentNativeHost: retro_load_game complete
I/LucentNativeHost: hardware context reset complete
I/LucentGlesBackend: pre-swap pixels sequence=0 policy=2
""")
        self.assertFalse(result.passed)
        self.assertEqual(result.presented_frame_count, 0)


if __name__ == "__main__":
    unittest.main()
