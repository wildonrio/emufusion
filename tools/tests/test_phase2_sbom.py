import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "unified-android" / "tools" / "generate_phase2_sbom.py"
SPEC = importlib.util.spec_from_file_location("generate_phase2_sbom", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class PhaseTwoSbomTest(unittest.TestCase):
    def setUp(self):
        self.registry = json.loads((ROOT / "engines/phase2-registry.json").read_text())
        self.lock = json.loads((ROOT / "engines/ppsspp-source-lock.json").read_text())
        row = next(row for row in self.registry["engines"] if row["id"] == "ppsspp")
        self.artifacts = {"artifacts": [{
            "engineId": "ppsspp",
            "sourceCommit": row["source"]["commit"],
            "fileName": "liblucent_core_ppsspp.so",
            "sha256": row["build"]["proofArtifactSha256"],
        }]}

    def test_sbom_is_deterministic_and_covers_exact_source_closure(self):
        first = MODULE.generate(self.registry, self.lock, self.artifacts)
        second = MODULE.generate(self.registry, self.lock, self.artifacts)
        self.assertEqual(first, second)
        self.assertEqual("SPDX-2.3", first["spdxVersion"])
        self.assertEqual("CC0-1.0", first["dataLicense"])

        packages = {package["name"]: package for package in first["packages"]}
        self.assertIn("PPSSPP source", packages)
        self.assertIn("liblucent_core_ppsspp.so", packages)
        for dependency in self.lock["dependencies"]:
            package = packages[dependency["path"]]
            self.assertEqual(dependency["commit"], package["versionInfo"])
            self.assertEqual(
                dependency["archiveSha256"],
                package["checksums"][0]["checksumValue"],
            )

    def test_sbom_never_invents_dependency_license_conclusions(self):
        sbom = MODULE.generate(self.registry, self.lock, self.artifacts)
        for package in sbom["packages"]:
            self.assertEqual("NOASSERTION", package["licenseConcluded"])

    def test_ps2_page_variant_is_a_separate_binary_from_same_source(self):
        row = next(r for r in self.registry["engines"] if r["id"] == "armsx2")
        artifact = {"engineId": "armsx2", "sourceCommit": row["source"]["commit"],
                    "fileName": "liblucent_core_armsx2.so", "sha256": "a" * 64,
                    "pageSizeVariants": [{"hostPageSize": 16384,
                        "fileName": "liblucent_core_armsx2_16k.so", "sha256": "b" * 64}]}
        lock = json.loads((ROOT / "engines/armsx2-source-lock.json").read_text())
        result = MODULE.generate(self.registry, {"armsx2": lock}, {"artifacts": [artifact]})
        variant = next(p for p in result["packages"] if p["name"] == "liblucent_core_armsx2_16k.so")
        self.assertEqual(variant["checksums"][0]["checksumValue"], "b" * 64)
        self.assertEqual(variant["versionInfo"], row["source"]["commit"])
        self.assertTrue(any(r["relationshipType"] == "GENERATED_FROM" and
                            r["spdxElementId"] == variant["SPDXID"] for r in result["relationships"]))

    def test_git_pinned_azahar_does_not_claim_release_extraction_or_archive_hash(self):
        row = next(r for r in self.registry['engines'] if r['id'] == 'azahar')
        lock = dict(sourceDateEpoch=1782740760, dependencies=[dict(path='externals/test',
            repository='https://github.com/example/test.git', commit='1' * 40, gitTreeSha1='2' * 40)])
        artifact = dict(engineId='azahar', fileName='liblucent_core_azahar.so', sha256='3' * 64,
            sourceCommit=row['source']['commit'])
        result = MODULE.generate(self.registry, {'azahar': lock}, {'artifacts': [artifact]})
        dep = next(p for p in result['packages'] if p['name'] == 'externals/test')
        self.assertEqual(dep['checksums'], [dict(algorithm='SHA1', checksumValue='2' * 40)])
        self.assertEqual(dep['downloadLocation'], 'git+https://github.com/example/test.git@' + '1' * 40)
        self.assertIn('Git tree object', dep['sourceInfo'])
        self.assertTrue(any(r['relationshipType'] == 'GENERATED_FROM' for r in result['relationships']))
        self.assertFalse(any(r['relationshipType'] == 'EXTRACTED_FROM' for r in result['relationships']))

    def test_play_patches_are_first_class_sbom_inputs(self):
        lock = json.loads((ROOT / "engines/play-source-lock.json").read_text())
        row = next(row for row in self.registry["engines"] if row["id"] == "play")
        artifacts = {"artifacts": [{
            "engineId": "play",
            "sourceCommit": row["source"]["commit"],
            "fileName": "liblucent_core_play.so",
            "sha256": row["build"]["proofArtifactSha256"],
        }]}
        sbom = MODULE.generate(self.registry, {"play": lock}, artifacts)
        packages = {package["name"]: package for package in sbom["packages"]}
        relationships = sbom["relationships"]
        for patch in lock["patches"]:
            package = packages[patch["path"]]
            self.assertEqual(patch["sha256"],
                             package["checksums"][0]["checksumValue"])
            self.assertTrue(any(
                relation["spdxElementId"] == package["SPDXID"] and
                relation["relationshipType"] == "PATCH_FOR"
                for relation in relationships
            ))


if __name__ == "__main__":
    unittest.main()
