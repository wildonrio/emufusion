"""The lower display must never keep Android's top focus away from the game.

Android chooses the top-focused display in `RootWindowContainer.updateFocused
WindowLocked` by walking displays from the top of the display order down and
taking the first one that has a focused window *or*, failing that, a focused
app. EmuFusion's display 4 satisfies only the second half, permanently:
`PreviewActivity` lives there, so the display always has an `mFocusedApp`, and
its window is `FLAG_NOT_FOCUSABLE`, so `mCurrentFocus` there is always null.

Every Activity start aimed at display 4 also moves that display to the top of
the display order, and it then claims top focus with nothing to dispatch to.
The Odin controller reports no display of its own, so Android routes its keys
to the top-focused display, finds no focusable window, and files

    ANR in com.thorium.preview (com.thorium.preview/.PreviewActivity)
    Reason: Input dispatching timed out (Application does not have a focused window)

five seconds later, while the running game never sees the press. Reproduced on
an AYN Thor from a single `adb shell input keyevent` with no game running.

Two mechanisms are pinned here and they are not interchangeable:

* the lower-display windows are handed over **in-process** while the Activity is
  resumed, so a game handing over its second screen, or opening the cheat panel,
  no longer starts an Activity on display 4 at all. Nothing re-tops that display
  mid-game.
* the starts that genuinely cannot be avoided — the boot-time preview, a restore
  after process death, the service's own watchdog — are followed by
  `PrimaryDisplayFocusGuard`, which hands the top-focused display back to
  display 0.

`FLAG_NOT_FOCUSABLE` stays on the lower window throughout. It is what stops a
GamePad touch pulling focus across displays, since Android only moves focus to a
tapped window that can receive keys, and touch dispatch never needs focus.
"""

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMPANION = ROOT / "android-companion" / "src" / "com" / "thorium" / "preview"
GUARD = COMPANION / "PrimaryDisplayFocusGuard.java"
PREVIEW_ACTIVITY = COMPANION / "PreviewActivity.java"
GAMEPLAY_ROUTER = COMPANION / "SecondaryGameplaySurfaceRouter.java"
CHEAT_ROUTER = COMPANION / "SecondaryCheatPanelRouter.java"


def read(path):
    return path.read_text(encoding="utf-8")


def code(source):
    """The source with comments removed, for "must never call X" assertions."""
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return re.sub(r"//[^\n]*", "", source)


def method(source, signature):
    """The body of one Java method, by its opening signature line."""
    start = source.index(signature)
    depth = 0
    for index in range(start, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    raise AssertionError(f"unterminated method: {signature}")


class PrimaryDisplayFocusGuardTests(unittest.TestCase):
    def setUp(self):
        self.source = read(GUARD)

    def test_it_targets_the_frontend_activity(self):
        self.assertIn('"org.pegasus_frontend.android.MainActivity"', self.source,
                      "the guard has to find the task that owns display 0")

    def test_it_moves_a_task_and_never_starts_an_activity(self):
        # MainActivity's onNewIntent hook calls setIntent, and while a game runs
        # the retained Intent is the LAUNCH_INTERNAL_GAME one that restores the
        # session if Android recreates the process. Re-topping display 0 must
        # not cost the player that, so no Intent may be delivered at all.
        body = code(self.source)
        self.assertIn(".moveToFront()", body)
        self.assertNotIn("startActivity", body)
        self.assertNotIn("new Intent(", body)

    def test_it_survives_having_no_frontend_task(self):
        # A boot-time preview launch happens before the frontend exists. That
        # is not a state where the lower display can take input from a game, so
        # it must not throw or log an error.
        restore = method(self.source,
                         "public static boolean restorePrimaryTopFocus(Context context)")
        self.assertIn("catch (RuntimeException", restore)
        self.assertIn("return false;", restore)


class PreviewActivityFocusTests(unittest.TestCase):
    def setUp(self):
        self.source = read(PREVIEW_ACTIVITY)

    def test_the_lower_window_stays_unfocusable(self):
        # Load-bearing for touch, not just for keys: Android only moves focus to
        # a tapped window that can receive keys, so a focusable lower window
        # would let every GamePad touch pull focus off the running game.
        self.assertIn(
            "getWindow().addFlags(WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE)",
            self.source)

    def test_it_hands_top_focus_back_after_every_start(self):
        resume = method(self.source, "protected void onResume()")
        self.assertIn("yieldTopFocusToPrimaryDisplay()", resume)
        # A redelivery to an already-resumed singleTop Activity skips onResume,
        # but the start that carried it still re-topped this display.
        new_intent = method(self.source, "protected void onNewIntent(Intent intent)")
        self.assertIn("yieldTopFocusToPrimaryDisplay()", new_intent)

    def test_the_retry_cannot_rob_the_browser_of_the_lower_display(self):
        # The in-app browser legitimately takes display 4 and its focus, and
        # pauses this Activity while it is open.
        yielded = method(self.source, "private void yieldTopFocusToPrimaryDisplay()")
        self.assertIn("PrimaryDisplayFocusGuard.restorePrimaryTopFocus(this)", yielded)
        self.assertIn("postDelayed(deferredFocusYield", yielded)
        deferred = self.source[self.source.index("deferredFocusYield = new Runnable"):]
        self.assertIn("if (!resumed || isFinishing()) return;", deferred)

    def test_it_offers_itself_to_the_routers_only_while_resumed(self):
        resume = method(self.source, "protected void onResume()")
        self.assertIn("SecondaryGameplaySurfaceRouter.attachHost(this)", resume)
        self.assertIn("SecondaryCheatPanelRouter.attachPanel(this)", resume)
        pause = method(self.source, "protected void onPause()")
        self.assertIn("SecondaryGameplaySurfaceRouter.detachHost(this)", pause)
        self.assertIn("SecondaryCheatPanelRouter.detach(this)", pause)
        destroy = method(self.source, "protected void onDestroy()")
        self.assertIn("SecondaryGameplaySurfaceRouter.detachHost(this)", destroy)

    def test_the_in_process_handover_reaches_the_ui_thread(self):
        # The engine asks from its own lifecycle thread.
        handover = method(
            self.source, "public void showSecondaryGameplaySurface(long generation)")
        self.assertIn("runOnUiThread", handover)
        self.assertIn("showGameplaySurface(generation)", handover)

    def test_the_second_screen_still_reports_touches(self):
        # A fix that keeps the pad on display 0 by killing GamePad touch is not
        # a fix. Touch dispatch does not need window focus, so this survives.
        self.assertIn("gameplaySurface.setOnTouchListener(", self.source)
        self.assertIn("SecondaryGameplaySurfaceRouter.touch(surfaceGeneration",
                      self.source)


class RouterHandoverTests(unittest.TestCase):
    def test_gameplay_prefers_the_resumed_activity_over_a_launch(self):
        source = read(GAMEPLAY_ROUTER)
        request = method(
            source,
            "public static synchronized boolean request(")
        handover = request.index("attached.showSecondaryGameplaySurface(")
        launch = request.index("new Intent(context, PreviewActivity.class)")
        self.assertLess(handover, launch,
                        "the Activity start must be the fallback, not the default")
        self.assertIn("Host attached = host;", request)

    def test_cheats_prefer_the_resumed_activity_over_a_launch(self):
        source = read(CHEAT_ROUTER)
        self.assertIn("static synchronized void attachPanel(Panel next)", source)
        request = method(
            source,
            "public static synchronized boolean request(")
        handover = request.index("panel.showCheatPanel(snapshot)")
        launch = request.index("new Intent(context, PreviewActivity.class)")
        self.assertLess(handover, launch)

    def test_both_routers_still_launch_onto_the_lower_display_when_they_must(self):
        for path in (GAMEPLAY_ROUTER, CHEAT_ROUTER):
            source = read(path)
            self.assertIn("options.setLaunchDisplayId(", source,
                          f"{path.name} lost its fallback Activity start")
            self.assertIsNotNone(
                re.search(r"Settings\.canDrawOverlays\(context\)", source),
                f"{path.name} lost its background-activity-start fork")


if __name__ == "__main__":
    unittest.main()
