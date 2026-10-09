"""Cheats have to be reachable *while the game runs*, on the Thor's lower screen.

The pre-launch cheats row in the theme and the pause-menu sheet both existed
before this, and both stop the game to show a list. What the feature is actually
for is switching a cheat and watching it take effect, which means the game keeps
running on the upper display while the list is drawn on the lower one.

Three things make that work and none of them are visible from the outside, so
they are pinned here:

* the lower-display window is `FLAG_NOT_FOCUSABLE` and must stay that way, or it
  takes the pad away from the game the moment it appears. It therefore cannot
  receive a key event at all: the pad is read by the game host on the primary
  display, which moves the selection and republishes a snapshot. The panel
  paints its own highlight rather than using Android focus.
* the chord that opens it is Select + L1, and Select already carries two
  countdowns — 1 s to Stop, 2 s with Start to reset. Both have to be retired
  when the chord lands or browsing a cheat list exits the game.
* display 4 is not always free. A DS/3DS/Wii U session is already rendering its
  second screen there, and a single-screen device has no display 4 at all. Both
  fall back to the in-window sheet rather than losing the feature.
"""

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMPANION = ROOT / "android-companion" / "src" / "com" / "thorium" / "preview"
PREVIEW_ACTIVITY = COMPANION / "PreviewActivity.java"
ROUTER = COMPANION / "SecondaryCheatPanelRouter.java"
GAMEPLAY_ROUTER = COMPANION / "SecondaryGameplaySurfaceRouter.java"
UNIFIED = ROOT / "unified-android" / "src" / "com" / "thorium"
HOST = UNIFIED / "preview" / "game" / "InWindowGameHost.java"
PANEL_VIEW = UNIFIED / "preview" / "cheats" / "CheatPanelView.java"
MODEL = UNIFIED / "lucent" / "cheats" / "CheatPanelModel.java"
SNAPSHOT = UNIFIED / "lucent" / "cheats" / "CheatPanelSnapshot.java"
TEST_RUNNER = ROOT / "unified-android" / "test.sh"
DOC = ROOT / "docs" / "controller-mapping.md"


def body(source: str, start: str, end: str) -> str:
    """The text between two anchors, so a test reads one method, not a file."""
    assert start in source, f"missing anchor {start!r}"
    remainder = source.split(start, 1)[1]
    assert end in remainder, f"missing anchor {end!r} after {start!r}"
    return remainder.split(end, 1)[0]


class ChordTests(unittest.TestCase):
    """Select + L1, and what it has to take back from the two countdowns."""

    def setUp(self):
        self.source = HOST.read_text(encoding="utf-8")

    def test_l1_is_routed_before_the_open_sheets_can_swallow_it(self):
        # The same chord closes the panel it opened. Handled after the
        # cheatsVisible branch it would never be seen while the panel was up.
        dispatch = body(self.source, "private boolean handleKeyEvent(KeyEvent event)",
                        "private boolean handleMotionEvent")
        self.assertIn("KeyEvent.KEYCODE_BUTTON_L1", dispatch)
        # The bare "if (cheatsVisible)" also appears in the Back handler above,
        # so the branch itself is anchored on its brace.
        self.assertLess(dispatch.index("KEYCODE_BUTTON_L1"),
                        dispatch.index("if (cheatsVisible) {"),
                        "L1 must be routed before the cheats sheet swallows keys")
        self.assertLess(dispatch.index("KEYCODE_BUTTON_L1"),
                        dispatch.index("if (menuVisible) {"),
                        "L1 must be routed before the pause menu swallows keys")

    def test_the_chord_only_fires_while_select_is_held(self):
        chord = body(self.source, "private boolean handleCheatsChord(KeyEvent event)",
                     "\n    /**")
        self.assertIn("if (stopPressed && event.getRepeatCount() == 0)", chord,
                      "a bare L1 belongs to the game, not to EmuFusion")
        self.assertIn("deliverToSession(event)", chord,
                      "an unmodified L1 has to reach the core")

    def test_the_chord_retires_the_stop_hold_and_the_reset_countdown(self):
        chord = body(self.source, "private boolean handleCheatsChord(KeyEvent event)",
                     "\n    /**")
        # Without these, holding Select to read the list exits to the library
        # after one second, or resets the game after two.
        self.assertIn("++stopGeneration;", chord)
        self.assertIn("++resetGeneration;", chord)
        self.assertIn("comboConsumedSelect = true;", chord,
                      "Select was spent on the chord and must not replay as a tap")

    def test_the_consumed_l1_press_never_reaches_the_game(self):
        chord = body(self.source, "private boolean handleCheatsChord(KeyEvent event)",
                     "\n    /**")
        self.assertIn("cheatChordArmed = true;", chord)
        self.assertIn("if (cheatChordArmed && event.getRepeatCount() != 0) return true;",
                      chord, "the auto-repeat of a spent press is not an L1 press")
        # Cleared on a fresh press as well as on the release: a release lost to
        # a focus change would otherwise swallow L1 for the rest of the session.
        self.assertEqual(2, chord.count("cheatChordArmed = false;"),
                         "the arm must be cleared on the release and on a fresh press")

    def test_the_chord_toggles_rather_than_only_opening(self):
        chord = body(self.source, "private boolean handleCheatsChord(KeyEvent event)",
                     "\n    /**")
        self.assertIn("if (cheatsVisible) hideCheatsPanel();", chord)
        self.assertIn("else showCheatsPanel();", chord)

    def test_the_binding_is_documented_where_the_others_are(self):
        doc = DOC.read_text(encoding="utf-8")
        self.assertIn("Select + L1", doc, "the chord has to be findable")
        self.assertIn("lower display", doc)


class LowerDisplayPreferenceTests(unittest.TestCase):
    """Below when there is a screen for it; in-window when there is not."""

    def setUp(self):
        self.source = HOST.read_text(encoding="utf-8")

    def test_the_lower_display_is_tried_first_and_the_sheet_is_the_fallback(self):
        show = body(self.source, "private void showCheatsPanel()",
                    "private void hideCheatsPanel()")
        self.assertIn("SecondaryCheatPanelRouter.request(", show)
        self.assertIn("if (!cheatsOnSecondDisplay) {", show,
                      "a refused lower display must fall back to the in-window sheet")
        self.assertIn("cheatOverlay.setVisibility(View.VISIBLE);", show)

    def test_the_game_is_never_paused_to_show_cheats(self):
        show = body(self.source, "private void showCheatsPanel()",
                    "private void hideCheatsPanel()")
        self.assertNotIn("session.pause(", show,
                         "the point of the panel is that the game keeps running")

    def test_closing_releases_the_lower_display(self):
        hide = body(self.source, "private void hideCheatsPanel()",
                    "private void buildCheatRows()")
        self.assertIn("SecondaryCheatPanelRouter.release(activity, this);", hide)
        self.assertIn("cheatsOnSecondDisplay = false;", hide)
        # Opened live there is no pause menu behind it to return to.
        self.assertIn("cheatsFromPauseMenu", hide)

    def test_every_way_out_of_a_game_takes_the_panel_with_it(self):
        for method, end in (("private void exitToLibrary(String reason)",
                             "private void returnToLibraryUi(long"),
                            ("private void replaceWith(GameLaunchRequest next)",
                             "private void buildUi()")):
            section = body(self.source, method, end)
            self.assertIn("hideCheatsPanel();", section,
                          f"{method} must not leave a dead game's cheats below")
        destroy = body(self.source, "private void destroyNow()",
                       "private void detachViewsAfterDestroyStop")
        self.assertIn("SecondaryCheatPanelRouter.release(activity, this);", destroy,
                      "a destroyed host must not stay registered with the router")

    def test_a_toggle_is_read_back_from_the_engine_not_assumed(self):
        toggle = body(self.source, "private void toggleCheat(int index)",
                      "/** Redraws whichever screen")
        self.assertIn("session.setCheatEnabled(", toggle)
        self.assertIn("cheatModel.setEnabledIds(session.enabledCheatIds());", toggle,
                      "a refused cheat must not leave the row showing ON")

    def test_a_touch_from_the_lower_display_is_bounced_onto_the_ui_thread(self):
        callback = body(self.source, "@Override public void onSecondaryCheatToggled",
                        "@Override public void onSecondaryCheatPanelClosed")
        self.assertIn("activity.runOnUiThread(", callback)
        self.assertIn("if (!cheatsVisible || !cheatsOnSecondDisplay) return;", callback,
                      "a late touch must not toggle a cheat after the panel closed")

    def test_a_game_with_no_cheats_still_answers_the_chord(self):
        rows = body(self.source, "private void buildCheatRows()",
                    "* Applies a toggle to the running game")
        self.assertIn("cheatModel.isEmpty()", rows,
                      "an empty list has to say so rather than draw nothing")
        dispatch = body(self.source, "private boolean handleKeyEvent(KeyEvent event)",
                        "private boolean handleMotionEvent")
        self.assertIn("if (cheatModel.isEmpty()) hideCheatsPanel();", dispatch,
                      "confirm on an empty panel closes it rather than trapping the pad")


class RouterTests(unittest.TestCase):
    """The half that addresses display 4."""

    def setUp(self):
        self.source = ROUTER.read_text(encoding="utf-8")

    def test_it_refuses_a_display_that_is_already_a_game_screen(self):
        available = body(self.source, "public static boolean available(Context context)",
                         "\n    /**")
        self.assertIn("BootReceiver.secondaryDisplayId(context) >= 0", available,
                      "a single-screen device has no display 4 to use")
        self.assertIn("!PreviewActivity.isGameplaySurfaceActive()", available,
                      "a DS/3DS/Wii U second screen must not be replaced by a menu")

    def test_it_addresses_display_four_the_same_way_the_gameplay_router_does(self):
        # Two different ways of reaching one display drift, and the failure mode
        # of the wrong one is a black lower screen with nothing in any log.
        gameplay = GAMEPLAY_ROUTER.read_text(encoding="utf-8")
        for shared in ("options.setLaunchDisplayId(",
                       "Settings.canDrawOverlays(context)",
                       "PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE",
                       "MODE_BACKGROUND_ACTIVITY_START_ALLOWED",
                       "Intent.FLAG_ACTIVITY_NEW_TASK |"):
            self.assertIn(shared, gameplay, f"the gameplay router lost {shared}")
            self.assertIn(shared, self.source, f"the cheat router must also do {shared}")

    def test_its_pending_intent_request_code_is_its_own(self):
        gameplay = GAMEPLAY_ROUTER.read_text(encoding="utf-8")
        mine = re.search(r"PendingIntent\.getActivity\(\s*\n?\s*context, (\d+)",
                         self.source)
        theirs = re.search(r"PendingIntent\.getActivity\(\s*\n?\s*context, (\d+)",
                           gameplay)
        self.assertIsNotNone(mine)
        self.assertIsNotNone(theirs)
        self.assertNotEqual(mine.group(1), theirs.group(1),
                            "FLAG_UPDATE_CURRENT would rewrite the other router's intent")

    def test_the_first_frame_is_not_blank(self):
        # The Activity attaches some frames after the launch, so the snapshot
        # handed to request() has to survive until then.
        request = body(self.source, "public static synchronized boolean request(",
                       "/** Redraws the lower display")
        self.assertIn("pending = snapshot;", request)
        attach = body(self.source, "static synchronized void attach(",
                      "static synchronized void detach(")
        self.assertIn("if (pending != null) next.showCheatPanel(pending);", attach)

    def test_a_stale_generation_cannot_resurrect_a_closed_panel(self):
        release = body(self.source, "public static synchronized void release(",
                       "static synchronized void attach(")
        self.assertIn("++generation;", release)
        attach = body(self.source, "static synchronized void attach(",
                      "static synchronized void detach(")
        self.assertIn("if (generation != candidate || controller == null)", attach)
        self.assertIn("next.hideCheatPanel();", attach)

    def test_a_touch_on_a_bounded_page_maps_back_to_the_global_row(self):
        view = PANEL_VIEW.read_text(encoding="utf-8")
        self.assertIn("pageFirstIndex = snapshot.firstIndex", view)
        self.assertIn("pageFirstIndex + tapped", view,
                      "page-local touches must not toggle a different global cheat")


class LowerDisplayViewTests(unittest.TestCase):
    """The panel itself, in a window that can never hold focus."""

    def test_the_preview_window_is_still_not_focusable(self):
        preview = PREVIEW_ACTIVITY.read_text(encoding="utf-8")
        self.assertIn("WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE", preview,
                      "the lower display must never take the pad from the game")

    def test_selection_is_painted_rather_than_focused(self):
        view = PANEL_VIEW.read_text(encoding="utf-8")
        self.assertNotIn(".requestFocus(", view,
                         "focus does nothing in a FLAG_NOT_FOCUSABLE window")
        self.assertIn("index == snapshot.selected", view,
                      "the highlight comes from the snapshot's index")
        self.assertIn("setBackground(background)", view)

    def test_rows_are_only_rebuilt_when_the_list_changes(self):
        view = PANEL_VIEW.read_text(encoding="utf-8")
        render = body(view, "public void render(CheatPanelSnapshot snapshot)",
                      "private void rebuild(")
        self.assertIn("if (rowViews.size() != snapshot.rows.size()) rebuild(snapshot);",
                      render,
                      "rebuilding on every D-pad step resets the scroll position")

    def test_the_activity_takes_the_panel_on_its_own_action(self):
        preview = PREVIEW_ACTIVITY.read_text(encoding="utf-8")
        self.assertEqual(
            2, preview.count("SecondaryCheatPanelRouter.ACTION_SECONDARY_CHEATS"),
            "the action must be handled from both onCreate and onNewIntent")
        self.assertIn("SecondaryCheatPanelRouter.detach(this);", preview,
                      "a destroyed Activity left registered swallows the next panel")

    def test_a_preview_selection_cannot_start_a_movie_under_the_panel(self):
        preview = PREVIEW_ACTIVITY.read_text(encoding="utf-8")
        selection = body(preview, "private void showSelection(", "leaveGameplaySurface(true);")
        self.assertIn("cheatPanel.getVisibility() == View.VISIBLE) return;", selection,
                      "audio from an invisible preview would play over the game")


class HostTestedModelTests(unittest.TestCase):
    """The selection logic is platform-neutral so it can be tested without a device."""

    def test_the_model_carries_no_android_dependency(self):
        for path in (MODEL, SNAPSHOT):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("import android.", source, f"{path.name} must stay host-testable")
            self.assertNotIn("import org.json.", source, f"{path.name} must stay host-testable")

    def test_the_host_suite_runs_the_panel_model_test(self):
        self.assertIn("com.thorium.lucent.cheats.CheatPanelModelTest",
                      TEST_RUNNER.read_text(encoding="utf-8"))

    def test_both_panels_label_a_row_from_one_place(self):
        host = HOST.read_text(encoding="utf-8")
        view = PANEL_VIEW.read_text(encoding="utf-8")
        self.assertIn("snapshot.rows.get(index).label()", host,
                      "the in-window sheet must borrow the snapshot's label")
        self.assertIn("entry.label()", view)
        self.assertEqual(1,
                         SNAPSHOT.read_text(encoding="utf-8").count('"ON" : "OFF"'),
                         "one place decides what a toggled row reads")

    def test_huge_catalogues_render_a_bounded_page(self):
        model = MODEL.read_text(encoding="utf-8")
        host = HOST.read_text(encoding="utf-8")
        self.assertIn("public static final int PAGE_SIZE = 96", model)
        self.assertIn("Math.min(cheats.size(), first + PAGE_SIZE)", model)
        self.assertIn("cheatRowsFirstIndex = snapshot.firstIndex", host)
        self.assertNotIn("index < cheatModel.size()", host,
                         "thirty thousand codes must not become thirty thousand Buttons")


if __name__ == "__main__":
    unittest.main()
