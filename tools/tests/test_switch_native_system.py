"""The Switch (Native) and Switch 2 systems stay wired end to end: library entries, launch
route, theme entries, and a normal build that stages its host from the pinned source."""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SYSTEMS = (ROOT / "android-companion/src/com/thorium/preview/GameSystems.java").read_text()
ROUTER = (ROOT / "android-companion/src/com/thorium/preview/GameLaunchRouter.java").read_text()
ROUTE = (ROOT / "android-companion/src/com/thorium/preview/SwitchNativeRoute.java").read_text()
ROUTES = (ROOT / "android-companion/src/com/thorium/preview/EngineRouteStore.java").read_text()
THEME = (ROOT / "theme/theme.qml").read_text()
BUILD = (ROOT / "unified-android/build.sh").read_text()
LOCK = json.loads((ROOT / "engines/nxnative-source-lock.json").read_text())


class SwitchNativeSystemTest(unittest.TestCase):
    def test_library_lists_only_nxpack_files(self):
        entry = re.search(r'add\("switchnative", "Nintendo Switch \(Native\)", "[^"]*", "([^"]*)"', SYSTEMS)
        self.assertIsNotNone(entry)
        self.assertEqual(entry.group(1), "nxpack")

    def test_switch_2_has_its_own_folder_and_file(self):
        entry = re.search(r'add\("switch2", "Nintendo Switch 2", "[^"]*", "([^"]*)"', SYSTEMS)
        self.assertIsNotNone(entry)
        self.assertEqual(entry.group(1), "nx2pack")
        self.assertIn('"switch2".equals(canonical)', ROUTE)
        self.assertIn('"switch2".equals(canonical)', ROUTES)
        self.assertIn('folder: "switch2"', THEME)
        self.assertTrue((ROOT / "theme/assets/logos-png/switch2.png").is_file())

    def test_nothing_claims_switch_2_games_work(self):
        self.assertIn("Not yet tested", SYSTEMS)
        self.assertIn("not yet tested", ROUTE)
        self.assertIn("No Switch 2 game has run", LOCK["note"])

    def test_a_pack_folder_is_one_game(self):
        scan = (ROOT / "android-companion/src/com/thorium/preview/ImportManager.java").read_text()
        self.assertIn('"nxpack".equals(packExtension) || "nx2pack".equals(packExtension)', scan)

    def test_eden_keeps_the_switch_system(self):
        self.assertRegex(SYSTEMS, r'add\("switch", "Nintendo Switch", "[^"]*", "nsp xci"')

    def test_launch_goes_to_the_activity_with_the_pack_file(self):
        self.assertIn('"com.thorium.nxnative.NxActivity"', ROUTE)
        self.assertIn('--es nxpack \\"{file.path}\\"', ROUTE)
        self.assertIn('"switchnative".equals(canonical)', ROUTES)

    def test_route_exists_only_when_the_activity_is_declared(self):
        self.assertIn("getActivityInfo", ROUTE)
        self.assertIn("if (SwitchNativeRoute.handles(system)) return SwitchNativeRoute.bundled(context);", ROUTER)

    def test_theme_lists_the_system_and_has_its_logos(self):
        self.assertIn('folder: "switchnative"', THEME)
        self.assertTrue((ROOT / "theme/assets/logos-png/switchnative.png").is_file())
        self.assertTrue((ROOT / "theme/assets/logos/switchnative.svg").is_file())

    def test_the_normal_build_stages_the_pinned_host(self):
        self.assertIn("INCLUDE_NXNATIVE=${EMUFUSION_INCLUDE_NXNATIVE:-1}", BUILD)
        self.assertIn('tools/stage_nxnative_host.py"', BUILD)
        self.assertRegex(LOCK["commit"], r"^[0-9a-f]{40}$")
        self.assertRegex(LOCK["libdmhostSha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(LOCK["ndk"], r"^\d+\.\d+\.\d+$")
        self.assertNotIn("nxnative-android-work", BUILD)
        declared = BUILD.index('android:name="com.thorium.nxnative.NxActivity"')
        guard = BUILD.rindex('if [ "$INCLUDE_NXNATIVE" = 1 ]; then', 0, declared)
        self.assertLess(BUILD.count("\nfi", guard, declared), 1)

    def test_upstream_licence_ships_with_the_host(self):
        self.assertIn("MIT License", (ROOT / "engines/compliance/nxnative/LICENSE").read_text())
        self.assertIn("LICENSE-MIT-NXNATIVE.txt", BUILD)
        third_party = (ROOT / "engines/compliance/nxnative/THIRD-PARTY.txt").read_text()
        self.assertIn("dav1d", third_party)
        self.assertIn("libvpx", third_party)
        self.assertIn("LICENSE-NXNATIVE-THIRD-PARTY.txt", BUILD)


if __name__ == "__main__":
    unittest.main()
