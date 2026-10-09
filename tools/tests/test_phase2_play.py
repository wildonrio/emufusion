import hashlib
import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "engines" / "phase2-registry.json"
LOCK = ROOT / "engines" / "play-source-lock.json"
RECIPE = ROOT / "engines" / "build_core.sh"


class PhaseTwoPlayTest(unittest.TestCase):
    def setUp(self):
        self.registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
        self.lock = json.loads(LOCK.read_text(encoding="utf-8"))
        self.recipe = RECIPE.read_text(encoding="utf-8")
        self.row = next(row for row in self.registry["engines"]
                        if row["id"] == "play")

    def test_recipe_uses_every_exact_locked_archive_and_fresh_staging(self):
        block = re.search(r"    play\).*?        ;;", self.recipe, re.DOTALL)
        self.assertIsNotNone(block)
        text = block.group(0)
        for identity in [self.lock["core"], *self.lock["dependencies"]]:
            self.assertIn(identity["commit"], text)
            self.assertIn(identity["archiveSha256"], text)
            self.assertIn(identity["repository"], text)
        self.assertGreaterEqual(text.count("fetch_source_fresh"), 13)
        self.assertIn("-DBUILD_LIBRETRO_CORE=ON", text)
        self.assertIn("-DBUILD_PLAY=OFF", text)
        self.assertIn("-DBUILD_TESTS=OFF", text)
        self.assertIn('ANDROID_ABI="$ABI"', text)
        self.assertIn('ANDROID_PLATFORM="android-$API"', text)

    def test_registry_and_dependency_lock_are_identical(self):
        source = self.row["source"]
        actual = {entry["path"]: (
            entry["repository"], entry["commit"], entry["archiveSha256"])
                  for entry in source["submodules"]}
        expected = {entry["path"]: (
            entry["repository"], entry["commit"], entry["archiveSha256"])
                    for entry in self.lock["dependencies"]}
        self.assertEqual(expected, actual)
        self.assertEqual(self.lock["core"]["repository"], source["repository"])
        self.assertEqual(self.lock["core"]["commit"], source["commit"])
        self.assertEqual(self.lock["core"]["archiveSha256"],
                         source["archiveSha256"])

    def test_every_integration_patch_is_hash_locked_and_recipe_verified(self):
        expected = {
            "play-expose-android-javavm-hook.patch",
            "play-libretro-no-jni-thread-attach.patch",
            "play-libretro-chain-ee-signal-handler.patch",
            "play-libretro-output-size-hook.patch",
            "play-libretro-lossless-audio-fifo.patch",
            "play-libretro-safe-state.patch",
        }
        patches = self.lock.get("patches", [])
        self.assertEqual(expected, {Path(row["path"]).name for row in patches})
        self.assertIn("apply_locked_patch", self.recipe)
        for row in patches:
            path = ROOT / row["path"]
            self.assertTrue(path.is_file(), row["path"])
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(row["sha256"], digest, row["path"])
            self.assertIn(row["path"], self.recipe)
            self.assertIn(row["sha256"], self.recipe)

    def test_play_keeps_fast_page_protection_and_restores_signal_handler(self):
        self.assertNotIn("play-libretro-disable-ee-page-protection.patch",
                         self.recipe)
        patch = (ROOT / "engines" / "patches" /
                 "play-libretro-chain-ee-signal-handler.patch").read_text(
                     encoding="utf-8")
        self.assertNotIn("+#define DISABLE_PROTECTION", patch)
        self.assertIn("&m_previousSigSegvAction", patch)
        self.assertIn("sigaction(SIGSEGV, &m_previousSigSegvAction, nullptr)",
                      patch)
        self.assertIn("previous.sa_sigaction(sigId, sigInfo, baseContext)",
                      patch)
        self.assertIn("0x00FFFFFFFFFFFFFFULL", patch)

    def test_checked_in_proof_matches_registry(self):
        # Uncommitted, build-Mac-only input (see tools/run_ci_tests.py).
        for needed in (ROOT / self.row["build"]["proofArtifactPath"],):
            if not needed.exists():
                self.skipTest("local-only input absent: " + str(needed))
        proof = ROOT / self.row["build"]["proofArtifactPath"]
        self.assertTrue(proof.is_file())
        digest = hashlib.sha256(proof.read_bytes()).hexdigest()
        self.assertEqual(self.row["build"]["proofArtifactSha256"], digest)
        self.assertEqual("build-reproduced",
                         self.row["android"]["integrationEvidence"])
        self.assertEqual(23, self.row["android"]["minApi"])
        self.assertTrue(self.row["gates"]["androidArm64"])

    def test_distribution_and_runtime_gates_remain_closed(self):
        self.assertFalse(self.row["shipped"])
        self.assertFalse(self.row["license"]["dependencyAuditComplete"])
        for gate in ("license", "dependencies", "legalContent", "renderer",
                     "state", "performance", "device"):
            self.assertFalse(self.row["gates"][gate], gate)


if __name__ == "__main__":
    unittest.main()
