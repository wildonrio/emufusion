import hashlib
import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "engines" / "phase2-registry.json"
RECIPE = ROOT / "engines" / "build_core.sh"


class PhaseTwoVirtualJaguarTest(unittest.TestCase):
    def setUp(self):
        self.registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
        self.recipe = RECIPE.read_text(encoding="utf-8")
        self.row = next(row for row in self.registry["engines"]
                        if row["id"] == "virtualjaguar")

    def test_recipe_uses_exact_official_archive_and_fresh_staging(self):
        source = self.row["source"]
        block = re.search(r"    virtualjaguar\).*?        ;;",
                          self.recipe, re.DOTALL)
        self.assertIsNotNone(block)
        text = block.group(0)
        self.assertIn(source["commit"], text)
        self.assertIn(source["archiveSha256"], text)
        self.assertIn(source["repository"], text)
        self.assertIn("fetch_source_fresh virtualjaguar", text)
        self.assertIn('APP_ABI="$ABI"', text)
        self.assertIn('APP_PLATFORM="android-$API"', text)

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
        self.assertTrue(self.row["gates"]["androidArm64"])

    def test_distribution_and_runtime_gates_remain_closed(self):
        self.assertFalse(self.row["shipped"])
        self.assertFalse(self.row["license"]["dependencyAuditComplete"])
        for gate in ("license", "dependencies", "firmware", "legalContent",
                     "renderer", "state", "performance", "device"):
            self.assertFalse(self.row["gates"][gate], gate)


if __name__ == "__main__":
    unittest.main()
