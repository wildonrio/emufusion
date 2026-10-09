import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "phase1_repro",
    ROOT / "tools" / "verify_phase1_reproducibility.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class Phase1ReproducibilityTest(unittest.TestCase):
    def test_checked_in_lock_and_artifacts_verify(self):
        # Uncommitted, build-Mac-only input (see tools/run_ci_tests.py).
        if not list((ROOT / "engines/build/arm64-v8a").glob("*_libretro.so")):
            self.skipTest("local-only input absent: engines/build/arm64-v8a/*_libretro.so")
        self.assertEqual([], MODULE.verify(
            ROOT / "engines/registry.json",
            ROOT / "engines/reproducibility-lock.json",
            ROOT / "engines/build/arm64-v8a",
            ROOT,
        ))

    def test_tampered_artifact_fails(self):
        # Uncommitted, build-Mac-only input (see tools/run_ci_tests.py).
        if not list((ROOT / "engines/build/arm64-v8a").glob("*_libretro.so")):
            self.skipTest("local-only input absent: engines/build/arm64-v8a/*_libretro.so")
        lock = json.loads((ROOT / "engines/reproducibility-lock.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for row in lock["engines"]:
                source = ROOT / "engines/build/arm64-v8a" / f"{row['id']}_libretro.so"
                (directory / source.name).write_bytes(source.read_bytes())
            (directory / "swanstation_libretro.so").write_bytes(b"tampered")
            errors = MODULE.verify(
                ROOT / "engines/registry.json",
                ROOT / "engines/reproducibility-lock.json",
                directory,
                ROOT,
            )
        self.assertTrue(any("artifact differs" in error for error in errors))

    def test_engine_recipe_and_patch_hashes_are_current(self):
        lock = json.loads((ROOT / "engines/reproducibility-lock.json").read_text(encoding="utf-8"))
        recipe = ROOT / lock["recipe"]["path"]
        for row in lock["engines"]:
            self.assertEqual(
                row["recipeSha256"], MODULE.recipe_sha256(recipe, row["id"])
            )
            for relative, digest in row["patches"].items():
                self.assertEqual(
                    digest, hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
                )


if __name__ == "__main__":
    unittest.main()
