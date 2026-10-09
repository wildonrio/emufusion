import hashlib
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = ROOT / "engines" / "phase2-registry.json"
LOCK_PATH = ROOT / "engines" / "armsx2-source-lock.json"
PATCH_PATH = ROOT / "engines" / "patches" / "armsx2-libretro-android-build.patch"
BUILD_PATH = ROOT / "engines" / "build_core.sh"
SESSION_PATH = (ROOT / "unified-android" / "src" / "com" / "thorium" /
                "preview" / "game" / "PpssppGlesEngineSession.java")
VALIDATOR_PATH = ROOT / "tools" / "validate_phase2_registry.py"
SPEC = importlib.util.spec_from_file_location("validate_phase2_registry", VALIDATOR_PATH)
VALIDATOR = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(VALIDATOR)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PhaseTwoArmsx2Test(unittest.TestCase):
    def setUp(self):
        self.registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        self.row = next(row for row in self.registry["engines"]
                        if row["id"] == "armsx2")
        self.lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
        self.recipe = BUILD_PATH.read_text(encoding="utf-8")

    def test_source_lock_is_exact_and_validator_bound(self):
        self.assertEqual(VALIDATOR.ARMSX2_COMMIT, self.lock["core"]["commit"])
        self.assertEqual(VALIDATOR.ARMSX2_ARCHIVE_SHA,
                         self.lock["core"]["archiveSha256"])
        self.assertEqual(VALIDATOR.ARMSX2_DEPENDENCY_LOCK_SHA, sha256(LOCK_PATH))
        self.assertEqual(7, len(self.lock["dependencies"]))
        self.assertEqual(7, len({item["path"] for item in self.lock["dependencies"]}))

    def test_patch_identity_is_locked_and_matches_recipe(self):
        self.assertEqual([{
            "path": VALIDATOR.ARMSX2_PATCH,
            "sha256": VALIDATOR.ARMSX2_PATCH_SHA,
        }, {
            "path": VALIDATOR.ARMSX2_CLOCK_PATCH,
            "sha256": VALIDATOR.ARMSX2_CLOCK_PATCH_SHA,
        }, {
            "path": VALIDATOR.ARMSX2_DESCRIPTOR_PATCH,
            "sha256": VALIDATOR.ARMSX2_DESCRIPTOR_PATCH_SHA,
        }, {
            "path": VALIDATOR.ARMSX2_INPUT_ATTACHMENT_PATCH,
            "sha256": VALIDATOR.ARMSX2_INPUT_ATTACHMENT_PATCH_SHA,
        }], self.lock["patches"])
        self.assertEqual(VALIDATOR.ARMSX2_PATCH_SHA, sha256(PATCH_PATH))
        self.assertIn(VALIDATOR.ARMSX2_PATCH_SHA, self.recipe)
        self.assertEqual(VALIDATOR.ARMSX2_CLOCK_PATCH_SHA,
                         sha256(ROOT / VALIDATOR.ARMSX2_CLOCK_PATCH))
        self.assertIn(VALIDATOR.ARMSX2_CLOCK_PATCH_SHA, self.recipe)
        for patch in self.lock['patches']:
            self.assertEqual(patch['sha256'], sha256(ROOT / patch['path']))
            self.assertIn(patch['sha256'], self.recipe)

    def test_registry_core_lock_recipe_and_proof_are_bound(self):
        source = self.row["source"]
        self.assertEqual(VALIDATOR.ARMSX2_DEPENDENCY_LOCK,
                         source["dependencyLock"])
        self.assertEqual(self.lock["core"]["repository"], source["repository"])
        self.assertEqual(self.lock["core"]["commit"], source["commit"])
        self.assertEqual(self.lock["core"]["archiveSha256"],
                         source["archiveSha256"])
        self.assertEqual("engines/build_core.sh armsx2",
                         self.row["build"]["recipe"])
        self.assertRegex(self.row["build"]["proofArtifactSha256"],
                         r"^[0-9a-f]{64}$")

    def test_recipe_enforces_host_abi_toolchain_and_deterministic_environment(self):
        case = self.recipe.split("    armsx2)", 1)[1].split("\n    play)", 1)[0]
        self.assertIn('"$ABI" != arm64-v8a', case)
        self.assertIn('"$(uname -s)" != Darwin', case)
        for field in ("ndkSourcePropertiesSha256", "cmakeExecutableSha256",
                      "ninjaExecutableSha256"):
            value = self.lock["toolchain"][field]
            self.assertIn(value, case)
        self.assertGreaterEqual(case.count(
            'LC_ALL=C TZ=UTC SOURCE_DATE_EPOCH="$source_date_epoch"'), 2)
        self.assertIn("-DANDROID_PLATFORM=android-26", case)
        self.assertIn("armsx2_link_flags='-Wl,--build-id=none'", case)
        self.assertIn('-DCMAKE_SHARED_LINKER_FLAGS="$armsx2_link_flags"', case)
        self.assertIn('-DARMSX2_ANDROID_HOST_PAGE_SIZE="$armsx2_host_page_size"', case)
        self.assertIn('armsx2_variant_suffix=_16k', case)
        self.assertIn('common-page-size=16384', case)

    def test_vulkan_presentation_owns_every_published_window_pixel(self):
        backend = (ROOT / "unified-android" / "native" /
                   "lucent_android_vulkan_backend.c").read_text(encoding="utf-8")
        record = backend.split(
            "static bool record_present_commands_for_target", 1)[1].split(
                "\nstatic bool record_present_commands(", 1)[0]
        # An aspect-preserving blit covers only the letterboxed destination
        # rectangle of a recycled swapchain image.  Every frame must clear the
        # complete image to opaque black first, or the pillarbox rows keep the
        # never-written (transparent) initial content and stale bands from an
        # earlier, wider core output size.
        self.assertEqual(1, record.count("vkCmdClearColorImage"))
        self.assertIn("opaque_black.float32[3] = 1.0f;", record)
        self.assertLess(record.index("vkCmdClearColorImage"),
                        record.index("vkCmdBlitImage"))

    def test_gameplay_layer_publishes_opaque_alpha_for_hardware_cores(self):
        surface = (ROOT / "unified-android" / "src" / "com" / "thorium" /
                   "preview" / "game" / "GameSurface.java").read_text(
                           encoding="utf-8")
        # vkCmdBlitImage copies the core's alpha channel, and the PS2 GS marks
        # a fully opaque pixel 0x80.  An opaque TextureView is composited with
        # SkBlendMode.SRC, which would publish that alpha as the gameplay
        # window's coverage and blend the EmuFusion library through the game.
        self.assertIn("setOpaque(false)", surface)
        self.assertNotIn("setOpaque(true)", surface)
        # Compositing over black is what makes the published alpha one, so both
        # gameplay hosts must keep an opaque backdrop under the video surface.
        for host in ("InWindowGameHost.java", "LucentGameActivity.java"):
            source = (ROOT / "unified-android" / "src" / "com" / "thorium" /
                      "preview" / "game" / host).read_text(encoding="utf-8")
            backdrop = source.index("setBackgroundColor(Color.BLACK)")
            surface_markers = [marker for marker in
                               ("new GameSurface(", "new GameSurfaceView(")
                               if marker in source]
            self.assertTrue(surface_markers)
            self.assertLess(backdrop,
                            min(source.index(marker) for marker in surface_markers))

    def test_runtime_state_restore_is_quarantined_without_deleting_memory_cards(self):
        session = SESSION_PATH.read_text(encoding="utf-8")
        policy = (ROOT / "unified-android" / "src" / "com" / "thorium" /
                  "lucent" / "state" / "QuickResumePolicy.java").read_text(
                          encoding="utf-8")
        self.assertIn('!"armsx2".equals(engineId)', policy)
        self.assertNotIn('!"dolphin".equals(engineId)', policy)
        load = session.split(
            "vault = StateVault.shared", 1)[1].split(
                "checkpointScheduler =", 1)[0]
        self.assertLess(load.index("QuickResumePolicy.allowsRuntimeRestore(entry.id)"),
                        load.index("vault.loadQuickResume(identity)"))
        self.assertIn("marker=state-restore-quarantined", load)

        save = session.split(
            "private Throwable saveQuickResume", 1)[1].split(
                "private void persistSaveRam", 1)[0]
        self.assertLess(save.index("persistSaveRam(active);"),
                        save.index("!QuickResumePolicy.allowsRuntimeRestore(entry.id)"))
        self.assertLess(save.index("!QuickResumePolicy.allowsRuntimeRestore(entry.id)"),
                        save.index("byte[] state = active.serialize();"))
        self.assertIn("marker=state-restore-quarantined", save)

        automatic = session.split(
            "private void saveAutomatic()", 1)[1].split(
                "private List<StateSnapshot> restorableHistory", 1)[0]
        self.assertLess(automatic.index("persistSaveRam(active);"),
                        automatic.index("!QuickResumePolicy.allowsRuntimeRestore(entry.id)"))
        self.assertLess(automatic.index("!QuickResumePolicy.allowsRuntimeRestore(entry.id)"),
                        automatic.index("active.serialize()"))

        restore = session.split(
            "private void restoreQuickResume", 1)[1].split(
                "private Throwable saveQuickResume", 1)[0]
        self.assertNotIn('"armsx2".equals(entry.id)', restore)

        history = session.split(
            "private List<StateSnapshot> restorableHistory", 1)[1].split(
                "private void notifyRestoreAvailability", 1)[0]
        self.assertIn("!QuickResumePolicy.allowsRuntimeRestore(entry.id)", history)

        manual = session.split(
            "private void restore(StateSnapshot snapshot)", 1)[1].split(
                "private synchronized void refreshDevices", 1)[0]
        self.assertIn("!QuickResumePolicy.allowsRuntimeRestore(entry.id)", manual)
        self.assertLess(manual.index("!QuickResumePolicy.allowsRuntimeRestore(entry.id)"),
                        manual.index("applyRuntimeState(active, loaded.state);"))

    def test_ppsspp_snapshot_restore_uses_the_renderer_migration(self):
        session = SESSION_PATH.read_text(encoding="utf-8")
        load = session.split(
            "StateLoadResult quick = vault.loadQuickResume(identity);", 1)[1].split(
            "checkpointScheduler =", 1)[0]
        self.assertIn("pendingQuickResume = quick.state;", load)
        self.assertNotIn("PPSSPP Quick Resume restore is disabled", load)
        restore = session.split(
            "private void restoreQuickResume", 1)[1].split(
                "private Throwable saveQuickResume", 1)[0]
        self.assertIn(
            '"ppsspp".equals(entry.id) || "dolphin".equals(entry.id)', restore)
        self.assertIn("applyRuntimeState(active, state);", restore)
        self.assertIn("active.unserialize(state, migrateRenderer);", restore)
        self.assertNotIn("active.recreateSurface(current);", restore)

    def test_armsx2_accuracy_defaults_to_full(self):
        host = (ROOT / "unified-android" / "native" /
                "lucent_libretro_host.c").read_text(encoding="utf-8")
        self.assertIn('strstr(host->core_path, "lucent_core_armsx2")', host)
        self.assertIn('strcmp(variable->key, "armsx2_blending_accuracy") == 0',
                      host)
        self.assertIn('find_option_token(\n                    options, "Full"', host)

    def test_armsx2_keeps_the_ps2_jit_audio_cushion(self):
        session = SESSION_PATH.read_text(encoding="utf-8")
        self.assertIn(
            'return "play".equals(entry.id) || "armsx2".equals(entry.id);',
            session,
        )
        self.assertEqual(2, session.count("isPs2Engine() ? 2"))

    def test_checked_in_registry_passes_strict_armsx2_policy(self):
        self.assertEqual([], VALIDATOR.validate(REGISTRY_PATH))


if __name__ == "__main__":
    unittest.main()
