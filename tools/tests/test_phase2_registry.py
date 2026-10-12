import copy
import hashlib
import importlib.util
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "validate_phase2_registry", ROOT / "tools" / "validate_phase2_registry.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class Phase2RegistryTest(unittest.TestCase):
    def setUp(self):
        self.path = ROOT / "engines" / "phase2-registry.json"
        self.data = json.loads(self.path.read_text(encoding="utf-8"))

    def validate_copy(self, data, *, verify_artifacts=False, artifact_root=None):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "phase2-registry.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            return MODULE.validate(
                path,
                verify_artifacts=verify_artifacts,
                artifact_root=artifact_root or ROOT,
            )

    def row(self, data, engine_id):
        return next(row for row in data["engines"] if row["id"] == engine_id)

    def test_checked_in_registry_is_valid(self):
        self.assertEqual([], MODULE.validate(self.path))

    def test_every_section_8_system_is_covered(self):
        covered = {system for row in self.data["engines"] for system in row["systems"]}
        self.assertEqual(MODULE.PHASE_TWO_SYSTEMS, covered)

    def test_duplicate_engine_is_rejected(self):
        data = copy.deepcopy(self.data)
        data["engines"].append(copy.deepcopy(data["engines"][0]))
        self.assertTrue(any("duplicate engine id" in error
                            for error in self.validate_copy(data)))

    def test_phase2_cannot_ship_or_qualify(self):
        data = copy.deepcopy(self.data)
        row = data["engines"][0]
        row["shipped"] = True
        row["state"]["qualified"] = True
        row["renderer"]["qualified"] = True
        row["build"]["reproducible"] = True
        errors = self.validate_copy(data)
        self.assertTrue(any("cannot ship" in error for error in errors))
        self.assertTrue(any("state must remain unqualified" in error for error in errors))
        self.assertTrue(any("renderer must remain unqualified" in error for error in errors))
        self.assertTrue(any("build must remain unqualified" in error for error in errors))

    def test_android_arm64_gate_requires_exact_reproduced_build_proof(self):
        data = copy.deepcopy(self.data)
        row = self.row(data, "virtualjaguar")
        self.assertTrue(row["gates"]["androidArm64"])

        row["build"].pop("proofArtifactSha256")
        errors = self.validate_copy(data)
        self.assertTrue(any("androidArm64 gate disagrees" in error for error in errors))

        data = copy.deepcopy(self.data)
        row = self.row(data, "virtualjaguar")
        row["android"]["integrationEvidence"] = "source-present"
        errors = self.validate_copy(data)
        self.assertTrue(any("androidArm64 gate disagrees" in error for error in errors))

    def test_ppsspp_is_only_first_runnable(self):
        selected = [row["id"] for row in self.data["engines"]
                    if row["selectedFirstRunnable"]]
        self.assertEqual(["ppsspp"], selected)
        data = copy.deepcopy(self.data)
        self.row(data, "play")["selectedFirstRunnable"] = True
        self.assertTrue(any("single first runnable" in error
                            for error in self.validate_copy(data)))

    def test_ppsspp_pin_is_official_v1204_peeled_commit(self):
        row = self.row(self.data, "ppsspp")
        self.assertEqual(MODULE.PPSSPP_COMMIT, row["source"]["commit"])
        self.assertEqual(MODULE.PPSSPP_TAG_OBJECT, row["source"]["tagObject"])
        self.assertEqual(MODULE.PPSSPP_ARCHIVE_SHA, row["source"]["archiveSha256"])

    def test_ppsspp_staged_compile_input_closure_is_exact(self):
        row = self.row(self.data, "ppsspp")
        actual = {item["path"]: item["commit"] for item in row["source"]["submodules"]}
        self.assertEqual(MODULE.PPSSPP_SUBMODULES, actual)
        data = copy.deepcopy(self.data)
        self.row(data, "ppsspp")["source"]["submodules"].pop()
        self.assertTrue(any("compile-input closure" in error
                            for error in self.validate_copy(data)))

    def test_ppsspp_compile_input_repository_and_hash_match_lock(self):
        data = copy.deepcopy(self.data)
        item = self.row(data, "ppsspp")["source"]["submodules"][0]
        item["repository"] = "https://github.com/example/wrong"
        self.assertTrue(any("registry and dependency lock disagree" in error
                            for error in self.validate_copy(data)))
        data = copy.deepcopy(self.data)
        item = self.row(data, "ppsspp")["source"]["submodules"][0]
        item["archiveSha256"] = "0" * 64
        self.assertTrue(any("registry and dependency lock disagree" in error
                            for error in self.validate_copy(data)))

    def test_ppsspp_fixture_is_emufusion_cc0_source_only(self):
        row = self.row(self.data, "ppsspp")
        self.assertEqual(MODULE.PPSSPP_FIXTURE_PATH,
                         row["legalTestContent"]["sourcePath"])
        self.assertEqual("CC0-1.0", row["legalTestContent"]["license"])
        self.assertIsNone(row["legalTestContent"]["artifactSha256"])
        data = copy.deepcopy(self.data)
        self.row(data, "ppsspp")["legalTestContent"]["artifactSha256"] = "0" * 64
        self.assertTrue(any("CC0 source-only" in error
                            for error in self.validate_copy(data)))

    def test_ppsspp_dependency_lock_and_build_proof_are_linked(self):
        row = self.row(self.data, "ppsspp")
        self.assertEqual(MODULE.PPSSPP_DEPENDENCY_LOCK,
                         row["source"]["dependencyLock"])
        self.assertRegex(row["build"]["proofArtifactSha256"], r"^[0-9a-f]{64}$")
        self.assertTrue(row["gates"]["androidArm64"])
        data = copy.deepcopy(self.data)
        self.row(data, "ppsspp")["source"]["dependencyLock"] = "wrong.json"
        self.assertTrue(any("dependency lock path" in error
                            for error in self.validate_copy(data)))

    def test_play_dependency_lock_and_build_proof_are_linked(self):
        row = self.row(self.data, "play")
        self.assertEqual(MODULE.PLAY_COMMIT, row["source"]["commit"])
        self.assertEqual(MODULE.PLAY_ARCHIVE_SHA,
                         row["source"]["archiveSha256"])
        self.assertEqual(MODULE.PLAY_DEPENDENCY_LOCK,
                         row["source"]["dependencyLock"])
        self.assertRegex(row["build"]["proofArtifactSha256"],
                         r"^[0-9a-f]{64}$")
        self.assertTrue(row["gates"]["androidArm64"])
        data = copy.deepcopy(self.data)
        self.row(data, "play")["source"]["submodules"][0]["commit"] = "0" * 40
        self.assertTrue(any("registry and dependency lock disagree" in error
                            for error in self.validate_copy(data)))

    def test_artifact_hashing_is_optional_and_streams_when_requested(self):
        data = copy.deepcopy(self.data)
        # Isolate the synthetic PPSSPP artifact. Virtual Jaguar has its own
        # real proof identity and dedicated Android proof test. Every other
        # reproduced engine keeps its proof identity declared, so copy those
        # artifacts generically instead of maintaining a fragile hand-written
        # list whenever a new compiler gate closes.
        jaguar = self.row(data, "virtualjaguar")
        jaguar["android"]["integrationEvidence"] = "build-published"
        jaguar["gates"]["androidArm64"] = False
        jaguar["build"].pop("proofArtifactPath")
        jaguar["build"].pop("proofArtifactSha256")
        row = self.row(data, "ppsspp")
        row["build"]["proofArtifactPath"] = "artifacts/ppsspp.so"
        payload = b"emufusion-ppsspp-proof\0" * 1000
        row["build"]["proofArtifactSha256"] = hashlib.sha256(payload).hexdigest()
        with TemporaryDirectory() as directory:
            artifact_root = Path(directory)
            artifact = artifact_root / "artifacts" / "ppsspp.so"
            artifact.parent.mkdir(parents=True)
            artifact.write_bytes(payload)
            for proven in data["engines"]:
                if proven["id"] in {"ppsspp", "virtualjaguar"}:
                    continue
                relative = proven.get("build", {}).get("proofArtifactPath")
                if not relative:
                    continue
                source = ROOT / relative
                copied = artifact_root / relative
                copied.parent.mkdir(parents=True, exist_ok=True)
                copied.write_bytes(source.read_bytes())
            self.assertEqual([], MODULE.validate(
                self.path, verify_artifacts=False, artifact_root=artifact_root))
            with TemporaryDirectory() as registry_directory:
                registry = Path(registry_directory) / "phase2-registry.json"
                registry.write_text(json.dumps(data), encoding="utf-8")
                self.assertEqual([], MODULE.validate(
                    registry, verify_artifacts=True, artifact_root=artifact_root))
                artifact.write_bytes(payload + b"drift")
                self.assertTrue(any("SHA-256 mismatch" in error for error in
                                    MODULE.validate(
                                        registry, verify_artifacts=True,
                                        artifact_root=artifact_root)))

    def test_clean_checkout_does_not_require_ignored_artifact(self):
        with TemporaryDirectory() as directory:
            self.assertEqual([], MODULE.validate(
                self.path, verify_artifacts=False, artifact_root=Path(directory)))

    def test_opt_in_artifact_check_rejects_missing_and_escaping_paths(self):
        with TemporaryDirectory() as directory:
            errors = MODULE.validate(
                self.path, verify_artifacts=True, artifact_root=Path(directory))
            self.assertTrue(any("proof artifact is missing" in error for error in errors))
        data = copy.deepcopy(self.data)
        self.row(data, "ppsspp")["build"]["proofArtifactPath"] = "../escape.so"
        self.assertTrue(any("path escapes repository" in error
                            for error in self.validate_copy(data)))

    def test_unavailable_source_cannot_claim_a_pin(self):
        data = copy.deepcopy(self.data)
        row = self.row(data, "yabasanshiro")
        row["source"]["commit"] = "0" * 40
        self.assertTrue(any("unavailable source cannot claim pins" in error
                            for error in self.validate_copy(data)))

    def test_source_gate_requires_both_commit_and_archive_hash(self):
        data = copy.deepcopy(self.data)
        self.row(data, "scummvm")["source"]["archiveSha256"] = None
        self.assertTrue(any("source gate disagrees" in error
                            for error in self.validate_copy(data)))

    def test_firmware_scope_must_be_mapped(self):
        data = copy.deepcopy(self.data)
        self.row(data, "dolphin")["firmware"]["requiredForSystems"] = ["psp"]
        self.assertTrue(any("firmware systems must be mapped" in error
                            for error in self.validate_copy(data)))

    def test_schema_rejects_unknown_properties(self):
        data = copy.deepcopy(self.data)
        self.row(data, "ppsspp")["surprise"] = True
        self.assertTrue(any("Additional properties are not allowed" in error
                            for error in self.validate_copy(data)))

    def test_legal_content_source_path_is_required(self):
        data = copy.deepcopy(self.data)
        del self.row(data, "ppsspp")["legalTestContent"]["sourcePath"]
        errors = self.validate_copy(data)
        self.assertTrue(any("sourcePath" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
