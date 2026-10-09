import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GAME = ROOT / "unified-android" / "src" / "com" / "thorium" / "preview" / "game"
HOST = GAME / "InWindowGameHost.java"
SESSION = GAME / "EngineSession.java"
LIBRETRO_SESSION = GAME / "LibretroEngineSession.java"
PPSSPP_SESSION = GAME / "PpssppGlesEngineSession.java"


def method_body(source: str, signature: str) -> str:
    """Returns the braced body of the first method whose header contains it."""
    start = source.index(signature)
    opening = source.index("{", start)
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[opening:index + 1]
    raise AssertionError(f"unbalanced braces after {signature!r}")


class ResetComboSemanticsTest(unittest.TestCase):
    """Select+Start held for two seconds resets the running game.

    The combo shares its two buttons with behaviour that already exists —
    Select taps through to the core and Select held for one second exits to the
    library — so these tests pin the interaction between them, not just the
    presence of the new code.
    """

    def setUp(self):
        self.source = HOST.read_text(encoding="utf-8")
        self.stop = method_body(self.source, "private boolean handleStopButton")
        self.start = method_body(self.source, "private boolean handleStartButton")
        self.arm = method_body(self.source, "private void armResetCombo")
        self.fire = method_body(self.source, "private void fireResetCombo")

    def test_combo_fires_after_two_seconds_of_both_buttons(self):
        # Two seconds: three felt like the game had hung rather than reset.
        self.assertIn("RESET_COMBO_HOLD_MS = 2000L", self.source)
        # The reset itself must never run on the UI thread; doing so
        # blocked on the engine lock and looked exactly like a freeze.
        self.assertIn("RETIREMENT_RELEASES.execute", self.source)
        self.assertIn("mainHandler.postDelayed", self.arm)
        self.assertIn("RESET_COMBO_HOLD_MS);", self.arm)
        self.assertIn("fireResetCombo();", self.arm)
        # Both buttons must still be physically down when the timer lands.
        self.assertIn("!stopPressed", self.arm)
        self.assertIn("!startPressed", self.arm)
        self.assertIn("target.reset()", self.fire)
        self.assertIn("marker=reset-combo", self.fire)

    def test_releasing_either_button_early_cancels_the_countdown(self):
        # The generation counter is the cancellation mechanism, exactly as it
        # is for the Stop hold: a stale callback compares unequal and returns.
        self.assertIn("generation != resetGeneration", self.arm)
        self.assertIn("final long generation = ++resetGeneration;", self.arm)
        release_paths = 0
        for body in (self.stop, self.start):
            up = body.split("KeyEvent.ACTION_UP", 1)[1]
            if "++resetGeneration;" in up:
                release_paths += 1
        self.assertEqual(release_paths, 2,
                         "both Select and Start releases must retire the combo")

    def test_the_one_second_stop_hold_cannot_win_the_three_second_combo(self):
        # Arming the combo retires the pending exit generation; otherwise
        # held-Select would return to the library a third of the way through.
        armed_by_select = self.stop.split("if (startPressed)", 1)[1]
        self.assertIn("++stopGeneration;", armed_by_select)
        self.assertIn("armResetCombo();", armed_by_select)
        armed_by_start = self.start.split("if (stopPressed)", 1)[1]
        self.assertIn("++stopGeneration;", armed_by_start)
        self.assertIn("armResetCombo();", armed_by_start)
        # And the exit hold itself is untouched when Start is not involved.
        self.assertIn("exitToLibrary(\"thor-stop-hold\")", self.stop)
        self.assertIn("STOP_HOLD_MS);", self.stop)

    def test_a_normal_start_press_still_reaches_the_game(self):
        # Start pressed on its own keeps its hold semantics: it is delivered on
        # the way down and released on the way up, not replayed as a tap.
        down = self.start.split("KeyEvent.ACTION_DOWN", 1)[1].split(
            "KeyEvent.ACTION_UP", 1)[0]
        self.assertIn("startDeliveredToGame = true;", down)
        self.assertIn("return deliverToSession(event);", down)
        up = self.start.split("KeyEvent.ACTION_UP", 1)[1]
        self.assertIn("if (startDeliveredToGame)", up)
        self.assertIn("return deliverToSession(event);", up)

    def test_a_withheld_start_press_is_replayed_when_the_combo_does_not_fire(self):
        up = self.start.split("KeyEvent.ACTION_UP", 1)[1]
        self.assertIn("if (startWithheldForCombo) latchTapToSession(event);", up)
        latch = method_body(self.source, "private void latchTapToSession")
        self.assertIn("KeyEvent.ACTION_DOWN", latch)
        self.assertIn("TAP_SELECT_HOLD_MS);", latch)

    def test_an_unowned_start_release_cannot_synthesize_a_start_tap(self):
        down = self.start.split("KeyEvent.ACTION_DOWN", 1)[1].split(
            "KeyEvent.ACTION_UP", 1)[0]
        self.assertIn("startWithheldForCombo = true;", down)
        self.assertIn("startWithheldForCombo = false;", down)
        up = self.start.split("KeyEvent.ACTION_UP", 1)[1]
        self.assertIn("if (startWithheldForCombo) latchTapToSession(event);", up)
        self.assertIn("startWithheldForCombo = false;", up)

    def test_select_keeps_its_existing_tap_and_hold_behaviour(self):
        up = self.stop.split("KeyEvent.ACTION_UP", 1)[1]
        self.assertIn("if (!stopHoldTriggered) latchTapToSession(event);", up)

    def test_a_fired_combo_leaks_neither_button_to_the_game(self):
        self.assertIn("comboConsumedSelect = true;", self.fire)
        self.assertIn("comboConsumedStart = true;", self.fire)
        # Start may already be down in the core when Start was pressed first;
        # the combo takes that press back rather than leaving the bit stuck.
        self.assertIn("releaseLeakedStartPress();", self.fire)
        release = method_body(self.source, "private void releaseLeakedStartPress")
        self.assertIn("KeyEvent.ACTION_UP", release)
        self.assertIn("down.getDeviceId()", release)
        select_up = self.stop.split("KeyEvent.ACTION_UP", 1)[1]
        consumed = select_up.split("if (comboConsumedSelect)", 1)[1]
        self.assertNotIn("latchTapToSession", consumed.split("}", 1)[0])
        start_up = self.start.split("KeyEvent.ACTION_UP", 1)[1]
        self.assertIn("if (comboConsumedStart)", start_up)

    def test_the_combo_is_inert_outside_live_gameplay(self):
        self.assertIn("menuVisible", self.arm)
        self.assertIn("fatalErrorVisible", self.arm)
        self.assertIn("exitStarted.get()", self.arm)
        # The pause menu takes the buttons over, so opening it drops the combo
        # instead of leaving a countdown running behind the overlay.
        show = method_body(self.source, "private void showPauseMenu")
        self.assertIn("cancelResetCombo();", show)

    def test_start_is_only_intercepted_during_gameplay(self):
        handle = method_body(self.source, "private boolean handleKeyEvent")
        menu_index = handle.index("if (menuVisible)")
        start_index = handle.index("KeyEvent.KEYCODE_BUTTON_START")
        self.assertGreater(start_index, menu_index,
                           "Start must fall through to the pause-menu handler")

    def test_libretro_logs_the_aggregate_start_boundary(self):
        libretro = LIBRETRO_SESSION.read_text(encoding="utf-8")
        self.assertIn("if (retroId == 3)", libretro)
        self.assertIn("Joypad aggregate Start transition", libretro)

    def test_reset_is_a_fail_closed_engine_capability(self):
        interface = SESSION.read_text(encoding="utf-8")
        self.assertIn("default boolean reset() { return false; }", interface)
        libretro = LIBRETRO_SESSION.read_text(encoding="utf-8")
        self.assertIn("@Override public boolean reset()", libretro)
        # The software session now power-cycles through libretro's own
        # retro_reset rather than an unload/reload pair.
        body = method_body(libretro, "@Override public boolean reset()")
        self.assertIn("open.reset();", body)
        self.assertNotIn("open.unloadGame();", body)
        self.assertIn("persistSaveRam(open);", body)
        # A soft reset is the console's reset button: the core keeps its
        # battery SRAM, so pushing the disk copy back would roll play back.
        self.assertNotIn("restoreSaveRam(", body)
        self.assertIn("flushAudioAfterRestore();", body)
        self.assertIn("marker=reset", body)
        # No frame may observe a half-reset core; the host's own methods
        # synchronize on the same monitor held here.
        self.assertIn("synchronized (open)", body)
        # A core without a usable retro_reset still gets a power cycle.
        self.assertIn("reloadAsReset(open, launch, failure);", body)
        fallback = method_body(libretro, "private void reloadAsReset(")
        self.assertIn("open.unloadGame();", fallback)
        self.assertIn("open.loadGame(game);", fallback)
        # Unloading destroys core memory, so this path does restore SRAM and
        # does reattach the port device that loading reset to a RetroPad.
        self.assertIn("restoreSaveRam(open, saveRamFile);", fallback)
        self.assertIn("open.setControllerPortDevice(0, portDevice);", fallback)
        self.assertIn("marker=reset-failure", fallback)
        hardware = PPSSPP_SESSION.read_text(encoding="utf-8")
        hardware_body = method_body(hardware, "@Override public boolean reset()")
        # The hardware session no longer fails unconditionally: it reaches
        # retro_reset through the render loop and reports honestly.
        self.assertIn("active.reset();", hardware_body)
        self.assertIn("marker=reset-failure", hardware_body)
        self.assertIn("marker=reset", hardware_body)
        self.assertIn("return true;", hardware_body)
        # reset-unavailable survives only as the not-prepared guard.
        unavailable = hardware_body.split("marker=reset-unavailable", 1)[0]
        self.assertIn("!prepared || active == null", unavailable)

    def test_the_host_reports_whether_the_reset_actually_happened(self):
        self.assertRegex(self.fire, re.compile(r"applied=\"\s*\+\s*applied"))


if __name__ == "__main__":
    unittest.main()
