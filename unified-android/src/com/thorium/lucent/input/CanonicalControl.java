package com.thorium.lucent.input;

/** EmuFusion's only public controller vocabulary; engines translate from this. */
public enum CanonicalControl {
    DPAD_UP, DPAD_DOWN, DPAD_LEFT, DPAD_RIGHT,
    SOUTH, EAST, WEST, NORTH,
    L1, R1, L2, R2, L3, R3,
    START, SELECT, GUIDE,
    LEFT_X_NEGATIVE, LEFT_X_POSITIVE, LEFT_Y_NEGATIVE, LEFT_Y_POSITIVE,
    RIGHT_X_NEGATIVE, RIGHT_X_POSITIVE, RIGHT_Y_NEGATIVE, RIGHT_Y_POSITIVE,
    TOUCH_PRIMARY, MOTION
}
