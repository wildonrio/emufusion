"""External-emulator routing backend (Workstream H).

Two layers of coverage:

1. Structural (always run): source-scanning assertions in the established
   tools/tests house style that lock the per-system routing contract:
   EngineRouteStore resolution precedence, the importer/migration delegation to
   the single source of truth, the EmulatorCatalog recipe shapes, and the
   RomLaunchActivity/manifest boundary.

2. Executing (skipped when the Android SDK / JDK17 are absent): compiles the
   real android-companion + unified-android Java tree and drives EmulatorCatalog
   directly, so the canonical-key regression (GameCube keyed "gc" instead of
   "gamecube", 3DS keyed "n3ds" instead of "3ds") cannot come back silently.
"""

import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
COMPANION = ROOT / "android-companion" / "src" / "com" / "thorium" / "preview"
UNIFIED = ROOT / "unified-android"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


CATALOG = _read(COMPANION / "EmulatorCatalog.java")
ROUTE_STORE = _read(COMPANION / "EngineRouteStore.java")
IMPORTER = _read(COMPANION / "ImportManager.java")
GAME_SYSTEMS = _read(COMPANION / "GameSystems.java")
MIGRATION = _read(COMPANION / "LaunchMetadataRouter.java")
TRAMPOLINE = _read(COMPANION / "RomLaunchActivity.java")
PROVIDER = _read(COMPANION / "RomFileProvider.java")
MANIFEST = _read(ROOT / "android-companion" / "AndroidManifest.xml")
DOC = _read(ROOT / "docs" / "external-emulator-routing.md") \
    if (ROOT / "docs" / "external-emulator-routing.md").is_file() else ""


class EngineRouteStoreContractTest(unittest.TestCase):
    def test_default_is_internal_and_external_requires_explicit_choice(self):
        # Engine/prerequisite failure must never grant permission to leave the
        # app. An explicit External selection remains supported.
        block = ROUTE_STORE[ROUTE_STORE.index("public static String resolve"):]
        block = block[:block.index("public static String chosenEmulator")]
        self.assertIn('if (EXTERNAL.equals(stored)) return EXTERNAL;', block)
        self.assertNotIn("hasInternalEngine(context, canonical)", block)
        self.assertNotIn("internalAvailable ? INTERNAL : EXTERNAL", block)
        self.assertIn("return INTERNAL;", block)

    def test_hasInternalEngine_uses_the_release_qualified_router(self):
        self.assertIn("GameLaunchRouter.supportsSystem(context,", ROUTE_STORE)

    def test_setRoute_rejects_unlaunchable_preferences(self):
        # INTERNAL without an engine and EXTERNAL without a catalog option are
        # both refused, and a chosen emulator id must be a real catalog entry.
        self.assertIn(
            "if (INTERNAL.equals(normalized) && "
            "!hasInternalEngine(context, canonical)) return false;", ROUTE_STORE)
        self.assertIn(
            "!EmulatorCatalog.hasExternalOption(canonical)", ROUTE_STORE)
        self.assertIn(
            "if (EmulatorCatalog.optionForId(canonical, trimmed) == null) "
            "return false;", ROUTE_STORE)

    def test_launchCommand_is_the_single_source_of_truth(self):
        # Internal route -> stable in-process command; otherwise the external
        # am-start recipe honouring the chosen emulator. Fail closed only when
        # neither exists (EmulatorCatalog returns "").
        block = ROUTE_STORE[ROUTE_STORE.index("public static String launchCommand"):]
        self.assertIn("GameLaunchRouter.metadataCommand(context, canonical)", block)
        self.assertIn(
            "EmulatorCatalog.externalLaunchCommand(", block)
        self.assertIn("chosenEmulator(context, canonical)", block)

    def test_setRoute_persists_and_clears_the_emulator_choice(self):
        self.assertIn("ROUTE_PREFIX + canonical", ROUTE_STORE)
        self.assertIn("EMULATOR_PREFIX + canonical", ROUTE_STORE)
        self.assertIn("editor.remove(EMULATOR_PREFIX + canonical)", ROUTE_STORE)

    def test_a_user_defined_custom_emulator_counts_as_an_external_option(self):
        # A system the curated catalog cannot serve at all (no maintained
        # standalone emulator) must still be pointable by hand, so the
        # "no catalog option" refusal yields to a validated custom target.
        block = ROUTE_STORE[ROUTE_STORE.index("public static boolean setRoute"):]
        self.assertIn("!EmulatorCatalog.hasExternalOption(canonical)", block)
        self.assertIn("&& !CustomEmulatorStore.has(context, canonical)", block)
        # ...but only once the guided setup has proved it resolves on device.
        self.assertIn(
            "if (CustomEmulatorStore.option(context, canonical) == null) return false;",
            block)

    def test_internal_stays_the_default_for_every_engine_backed_system(self):
        # The picker must not be able to weaken this: nothing in the settings
        # surface writes a route except through setRoute, and resolve() has no
        # branch that prefers external when an engine exists.
        block = ROUTE_STORE[ROUTE_STORE.index("public static String resolve"):]
        block = block[:block.index("public static String chosenEmulator")]
        self.assertNotIn("EXTERNAL : INTERNAL", block)
        self.assertNotIn("internalAvailable ? INTERNAL : EXTERNAL", block)
        self.assertIn("return INTERNAL;", block)

    def test_dolphin_never_falls_back_external_without_user_choice(self):
        block = ROUTE_STORE[ROUTE_STORE.index("public static String resolve"):]
        block = block[:block.index("public static String chosenEmulator")]
        self.assertLess(block.index('if (EXTERNAL.equals(stored)) return EXTERNAL;'),
                        block.rindex('return INTERNAL;'))
        launch = ROUTE_STORE[ROUTE_STORE.index("public static String launchCommand"):]
        self.assertIn('? GameLaunchRouter.metadataCommand(context, canonical) : "";',
                      launch)


class RouteChangeRewritesMetadataTest(unittest.TestCase):
    def test_importer_delegates_to_the_route_store(self):
        block = IMPORTER[IMPORTER.index("private String launchCommand"):]
        block = block[:block.index("private boolean installed")]
        self.assertIn("EngineRouteStore.launchCommand(context, system)", block)

    def test_route_change_re_emits_every_systems_launch_command(self):
        # A route change must regenerate fresh metadata AND normalize on-disk
        # metadata, then ask Pegasus to reload so the new launch: lines apply.
        self.assertIn("boolean rewriteLaunchRoutes()", IMPORTER)
        block = IMPORTER[IMPORTER.index("boolean rewriteLaunchRoutes"):]
        block = block[:block.index("private void requestLibraryReload")]
        self.assertIn("writeMetadata(registry)", block)
        self.assertIn("LaunchMetadataRouter.normalize(context)", block)
        self.assertIn("requestLibraryReload()", block)
        self.assertIn('status.put("needsReload", true)', IMPORTER)

    def test_on_disk_normalizer_routes_through_the_route_store(self):
        self.assertIn(
            "EngineRouteStore.launchCommand(context, system)", MIGRATION)


class EmulatorCatalogRecipeTest(unittest.TestCase):
    def test_catalog_keys_are_canonical_for_gamecube_and_3ds(self):
        # Regression: optionsForSystem canonicalizes before lookup, so keying on
        # the raw aliases "gc"/"n3ds" left GameCube and the 3DS with no reachable
        # external option (the 3DS-does-not-load bug).
        self.assertIn('put("gamecube",', CATALOG)
        self.assertIn('put("3ds",', CATALOG)
        self.assertNotIn('put("gc",', CATALOG)
        self.assertNotIn('put("n3ds",', CATALOG)

    def test_unsupported_list_has_no_malformed_tokens(self):
        match = re.search(r'unsupported\("([^"]*(?:"\s*\+\s*"[^"]*)*)"\)', CATALOG)
        self.assertIsNotNone(match)
        systems = match.group(1).replace('" +', "").replace('"', "").split()
        for token in systems:
            self.assertNotIn("-none", token, f"malformed unsupported token {token!r}")
        # Xbox/Xbox360/Apple II stay genuinely optionless (no maintained Android
        # port). PS3 is intentionally absent because aPS3e is built in.
        self.assertIn("xbox", systems)
        self.assertNotIn('put("ps3",', CATALOG)

    def test_three_delivery_recipes_exist(self):
        # FILE_PATH -> --es <key>; ACTION_VIEW -> -d file://; CONTENT_URI -> the
        # RomLaunchActivity trampoline.
        block = CATALOG[CATALOG.index("static String directLaunchCommand"):]
        block = block[:block.index("static String installCommand")]
        self.assertIn("RomLaunchActivity.ACTION_LAUNCH_FILE", block)
        self.assertIn("com.thorium.preview/com.thorium.preview.RomLaunchActivity", block)
        self.assertIn("--es target_package ", block)
        self.assertIn('-d \\"file://{file.path}\\"', block)
        self.assertIn('--es ").append(key).append(" \\"{file.path}\\"', block)
        self.assertIn("--activity-clear-task", block)
        self.assertIn("--es LIBRETRO ", block)

    def test_content_uri_systems_target_the_trampoline(self):
        # Switch, Wii U, and official Dolphin all use a one-shot scoped URI.
        self.assertIn('put("switch", contentUri(', CATALOG)
        self.assertIn('put("wiiu", contentUri(', CATALOG)
        self.assertIn('put("gamecube", contentUri("dolphin"', CATALOG)
        self.assertIn('put("wii", contentUri("dolphin"', CATALOG)

    def test_dolphin_trampoline_preflights_compressed_disc_images(self):
        self.assertIn('" --es launch_profile dolphin"', CATALOG)
        self.assertIn('!"dolphin".equals(launchProfile)', TRAMPOLINE)
        self.assertIn('DiscImagePreflight.validate("gamecube", rom)', TRAMPOLINE)

    def test_ps3_has_no_external_emulator_recipe(self):
        self.assertNotIn('put("ps3",', CATALOG)
        self.assertNotIn("ps3App()", CATALOG)
        self.assertNotIn('" --es launch_profile ps3"', CATALOG)

    def test_retroarch_is_a_listed_external_option(self):
        self.assertIn('"RetroArch"', CATALOG)
        self.assertIn("com.retroarch.aarch64", CATALOG)

    def test_multiple_ordered_options_per_system(self):
        # e.g. PSX lists DuckStation, ePSXe and RetroArch in order.
        psx = CATALOG[CATALOG.index('put("psx",'):]
        psx = psx[:psx.index("put(\"ps2\",")]
        self.assertIn("duckstation", psx)
        self.assertIn("epsxe", psx)
        self.assertIn("retroArch(\"psx\"", psx)


class TrampolineBoundaryTest(unittest.TestCase):
    def test_trampoline_is_non_exported_in_manifest(self):
        block = re.search(
            r'<activity[^>]*RomLaunchActivity.*?/>', MANIFEST, re.DOTALL)
        self.assertIsNotNone(block)
        self.assertIn('android:exported="false"', block.group(0))
        self.assertNotIn("intent-filter", block.group(0))

    def test_rom_provider_is_declared_non_exported_with_grants(self):
        block = re.search(
            r'<provider[^>]*RomFileProvider.*?/>', MANIFEST, re.DOTALL)
        self.assertIsNotNone(block)
        self.assertIn('android:authorities="com.thorium.preview.roms"', block.group(0))
        self.assertIn('android:exported="false"', block.group(0))
        self.assertIn('android:grantUriPermissions="true"', block.group(0))

    def test_trampoline_confines_source_to_shared_storage(self):
        self.assertIn("getCanonicalFile()", TRAMPOLINE)
        self.assertIn('canonical.startsWith("/storage/")', TRAMPOLINE)
        self.assertIn('canonical.startsWith("/mnt/media_rw/")', TRAMPOLINE)
        self.assertIn("FLAG_GRANT_READ_URI_PERMISSION", TRAMPOLINE)
        # The provider enforces the same confinement and read-only access.
        self.assertIn('canonical.startsWith("/storage/")', PROVIDER)
        self.assertIn('throw new FileNotFoundException("Read only")', PROVIDER)

    def test_ps3_trampoline_derives_only_verified_folder_or_iso_shapes(self):
        self.assertIn('!"aenu.aps3e".equals(targetPackage)', TRAMPOLINE)
        self.assertIn('!"aenu.aps3e.EmulatorActivity".equals(targetActivity)',
                      TRAMPOLINE)
        self.assertIn('!"aenu.intent.action.APS3E".equals(targetAction)', TRAMPOLINE)
        self.assertIn('"eboot.bin".equals(lower)', TRAMPOLINE)
        self.assertIn('"ps3_game".equalsIgnoreCase', TRAMPOLINE)
        self.assertIn('new File(ps3Game, "PARAM.SFO").isFile()', TRAMPOLINE)
        self.assertIn('launch.putExtra("game_dir", titleRoot.getAbsolutePath())', TRAMPOLINE)
        self.assertIn('launch.putExtra("iso_uri", uri.toString())', TRAMPOLINE)


class Ps3ImportShapeTest(unittest.TestCase):
    def test_download_scan_indexes_verified_folder_dump_in_place(self):
        self.assertIn('new File(file, "PS3_GAME/USRDIR/EBOOT.BIN")', IMPORTER)
        self.assertIn("File titleRoot = ps3TitleRoot(eboot);", IMPORTER)
        self.assertIn('canonical(eboot.getAbsolutePath()) + ":" + eboot.length(), true',
                      IMPORTER)
        self.assertIn("candidates = uniqueCandidates(candidates);", IMPORTER)

    def test_pkg_is_not_advertised_as_a_bootable_ps3_game(self):
        ps3 = GAME_SYSTEMS[GAME_SYSTEMS.index('add("ps3",'):]
        ps3 = ps3[:ps3.index('add("wii",')]
        self.assertIn('"iso"', ps3)
        self.assertNotIn("pkg", ps3.lower())


class DesignNoteTest(unittest.TestCase):
    def test_design_note_names_the_future_route_endpoints(self):
        self.assertTrue(DOC, "docs/external-emulator-routing.md must exist")
        for endpoint in ("/route/resolve", "/route/set", "/route/clear",
                         "/route/options"):
            self.assertIn(endpoint, DOC)
        # It must record the one-app verifier tension so it is not forgotten.
        self.assertIn("verify_one_app_apk", DOC)


# ---------------------------------------------------------------------------
# Executing harness: compile the real tree and drive EmulatorCatalog.
# ---------------------------------------------------------------------------

SDK_DIR = Path(os.environ.get(
    "ANDROID_SDK_ROOT",
    os.environ.get("ANDROID_HOME",
                   "/Users/tyleryoung/Code/cemu/Cemu-0.5/android-sdk")))
ANDROID_JAR = SDK_DIR / "platforms" / \
    os.environ.get("ANDROID_PLATFORM", "android-36") / "android.jar"
JAVA_HOME = Path(os.environ.get(
    "JAVA_HOME",
    "/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home"))
JAVAC = JAVA_HOME / "bin" / "javac"
JAVA = JAVA_HOME / "bin" / "java"
DEPS = UNIFIED / "build" / "deps"
COMMONS = DEPS / "commons-compress-1.21.jar"
XZ = DEPS / "xz-1.9.jar"
WEBSOCKET = DEPS / "nv-websocket-client-2.14.jar"
WEBRTC = DEPS / "webrtc-android-150.7871.01/classes.jar"

HARNESS = r'''
package com.thorium.preview;

import java.util.List;

/** Drives the real EmulatorCatalog with no Android runtime (pure lookups). */
public final class ExternalEmulatorRoutingHarness {
    static void check(boolean ok, String label) {
        if (!ok) throw new AssertionError("FAIL: " + label);
        System.out.println("ok: " + label);
    }

    public static void main(String[] args) {
        // Canonical-key regression: aliases resolve to the same options.
        check(!EmulatorCatalog.optionsForSystem("3ds").isEmpty(), "3ds has options");
        check(!EmulatorCatalog.optionsForSystem("n3ds").isEmpty(), "n3ds alias resolves");
        check(!EmulatorCatalog.optionsForSystem("gamecube").isEmpty(), "gamecube has options");
        check(!EmulatorCatalog.optionsForSystem("gc").isEmpty(), "gc alias resolves");

        // Auto-external systems with no internal engine still launch.
        check(EmulatorCatalog.hasExternalOption("switch"), "switch external option");
        check(EmulatorCatalog.hasExternalOption("wiiu"), "wiiu external option");
        check(EmulatorCatalog.hasExternalOption("3ds"), "3ds external option");
        // PS3 now routes to aPS3e (user-required representation).
        check(!EmulatorCatalog.hasExternalOption("ps3"),
                "ps3 is built in and has no external option");
        // Genuinely optionless system stays fail-closed.
        check(!EmulatorCatalog.hasExternalOption("xbox"), "xbox optionless");

        // Multiple ordered options per system.
        check(EmulatorCatalog.optionsForSystem("psx").size() >= 3, "psx >=3 options");

        // CONTENT_URI recipe routes through the trampoline.
        EmulatorCatalog.Option sw = EmulatorCatalog.optionsForSystem("switch").get(0);
        String swCmd = EmulatorCatalog.directLaunchCommand(sw, "dev.legacy.eden_emulator");
        check(swCmd.contains("com.thorium.preview/com.thorium.preview.RomLaunchActivity"),
                "switch recipe uses trampoline");
        check(swCmd.contains("--es target_package dev.legacy.eden_emulator"),
                "switch recipe forwards package");

        check(GameSystems.byFolder("ps3").extensions.contains("iso") &&
                !GameSystems.byFolder("ps3").extensions.contains("pkg"),
                "ps3 accepts bootable ISO but not install-only PKG");

        // FILE_PATH recipe uses the emulator's own ROM extra + clear-task.
        EmulatorCatalog.Option psx = EmulatorCatalog.optionForId("psx", "duckstation");
        String psxCmd = EmulatorCatalog.directLaunchCommand(psx, "com.github.stenzek.duckstation");
        check(psxCmd.contains("--es bootPath \"{file.path}\""), "psx file-path extra");
        check(psxCmd.contains("--activity-clear-task"), "psx clear-task");

        // ACTION_VIEW recipe hands the ROM as file:// data.
        EmulatorCatalog.Option nes = EmulatorCatalog.optionsForSystem("nes").get(0);
        String nesCmd = EmulatorCatalog.directLaunchCommand(nes, "com.explusalpha.NesEmu");
        check(nesCmd.contains("-d \"file://{file.path}\""), "nes action-view data");

        // RetroArch recipe supplies the libretro core path.
        EmulatorCatalog.Option ra = EmulatorCatalog.optionForId("nes", "retroarch-nes");
        String raCmd = EmulatorCatalog.directLaunchCommand(ra, "com.retroarch.aarch64");
        check(raCmd.contains("--es LIBRETRO /data/data/com.retroarch.aarch64/cores/"),
                "retroarch core path");

        // Update-availability logic (offer, never force).
        check(ExternalEmulatorUpdater.isNewer("1.2.0", "1.2.1"), "patch bump newer");
        check(ExternalEmulatorUpdater.isNewer("v1.9", "v1.10"), "numeric segment order");
        check(!ExternalEmulatorUpdater.isNewer("2.0", "2.0.0"), "equal versions not newer");
        check(!ExternalEmulatorUpdater.isNewer("1.5", "1.4.9"), "older not newer");
        EmulatorCatalog.Option dol = EmulatorCatalog.optionsForSystem("gamecube").get(0);
        check(ExternalEmulatorUpdater.hasCheckableSource(dol),
                "official-api source is checkable");
        ExternalEmulatorUpdater.Result up = ExternalEmulatorUpdater.checkForUpdate(
                dol, "2000", (source, type) -> "2100");
        check(up.updateAvailable && !up.offerCommand.isEmpty(),
                "update offer built when newer");
        ExternalEmulatorUpdater.Result none = ExternalEmulatorUpdater.checkForUpdate(
                dol, "2100", (source, type) -> "2100");
        check(!none.updateAvailable && none.offerCommand.isEmpty(),
                "no offer when current");

        // The settings picker validates a custom emulator against the pure
        // delivery vocabulary while the recipe builder switches on the
        // catalog's copies. They are aliases, not parallel spellings: a
        // divergence would make a validated custom entry unlaunchable.
        check(EmulatorCatalog.DELIVERY_FILE_PATH ==
                com.thorium.lucent.emulators.ExternalEmulatorDelivery.FILE_PATH,
                "file-path delivery constant is shared");
        check(EmulatorCatalog.DELIVERY_ACTION_VIEW ==
                com.thorium.lucent.emulators.ExternalEmulatorDelivery.ACTION_VIEW,
                "action-view delivery constant is shared");
        check(EmulatorCatalog.DELIVERY_CONTENT_URI ==
                com.thorium.lucent.emulators.ExternalEmulatorDelivery.CONTENT_URI,
                "content-uri delivery constant is shared");
        check(!com.thorium.lucent.emulators.ExternalEmulatorDelivery.known(
                EmulatorCatalog.DELIVERY_UNSUPPORTED),
                "the unsupported marker is not a delivery a custom entry can pick");

        System.out.println("HARNESS_OK");
    }
}
'''


@unittest.skipUnless(
    ANDROID_JAR.is_file() and JAVAC.is_file() and COMMONS.is_file()
    and XZ.is_file() and WEBSOCKET.is_file() and WEBRTC.is_file(),
    "Android SDK / JDK17 / build deps not available for the executing harness")
class EmulatorCatalogExecutingTest(unittest.TestCase):
    def test_catalog_logic_runs(self):
        workdir = tempfile.mkdtemp(prefix="lucent-emu-routing-")
        self.addCleanup(shutil.rmtree, workdir, ignore_errors=True)
        classes = Path(workdir) / "classes"
        classes.mkdir()
        harness = Path(workdir) / "ExternalEmulatorRoutingHarness.java"
        harness.write_text(HARNESS, encoding="utf-8")

        sources = []
        for base in (ROOT / "android-companion" / "src",
                     ROOT / "android-launch-bridge" / "src",
                     UNIFIED / "src", UNIFIED / "stubs"):
            for path in base.rglob("*.java"):
                name = path.as_posix()
                if any(name.endswith(skip) for skip in (
                        "/com/thorium/preview/MainActivity.java",
                        "/com/thorium/launchbridge/LaunchActivity.java",
                        "/com/thorium/launchbridge/RomFileProvider.java",
                        "/com/thorium/launchbridge/StopButtonService.java",
                        "/com/thorium/preview/game/InternalGameLaunchActivity.java",
                        "/com/thorium/preview/game/LucentGameActivity.java",
                        "/com/thorium/preview/game/QualificationLaunchActivity.java",
                        "/com/thorium/preview/game/SessionReturnRouter.java")):
                    continue
                sources.append(name)
        sources.append(harness.as_posix())

        argfile = Path(workdir) / "sources.txt"
        argfile.write_text("\n".join(sources), encoding="utf-8")
        classpath = os.pathsep.join(
            str(p) for p in (ANDROID_JAR, COMMONS, XZ, WEBSOCKET, WEBRTC))
        compile_result = subprocess.run(
            [str(JAVAC), "-source", "8", "-target", "8", "-encoding", "UTF-8",
             "-classpath", classpath, "-d", str(classes), f"@{argfile}"],
            cwd=workdir, text=True, capture_output=True)
        self.assertEqual(
            0, compile_result.returncode,
            f"javac failed:\n{compile_result.stderr}")

        run_result = subprocess.run(
            [str(JAVA), "-cp", os.pathsep.join([str(classes), classpath]),
             "com.thorium.preview.ExternalEmulatorRoutingHarness"],
            cwd=workdir, text=True, capture_output=True)
        self.assertEqual(
            0, run_result.returncode,
            f"harness failed:\n{run_result.stdout}\n{run_result.stderr}")
        self.assertIn("HARNESS_OK", run_result.stdout)


if __name__ == "__main__":
    unittest.main()
