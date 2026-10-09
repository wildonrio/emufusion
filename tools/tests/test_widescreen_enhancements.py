import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]


class WidescreenEnhancementsTest(unittest.TestCase):
    def read(self, path):
        return (ROOT / path).read_text(encoding="utf-8")

    def test_setting_is_default_on_durable_and_exposed_once(self):
        settings = self.read(
            "unified-android/src/com/thorium/preview/game/WidescreenSettings.java")
        service = self.read(
            "android-companion/src/com/thorium/preview/PreviewService.java")
        theme = self.read("theme/theme.qml")
        self.assertIn('getBoolean(ENABLED, true)', settings)
        self.assertIn('.putBoolean(ENABLED, enabled).commit()', settings)
        self.assertIn('"/settings/widescreen"', service)
        self.assertIn('"WIDESCREEN ENHANCEMENTS"', theme)
        # 2026-09-06: slot 23 (WIDESCREEN HACK) sits directly under the native
        # 16:9 row; the tail order otherwise keeps the legal notice last.
        self.assertIn('settingsTailSlots: [17, 21, 22, 23, 20, 19, 24, 18]', theme)
        # The old flag's default stays true even though the hack defaults off.
        self.assertIn('getBoolean(HACK_ENABLED, false)', settings)

    def test_only_native_game_controlled_widescreen_is_selected(self):
        host = self.read("unified-android/native/lucent_libretro_host.c")
        for key in (
            "dolphin_widescreen",
            "dolphin_widescreen_hack",
            "dolphin_aspect_ratio",
            "mupen64plus-aspect",
            "swanstation_GPU_WidescreenHack",
            "swanstation_Display_AspectRatio",
            "reicast_widescreen_cheats",
            "reicast_widescreen_hack",
            "armsx2_aspect_ratio",
            "armsx2_widescreen_patches",
        ):
            self.assertIn(key, host)
        self.assertIn('find_option_token(options, "4:3", &value_size)', host)
        self.assertGreaterEqual(
            host.count('find_option_token(options, "4:3", &value_size)'), 2,
            "N64 and PlayStation must retain their original 4:3 display")
        self.assertIn('"Auto 4:3/3:2", &value_size', host)
        self.assertIn('strcmp(variable->key, "mesen_aspect_ratio") == 0', host)
        # The launch-time override channel is the only path off these defaults:
        # it must read the file the Java policy writes, apply a token only when
        # the core advertises it, and never be driven by the old boolean.
        self.assertIn('"lucent-core-overrides.txt"', host)
        self.assertIn("load_core_overrides(host)", host)
        self.assertIn("find_core_override(host, variable->key)", host)
        self.assertIn("declared_options, override, &override_size", host)
        # Live cheats need the cores' internal cheat gates open.
        self.assertIn('strcmp(variable->key, "dolphin_cheats_enabled") == 0', host)
        self.assertIn('strcmp(variable->key, "ppsspp_cheats") == 0', host)
        self.assertNotIn('"16:9 adjusted" : "4:3"', host)
        self.assertNotIn('widescreen_enhancements_enabled ? "1" : "0"', host)
        self.assertNotIn(
            'widescreen_enhancements_enabled ? "3"', host,
            "Dolphin transport fill must not depend on widescreen preference")

    def test_dolphin_transport_fill_is_separate_from_display_aspect(self):
        host = self.read("unified-android/native/lucent_libretro_host.c")
        block = host.split('strcmp(variable->key, "dolphin_aspect_ratio") == 0')[1]
        block = block.split('} else if', 1)[0]
        self.assertIn('find_option_token(options, "3", &value_size)', block)
        self.assertNotIn('host->widescreen_enhancements_enabled', block)
        session = self.read(
            "unified-android/src/com/thorium/preview/game/PpssppGlesEngineSession.java")
        self.assertIn('request.systemId, av.aspectRatio', session)
        self.assertIn('loop.setPresentationAspect(presentationAspect)', session)

    def test_every_internal_libretro_route_captures_one_launch_value(self):
        software = self.read(
            "unified-android/src/com/thorium/preview/game/LibretroEngineSession.java")
        hardware = self.read(
            "unified-android/src/com/thorium/preview/game/PpssppGlesEngineSession.java")
        self.assertIn("WidescreenSettings.isEnabled(appContext)", software)
        self.assertIn("WidescreenSettings.isEnabled(appContext)", hardware)
        self.assertIn("widescreenEnhancementsEnabled", self.read(
            "unified-android/src/com/thorium/preview/ExperimentalGlesRenderLoop.java"))

    def test_pinned_core_sources_still_advertise_exact_tokens(self):
        def one(pattern):
            paths = list((ROOT / "engines/build/sources").glob(pattern))
            self.assertEqual(1, len(paths), pattern)
            return paths[0].read_text(encoding="utf-8", errors="ignore")

        dolphin = one("dolphin-*/Source/Core/DolphinLibretro/Common/Options.h")
        mupen = one("mupen64plus-next-*/libretro/libretro_core_options.h")
        swan = one("swanstation-*/src/libretro/libretro_core_options.h")
        flycast = one("flycast-*/shell/libretro/libretro_core_options.h")
        armsx2 = one("armsx2-*/pcsx2-libretro/Main.cpp")
        self.assertIn('WIDESCREEN_HACK[] = "dolphin_widescreen_hack"', dolphin)
        self.assertIn('CORE_NAME "-aspect"', mupen)
        self.assertIn('"swanstation_GPU_WidescreenHack"', swan)
        self.assertIn('CORE_OPTION_NAME "_widescreen_cheats"', flycast)
        self.assertIn('"armsx2_widescreen_patches"', armsx2)
        # The per-system hack table (WidescreenHackTable) writes exactly these
        # tokens; the cores must keep advertising them.
        self.assertIn('CORE_NAME "-169screensize"', mupen)
        self.assertIn('{"16:9 adjusted", "Wide (Adjusted)"}', mupen)
        self.assertIn('{"1920x1080",  "1920x1080 (16:9)"}', mupen)
        self.assertIn('{"16:9", "16:9"}', swan)
        self.assertIn('{"true", "Enabled"}', swan)
        self.assertIn('{"armsx2_widescreen_patches", "Widescreen patches (restart); disabled|enabled"}', armsx2)
        self.assertIn('{"armsx2_aspect_ratio", "Aspect ratio; Auto 4:3/3:2|4:3|16:9|Stretch"}', armsx2)
        self.assertIn('CORE_OPTION_NAME "_widescreen_hack"', flycast)
        self.assertIn('CHEATS_ENABLED[] = "dolphin_cheats_enabled"', dolphin)
        ppsspp = list((ROOT / "engines/build/sources").glob(
            "ppsspp-*/libretro/libretro_core_options.h"))
        self.assertTrue(ppsspp)
        for path in ppsspp:
            self.assertIn('"ppsspp_cheats"', path.read_text(encoding="utf-8", errors="ignore"))


if __name__ == "__main__":
    unittest.main()
