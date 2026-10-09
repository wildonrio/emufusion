package com.thorium.lucent.input;

import com.thorium.lucent.TestSupport;

public final class WiiIrPointerTest {
    public static void main(String[] ignored) {
        mapsTheCompleteIrPlaneWithoutStretchingAnAxis();
        aClickDoesNotMoveOrConsumeTheCursor();
        clampsBadPhysicalValues();
        System.out.println("WiiIrPointerTest passed");
    }

    private static void mapsTheCompleteIrPlaneWithoutStretchingAnAxis() {
        WiiIrPointer pointer = new WiiIrPointer();
        WiiIrPointer.State center = pointer.move(0f, 0f);
        TestSupport.equal((short)0, center.x, "neutral right X is IR center");
        TestSupport.equal((short)0, center.y, "neutral right Y is IR center");
        WiiIrPointer.State corners = pointer.move(-1f, 1f);
        TestSupport.equal(Short.MIN_VALUE, corners.x, "left reaches IR minimum");
        TestSupport.equal(Short.MAX_VALUE, corners.y, "down reaches IR maximum");
    }

    private static void aClickDoesNotMoveOrConsumeTheCursor() {
        WiiIrPointer pointer = new WiiIrPointer();
        WiiIrPointer.State aimed = pointer.move(0.5f, -0.25f);
        WiiIrPointer.State down = pointer.setPressed(true);
        TestSupport.equal(aimed.x, down.x, "A down preserves IR X");
        TestSupport.equal(aimed.y, down.y, "A down preserves IR Y");
        TestSupport.truth(down.pressed, "A down presses pointer contact");
        WiiIrPointer.State up = pointer.setPressed(false);
        TestSupport.truth(!up.pressed, "A up releases pointer contact");
    }

    private static void clampsBadPhysicalValues() {
        WiiIrPointer pointer = new WiiIrPointer();
        WiiIrPointer.State state = pointer.move(Float.NaN, 4f);
        TestSupport.equal((short)0, state.x, "NaN becomes neutral");
        TestSupport.equal(Short.MAX_VALUE, state.y, "overshoot clamps high");
    }
}
