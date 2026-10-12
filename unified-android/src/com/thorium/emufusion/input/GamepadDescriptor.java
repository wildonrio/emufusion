package com.thorium.emufusion.input;

import java.util.Collections;
import java.util.HashSet;
import java.util.Locale;
import java.util.Set;

/** Platform-neutral snapshot of one Android InputDevice and its capabilities. */
public final class GamepadDescriptor {
    public final int deviceId;
    public final int vendorId;
    public final int productId;
    public final String descriptor;
    public final String name;
    public final boolean external;
    public final boolean gamepadSource;
    public final boolean joystickSource;
    public final Set<Integer> keys;
    public final Set<Integer> axes;

    public GamepadDescriptor(int deviceId, int vendorId, int productId, String descriptor,
            String name, boolean external, boolean gamepadSource, boolean joystickSource,
            Set<Integer> keys, Set<Integer> axes) {
        this.deviceId = deviceId;
        this.vendorId = vendorId;
        this.productId = productId;
        this.descriptor = descriptor == null ? "" : descriptor;
        this.name = name == null ? "" : name;
        this.external = external;
        this.gamepadSource = gamepadSource;
        this.joystickSource = joystickSource;
        this.keys = Collections.unmodifiableSet(new HashSet<>(keys));
        this.axes = Collections.unmodifiableSet(new HashSet<>(axes));
    }

    public boolean isPhysicalGamepad() { return gamepadSource || joystickSource; }

    public boolean isCompleteGamepad() {
        boolean directions = (keys.contains(AndroidInputCodes.DPAD_UP) &&
                keys.contains(AndroidInputCodes.DPAD_DOWN) &&
                keys.contains(AndroidInputCodes.DPAD_LEFT) &&
                keys.contains(AndroidInputCodes.DPAD_RIGHT)) ||
                (axes.contains(AndroidInputCodes.AXIS_HAT_X) && axes.contains(AndroidInputCodes.AXIS_HAT_Y)) ||
                (axes.contains(AndroidInputCodes.AXIS_X) && axes.contains(AndroidInputCodes.AXIS_Y));
        boolean face = keys.contains(AndroidInputCodes.BUTTON_A) &&
                keys.contains(AndroidInputCodes.BUTTON_B);
        return isPhysicalGamepad() && directions && face;
    }

    /** Persistent identity avoids relying on mutable display names alone. */
    public String persistentKey() {
        String stable = descriptor.trim();
        if (stable.isEmpty()) stable = name.toLowerCase(Locale.ROOT).replaceAll("[^a-z0-9]+", "-");
        return Integer.toHexString(vendorId) + ":" + Integer.toHexString(productId) + ":" + stable;
    }
}
