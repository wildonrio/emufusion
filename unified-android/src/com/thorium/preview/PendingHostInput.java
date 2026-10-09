package com.thorium.preview;

/**
 * Most recent input and pause state requested for a software libretro host.
 *
 * <p>{@link LibretroHost} holds its monitor, and the native host mutex, for the
 * whole of retro_run. Touch, key and pause-menu callbacks arrive on the UI
 * thread; writing them straight through made each one wait for the frame in
 * progress, so a slow or wedged core turned the next touch into an Android ANR
 * and the pause menu could not open to leave it. Callers record the state here
 * under a lock that is never held across native code, and the frame thread
 * applies whatever changed immediately before its next retro_run.
 *
 * <p>Only the newest value of each control matters at a frame boundary: the
 * native host stores one joypad mask, one set of axis values and one pointer
 * per port, so applying the latest state is equivalent to applying every
 * intermediate write in order. Arguments are checked against the native bounds
 * here, so an invalid call still fails on the caller's thread rather than on
 * the frame thread.
 */
final class PendingHostInput {
    interface Sink {
        void joypadButton(int port, int button, boolean pressed);
        void analogAxis(int port, int index, int id, int value);
        void pointer(int port, int x, int y, boolean pressed);
        void paused(boolean paused);
    }

    // Mirrors MAX_PORTS, MAX_JOYPAD_BUTTONS, MAX_ANALOG_INDEXES and
    // MAX_ANALOG_IDS in native/lucent_libretro_host.c.
    static final int PORTS = 8;
    static final int JOYPAD_BUTTONS = 16;
    static final int ANALOG_INDEXES = 3;
    static final int ANALOG_IDS = 16;
    private static final int ANALOG_INDEX_BUTTON = 2;
    private static final int ANALOG_ID_Y = 1;

    private final Object lock = new Object();
    private final int[] requestedJoypad = new int[PORTS];
    private final short[][][] requestedAnalog = new short[PORTS][ANALOG_INDEXES][ANALOG_IDS];
    private final short[] requestedPointerX = new short[PORTS];
    private final short[] requestedPointerY = new short[PORTS];
    private final boolean[] requestedPointerPressed = new boolean[PORTS];
    private boolean requestedPaused;
    private boolean dirty;

    // Written only by applyTo(), which the frame thread calls with the host
    // monitor held; initial values match a freshly created native host.
    private final int[] appliedJoypad = new int[PORTS];
    private final short[][][] appliedAnalog = new short[PORTS][ANALOG_INDEXES][ANALOG_IDS];
    private final short[] appliedPointerX = new short[PORTS];
    private final short[] appliedPointerY = new short[PORTS];
    private final boolean[] appliedPointerPressed = new boolean[PORTS];
    private boolean appliedPaused;

    void setJoypadButton(int port, int button, boolean pressed) {
        if (port < 0 || port >= PORTS || button < 0 || button >= JOYPAD_BUTTONS)
            throw new IllegalStateException("invalid joypad port or button");
        synchronized (lock) {
            if (pressed) requestedJoypad[port] |= 1 << button;
            else requestedJoypad[port] &= ~(1 << button);
            dirty = true;
        }
    }

    void setAnalogAxis(int port, int index, int id, int value) {
        if (port < 0 || port >= PORTS || index < 0 || index >= ANALOG_INDEXES ||
                id < 0 || id >= ANALOG_IDS || value < Short.MIN_VALUE ||
                value > Short.MAX_VALUE ||
                (index < ANALOG_INDEX_BUTTON && id > ANALOG_ID_Y))
            throw new IllegalStateException("invalid analog port, index, id, or value");
        synchronized (lock) {
            requestedAnalog[port][index][id] = (short) value;
            dirty = true;
        }
    }

    void setPointer(int port, int x, int y, boolean pressed) {
        if (port < 0 || port >= PORTS || x < Short.MIN_VALUE || x > Short.MAX_VALUE ||
                y < Short.MIN_VALUE || y > Short.MAX_VALUE)
            throw new IllegalStateException("invalid pointer port or coordinate");
        synchronized (lock) {
            requestedPointerX[port] = (short) x;
            requestedPointerY[port] = (short) y;
            requestedPointerPressed[port] = pressed;
            dirty = true;
        }
    }

    void setPaused(boolean paused) {
        synchronized (lock) {
            requestedPaused = paused;
            dirty = true;
        }
    }

    /** Applies every value that differs from what the native host last received. */
    void applyTo(Sink sink) {
        int[] joypad = new int[PORTS];
        short[][][] analog = new short[PORTS][ANALOG_INDEXES][ANALOG_IDS];
        short[] pointerX = new short[PORTS];
        short[] pointerY = new short[PORTS];
        boolean[] pointerPressed = new boolean[PORTS];
        boolean paused;
        synchronized (lock) {
            if (!dirty) return;
            dirty = false;
            System.arraycopy(requestedJoypad, 0, joypad, 0, PORTS);
            for (int port = 0; port < PORTS; port++)
                for (int index = 0; index < ANALOG_INDEXES; index++)
                    System.arraycopy(requestedAnalog[port][index], 0,
                            analog[port][index], 0, ANALOG_IDS);
            System.arraycopy(requestedPointerX, 0, pointerX, 0, PORTS);
            System.arraycopy(requestedPointerY, 0, pointerY, 0, PORTS);
            System.arraycopy(requestedPointerPressed, 0, pointerPressed, 0, PORTS);
            paused = requestedPaused;
        }
        if (paused != appliedPaused) {
            sink.paused(paused);
            appliedPaused = paused;
        }
        for (int port = 0; port < PORTS; port++) {
            int changed = joypad[port] ^ appliedJoypad[port];
            for (int button = 0; changed != 0 && button < JOYPAD_BUTTONS; button++) {
                int bit = 1 << button;
                if ((changed & bit) == 0) continue;
                boolean pressed = (joypad[port] & bit) != 0;
                sink.joypadButton(port, button, pressed);
                if (pressed) appliedJoypad[port] |= bit;
                else appliedJoypad[port] &= ~bit;
                changed &= ~bit;
            }
            for (int index = 0; index < ANALOG_INDEXES; index++) {
                for (int id = 0; id < ANALOG_IDS; id++) {
                    short value = analog[port][index][id];
                    if (value == appliedAnalog[port][index][id]) continue;
                    sink.analogAxis(port, index, id, value);
                    appliedAnalog[port][index][id] = value;
                }
            }
            if (pointerX[port] != appliedPointerX[port] ||
                    pointerY[port] != appliedPointerY[port] ||
                    pointerPressed[port] != appliedPointerPressed[port]) {
                sink.pointer(port, pointerX[port], pointerY[port], pointerPressed[port]);
                appliedPointerX[port] = pointerX[port];
                appliedPointerY[port] = pointerY[port];
                appliedPointerPressed[port] = pointerPressed[port];
            }
        }
    }
}
