import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "unified-android" / "tools" / "generate_engine_artifact_manifest.py"
SPEC = importlib.util.spec_from_file_location("artifact_manifest", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class EngineArtifactManifestTest(unittest.TestCase):
    def test_only_registered_core_artifacts_are_hashed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            libraries = root / "lib"
            libraries.mkdir()
            (libraries / "libemufusion_core_test_core.so").write_bytes(b"qualified")
            (libraries / "libunrelated.so").write_bytes(b"ignored")
            registry = root / "registry.json"
            registry.write_text(json.dumps({"engines": [{
                "id": "test-core",
                "source": {"commit": "a" * 40},
            }]}), encoding="utf-8")
            result = MODULE.generate(registry, libraries)
            self.assertEqual(1, len(result["artifacts"]))
            self.assertEqual("test-core", result["artifacts"][0]["engineId"])
            self.assertEqual("a" * 40, result["artifacts"][0]["sourceCommit"])
            self.assertEqual(64, len(result["artifacts"][0]["sha256"]))

    def run_tool(self, root: Path, expected_count: int) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(MODULE_PATH),
             "--registry", str(root / "registry.json"),
             "--library-dir", str(root / "lib"),
             "--expected-count", str(expected_count),
             "--output", str(root / "manifest.json")],
            capture_output=True, text=True,
        )

    def write_fixture(self, root: Path, core_count: int) -> None:
        libraries = root / "lib"
        libraries.mkdir()
        engines = []
        for index in range(core_count):
            engines.append({"id": f"core-{index}",
                            "source": {"commit": "a" * 40}})
            (libraries / f"libemufusion_core_core_{index}.so").write_bytes(b"x")
        (root / "registry.json").write_text(
            json.dumps({"engines": engines}), encoding="utf-8")

    def test_expected_count_mismatch_fails_without_writing_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_fixture(root, core_count=0)
            completed = self.run_tool(root, expected_count=16)
            self.assertEqual(1, completed.returncode)
            self.assertIn("expected exactly 16", completed.stderr)
            self.assertIn("found 0", completed.stderr)
            self.assertFalse((root / "manifest.json").exists())

    def test_expected_count_zero_rejects_stray_registered_core(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_fixture(root, core_count=1)
            completed = self.run_tool(root, expected_count=0)
            self.assertEqual(1, completed.returncode)
            self.assertIn("found 1", completed.stderr)
            self.assertFalse((root / "manifest.json").exists())

    def test_expected_count_match_writes_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_fixture(root, core_count=2)
            completed = self.run_tool(root, expected_count=2)
            self.assertEqual(0, completed.returncode, completed.stderr)
            manifest = json.loads(
                (root / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(2, len(manifest["artifacts"]))

    def test_build_script_pins_expected_counts_to_staged_core_lists(self):
        build = (ROOT / "unified-android" / "build.sh").read_text(
            encoding="utf-8")
        self.assertIn("PHASE1_STAGED_CORE_COUNT=0", build)
        self.assertIn("PHASE2_STAGED_CORE_COUNT=0", build)
        self.assertIn(
            "PHASE1_STAGED_CORE_COUNT=$((PHASE1_STAGED_CORE_COUNT + 1))", build)
        self.assertIn(
            "PHASE2_STAGED_CORE_COUNT=$((PHASE2_STAGED_CORE_COUNT + 1))", build)
        self.assertIn('--expected-count "$PHASE1_STAGED_CORE_COUNT"', build)
        self.assertIn('--expected-count "$PHASE2_STAGED_CORE_COUNT"', build)
        # Every manifest generation is count-gated; none may run unchecked.
        self.assertEqual(
            build.count("generate_engine_artifact_manifest.py"),
            build.count("--expected-count"),
        )


if __name__ == "__main__":
    unittest.main()
