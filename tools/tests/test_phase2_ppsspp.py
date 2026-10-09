import hashlib
import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RECIPE = ROOT / "engines" / "build_core.sh"
FIXTURE = ROOT / "engines" / "qa" / "fixtures" / "ppsspp-minimal"
LOCK = ROOT / "engines" / "ppsspp-source-lock.json"
AUDIT = ROOT / "engines" / "ppsspp-dependency-audit.json"
ARTIFACT = ROOT / "engines" / "build" / "arm64-v8a" / "ppsspp_libretro.so"
SESSION = ROOT / "unified-android" / "src" / "com" / "thorium" / \
    "preview" / "game" / "PpssppGlesEngineSession.java"


class PhaseTwoPpssppTest(unittest.TestCase):
    def setUp(self):
        self.recipe = RECIPE.read_text(encoding="utf-8")

    def test_recipe_pins_official_release_commit_and_archive(self):
        self.assertIn("ppsspp)", self.recipe)
        self.assertIn(
            "commit=fa50bb1976065c4f8b1b47af227d367fe9771555",
            self.recipe,
        )
        self.assertIn(
            "9054138072d49c306d65c17059bd85662b4ff46abe1ea6bb53d854dc80592ea6",
            self.recipe,
        )
        self.assertIn("https://github.com/hrydgard/ppsspp", self.recipe)
        self.assertIn("source=$(fetch_source_fresh ppsspp", self.recipe)
        self.assertIn("source_date_epoch=1778934711", self.recipe)

    def test_recipe_stages_required_nested_header_closure(self):
        for path in (
            "ext/armips/ext/filesystem",
            "ext/libadrenotools/lib/linkernsbypass",
            "ext/OpenXR-SDK",
            "ext/miniupnp",
            "libretro/libretro-common",
        ):
            self.assertIn(path, self.recipe)

    def test_production_recipe_requires_pinned_ffmpeg_and_atomic_publication(self):
        for flag in ("-DLIBRETRO=ON", "-DOPENXR=OFF", "-DUSE_MINIUPNPC=OFF"):
            self.assertIn(flag, self.recipe)
        ppsspp_case = self.recipe.split("    ppsspp)", 1)[1].split("    mame)", 1)[0]
        self.assertNotIn("ppsspp_use_ffmpeg=OFF", ppsspp_case)
        self.assertNotIn("LUCENT_PPSSPP_FFMPEG_CANDIDATE", ppsspp_case)
        for token in (
            "ppsspp_use_ffmpeg=ON",
            '-DUSE_FFMPEG="$ppsspp_use_ffmpeg"',
            "fetch_ppsspp_ffmpeg_fresh",
            "1e3b4965632f60b1d85360261d1b9dd45444bc71",
            "93b942daa799dedf4f7a1a3f143c081c1945f2a67b7d13717f9fbb5c0ef4dd51",
            "--remove-section=.note.gnu.build-id",
            "376659948724e422876d31d61cc5dd130bfe5a2e941d64c6bf4225c2f2a23c6d",
            "PPSSPP DT_NEEDED closure changed",
            "PPSSPP core is missing required export",
            'defined_symbols_file="$ppsspp_candidate_dir/ppsspp-defined-symbols.txt"',
            'grep -qx "$required_symbol" "$defined_symbols_file"',
            '--lock "$ROOT/engines/ppsspp-source-lock.json"',
            'mv "$normalized_core" "$OUTPUT_DIR/ppsspp_libretro.so"',
        ):
            self.assertIn(token, ppsspp_case)
        self.assertLess(
            ppsspp_case.index("generate_ppsspp_compliance_bundle.py"),
            ppsspp_case.index('mv "$normalized_core" "$OUTPUT_DIR/ppsspp_libretro.so"'),
        )

    def test_recipe_locks_toolchain_patch_paths_and_concurrency(self):
        ppsspp_case = self.recipe.split("    ppsspp)", 1)[1].split("    mame)", 1)[0]
        for token in (
            'ppsspp_ndk_dir="$SDK_DIR/ndk/27.0.12077973"',
            'ppsspp_cmake="$SDK_DIR/cmake/3.31.6/bin/cmake"',
            "expected_ppsspp_ndk_sha=1c4a54b31c5ed242a901b4a472d412819b5e08405df1c58066bd555f9dd52515",
            "expected_ppsspp_cmake_sha=94d4a3ce9e70cd9dae26e5fc7bb6ff4de67c58759762d4118a96ad2bc1b76be8",
            "expected_ppsspp_ninja_sha=3d508e91d5c159986bea2a472b1bfa849909da133aa05582a7174d33328af933",
            "Pinned PPSSPP patch checksum mismatch",
            'ppsspp_lock_dir="$BUILD_ROOT/locks/ppsspp"',
            "-ffile-prefix-map=",
            "-fdebug-prefix-map=",
            "-fmacro-prefix-map=",
        ):
            self.assertIn(token, ppsspp_case)
        self.assertNotIn('"$CMAKE" -S', ppsspp_case)
        self.assertNotIn('"$NDK_DIR/build/cmake/android.toolchain.cmake"', ppsspp_case)

    def test_wrong_api_fails_before_source_mutation(self):
        result = subprocess.run(
            [str(RECIPE), "ppsspp"],
            cwd=ROOT,
            env={
                "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                "LUCENT_NATIVE_API": "24",
                "ANDROID_SDK_ROOT": "/Users/tyleryoung/Code/cemu/Cemu-0.5/android-sdk",
                "CMAKE": "/bin/false",
                "ANDROID_NDK_ROOT": "/definitely/not/the/pinned/ndk",
            },
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("requires ABI arm64-v8a and API 23", result.stderr)

    def test_no_retroarch_frontend_or_unlicensed_upstream_fixture(self):
        ppsspp_case = self.recipe.split("    ppsspp)", 1)[1].split("    mame)", 1)[0]
        self.assertNotIn("github.com/libretro/RetroArch", ppsspp_case)
        self.assertNotIn("com.retroarch", ppsspp_case)
        self.assertNotIn("pspautotests", ppsspp_case)

    def test_legal_fixture_is_source_only(self):
        self.assertTrue((FIXTURE / "main.c").is_file())
        self.assertTrue((FIXTURE / "LICENSE").is_file())
        self.assertIn("CC0-1.0", (FIXTURE / "LICENSE").read_text(encoding="utf-8"))
        forbidden = {".pbp", ".elf", ".iso", ".cso", ".prx"}
        self.assertFalse(
            [path for path in FIXTURE.rglob("*") if path.suffix.lower() in forbidden]
        )

    def test_source_lock_is_complete_and_matches_recipe(self):
        lock = json.loads(LOCK.read_text(encoding="utf-8"))
        self.assertEqual(
            "fa50bb1976065c4f8b1b47af227d367fe9771555",
            lock["core"]["commit"],
        )
        self.assertEqual(1778934711, lock["sourceDateEpoch"])
        self.assertEqual(
            "exact-staged-compile-inputs-for-this-build-profile",
            lock["closureScope"],
        )
        self.assertEqual("27.0.12077973", lock["toolchain"]["ndkVersion"])
        self.assertEqual("3.31.6-g38307f9", lock["toolchain"]["cmakeVersion"])
        self.assertEqual("android-arm64-libretro-ffmpeg", lock["buildProfile"])
        proof = lock["productionProfileReproducibilityProof"]
        self.assertEqual(2, proof["freshBuildCount"])
        self.assertTrue(proof["byteIdentical"])
        self.assertEqual(
            "376659948724e422876d31d61cc5dd130bfe5a2e941d64c6bf4225c2f2a23c6d",
            proof["artifactSha256"],
        )
        self.assertIsNone(proof["gnuBuildId"])
        self.assertIn(".note.gnu.build-id", proof["normalization"])
        self.assertEqual(0, proof["absoluteBuilderPathMatches"])
        paths = {row["path"] for row in lock["dependencies"]}
        self.assertIn("ext/OpenXR-SDK", paths)
        self.assertIn("ext/miniupnp", paths)
        self.assertIn("ext/armips/ext/filesystem", paths)
        self.assertIn("ext/libadrenotools/lib/linkernsbypass", paths)
        ffmpeg = lock["ffmpeg"]
        self.assertEqual(
            "1e3b4965632f60b1d85360261d1b9dd45444bc71",
            ffmpeg["commit"],
        )
        self.assertEqual(3381, ffmpeg["sparseFileCount"])
        self.assertEqual(
            "93b942daa799dedf4f7a1a3f143c081c1945f2a67b7d13717f9fbb5c0ef4dd51",
            ffmpeg["sparseClosureSha256"],
        )
        self.assertFalse(ffmpeg["embeddedConfiguration"]["gplEnabled"])
        self.assertFalse(ffmpeg["embeddedConfiguration"]["nonfreeEnabled"])
        self.assertFalse(ffmpeg["embeddedConfiguration"]["version3Enabled"])
        self.assertEqual(5, len(ffmpeg["androidArm64Archives"]))
        self.assertEqual("LGPL-2.1-or-later AND IJG", ffmpeg["licenseConcluded"])
        for archive in ffmpeg["androidArm64Archives"]:
            self.assertIn(Path(archive["path"]).name, self.recipe)
            self.assertIn(archive["sha256"], self.recipe)
        for tool_key in (
            "llvmStripExecutableSha256",
            "llvmObjcopyExecutableSha256",
            "llvmReadelfExecutableSha256",
            "llvmNmExecutableSha256",
        ):
            self.assertIn(lock["toolchain"][tool_key], self.recipe)
        self.assertNotIn("ffmpeg", {row["path"] for row in lock["excluded"]})
        patch = ROOT / lock["recipePatch"]["path"]
        self.assertTrue(patch.is_file())
        self.assertIn("v1.20.4-fa50bb1", patch.read_text(encoding="utf-8"))
        self.assertEqual(
            lock["recipePatch"]["sha256"],
            hashlib.sha256(patch.read_bytes()).hexdigest(),
        )
        for row in [lock["core"], *lock["dependencies"]]:
            self.assertRegex(row["commit"], r"^[0-9a-f]{40}$")
            self.assertRegex(row["archiveSha256"], r"^[0-9a-f]{64}$")
            self.assertIn(row["commit"], self.recipe)
            self.assertIn(row["archiveSha256"], self.recipe)

    def test_dependency_audit_and_staged_artifact_use_normalized_identity(self):
        expected = "376659948724e422876d31d61cc5dd130bfe5a2e941d64c6bf4225c2f2a23c6d"
        audit = json.loads(AUDIT.read_text(encoding="utf-8"))
        self.assertEqual(expected, audit["artifactSha256"])
        if ARTIFACT.is_file():
            self.assertEqual(expected, hashlib.sha256(ARTIFACT.read_bytes()).hexdigest())

    def test_state_readiness_is_only_probed_for_a_pending_restore(self):
        session = SESSION.read_text(encoding="utf-8")
        self.assertIn(
            "if (pendingQuickResume != null &&\n"
            "                                            active.stateReady())",
            session,
        )
        self.assertNotIn(
            "if (active.stateReady()) restoreQuickResume(active);",
            session,
        )


if __name__ == "__main__":
    unittest.main()
