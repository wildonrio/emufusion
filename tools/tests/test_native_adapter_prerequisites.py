"""Fail-closed Switch/Wii U/PS3 native-adapter prerequisite routing.

The executing harness drives the real storage probe against temporary roots;
the structural checks lock the scan lifecycle, persistence boundary, routing
gate, generic launch error, and explicitly selected external Eden routing.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
GAME = ROOT / "unified-android" / "src" / "com" / "thorium" / "preview" / "game"
COMPANION = ROOT / "android-companion" / "src" / "com" / "thorium" / "preview"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


READINESS = _read(GAME / "NativeAdapterPrerequisites.java")
SYSTEM_DIR = _read(GAME / "NativeAdapterSystemDirectory.java")
ROUTER = _read(COMPANION / "GameLaunchRouter.java")
ROUTES = _read(COMPANION / "EngineRouteStore.java")
IMPORTER = _read(COMPANION / "ImportManager.java")
CATALOG = _read(COMPANION / "EmulatorCatalog.java")
MANIFEST = _read(ROOT / "android-companion" / "AndroidManifest.xml")
DIRECTORY = json.loads(_read(ROOT / "engines" / "external-emulators.json"))
SESSION = _read(COMPANION / "ExternalEmulationSession.java")
STOP_SERVICE = _read(COMPANION / "ExternalStopAccessibilityService.java")
TRAMPOLINE = _read(COMPANION / "RomLaunchActivity.java")
FALLBACK = _read(COMPANION / "ExternalGameFallback.java")
HOST = _read(GAME / "InWindowGameHost.java")
BUILD = _read(ROOT / "unified-android" / "build.sh")
ROUTE_PICKER = _read(COMPANION / "RoutePicker.java")
PREVIEW_SERVICE = _read(COMPANION / "PreviewService.java")
THEME = _read(ROOT / "theme" / "theme.qml")
STOP_CONFIG = _read(
    ROOT / "android-companion" / "res" / "xml" /
    "external_stop_accessibility.xml"
)


class PrerequisiteLifecycleContractTest(unittest.TestCase):
    def test_every_prerequisite_gated_native_adapter_is_refreshed(self):
        self.assertIn('new Spec("switch", "eden")', READINESS)
        self.assertIn('new Spec("wiiu", "cemu")', READINESS)
        self.assertIn('new Spec("ps3", "aps3e")', READINESS)

    def test_refresh_runs_during_scan_before_candidate_discovery(self):
        scan = IMPORTER[IMPORTER.index("private void runScan(boolean fullDiscovery)"):]
        refresh = scan.index("NativeAdapterPrerequisites.refresh(context)")
        discover = scan.index("discoverCandidates(cacheRoot)")
        self.assertLess(refresh, discover)
        self.assertIn("!imported.isEmpty() || prerequisiteRoutesChanged", scan)
        self.assertIn("LaunchMetadataRouter.normalize(context)", scan)

    def test_startup_route_migration_reloads_only_from_a_safe_heartbeat(self):
        startup = PREVIEW_SERVICE[
            PREVIEW_SERVICE.index("Thread launchMigration = new Thread"):
            PREVIEW_SERVICE.index('}, "lucent-launch-metadata")')
        ]
        self.assertIn("LaunchMetadataRouter.normalize(this)", startup)
        self.assertIn("launchRouteReloadPending.set(true)", startup)
        heartbeat = PREVIEW_SERVICE[
            PREVIEW_SERVICE.index('} else if ("/heartbeat".equals(path)) {'):
            PREVIEW_SERVICE.index('} else if ("/hide".equals(path)) {')
        ]
        self.assertIn("maybeReloadMigratedLaunchRoutes();", heartbeat)
        deferred = PREVIEW_SERVICE[
            PREVIEW_SERVICE.index("private void maybeReloadMigratedLaunchRoutes()"):
            PREVIEW_SERVICE.index("private static long parseLong")
        ]
        self.assertIn("compareAndSet(true, false)", deferred)
        self.assertIn("gameplayActive || browserActive || screensaverActive", deferred)
        self.assertIn("owner == null || !owner.hasWindowFocus()", deferred)
        self.assertIn("launchRouteReloadPending.set(true)", deferred)
        self.assertIn("reloadEmuFusionFrontend();", deferred)

    def test_persistence_is_only_ready_or_not_ready(self):
        self.assertIn('static final String READY = "READY";', READINESS)
        self.assertIn('static final String NOT_READY = "NOT_READY";', READINESS)
        record = READINESS[READINESS.index("static boolean record("):]
        record = record[:record.index("static String engineForSystem")]
        self.assertIn("String next = ready ? READY : NOT_READY;", record)
        self.assertIn("putString(PREFIX + system, next)", record)
        self.assertNotIn("getAbsolutePath", record)
        self.assertNotIn("getName()", record)

    def test_only_readable_shared_and_removable_roots_are_permitted(self):
        roots = READINESS[READINESS.index("static List<File> permittedVolumeRoots()"):]
        roots = roots[:roots.index("private static void addReadableRoot")]
        self.assertIn("Environment.getExternalStorageDirectory()", roots)
        self.assertIn('new File("/storage").listFiles()', roots)
        self.assertNotIn("getFilesDir", roots)
        add = READINESS[READINESS.index("private static void addReadableRoot"):]
        self.assertIn("!root.canRead()", add)
        self.assertIn("getCanonicalFile()", add)

    def test_routing_requires_verified_adapter_but_not_saved_readiness(self):
        block = ROUTER[ROUTER.index("private static String engineIdForSystem"):]
        self.assertIn("NativeAdapterCatalog.libraryEngineIdForSystem", block)
        self.assertNotIn("NativeAdapterPrerequisites.isReady", block)
        self.assertIn("return nativeAdapter;", block)
        # A bundled engine remains selectable before setup; validation is at
        # launch, never an excuse to change the user's chosen route.
        self.assertIn("!hasInternalEngine(context, canonical)) return false", ROUTES)
        self.assertNotIn("internalAvailable ? INTERNAL : EXTERNAL", ROUTES)

    def test_launch_revalidates_and_surfaces_only_generic_failure(self):
        resolve = SYSTEM_DIR[SYSTEM_DIR.index("static File resolve("):]
        resolve = resolve[:resolve.index("private static Layout layoutFor")]
        # A validated private baseline is the fast launch path.  The broad
        # shared-storage search remains only for first installation/recovery;
        # otherwise a ready Switch launch walked every volume to depth eight.
        self.assertIn("if (hasRuntimeInputs(root, layout))", resolve)
        self.assertLess(
            resolve.index("if (hasRuntimeInputs(root, layout))"),
            resolve.index("installRuntimeInputs(root, layout)"),
        )
        self.assertIn("installRuntimeInputs(root, layout)", resolve)
        self.assertIn("NativeAdapterPrerequisites.record(context, systemId, true)", resolve)
        self.assertIn("NativeAdapterPrerequisites.record(context, systemId, false)", resolve)
        self.assertIn(
            'new IllegalStateException("Internal emulator prerequisites are unavailable")',
            resolve,
        )
        self.assertNotIn("throw new IllegalStateException(file.sourceName", resolve)

    def test_source_markers_persist_only_content_hashes(self):
        identity = SYSTEM_DIR[SYSTEM_DIR.index("private static String sourceIdentity("):]
        identity = identity[:identity.index("private static String digestText")]
        self.assertIn('MessageDigest.getInstance("SHA-256")', identity)
        for identifying_call in ("getName()", "getPath()", "getAbsolutePath()",
                                 "lastModified()"):
            self.assertNotIn(identifying_call, identity)
        install = SYSTEM_DIR[SYSTEM_DIR.index("private static void installFile("):]
        install = install[:install.index("private static void installFirmware")]
        self.assertIn("digestText(file.destination).substring(0, 16)", install)
        self.assertNotIn("SOURCE_MARKER_PREFIX + file.destination", install)


class EdenExplicitExternalContractTest(unittest.TestCase):
    def _eden(self):
        return next(row for row in DIRECTORY["emulators"] if row["id"] == "eden")

    def test_official_package_and_downloads_are_first_with_legacy_compatibility(self):
        eden = self._eden()
        self.assertEqual("dev.eden.eden_emulator", eden["packages"][0])
        self.assertIn("dev.legacy.eden_emulator", eden["packages"])
        self.assertIn("org.citron.citron_emu", eden["packages"])
        self.assertEqual("https://eden-emu.dev/downloads/", eden["install"]["url"])
        self.assertIn(
            '"dev.eden.eden_emulator dev.legacy.eden_emulator org.citron.citron_emu"',
            CATALOG,
        )
        self.assertIn('"https://eden-emu.dev/downloads/", "official"', CATALOG)
        self.assertIn('<package android:name="dev.eden.eden_emulator" />', MANIFEST)

    def test_external_switch_direct_game_route_remains_content_uri(self):
        self.assertIn('put("switch", contentUri("eden", "Eden"', CATALOG)
        block = CATALOG[CATALOG.index("static String directLaunchCommand"):]
        block = block[:block.index("static String installCommand")]
        self.assertIn("RomLaunchActivity.ACTION_LAUNCH_FILE", block)
        self.assertIn("--es target_package ", block)

    def test_title_prerequisite_failure_does_not_change_an_internal_session_route(self):
        classifier = SYSTEM_DIR[SYSTEM_DIR.index("static boolean isPrerequisiteFailure"):]
        classifier = classifier[:classifier.index("private static Layout layoutFor")]
        self.assertIn('!"eden".equals(engine) && !"aps3e".equals(engine)',
                      classifier)
        self.assertIn('value.contains("missing firmware")', classifier)
        self.assertNotIn('value.contains("crash")', classifier)
        self.assertNotIn('value.contains("unsupported")', classifier)

        callback = HOST[HOST.index("@Override public void onSessionError("):
                        HOST.index("@Override public void onSessionStopRejected(")]
        self.assertIn("showFatalError(message);", callback)
        self.assertNotIn("ExternalGameFallback", HOST)
        self.assertNotIn("trySwitchPrerequisiteFallback", HOST)
        self.assertNotIn("exitToLibrary", callback)

        self.assertIn("RomLaunchActivity.ACTION_LAUNCH_FILE", FALLBACK)
        self.assertIn('"content-uri".equals(option.delivery)', FALLBACK)
        self.assertIn("option.installedPackage(context)", FALLBACK)
        self.assertNotIn("EngineRouteStore.set", FALLBACK)
        self.assertNotIn("Intent.ACTION_MAIN", FALLBACK)
        self.assertIn('!EngineRouteStore.isExplicit(context, "switch")', FALLBACK)
        self.assertIn('!EngineRouteStore.EXTERNAL.equals(', FALLBACK)
        self.assertIn('EngineRouteStore.resolve(context, "switch")', FALLBACK)


class ExternalStopReturnContractTest(unittest.TestCase):
    def test_same_apk_accessibility_service_is_packaged_with_key_filter_only(self):
        self.assertIn('android:name=".ExternalStopAccessibilityService"', MANIFEST)
        self.assertIn('android.permission.BIND_ACCESSIBILITY_SERVICE', MANIFEST)
        self.assertIn('android:resource="@xml/external_stop_accessibility"', MANIFEST)
        self.assertIn("ExternalStopAccessibilityService", BUILD)
        self.assertIn('cp "$ROOT_DIR/android-companion/res/xml/"*', BUILD)
        # The decoded-manifest fragment is interpolated into Perl source.
        # Failing to escape '@' silently turns @xml/foo into /foo and makes
        # apktool reject the otherwise valid accessibility resource.
        self.assertIn("s/[@&/]/\\\\&/g", BUILD)
        self.assertIn('android:accessibilityEventTypes="typeWindowStateChanged"',
                      STOP_CONFIG)
        self.assertIn('android:accessibilityFlags="flagRequestFilterKeyEvents"',
                      STOP_CONFIG)
        self.assertIn('android:canRetrieveWindowContent="false"', STOP_CONFIG)
        # The decoded Pegasus base has no @string/app_name resource.  The
        # manifest service label is sufficient for Android Settings, and the
        # config must remain linkable inside the unified APK.
        self.assertNotIn('@string/app_name', STOP_CONFIG)

    def test_exact_launched_session_is_tracked_without_rom_identity(self):
        guard = TRAMPOLINE[:TRAMPOLINE.index("File rom;")]
        self.assertIn("ExternalEmulationSession.stopControlEnabled(this)", guard)
        self.assertIn("Finish external emulator setup", guard)
        start = TRAMPOLINE.index("startActivity(launch);")
        begin = TRAMPOLINE.index("ExternalEmulationSession.begin(")
        self.assertLess(start, begin)
        self.assertIn("targetPackage, launch.getComponent().flattenToString()", TRAMPOLINE)
        for forbidden in ('putString("path"', 'putString("title"',
                          'putString("rom"', 'putString("firmware"'):
            self.assertNotIn(forbidden, SESSION)
        self.assertIn('.putBoolean("saveProven", false)', SESSION)
        self.assertIn('.putBoolean("externalClosedProven", false)', SESSION)

    def test_hold_is_exact_package_scoped_and_return_claims_fail_closed(self):
        self.assertIn("STOP_HOLD_MS = 1000L", STOP_SERVICE)
        self.assertIn("session.packageName.equals(foregroundPackage)", STOP_SERVICE)
        self.assertIn("armedToken.equals(session.token)", STOP_SERVICE)
        self.assertIn("event.getRepeatCount() == 0", STOP_SERVICE)
        self.assertIn("return false;", STOP_SERVICE)
        self.assertIn("GLOBAL_ACTION_BACK", STOP_SERVICE)
        self.assertIn("ExternalEmulationSession.returnToLibrary", STOP_SERVICE)
        self.assertNotIn("forceStopPackage", STOP_SERVICE)
        self.assertNotIn("KILL_BACKGROUND_PROCESSES", STOP_SERVICE)
        self.assertIn("saveProven=false externalClosedProven=false", STOP_SERVICE)
        self.assertIn("event.getDisplayId() != Display.DEFAULT_DISPLAY", STOP_SERVICE)
        self.assertIn("session.packageName.equals(observed)", STOP_SERVICE)
        self.assertIn("getPackageName().equals(observed)", STOP_SERVICE)
        self.assertIn("if (!session.returnRequested) return", STOP_SERVICE)
        self.assertIn('!"com.android.systemui".equals(observed)', STOP_SERVICE)
        self.assertIn("session.packageName.equals(foregroundPackage)", STOP_SERVICE)
        self.assertNotIn('foregroundPackage = event.getPackageName().toString()',
                         STOP_SERVICE)
        self.assertNotIn("getRootInActiveWindow()", STOP_SERVICE)
        self.assertNotIn("AccessibilityNodeInfo", STOP_SERVICE)
        self.assertNotIn("getText()", STOP_SERVICE)

    def test_lower_display_library_event_cannot_complete_external_session(self):
        event = STOP_SERVICE[STOP_SERVICE.index("onAccessibilityEvent("):]
        display_guard = event.index(
            "event.getDisplayId() != Display.DEFAULT_DISPLAY")
        mark = event.index("ExternalEmulationSession.markLibraryForeground")
        self.assertLess(display_guard, mark)
        self.assertIn("if (!session.active || session.token.isEmpty()) return", event)

    def test_natural_close_is_proven_only_before_fallback_launch(self):
        mark = SESSION[SESSION.index("static void markLibraryForeground"):]
        mark = mark[:mark.index("/** Whether Android")]
        self.assertIn("current.returnRequested", mark)
        self.assertIn("!current.fallbackLaunchIssued", mark)
        self.assertIn('.putBoolean("externalClosedProven", naturalClosure)', mark)
        fallback = SESSION[SESSION.index("static boolean returnToLibrary"):]
        self.assertLess(fallback.index('.putBoolean("fallbackLaunchIssued", true)'),
                        fallback.index("context.startActivity(intent)"))
        self.assertIn("afterBack.externalClosedProven", STOP_SERVICE)

    def test_external_selection_requires_one_time_os_authorization(self):
        link = ROUTE_PICKER[ROUTE_PICKER.index("static JSONObject link("):]
        auth = link.index("ExternalEmulationSession.stopControlEnabled(context)")
        persist = link.index("EngineRouteStore.setRoute(")
        self.assertLess(auth, persist)
        self.assertIn('response.put("authorizationRequired", true)', link)
        self.assertIn("Settings.ACTION_ACCESSIBILITY_SETTINGS", PREVIEW_SERVICE)
        self.assertIn("openExternalStopAuthorization()", PREVIEW_SERVICE)
        self.assertIn("data.authorizationRequired", THEME)
        self.assertIn("Android Accessibility", THEME)
        self.assertIn("ExternalEmulationSession.stopControlEnabled(context)", FALLBACK)


SDK_DIR = Path(os.environ.get(
    "ANDROID_SDK_ROOT",
    os.environ.get("ANDROID_HOME", "/Users/tyleryoung/Code/cemu/Cemu-0.5/android-sdk"),
))
ANDROID_JAR = SDK_DIR / "platforms" / os.environ.get("ANDROID_PLATFORM", "android-36") / "android.jar"
JAVA_HOME = Path(os.environ.get(
    "JAVA_HOME", "/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home"
))
JAVAC = JAVA_HOME / "bin" / "javac"
JAVA = JAVA_HOME / "bin" / "java"


HARNESS = r'''
package com.thorium.preview.game;

import java.io.File;
import java.io.FileOutputStream;
import java.io.FileWriter;
import java.io.RandomAccessFile;
import java.util.Arrays;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

public final class NativeAdapterPrerequisiteHarness {
    private static void check(boolean value, String label) {
        if (!value) throw new AssertionError(label);
        System.out.println("ok: " + label);
    }

    private static void text(File file, String value) throws Exception {
        file.getParentFile().mkdirs();
        FileWriter writer = new FileWriter(file);
        try { writer.write(value); } finally { writer.close(); }
    }

    private static void firmware(File file, String entryName) throws Exception {
        file.getParentFile().mkdirs();
        ZipOutputStream zip = new ZipOutputStream(new FileOutputStream(file));
        try {
            zip.putNextEntry(new ZipEntry(entryName));
            zip.write(new byte[] {1, 2, 3, 4});
            zip.closeEntry();
        } finally { zip.close(); }
    }

    private static void ps3Firmware(File file, boolean validMagic,
                                    long sizeBytes) throws Exception {
        file.getParentFile().mkdirs();
        RandomAccessFile output = new RandomAccessFile(file, "rw");
        try {
            output.setLength(0);
            output.write(validMagic
                    ? new byte[] {'S', 'C', 'E', 'U', 'F', 0, 0, 0}
                    : new byte[] {'N', 'O', 'T', 'P', 'U', 'P', 0, 0});
            output.setLength(sizeBytes);
        } finally { output.close(); }
    }

    public static void main(String[] args) throws Exception {
        File base = new File(args[0]);
        check(NativeAdapterSystemDirectory.systemDirectoryName("").equals("engine-system"),
                "normal system directory unchanged");
        check(NativeAdapterSystemDirectory.saveDirectoryName(null).equals("engine-saves"),
                "normal save directory unchanged");
        String qaOne = "qa-0123456789abcdef0123456789abcdef";
        String qaTwo = "qa-fedcba9876543210fedcba9876543210";
        File normalSystem = new File(base, "engine-system/aps3e/config/dev_hdd0/save");
        File normalSnapshot = new File(base, "engine-saves/aps3e/game/adapter-save.bin");
        File switchProfile = new File(base, "engine-system/eden/nand/system/save/8000000000000010/su/avators/profiles.dat");
        File switchSave = new File(base, "engine-system/eden/nand/user/save/0000000000000000/owner/game/progress");
        text(switchProfile, "existing Switch profile");
        text(switchSave, "existing Switch progress");
        text(normalSystem, "existing guest progress");
        text(normalSnapshot, "existing quick resume");
        for (String session : new String[] {qaOne, qaTwo}) {
            String systemRoot = NativeAdapterSystemDirectory.systemDirectoryName(session);
            String saveRoot = NativeAdapterSystemDirectory.saveDirectoryName(session);
            check(systemRoot.equals("engine-system-qa-" + session), "isolated guest root");
            check(saveRoot.equals("engine-saves-qa/" + session), "isolated snapshot root");
            text(new File(base, systemRoot + "/aps3e/config/dev_hdd0/save"), "test guest progress");
            text(new File(base, saveRoot + "/aps3e/game/adapter-save.bin"), "test quick resume");
            text(new File(base, systemRoot + "/eden/nand/system/save/8000000000000010/su/avators/profiles.dat"), "isolated Switch profile");
            text(new File(base, systemRoot + "/eden/nand/user/save/0000000000000000/owner/game/progress"), "isolated Switch progress");
        }
        check(new String(java.nio.file.Files.readAllBytes(normalSystem.toPath()), "UTF-8")
                .equals("existing guest progress"), "guest progress preserved by QA writes");
        check(new String(java.nio.file.Files.readAllBytes(normalSnapshot.toPath()), "UTF-8")
                .equals("existing quick resume"), "quick resume preserved by QA writes");
        check(new String(java.nio.file.Files.readAllBytes(switchProfile.toPath()), "UTF-8")
                .equals("existing Switch profile"), "Switch profile preserved by QA writes");
        check(new String(java.nio.file.Files.readAllBytes(switchSave.toPath()), "UTF-8")
                .equals("existing Switch progress"), "Switch progress preserved by QA writes");
        for (String invalid : new String[] {"qa", "../engine-system", "/tmp/root", " ",
                qaOne + "/..", "qa-0123456789ABCDEF0123456789ABCDEF"}) {
            boolean systemRejected = false, savesRejected = false;
            try { NativeAdapterSystemDirectory.systemDirectoryName(invalid); }
            catch (IllegalArgumentException expected) { systemRejected = true; }
            try { NativeAdapterSystemDirectory.saveDirectoryName(invalid); }
            catch (IllegalArgumentException expected) { savesRejected = true; }
            check(systemRejected && savesRejected, "invalid namespace cannot reach normal storage");
        }
        File internal = new File(base, "internal");
        File removable = new File(base, "removable");
        internal.mkdirs();
        removable.mkdirs();

        File switchKeys = new File(internal, "games/SWITCH/keys/prod.keys");
        text(switchKeys, "header_key = 00112233445566778899aabbccddeeff\n");
        File switchFirmware = new File(internal, "games/SWITCH/Firmware-18.zip");
        firmware(switchFirmware, "registered/0100000000000000.nca");
        check(NativeAdapterSystemDirectory.prerequisiteSourcesPresent(
                "eden", "switch", Arrays.asList(internal, removable)),
                "Switch finds valid key + NCA firmware case-insensitively");

        check(switchFirmware.delete(), "remove optional Switch firmware");
        check(NativeAdapterSystemDirectory.prerequisiteSourcesPresent(
                "eden", "switch", Arrays.asList(internal, removable)),
                "Switch keys-only baseline is ready without firmware");
        firmware(switchFirmware, "readme.txt");
        check(NativeAdapterSystemDirectory.prerequisiteSourcesPresent(
                "eden", "switch", Arrays.asList(internal, removable)),
                "Switch ignores an invalid optional firmware archive");
        check(switchFirmware.delete(), "replace invalid firmware");
        firmware(switchFirmware, "0100000000000000.nca/00");
        text(switchKeys, "# comment only\nnot-a-key\n");
        check(!NativeAdapterSystemDirectory.prerequisiteSourcesPresent(
                "eden", "switch", Arrays.asList(internal, removable)),
                "Switch still rejects invalid prod.keys content");

        // The preferred paths are not mandatory: final volume-root traversal
        // finds a deeply nested user-owned location on internal storage.
        check(switchKeys.delete(), "remove preferred Switch key");
        File customInternal = new File(internal,
                "Documents/My/Emulation/Setup/Switch/Security/prod.keys");
        text(customInternal,
                "header_key = 00112233445566778899aabbccddeeff\n");
        check(NativeAdapterSystemDirectory.prerequisiteSourcesPresent(
                "eden", "switch", Arrays.asList(internal, removable)),
                "Switch finds a valid arbitrary nested internal location");
        check(customInternal.delete(), "move arbitrary Switch key");
        File customRemovable = new File(removable,
                "Documents/Portable/Console/Config/prod.keys");
        text(customRemovable,
                "header_key = 00112233445566778899aabbccddeeff\n");
        check(NativeAdapterSystemDirectory.prerequisiteSourcesPresent(
                "eden", "switch", Arrays.asList(new File(base, "missing"), removable)),
                "Switch finds a valid arbitrary nested removable location");
        check(!NativeAdapterSystemDirectory.prerequisiteSourcesPresent(
                "eden", "switch", Arrays.asList(new File(base, "missing"))),
                "nonexistent roots are skipped and fail closed");

        File wiiuKeys = new File(removable, "Games/wiiu/Keys/keys.txt");
        text(wiiuKeys,
                "; comment\n0011-2233_4455 6677 8899 aabb ccdd eeff # title\n");
        check(NativeAdapterSystemDirectory.prerequisiteSourcesPresent(
                "cemu", "wii-u", Arrays.asList(internal, removable)),
                "Wii U mirrors Cemu formatting/comment parsing");
        text(wiiuKeys,
                "541b9889519b27d363cd21604b97c67a # example key (can be deleted)\n");
        check(!NativeAdapterSystemDirectory.prerequisiteSourcesPresent(
                "cemu", "wiiu", Arrays.asList(internal, removable)),
                "Wii U rejects Cemu's generated example placeholder");
        text(wiiuKeys, "# no key\n0011\n");
        check(!NativeAdapterSystemDirectory.prerequisiteSourcesPresent(
                "cemu", "wiiu", Arrays.asList(internal, removable)),
                "Wii U rejects comments and malformed keys");

        File ps3Update = new File(internal, "Games/PS3/Firmware/ps3updat.pup");
        ps3Firmware(ps3Update, true, 10L * 1024L * 1024L);
        check(NativeAdapterSystemDirectory.prerequisiteSourcesPresent(
                "aps3e", "ps3", Arrays.asList(internal, removable)),
                "PS3 finds a plausible owner-supplied update case-insensitively");
        ps3Firmware(ps3Update, false, 10L * 1024L * 1024L);
        check(!NativeAdapterSystemDirectory.prerequisiteSourcesPresent(
                "aps3e", "ps3", Arrays.asList(internal, removable)),
                "PS3 rejects the wrong update-container magic");
        ps3Firmware(ps3Update, true, 1024L);
        check(!NativeAdapterSystemDirectory.prerequisiteSourcesPresent(
                "aps3e", "ps3", Arrays.asList(internal, removable)),
                "PS3 rejects an implausibly small update");
        check(ps3Update.delete(), "move PS3 update to arbitrary nested location");
        File customPs3Update = new File(removable,
                "Documents/Console/Firmware/PS3UPDAT.PUP");
        ps3Firmware(customPs3Update, true, 10L * 1024L * 1024L + 1L);
        check(NativeAdapterSystemDirectory.prerequisiteSourcesPresent(
                "aps3e", "ps3", Arrays.asList(internal, removable)),
                "PS3 finds a valid arbitrary nested removable location");

        File installedSwitch = new File(base, "private-eden");
        text(new File(installedSwitch, "keys/prod.keys"),
                "header_key = 00112233445566778899aabbccddeeff\n");
        text(new File(installedSwitch,
                "nand/system/Contents/registered/0100000000000000.nca"), "nca");
        check(NativeAdapterSystemDirectory.installedPrerequisitesPresent(
                installedSwitch, "eden", "switch"),
                "validated private Switch installation remains ready");
        File installedPs3 = new File(base, "private-aps3e");
        ps3Firmware(new File(installedPs3, "PS3UPDAT.PUP"), true,
                10L * 1024L * 1024L);
        check(NativeAdapterSystemDirectory.installedPrerequisitesPresent(
                installedPs3, "aps3e", "ps3"),
                "validated private PS3 system update remains ready");
        check(!NativeAdapterSystemDirectory.prerequisiteSourcesPresent(
                "unknown", "switch", Arrays.asList(internal, removable)),
                "unknown engine fails closed");
        check(NativeAdapterSystemDirectory.isPrerequisiteFailure(
                "eden", new IllegalStateException("missing firmware for this title")),
                "Eden title prerequisite is classified");
        check(!NativeAdapterSystemDirectory.isPrerequisiteFailure(
                "eden", new IllegalStateException("GPU crash")),
                "generic Eden crash does not trigger external fallback");
        check(!NativeAdapterSystemDirectory.isPrerequisiteFailure(
                "cemu", new IllegalStateException("missing firmware")),
                "non-Eden prerequisite does not trigger Switch fallback");
        check(NativeAdapterSystemDirectory.isPrerequisiteFailure(
                "aps3e", new IllegalStateException("PS3 system update is required")),
                "aPS3e firmware prerequisite is classified");
        check(!NativeAdapterSystemDirectory.isPrerequisiteFailure(
                "aps3e", new IllegalStateException("Vulkan device lost")),
                "generic aPS3e failure is not mislabeled as firmware");
        for (String[] target : new String[][] {
                {"eden", "switch", "ROMs/switch/Keys"},
                {"cemu", "wiiu", "ROMs/wiiu/Keys"},
                {"aps3e", "ps3", "ROMs/ps3/Firmware"}}) {
            String help = NativeAdapterSystemDirectory.prerequisiteHelp(
                    target[0], target[1], new IllegalStateException(
                            "Internal emulator prerequisites are unavailable"));
            check(help.contains(target[2]) && help.contains("refresh the library"),
                    "missing setup has actionable, system-specific help");
            check(!help.contains(base.getAbsolutePath()), "help must not leak private paths");
            check(NativeAdapterSystemDirectory.prerequisiteHelp(target[0], target[1],
                    new IllegalStateException("GPU crash")).isEmpty(),
                    "do not mislabel GPU crashes as setup failures");
        }
        System.out.println("HARNESS_OK");
    }
}
'''


@unittest.skipUnless(ANDROID_JAR.is_file() and JAVAC.is_file(),
                     "Android SDK / JDK17 unavailable")
class NativeAdapterPrerequisiteExecutingTest(unittest.TestCase):
    def test_real_probe_accepts_only_complete_valid_inputs(self):
        work = Path(tempfile.mkdtemp(prefix="emufusion-prereq-"))
        self.addCleanup(shutil.rmtree, work, ignore_errors=True)
        classes = work / "classes"
        classes.mkdir()
        harness = work / "NativeAdapterPrerequisiteHarness.java"
        harness.write_text(HARNESS, encoding="utf-8")
        compile_result = subprocess.run(
            [str(JAVAC), "-source", "8", "-target", "8", "-encoding", "UTF-8",
             "-classpath", str(ANDROID_JAR), "-d", str(classes),
             str(GAME / "NativeAdapterPrerequisites.java"),
             str(GAME / "NativeAdapterSystemDirectory.java"), str(harness)],
            text=True, capture_output=True,
        )
        self.assertEqual(0, compile_result.returncode, compile_result.stderr)
        run_result = subprocess.run(
            [str(JAVA), "-cp", os.pathsep.join((str(classes), str(ANDROID_JAR))),
             "com.thorium.preview.game.NativeAdapterPrerequisiteHarness", str(work / "data")],
            text=True, capture_output=True,
        )
        self.assertEqual(0, run_result.returncode,
                         run_result.stdout + "\n" + run_result.stderr)
        self.assertIn("HARNESS_OK", run_result.stdout)


if __name__ == "__main__":
    unittest.main()
