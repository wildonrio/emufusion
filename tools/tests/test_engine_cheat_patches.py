import hashlib
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PATCHES_DIR = ROOT / "engines" / "patches"
SOURCES_DIR = ROOT / "engines" / "build" / "sources"
BUILD_CORE_SH = ROOT / "engines" / "build_core.sh"

# Matches one `apply_locked_patch "$var" \` call's patch path + sha256
# arguments in build_core.sh, e.g.:
#   apply_locked_patch "$staged_source" \
#       engines/patches/foo.patch \
#       0123...abcd
_APPLY_LOCKED_PATCH_CALL_RE = re.compile(
    r"apply_locked_patch\s+\S+\s*\\\s*\n\s*(engines/patches/\S+\.patch)\s*\\\s*\n\s*([0-9a-f]{64})",
)

# One row per new patch this task adds: the locked-patch registry that
# records it, the patch file itself, and the exact vendored source commit
# directory it must apply to cleanly.
ENGINE_PATCHES = [
    {
        "engine": "sameboy",
        "lock": ROOT / "engines" / "sameboy-source-lock.json",
        "patch": PATCHES_DIR / "sameboy-libretro-cheat-support.patch",
        "commit": "213a12ce93d66b105a113debd9396306066a7cfc",
    },
    {
        "engine": "flycast",
        "lock": ROOT / "engines" / "flycast-source-lock.json",
        "patch": PATCHES_DIR / "flycast-libretro-cheat-support.patch",
        "commit": "d4fc0774107c4c307346b469499b9303a6ca0ffa",
    },
]


def _find_patch_lock_entry(lock, patch_path):
    """The lock's "patches" row whose path matches patch_path, or None."""
    relative = patch_path.relative_to(ROOT).as_posix()
    for row in lock.get("patches", []):
        if row.get("path") == relative:
            return row
    return None


class EngineCheatPatchRegistrationTest(unittest.TestCase):
    """Catches patch bit-rot: every new cheat-support patch must exist,
    be registered in its engine's locked-patch registry with a sha256 that
    matches the file on disk, name the exact vendored commit it targets, and
    still apply cleanly (git apply --check) to the vendored source already
    present on this machine.
    """

    def test_patch_files_exist(self):
        for row in ENGINE_PATCHES:
            with self.subTest(engine=row["engine"]):
                self.assertTrue(
                    row["patch"].is_file(),
                    f"missing patch file: {row['patch']}",
                )

    def test_registered_in_locked_patch_registry_with_matching_sha256(self):
        for row in ENGINE_PATCHES:
            with self.subTest(engine=row["engine"]):
                self.assertTrue(row["lock"].is_file(),
                                 f"missing source lock: {row['lock']}")
                lock = json.loads(row["lock"].read_text(encoding="utf-8"))
                self.assertEqual(
                    row["commit"], lock["core"]["commit"],
                    "source lock's pinned commit does not match the "
                    "vendored source directory this test targets",
                )
                entry = _find_patch_lock_entry(lock, row["patch"])
                self.assertIsNotNone(
                    entry,
                    f"{row['patch'].name} is not registered in "
                    f"{row['lock'].name}'s \"patches\" array",
                )
                actual_sha256 = hashlib.sha256(
                    row["patch"].read_bytes()).hexdigest()
                self.assertEqual(
                    entry["sha256"], actual_sha256,
                    "registered sha256 does not match the patch file on "
                    "disk -- the patch changed without updating its lock",
                )

    def test_build_core_sh_embedded_sha256_matches_patch_on_disk(self):
        """build_core.sh hardcodes its own copy of each patch's sha256 in
        the apply_locked_patch() call (independent of the per-engine
        *-source-lock.json registry checked above). A patch edited without
        updating that call makes apply_locked_patch() hard-fail the real
        build with 'Patch checksum mismatch', even though the lock-registry
        check above still passes -- this catches that drift directly.
        """
        self.assertTrue(BUILD_CORE_SH.is_file(),
                         f"missing build script: {BUILD_CORE_SH}")
        build_core_text = BUILD_CORE_SH.read_text(encoding="utf-8")
        embedded_shas = {
            path: sha
            for path, sha in _APPLY_LOCKED_PATCH_CALL_RE.findall(build_core_text)
        }
        for row in ENGINE_PATCHES:
            with self.subTest(engine=row["engine"]):
                relative = row["patch"].relative_to(ROOT).as_posix()
                self.assertIn(
                    relative, embedded_shas,
                    f"no apply_locked_patch(...) call for {relative} found "
                    f"in {BUILD_CORE_SH.name}",
                )
                actual_sha256 = hashlib.sha256(
                    row["patch"].read_bytes()).hexdigest()
                self.assertEqual(
                    embedded_shas[relative], actual_sha256,
                    f"{BUILD_CORE_SH.name}'s apply_locked_patch(...) call "
                    f"for {relative} has a stale sha256 -- the patch "
                    f"changed without updating that call, so the real "
                    f"build will hard-fail with a checksum mismatch",
                )

    def test_patch_applies_cleanly_to_the_vendored_source_on_this_machine(self):
        for row in ENGINE_PATCHES:
            with self.subTest(engine=row["engine"]):
                source_dir = SOURCES_DIR / f"{row['engine']}-{row['commit']}"
                if not source_dir.is_dir():
                    self.skipTest(
                        f"vendored source not present on this machine: "
                        f"{source_dir}")
                if shutil.which("git") is None:
                    self.skipTest("git is not available on this machine")
                # --directory is prefixed onto the patch's own paths and
                # must be given relative to cwd; an absolute path here makes
                # git concatenate it onto the repo root and fail to find the
                # file, so pass it relative to ROOT (our cwd below).
                relative_source_dir = source_dir.relative_to(ROOT)
                result = subprocess.run(
                    ["git", "apply", "--check", "-p1",
                     "--directory", str(relative_source_dir),
                     str(row["patch"].relative_to(ROOT))],
                    cwd=ROOT, capture_output=True, text=True,
                )
                self.assertEqual(
                    0, result.returncode,
                    f"{row['patch'].name} no longer applies cleanly to "
                    f"{source_dir}:\n{result.stderr}",
                )


if __name__ == "__main__":
    unittest.main()
