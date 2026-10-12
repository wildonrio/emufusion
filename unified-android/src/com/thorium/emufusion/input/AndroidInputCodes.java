package com.thorium.emufusion.input;

/** Stable Android KeyEvent/MotionEvent numeric constants without an Android dependency. */
public final class AndroidInputCodes {
    private AndroidInputCodes() {}
    public static final int DPAD_UP = 19, DPAD_DOWN = 20, DPAD_LEFT = 21, DPAD_RIGHT = 22;
    public static final int BUTTON_A = 96, BUTTON_B = 97, BUTTON_C = 98, BUTTON_X = 99;
    public static final int BUTTON_Y = 100, BUTTON_Z = 101, BUTTON_L1 = 102, BUTTON_R1 = 103;
    public static final int BUTTON_L2 = 104, BUTTON_R2 = 105, BUTTON_THUMBL = 106;
    public static final int BUTTON_THUMBR = 107, BUTTON_START = 108, BUTTON_SELECT = 109;
    public static final int BUTTON_MODE = 110;
    public static final int AXIS_X = 0, AXIS_Y = 1, AXIS_Z = 11, AXIS_RX = 12;
    public static final int AXIS_RY = 13, AXIS_RZ = 14, AXIS_HAT_X = 15, AXIS_HAT_Y = 16;
    public static final int AXIS_LTRIGGER = 17, AXIS_RTRIGGER = 18, AXIS_BRAKE = 23, AXIS_GAS = 22;
}
