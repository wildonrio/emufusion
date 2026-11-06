"""The Switch (Native) system stays wired end to end: library entry, launch route,
theme entry, and a build that declares its Activity only when it bundles the host."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SYSTEMS = (ROOT / "android-companion/src/com/thorium/preview/GameSystems.java").read_text()
ROUTER = (ROOT / "android-companion/src/com/thorium/preview/GameLaunchRouter.java").read_text()
ROUTES = (ROOT / "android-companion/src/com/thorium/preview/EngineRouteStore.java").read_text()
THEME = (ROOT / "theme/theme.qml").read_text()
BUILD = (ROOT / "unified-android/build.sh").read_text()


class SwitchNativeSystemTest(unittest.TestCase):
    def test_library_lists_only_nxpack_files(self):
        entry = re.search(r'add\("switchnative", "Nintendo Switch \(Native\)", "[^"]*", "([^"]*)"', SYSTEMS)
        self.assertIsNotNone(entry)
        self.assertEqual(entry.group(1), "nxpack")

    def test_eden_keeps_the_switch_system(self):
        self.assertRegex(SYSTEMS, r'add\("switch", "Nintendo Switch", "[^"]*", "nsp xci"')

    def test_launch_goes_to_the_activity_with_the_pack_file(self):
        self.assertIn('"com.thorium.nxnative.NxActivity"', ROUTER)
        self.assertIn('--es nxpack \\"{file.path}\\"', ROUTER)
        self.assertIn('"switchnative".equals(canonical)', ROUTES)

    def test_route_exists_only_when_the_activity_is_declared(self):
        self.assertIn("getActivityInfo", ROUTER)
        self.assertIn("if (isSwitchNative(system)) return switchNativeBundled(context);", ROUTER)

    def test_theme_lists_the_system_and_has_its_logos(self):
        self.assertIn('folder: "switchnative"', THEME)
        self.assertTrue((ROOT / "theme/assets/logos-png/switchnative.png").is_file())
        self.assertTrue((ROOT / "theme/assets/logos/switchnative.svg").is_file())

    def test_build_is_opt_in_and_refuses_a_missing_host(self):
        self.assertIn("INCLUDE_NXNATIVE=${EMUFUSION_INCLUDE_NXNATIVE:-0}", BUILD)
        self.assertIn("EMUFUSION_INCLUDE_NXNATIVE=1 requires the staged host library", BUILD)
        declared = BUILD.index('android:name="com.thorium.nxnative.NxActivity"')
        guard = BUILD.rindex('if [ "$INCLUDE_NXNATIVE" = 1 ]; then', 0, declared)
        self.assertLess(BUILD.count("\nfi", guard, declared), 1)

    def test_upstream_licence_ships_with_the_host(self):
        self.assertIn("MIT License", (ROOT / "engines/compliance/nxnative/LICENSE").read_text())
        self.assertIn("LICENSE-MIT-NXNATIVE.txt", BUILD)


if __name__ == "__main__":
    unittest.main()
