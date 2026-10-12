import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class ProSystemPhase1Test(unittest.TestCase):
    def setUp(self):
        registry = json.loads((ROOT / "engines/registry.json").read_text(encoding="utf-8"))
        self.row = next(row for row in registry["engines"] if row["id"] == "prosystem")
        self.audit = json.loads((
            ROOT / "engines/audits/prosystem-license.json"
        ).read_text(encoding="utf-8"))

    def test_candidate_is_pinned_compatible_and_fail_closed(self):
        self.assertEqual("1A", self.row["tier"])
        self.assertEqual("experimental", self.row["status"])
        self.assertEqual("GPL-2.0-or-later", self.row["license"]["spdx"])
        self.assertEqual("compatible-candidate", self.row["license"]["distributionGate"])
        self.assertEqual(
            "7abed225b58d306bd3988c6950f851aa52a4c7b30d97cedcf626aa18fbf05282",
            self.row["source"]["archiveSha256"],
        )
        self.assertFalse(self.row["state"]["qualified"])
        self.assertTrue(self.row["build"]["reproducible"])
        self.assertFalse(self.row["shipped"])
        self.assertFalse(self.row["firmware"]["required"])

    def test_recipe_and_license_audit_are_locked(self):
        recipe = (ROOT / "engines/build_core.sh").read_text(encoding="utf-8")
        for value in (
            "prosystem)",
            "363b6dfbd3e240762e022c2b4897b4fe55722be3",
            "7abed225b58d306bd3988c6950f851aa52a4c7b30d97cedcf626aa18fbf05282",
            "prosystem-LICENSE.txt",
        ):
            self.assertIn(value, recipe)
        self.assertEqual(self.row["source"]["commit"], self.audit["sourceCommit"])
        self.assertTrue(self.audit["remainingReleaseGates"])

    def test_candidate_is_qualification_only(self):
        opt_in = json.loads((
            ROOT / "engines/qualification-opt-in.json"
        ).read_text(encoding="utf-8"))
        selected = next(row for row in opt_in["engines"] if row["id"] == "prosystem")
        self.assertEqual("libemufusion_core_prosystem.so", selected["libraryName"])
        self.assertFalse(opt_in["autoSelect"])


if __name__ == "__main__":
    unittest.main()
