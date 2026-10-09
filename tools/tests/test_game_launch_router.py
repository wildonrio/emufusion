from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
NORMALIZER = (ROOT / "unified-android" / "src" / "com" / "thorium" /
              "lucent" / "metadata" / "MetadataLaunchNormalizer.java").read_text(
                  encoding="utf-8")
SYSTEM_RESOLVER = (ROOT / "unified-android" / "src" / "com" / "thorium" /
                   "lucent" / "metadata" / "EngineSystemIdResolver.java").read_text(
                           encoding="utf-8")
COMMAND = (ROOT / "unified-android" / "src" / "com" / "thorium" /
           "lucent" / "metadata" / "MetadataGameLaunchCommand.java").read_text(
                   encoding="utf-8")
ROUTER = (ROOT / "android-companion" / "src" / "com" / "thorium" /
          "preview" / "GameLaunchRouter.java").read_text(encoding="utf-8")
ROUTE_STORE = (ROOT / "android-companion" / "src" / "com" / "thorium" /
               "preview" / "EngineRouteStore.java").read_text(encoding="utf-8")
MIGRATION = (ROOT / "android-companion" / "src" / "com" / "thorium" /
             "preview" / "LaunchMetadataRouter.java").read_text(encoding="utf-8")
IMPORTER = (ROOT / "android-companion" / "src" / "com" / "thorium" /
            "preview" / "ImportManager.java").read_text(encoding="utf-8")
SERVICE = (ROOT / "android-companion" / "src" / "com" / "thorium" /
           "preview" / "PreviewService.java").read_text(encoding="utf-8")
BRIDGE = (ROOT / "android-companion" / "src" / "com" / "thorium" /
          "preview" / "InProcessGameLaunchCommand.java").read_text(encoding="utf-8")
PATCHER = (ROOT / "unified-android" / "tools" /
           "patch_main_activity_right_stick.py").read_text(encoding="utf-8")
APPLICATION = (ROOT / "unified-android" / "src" / "com" / "thorium" /
               "preview" / "LucentApplication.java").read_text(encoding="utf-8")
BUILD = (ROOT / "unified-android" / "build.sh").read_text(encoding="utf-8")
THEME = (ROOT / "theme" / "theme.qml").read_text(encoding="utf-8")
BOOTSTRAP = (ROOT / "unified-android" / "src" / "com" / "thorium" /
             "preview" / "game" / "InternalEngineBootstrap.java").read_text(
                     encoding="utf-8")
SECONDARY = (ROOT / "android-companion" / "src" / "com" / "thorium" /
             "preview" / "SecondaryGameplaySurfaceRouter.java").read_text(
                     encoding="utf-8")


class GameLaunchRouterTest(unittest.TestCase):
    def test_ps3_is_built_in_and_never_uses_stale_external_routing(self):
        self.assertNotIn('if ("ps3".equals(normalized)) return "";', ROUTER)
        self.assertIn('return nativeAdapter;', ROUTER)
        self.assertNotIn('NativeAdapterPrerequisites.isReady', ROUTER)
        self.assertIn('if (isInternalOnly(canonical)) return INTERNAL;', ROUTE_STORE)
        self.assertIn('if (isInternalOnly(canonical)) {', ROUTE_STORE)
        self.assertIn('LUCENT_INCLUDE_PHASE3_APS3E:-1', BUILD)

    def test_dolphin_is_internal_by_default_and_external_only_when_explicit(self):
        self.assertNotIn(
            'if ("gamecube".equals(normalized) || "wii".equals(normalized)) return "";',
            ROUTER,
        )
        resolve = ROUTE_STORE[ROUTE_STORE.index('public static String resolve'):]
        resolve = resolve[:resolve.index('public static String chosenEmulator')]
        self.assertIn('return INTERNAL;', resolve)
        self.assertNotIn('hasInternalEngine', resolve)
        self.assertIn('if (EXTERNAL.equals(stored)) return EXTERNAL;', ROUTE_STORE)
        self.assertIn('LUCENT_INCLUDE_PHASE2_PPSSPP:-1', BUILD)
        self.assertIn('put("gamecube", contentUri("dolphin"',
                      (ROOT / "android-companion" / "src" / "com" / "thorium" /
                       "preview" / "EmulatorCatalog.java").read_text(encoding="utf-8"))
        self.assertIn('put("wii", contentUri("dolphin"',
                      (ROOT / "android-companion" / "src" / "com" / "thorium" /
                       "preview" / "EmulatorCatalog.java").read_text(encoding="utf-8"))

    def test_imported_metadata_uses_stable_runtime_router(self):
        # The importer now delegates to EngineRouteStore, the single source of
        # truth for a system's launch command. EngineRouteStore preserves the
        # internal route: when it resolves INTERNAL it still emits exactly the
        # stable in-process runtime command from GameLaunchRouter.
        self.assertIn("EngineRouteStore.launchCommand(context, system)", IMPORTER)
        self.assertIn("GameLaunchRouter.supportsSystem(context, canonical)", ROUTE_STORE)
        self.assertIn("GameLaunchRouter.metadataCommand(context, canonical)", ROUTE_STORE)
        self.assertIn("InWindowGameHost.ACTION_LAUNCH", ROUTER)
        self.assertIn("org.pegasus_frontend.android.MainActivity", COMMAND)
        self.assertIn('return "am start -a', COMMAND)
        self.assertNotIn('return "am broadcast', COMMAND)
        self.assertIn("Phase2QualificationCatalog.libraryEngineIdForSystem", ROUTER)
        self.assertIn('" --es engine_id " + engine', COMMAND)

    def test_menu_command_is_intercepted_before_starting_an_activity(self):
        self.assertIn("LucentApplication.currentMainActivity()", BRIDGE)
        self.assertIn("Intercepted lifecycle-neutral menu launch", BRIDGE)
        self.assertIn("activity.runOnUiThread", BRIDGE)
        self.assertIn("InWindowGameHost.handleIntent(activity, request)", BRIDGE)
        self.assertIn("com.thorium.preview/org.pegasus_frontend.android.MainActivity", BRIDGE)
        self.assertNotIn("startActivity(", BRIDGE)
        self.assertIn("InProcessGameLaunchCommand;->tryLaunch", PATCHER)
        self.assertIn(":lucent_normal_am_launch", PATCHER)
        self.assertIn("WeakReference<Activity>", APPLICATION)
        self.assertIn("activity.isDestroyed()", APPLICATION)
        self.assertNotIn("GameLaunchReceiver", BUILD)

    def test_live_shortnames_resolve_before_catalog_lookup_and_command_output(self):
        self.assertIn("EngineSystemIdResolver.canonical(system)", ROUTER)
        self.assertIn('alias(aliases, "gamecube", "gc"', SYSTEM_RESOLVER)
        self.assertIn('alias(aliases, "3ds", "n3ds"', SYSTEM_RESOLVER)
        self.assertIn('alias(aliases, "megadrive", "genesis"', SYSTEM_RESOLVER)
        self.assertIn('" --es system " + system', COMMAND)
        self.assertIn("MetadataGameLaunchCommand.build", ROUTER)

    def test_canonical_routes_reach_registered_engines_and_dual_screen_ids(self):
        self.assertIn("EngineSessionRegistry.register(entry.id", BOOTSTRAP)
        self.assertIn("new PpssppGlesEngineSession", BOOTSTRAP)
        self.assertIn('"nds".equals(value)', SECONDARY)
        self.assertIn('"3ds".equals(value)', SECONDARY)
        self.assertIn('"gamecube"', SYSTEM_RESOLVER)
        self.assertIn('"megadrive"', SYSTEM_RESOLVER)

    def test_internal_is_the_only_route(self):
        self.assertNotIn("extends Activity", ROUTER)
        self.assertNotIn("MODE_EXTERNAL", ROUTER)
        self.assertNotIn("startActivity(", ROUTER)
        self.assertNotIn("ExternalOption", ROUTER)
        launch_block = IMPORTER[IMPORTER.index("private String launchCommand") :]
        launch_block = launch_block[:launch_block.index("private boolean installed")]
        self.assertNotIn("bridgeLaunch", launch_block)
        self.assertNotIn("org.ppsspp", launch_block)
        self.assertNotIn("org.dolphinemu", launch_block)

    def test_external_settings_and_service_routes_are_absent(self):
        self.assertNotIn('"/emulation/settings".equals(path)', SERVICE)
        self.assertNotIn('"/emulation/mode".equals(path)', SERVICE)
        self.assertNotIn('"/emulation/external".equals(path)', SERVICE)
        for label in ("EMULATION SYSTEM", "GAME ENGINE", "EXTERNAL EMULATOR"):
            self.assertNotIn(label, THEME)

    def test_migration_rewrites_every_collection_in_combined_metadata(self):
        self.assertIn("MetadataLaunchNormalizer.rewrite", MIGRATION)
        self.assertIn('lines[cursor].startsWith("collection:")', NORMALIZER)
        self.assertIn('lines[index].startsWith("shortname:")', NORMALIZER)
        self.assertIn('lines[index].startsWith("launch:")', NORMALIZER)
        self.assertIn("firstLaunchIndex < 0", NORMALIZER)
        self.assertIn("!wroteLaunch", NORMALIZER)
        self.assertIn("Stale per-game", NORMALIZER)
        self.assertIn('boolean launch = lines[index].startsWith("launch:");', NORMALIZER)
        self.assertNotIn("matcher.find()", MIGRATION)
        migration_block = SERVICE[SERVICE.index("Thread launchMigration"):]
        migration_block = migration_block[:migration_block.index("launchMigration.start()")]
        self.assertNotIn("reloadPegasusFrontend", migration_block)

    def test_migration_drops_unsupported_stale_launch_routes(self):
        # On-disk metadata is normalized through the same single source of truth
        # the importer uses. EngineRouteStore.launchCommand re-emits the resolved
        # route (internal command when internal, else the external am-start
        # recipe), so a route change or a stale standalone route is corrected in
        # place. Internal remains preserved inside EngineRouteStore.
        self.assertIn("EngineRouteStore.launchCommand(context, system)", MIGRATION)
        self.assertIn("GameLaunchRouter.metadataCommand(context, canonical)", ROUTE_STORE)
        self.assertIn("if (collectionLaunch)", NORMALIZER)
        self.assertIn("if (!desired.isEmpty()", NORMALIZER)

    def test_migration_covers_legacy_system_metadata_directory(self):
        # Older EmuFusion installs generated per-system metadata here. Leaving it
        # out lets Pegasus keep selecting stale external-emulator launch
        # commands even after the current metadata tree has been normalized.
        self.assertIn('new File(root, "metadata-systems")', MIGRATION)


if __name__ == "__main__":
    unittest.main()
