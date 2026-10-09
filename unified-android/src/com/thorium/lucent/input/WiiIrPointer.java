package com.thorium.lucent.input;

/**
 * Absolute Wii IR cursor driven by the physical right stick.
 *
 * <p>The session continues to send the same stick as libretro analog index 1,
 * because Dolphin uses that channel for Wiimote tilt in pointer-backed IR mode.
 * This class only mirrors it into the independent libretro pointer device and
 * carries A's contact state; it never consumes or remaps the analog signal.</p>
 */
public final class WiiIrPointer {
    public static final class State {
        public final short x;
        public final short y;
        public final boolean pressed;

        private State(short x, short y, boolean pressed) {
            this.x = x;
            this.y = y;
            this.pressed = pressed;
        }
    }

    private short x;
    private short y;
    private boolean pressed;

    /** Maps the spring-centred right stick over the complete IR plane. */
    public State move(float rightX, float rightY) {
        x = coordinate(rightX);
        y = coordinate(rightY);
        return state();
    }

    /** Mirrors the mapped Wii A button as pointer contact without moving it. */
    public State setPressed(boolean value) {
        pressed = value;
        return state();
    }

    public State state() {
        return new State(x, y, pressed);
    }

    private static short coordinate(float value) {
        if (Float.isNaN(value)) value = 0f;
        float clamped = Math.max(-1f, Math.min(1f, value));
        return clamped <= -1f ? Short.MIN_VALUE
                : (short)Math.round(clamped * Short.MAX_VALUE);
    }
}
