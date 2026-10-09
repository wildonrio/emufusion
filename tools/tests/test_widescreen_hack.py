import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
GAME = ROOT / "unified-android/src/com/thorium/preview/game"


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


class WidescreenHackSettingsTest(unittest.TestCase):
    """Design section 7: the hack is opt-in and per-system."""

    def test_hack_defaults_off_while_the_native_flag_stays_on(self):
        settings = read("unified-android/src/com/thorium/preview/game/WidescreenSettings.java")
        self.assertIn('getBoolean(ENABLED, true)', settings)
        self.assertIn('getBoolean(HACK_ENABLED, false)', settings)
        self.assertIn('HACK_SYSTEM_PREFIX = "hack."', settings)
        for mode in ("on", "off", "auto"):
            self.assertIn('"%s"' % mode, settings)
        # Writes persist before the HTTP response, like the old flag.
        self.assertIn('.putBoolean(HACK_ENABLED, enabled).commit()', settings)

    def test_policy_contract_signatures(self):
        policy = read("unified-android/src/com/thorium/preview/game/WidescreenHackPolicy.java")
        self.assertIn("public static boolean isHackEnabledFor(Context context, String systemId)", policy)
        self.assertIn("public static String availability(String systemId)", policy)
        self.assertIn("public static void prepareLaunch(Context context, GameLaunchRequest request,", policy)
        self.assertIn("public static Map<String, String> coreOptionOverrides(", policy)
        self.assertIn("public static File engineRoot(Context context, String engineId)", policy)
        # Engine roots are derived exactly as the sessions derive them.
        self.assertIn('getDir("engine-system", Context.MODE_PRIVATE), engine)', policy)
        for source in ("LibretroEngineSpec.java", "Phase2QualificationCatalog.java",
                       "NativeAdapterSystemDirectory.java"):
            self.assertIn('getDir("engine-system", Context.MODE_PRIVATE)', read(
                "unified-android/src/com/thorium/preview/game/" + source), source)
        # Failures never block a launch.
        self.assertIn("catch (IOException | RuntimeException e)", policy)

    def test_table_matches_the_design(self):
        table = read("unified-android/src/com/thorium/preview/game/WidescreenHackTable.java")
        expected = {
            "mupen64plus-aspect": "16:9 adjusted",
            "mupen64plus-169screensize": "1920x1080",
            "swanstation_GPU_WidescreenHack": "true",
            "swanstation_Display_AspectRatio": "16:9",
            "armsx2_widescreen_patches": "enabled",
            "armsx2_aspect_ratio": "16:9",
            "armsx2_cheats": "enabled",
            "dolphin_widescreen_hack": "enabled",
            "dolphin_cheats_enabled": "enabled",
            "reicast_widescreen_cheats": "enabled",
            "reicast_widescreen_hack": "enabled",
            "ppsspp_cheats": "enabled",
        }
        for key, value in expected.items():
            self.assertIn('overrides.put("%s", "%s")' % (key, value), table, key)
        # Availability per system, exactly as documented.
        block = table.split("public static String availability")[1].split("}")[0]
        for system in ("n64", "psx", "ps2", "gamecube", "wii", "dreamcast"):
            self.assertIn('case "%s":' % system, block.split("return HACK")[0], system)
        self.assertIn('case "psp":\n                return CHEATS', block)
        for system in ("wiiu", "switch", "ps3"):
            self.assertIn('case "%s":' % system, block.split("return NATIVE")[0], system)
        self.assertIn("return UNAVAILABLE", block)
        self.assertIn('"gamecube", "wii", "psp"', table)  # widescreen-by-cheat systems


class OverrideFileTest(unittest.TestCase):
    """The file name and bounds agree between Java and the native host."""

    def test_java_and_native_agree_on_the_channel(self):
        java = read("unified-android/src/com/thorium/preview/game/CoreOptionOverrideFile.java")
        host = read("unified-android/native/lucent_libretro_host.c")
        self.assertIn('NAME = "lucent-core-overrides.txt"', java)
        self.assertIn('#define CORE_OVERRIDE_FILE_NAME "lucent-core-overrides.txt"', host)
        self.assertIn("MAX_ENTRIES = 64", java)
        self.assertIn("#define MAX_CORE_OVERRIDES 64u", host)
        self.assertIn("MAX_FILE_BYTES = 64 * 1024", java)
        self.assertIn("#define MAX_CORE_OVERRIDE_FILE_BYTES (64u * 1024u)", host)
        # Atomic write, bounded read.
        self.assertIn('".part"', java)
        self.assertIn("part.renameTo(file)", java)
        self.assertIn("file.length() > MAX_FILE_BYTES", java)

    def test_native_host_applies_overrides_after_defaults_and_frees_them(self):
        host = read("unified-android/native/lucent_libretro_host.c")
        defaults = host.split("static bool register_core_variable_defaults(")[1]
        override_at = defaults.index("find_core_override(host, variable->key)")
        # Every reviewed default precedes the override lookup in the loop body.
        for key in ("mupen64plus-aspect", "swanstation_Display_AspectRatio",
                    "armsx2_widescreen_patches", "dolphin_widescreen_hack",
                    "dolphin_cheats_enabled", "ppsspp_cheats"):
            self.assertLess(defaults.index('"%s"' % key), override_at, key)
        # Only tokens the core advertises are accepted.
        self.assertIn("declared_options, override, &override_size", defaults)
        self.assertIn("advertise token", defaults)
        self.assertIn("load_core_overrides(host);", host)
        self.assertIn("free_core_overrides(host);", host)
        self.assertIn("S_ISREG(info.st_mode)", host)

    def test_native_tests_cover_the_round_trip(self):
        test = read("unified-android/native/tests/host_test.c")
        mock = read("unified-android/native/tests/mock_core.c")
        self.assertIn('"%s/lucent-core-overrides.txt", argv[3]', test)
        self.assertIn('"mupen64plus-aspect"), "16:9 adjusted") == 0', test)
        self.assertIn("an override token the core does not advertise must be ignored", test)
        self.assertIn("removing the override file did not restore the defaults", test)
        self.assertIn('"dolphin_cheats_enabled"), "enabled") == 0', test)
        for key in ("dolphin_cheats_enabled", "ppsspp_cheats", "mupen64plus-169screensize"):
            self.assertIn('{ "%s",' % key, mock, key)


class CompanionAndThemeTest(unittest.TestCase):
    def test_endpoint_is_registered_like_the_native_flag(self):
        service = read("android-companion/src/com/thorium/preview/PreviewService.java")
        endpoint = read("android-companion/src/com/thorium/preview/WidescreenHackEndpoint.java")
        mutating = service.split("MUTATING_ENDPOINTS = new HashSet")[1].split("));")[0]
        theme_called = service.split("THEME_CALLED_ENDPOINTS = new HashSet")[1].split("));")[0]
        self.assertIn('"/settings/widescreen-hack"', mutating)
        self.assertIn('"/settings/widescreen-hack"', theme_called)
        self.assertIn('"/settings/widescreen-hack".equals(path)', service)
        self.assertIn("WidescreenHackEndpoint.handle(this, query)", service)
        self.assertIn('root.put("hackEnabled"', endpoint)
        self.assertIn('entry.put("mode"', endpoint)
        self.assertIn('entry.put("availability"', endpoint)
        self.assertIn("WidescreenSettings.setHackEnabled(context", endpoint)
        self.assertIn("WidescreenSettings.setHackMode(context, system, mode)", endpoint)
        self.assertIn('mode must be on, off, or auto', endpoint)

    def test_theme_slot_mirrors_the_native_flag_row(self):
        theme = read("theme/theme.qml")
        self.assertIn("property bool widescreenHackEnabled: false", theme)
        self.assertIn("property bool widescreenHackPending: false", theme)
        self.assertIn("settingsTailSlots: [17, 21, 22, 23, 20, 19, 24, 18]", theme)
        titles = re.search(r"function settingTitle\(index\).*?\n    \}", theme,
                           re.DOTALL).group(0)
        entries = re.findall(r'"([A-Z][^"]*)"', titles)
        self.assertEqual("WIDESCREEN HACK", entries[23])
        self.assertEqual("LEGAL NOTICE", entries[18])
        for snippet in (
            'requestPreviewJson("settings/widescreen-hack", function(payload) {',
            'requestPreviewJson("settings/widescreen-hack?enabled=" + (enabled ? "1" : "0"),',
            'if (index === 23) return widescreenHackPending ? "SAVING…" :',
            "if (slot === 23) {\n            setWidescreenHack(!widescreenHackEnabled)",
            'api.memory.has("emufusionWidescreenHack") ?',
            "refreshWidescreenHack()",
        ):
            self.assertIn(snippet, theme, snippet)

    def test_contract_doc_describes_the_channel(self):
        doc = read("docs/internal-core-aspect-contract.md")
        self.assertIn("lucent-core-overrides.txt", doc)
        self.assertIn("`hackEnabled`", doc)
        self.assertIn("default **false**", doc)
        self.assertIn("dolphin_cheats_enabled=enabled", doc)


if __name__ == "__main__":
    unittest.main()
