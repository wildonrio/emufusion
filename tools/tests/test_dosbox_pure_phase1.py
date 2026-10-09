import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class DosboxPurePhase1Test(unittest.TestCase):
    def setUp(self):
        registry = json.loads((ROOT / "engines/registry.json").read_text(encoding="utf-8"))
        self.row = next(row for row in registry["engines"] if row["id"] == "dosbox-pure")
        self.audit = json.loads((
            ROOT / "engines/audits/dosbox-pure-license.json"
        ).read_text(encoding="utf-8"))

    def test_candidate_is_pinned_compatible_and_fail_closed(self):
        self.assertEqual("1A", self.row["tier"])
        self.assertEqual("experimental", self.row["status"])
        self.assertEqual("GPL-2.0-or-later", self.row["license"]["spdx"])
        self.assertEqual("compatible-candidate", self.row["license"]["distributionGate"])
        self.assertEqual(
            "b413767bf4d61e03c9a779cb0001bcc1bb68c78afbb058fd68d947a9f065f300",
            self.row["source"]["archiveSha256"],
        )
        self.assertFalse(self.row["state"]["qualified"])
        self.assertTrue(self.row["build"]["reproducible"])
        self.assertFalse(self.row["shipped"])
        self.assertFalse(self.row["firmware"]["required"])

    def test_one_internal_core_owns_dos_and_windows_pc(self):
        self.assertEqual(["dos", "windows"], self.row["systems"])
        self.assertIn("Windows 3.x/9x", self.row["statusReason"])
        self.assertIn("user-supplied", self.row["firmware"]["notes"])

    def test_configuration_audit_covers_known_embedded_components(self):
        self.assertEqual(self.row["source"]["commit"], self.audit["sourceCommit"])
        self.assertEqual(
            self.row["source"]["archiveSha256"], self.audit["sourceArchiveSha256"]
        )
        licenses = {entry["license"] for entry in self.audit["components"]}
        for expected in (
            "GPL-2.0-or-later", "MIT", "BSD-3-Clause", "LGPL-2.1-or-later",
            "GPL-3.0-or-later", "MIT AND CC0-1.0",
        ):
            self.assertIn(expected, licenses)
        self.assertIn("no guest OS", self.audit["scope"])
        self.assertTrue(self.audit["remainingReleaseGates"])

    def test_recipe_is_pinned_and_qualification_only(self):
        recipe = (ROOT / "engines/build_core.sh").read_text(encoding="utf-8")
        for value in (
            "dosbox-pure)",
            "7f6e8fb7385fa446d1444d671063268520bf9b54",
            "b413767bf4d61e03c9a779cb0001bcc1bb68c78afbb058fd68d947a9f065f300",
            "dosbox-pure-LICENSE.txt",
        ):
            self.assertIn(value, recipe)
        opt_in = json.loads((
            ROOT / "engines/qualification-opt-in.json"
        ).read_text(encoding="utf-8"))
        selected = next(row for row in opt_in["engines"] if row["id"] == "dosbox-pure")
        self.assertEqual("liblucent_core_dosbox_pure.so", selected["libraryName"])
        self.assertTrue(opt_in["qualificationOnly"])
        self.assertFalse(opt_in["autoSelect"])

    def test_reproducibility_proof_is_locked(self):
        lock = json.loads((
            ROOT / "engines/reproducibility-lock.json"
        ).read_text(encoding="utf-8"))
        proof = next(row for row in lock["engines"] if row["id"] == "dosbox-pure")
        self.assertEqual(2, proof["independentBuilds"])
        self.assertTrue(proof["byteIdentical"])
        self.assertEqual(
            "76bf9d996af849966074673bbdb759a14143ce495a8d75d8539d69764d1ce190",
            proof["artifactSha256"],
        )
        recipe = (ROOT / "engines/build_core.sh").read_text(encoding="utf-8")
        self.assertIn('LDFLAGS="-Wl,--build-id=none"', recipe)


if __name__ == "__main__":
    unittest.main()
