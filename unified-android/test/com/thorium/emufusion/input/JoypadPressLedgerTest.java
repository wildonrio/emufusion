package com.thorium.emufusion.input;

import com.thorium.emufusion.TestSupport;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

/**
 * Reproduces the reported Thor failure — "up/down works on the stick but not
 * left/right, left/right works on the D-pad but not up/down" — and proves the
 * ledger fixes it.
 *
 * <p>The Thor's hat is ABS_HAT0X/ABS_HAT0Y, so the D-pad and the left stick
 * both arrive as axes inside the same MotionEvent, and both resolve to libretro
 * IDs 4-7 on a D-pad-only console. The engine used to sweep every axis on the
 * device and write each result straight to setJoypadButton, so whichever axis
 * the sweep visited last won. The sweep order came from a HashSet of Android
 * axis codes, which for the Thor's axis set visits AXIS_X(0) before
 * AXIS_HAT_X(15) but AXIS_HAT_Y(16) before AXIS_Y(1) — the hat won horizontally
 * and the stick won vertically, exactly the reported half-dead behaviour.
 */
public final class JoypadPressLedgerTest {
    private static final int UP = 4, DOWN = 5, LEFT = 6, RIGHT = 7;

    public static void main(String[] args) {
        holdSurvivesTheOtherSourceCentring("snes");
        holdSurvivesTheOtherSourceCentring("genesis");
        theThorAxisSweepOrderNoLongerDecidesTheWinner("snes");
        theThorAxisSweepOrderNoLongerDecidesTheWinner("genesis");
        releasedOnlyWhenEveryHolderLetsGo();
        unheldReleasesNeverClearAnotherSource();
        remappedSourceReleasesItsOldId();
        virtualControlsShareTheLedgerWithoutColliding();
        System.out.println("JoypadPressLedgerTest passed");
    }

    /** A held hat direction must survive the stick returning to centre. */
    private static void holdSurvivesTheOtherSourceCentring(String system) {
        int left = LibretroJoypadLayout.idFor(system, CanonicalControl.DPAD_LEFT);
        int stickLeft = LibretroJoypadLayout.idFor(system, CanonicalControl.LEFT_X_NEGATIVE);
        TestSupport.equal(left, stickLeft,
                system + " routes the left stick onto the D-pad, so both share one ID");

        Recorder sink = new Recorder();
        JoypadPressLedger ledger = new JoypadPressLedger();
        InputSignal hat = InputSignal.axis(AndroidInputCodes.AXIS_HAT_X, -1);
        InputSignal stick = InputSignal.axis(AndroidInputCodes.AXIS_X, -1);

        ledger.apply(hat, left, true, sink);
        ledger.apply(stick, stickLeft, false, sink);
        TestSupport.truth(ledger.isPressed(left),
                system + " keeps a held D-pad direction when the stick is centred");

        // ...and the mirror case: a held stick survives the hat centring.
        int up = LibretroJoypadLayout.idFor(system, CanonicalControl.DPAD_UP);
        int stickUp = LibretroJoypadLayout.idFor(system, CanonicalControl.LEFT_Y_NEGATIVE);
        ledger.apply(InputSignal.axis(AndroidInputCodes.AXIS_Y, -1), stickUp, true, sink);
        ledger.apply(InputSignal.axis(AndroidInputCodes.AXIS_HAT_Y, -1), up, false, sink);
        TestSupport.truth(ledger.isPressed(up),
                system + " keeps a held stick direction when the hat is centred");
    }

    /**
     * Replays one MotionEvent in the order a HashSet of the Thor's axis codes
     * actually iterates, with the hat held left and the stick pushed up. Both
     * directions must be asserted no matter where in that order they land.
     */
    private static void theThorAxisSweepOrderNoLongerDecidesTheWinner(String system) {
        Recorder sink = new Recorder();
        JoypadPressLedger ledger = new JoypadPressLedger();
        for (int axis : thorAxisSweepOrder()) {
            boolean hatHeldLeft = axis == AndroidInputCodes.AXIS_HAT_X;
            boolean stickPushedUp = axis == AndroidInputCodes.AXIS_Y;
            dispatch(ledger, sink, system, axis, -1, hatHeldLeft || stickPushedUp);
            dispatch(ledger, sink, system, axis, 1, false);
        }
        TestSupport.truth(ledger.isPressed(LEFT),
                system + " hat-left survives the whole axis sweep");
        TestSupport.truth(ledger.isPressed(UP),
                system + " stick-up survives the whole axis sweep");
        TestSupport.truth(!ledger.isPressed(RIGHT), system + " right is not asserted");
        TestSupport.truth(!ledger.isPressed(DOWN), system + " down is not asserted");
        TestSupport.equal(2, sink.presses.size(),
                system + " presses one ID per asserted direction and nothing else");
    }

    /**
     * Exactly the iteration order java.util.HashSet produces for the Thor's
     * axis codes: a 16-bucket table indexed by the Integer's own value, so 16
     * and 17 share buckets with 0 and 1 and are visited right after them.
     */
    private static List<Integer> thorAxisSweepOrder() {
        Set<Integer> axes = new LinkedHashSet<>(Arrays.asList(
                AndroidInputCodes.AXIS_X, AndroidInputCodes.AXIS_Y,
                AndroidInputCodes.AXIS_Z, AndroidInputCodes.AXIS_RZ,
                AndroidInputCodes.AXIS_HAT_X, AndroidInputCodes.AXIS_HAT_Y,
                AndroidInputCodes.AXIS_LTRIGGER, AndroidInputCodes.AXIS_RTRIGGER));
        List<Integer> order = new ArrayList<>();
        for (int bucket = 0; bucket < 16; bucket++)
            for (int axis : axes) if ((axis & 15) == bucket) order.add(axis);
        TestSupport.equal(AndroidInputCodes.AXIS_HAT_Y, (int) order.get(1),
                "the hat's vertical axis is swept before the stick's");
        TestSupport.equal(AndroidInputCodes.AXIS_HAT_X, (int) order.get(order.size() - 1),
                "the hat's horizontal axis is swept after the stick's");
        return order;
    }

    private static void dispatch(JoypadPressLedger ledger, Recorder sink, String system,
            int axis, int direction, boolean pressed) {
        CanonicalControl control = axisControl(axis, direction);
        int id = LibretroJoypadLayout.idFor(system, control);
        if (id < 0) return;
        ledger.apply(InputSignal.axis(axis, direction), id, pressed, sink);
    }

    private static CanonicalControl axisControl(int axis, int direction) {
        if (axis == AndroidInputCodes.AXIS_HAT_X)
            return direction < 0 ? CanonicalControl.DPAD_LEFT : CanonicalControl.DPAD_RIGHT;
        if (axis == AndroidInputCodes.AXIS_HAT_Y)
            return direction < 0 ? CanonicalControl.DPAD_UP : CanonicalControl.DPAD_DOWN;
        if (axis == AndroidInputCodes.AXIS_X)
            return direction < 0 ? CanonicalControl.LEFT_X_NEGATIVE
                    : CanonicalControl.LEFT_X_POSITIVE;
        if (axis == AndroidInputCodes.AXIS_Y)
            return direction < 0 ? CanonicalControl.LEFT_Y_NEGATIVE
                    : CanonicalControl.LEFT_Y_POSITIVE;
        return null;
    }

    private static void releasedOnlyWhenEveryHolderLetsGo() {
        Recorder sink = new Recorder();
        JoypadPressLedger ledger = new JoypadPressLedger();
        InputSignal hat = InputSignal.axis(AndroidInputCodes.AXIS_HAT_X, -1);
        InputSignal stick = InputSignal.axis(AndroidInputCodes.AXIS_X, -1);
        InputSignal key = InputSignal.key(AndroidInputCodes.DPAD_LEFT);
        ledger.apply(hat, LEFT, true, sink);
        ledger.apply(stick, LEFT, true, sink);
        ledger.apply(key, LEFT, true, sink);
        TestSupport.equal(3, ledger.holderCount(LEFT), "three sources hold one direction");
        TestSupport.equal(1, sink.presses.size(), "the core sees one press, not three");
        ledger.apply(hat, LEFT, false, sink);
        ledger.apply(key, LEFT, false, sink);
        TestSupport.truth(ledger.isPressed(LEFT), "still held by the remaining source");
        TestSupport.equal(0, sink.releases.size(), "no release while a source still holds it");
        ledger.apply(stick, LEFT, false, sink);
        TestSupport.truth(!ledger.isPressed(LEFT), "released once the last source lets go");
        TestSupport.equal(1, sink.releases.size(), "and exactly one release reaches the core");
    }

    private static void unheldReleasesNeverClearAnotherSource() {
        Recorder sink = new Recorder();
        JoypadPressLedger ledger = new JoypadPressLedger();
        ledger.apply(InputSignal.axis(AndroidInputCodes.AXIS_HAT_X, -1), LEFT, true, sink);
        // The motion sweep reports every axis on every event, so the stick's
        // idle "not pressed" arrives constantly. It must be inert.
        for (int i = 0; i < 5; i++)
            ledger.apply(InputSignal.axis(AndroidInputCodes.AXIS_X, -1), LEFT, false, sink);
        TestSupport.truth(ledger.isPressed(LEFT), "idle sources do not release a held ID");
        TestSupport.equal(0, sink.releases.size(), "and produce no core traffic at all");
    }

    private static void remappedSourceReleasesItsOldId() {
        Recorder sink = new Recorder();
        JoypadPressLedger ledger = new JoypadPressLedger();
        InputSignal button = InputSignal.key(AndroidInputCodes.BUTTON_A);
        ledger.apply(button, 8, true, sink);
        ledger.apply(button, 0, true, sink);
        TestSupport.truth(!ledger.isPressed(8), "a remap frees the ID the source used to hold");
        TestSupport.truth(ledger.isPressed(0), "and asserts the new one");
    }

    private static void virtualControlsShareTheLedgerWithoutColliding() {
        Recorder sink = new Recorder();
        JoypadPressLedger ledger = new JoypadPressLedger();
        ledger.apply(CanonicalControl.DPAD_LEFT, LEFT, true, sink);
        ledger.apply(InputSignal.axis(AndroidInputCodes.AXIS_HAT_X, -1), LEFT, true, sink);
        TestSupport.equal(2, ledger.holderCount(LEFT),
                "on-screen and physical controls are separate sources");
        ledger.apply(CanonicalControl.DPAD_LEFT, LEFT, false, sink);
        TestSupport.truth(ledger.isPressed(LEFT),
                "lifting a finger does not release the physical hat");
        ledger.releaseAll(sink);
        TestSupport.truth(!ledger.isPressed(LEFT), "releaseAll clears every holder");
    }

    private static final class Recorder implements JoypadPressLedger.Sink {
        final List<Integer> presses = new ArrayList<>();
        final List<Integer> releases = new ArrayList<>();

        @Override public void setJoypadButton(int retroId, boolean pressed) {
            (pressed ? presses : releases).add(retroId);
        }
    }
}
