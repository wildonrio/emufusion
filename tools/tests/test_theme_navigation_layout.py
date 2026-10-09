from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class ThemeNavigationLayoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.theme = (ROOT / "theme" / "theme.qml").read_text(encoding="utf-8")
        cls.build = (ROOT / "unified-android" / "build.sh").read_text(encoding="utf-8")

    def test_system_list_uses_complete_eight_row_pages(self):
        self.assertIn("var visibleRows = 8", self.theme)
        self.assertIn("gameListRail.positionViewAtIndex(start, ListView.Beginning)", self.theme)
        # The highlight band still sits three WHOLE rows down from the top of
        # the viewport, but the stride is no longer the constant 80 px it was:
        # the row grows to spend the reclaimed height, so the band is expressed
        # in strides. Pinning the literal 240 here is what previously forced the
        # row height to stay at 76 and stranded 59 px under the eighth row.
        self.assertIn("readonly property real rowStride: rowHeight + rowSpacing", self.theme)
        self.assertIn("preferredHighlightBegin: 3 * rowStride", self.theme)
        self.assertIn("preferredHighlightEnd: 3 * rowStride", self.theme)
        self.assertIn("snapMode: ListView.SnapToItem", self.theme)
        self.assertIn("boundsBehavior: Flickable.StopAtBounds", self.theme)

    def test_lists_spend_reclaimed_height_on_rows_not_padding(self):
        """Every wallpaper-facing list quantises to whole rows via the shared
        helpers, and none of them pins row height to its own minimum -- a list
        whose maximum equals its minimum cannot grow and leaves a dead band."""
        self.assertIn("function listRowCount(available, minimum, spacing)", self.theme)
        self.assertIn("function listRowHeight(available, minimum, maximum, spacing)", self.theme)
        for call, minimum, maximum in (
            ("parent.height, 76, 92, rowSpacing", 76, 92),      # games list
            ("parent.height - y, 76, 88, rowSpacing", 76, 88),  # home list, games
            ("parent.height, 70, 80, rowSpacing", 70, 80),      # home list, systems
        ):
            self.assertIn(call, self.theme)
            self.assertGreater(maximum, minimum)

    def test_cover_system_shelf_is_sized_from_its_slot(self):
        """The hero shelf used to be a 440x330 constant inside a 697 px slot,
        which left a 239 px band of wallpaper under it."""
        self.assertIn("readonly property real coverSystemBandHeight", self.theme)
        self.assertIn("Math.floor(coverSystemBandHeight / coverSystemSelectedScale)",
                      self.theme)
        self.assertNotIn("readonly property real coverSystemCardHeight: coverViewRowCount === 1 ? 330",
                         self.theme)

    def test_home_list_left_right_pages_and_shoulders_own_categories(self):
        self.assertIn("function stepHomeListPage(direction)", self.theme)
        self.assertIn("api.keys.isPrevPage(event)", self.theme)
        self.assertIn("cycleHomeListCategory(-1)", self.theme)
        self.assertIn("cycleHomeListCategory(1)", self.theme)
        self.assertIn("event.key === Qt.Key_Left) {\n                    stepHomeListPage(-1)",
                      self.theme)
        self.assertIn("event.key === Qt.Key_Right) {\n                    stepHomeListPage(1)",
                      self.theme)

    def test_all_system_tabs_keep_box_art_reservation(self):
        self.assertIn("id: homeCategoryTabs", self.theme)
        self.assertIn("homeListBoxArt.x - homeListPanel.x", self.theme)
        self.assertIn("width: (homeCategoryTabs.width - 36) / 7", self.theme)

    def test_right_stick_and_optional_transitions_are_configured(self):
        self.assertIn("property bool rightStickViewSwitchingEnabled: true", self.theme)
        self.assertIn("property bool viewTransitionsEnabled: false", self.theme)
        for key in ("Qt.Key_F1", "Qt.Key_F2", "Qt.Key_F3", "Qt.Key_F4"):
            self.assertIn(key, self.theme)
        self.assertIn('"RIGHT STICK VIEW SWITCHING"', self.theme)
        self.assertIn('"VIEW TRANSITIONS"', self.theme)

    def test_settings_are_paginated(self):
        # The page size is no longer a constant 6: it is whatever the panel
        # actually holds, so reclaimed height becomes another row rather than a
        # band under the last one. The paging contract itself is unchanged.
        self.assertIn("readonly property int settingsPageSize:", self.theme)
        self.assertIn("listRowCount(settingsListAvailable, 102, settingsListSpacing)",
                      self.theme)
        self.assertIn("listRowHeight(settingsListAvailable, 102, 132, settingsListSpacing)",
                      self.theme)
        self.assertIn("Math.ceil(root.settingsOptionCount / root.settingsPageSize)", self.theme)
        self.assertIn('"PAGE " + (root.settingsPage + 1)', self.theme)

    def test_settings_rows_use_the_shared_list_helpers(self):
        # Hand-rolled arithmetic is what left the old 132px stride ending
        # short of the panel floor; the row stride must come from the helpers.
        self.assertIn(
            "y: root.settingsListTop +\n                       index * "
            "(root.settingsRowHeight + root.settingsListSpacing)", self.theme)
        self.assertIn("height: root.settingsRowHeight", self.theme)

    def test_qt_launcher_is_patched_in_place_not_subclassed(self):
        self.assertNotIn("LucentMainActivity", self.build)
        self.assertIn("patch_main_activity_right_stick.py", self.build)
        self.assertFalse((ROOT / "unified-android" / "src" / "com" / "thorium" /
                          "preview" / "LucentMainActivity.java").exists())

    def test_launch_persists_the_complete_navigation_tuple_before_gameplay(self):
        launch = self.theme.split("function launch(game) {", 1)[1].split(
            "function scheduleNavigationPersistence()", 1)[0]
        self.assertIn("navigationPersistence.stop()", launch)
        for key, value in (
            ("thoriumSystem", 'page === "games" ? activeSystemIndex : systemRail.currentIndex'),
            ("thoriumGame", "gameRail.currentIndex"),
            ("thoriumPage", "page"),
            ("thoriumSortMode", "sortMode"),
            ("thoriumGameView", "gameViewMode"),
            ("thoriumHomeView", "homeViewMode"),
        ):
            self.assertIn(f'api.memory.set("{key}", {value})', launch)
        self.assertLess(launch.index('api.memory.set("thoriumSortMode"'),
                        launch.index("game.launch()"))


if __name__ == "__main__":
    unittest.main()
