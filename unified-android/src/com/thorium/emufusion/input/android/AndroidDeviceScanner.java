package com.thorium.emufusion.input.android;

import android.os.Build;
import android.os.SystemClock;
import android.util.Log;
import android.view.InputDevice;

import com.thorium.emufusion.input.AndroidInputCodes;
import com.thorium.emufusion.input.GamepadDescriptor;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/** Thin Android adapter; all matching and policy decisions remain host-JVM testable. */
public final class AndroidDeviceScanner {
    private static final String TAG = "EmuFusionInput";
    private static final int[] KNOWN_KEYS = {
            AndroidInputCodes.DPAD_UP, AndroidInputCodes.DPAD_DOWN,
            AndroidInputCodes.DPAD_LEFT, AndroidInputCodes.DPAD_RIGHT,
            AndroidInputCodes.BUTTON_A, AndroidInputCodes.BUTTON_B,
            AndroidInputCodes.BUTTON_C, AndroidInputCodes.BUTTON_X,
            AndroidInputCodes.BUTTON_Y, AndroidInputCodes.BUTTON_Z,
            AndroidInputCodes.BUTTON_L1, AndroidInputCodes.BUTTON_R1,
            AndroidInputCodes.BUTTON_L2, AndroidInputCodes.BUTTON_R2,
            AndroidInputCodes.BUTTON_THUMBL, AndroidInputCodes.BUTTON_THUMBR,
            AndroidInputCodes.BUTTON_START, AndroidInputCodes.BUTTON_SELECT,
            AndroidInputCodes.BUTTON_MODE
    };

    private AndroidDeviceScanner() {}

    public static List<GamepadDescriptor> scan() {
        List<GamepadDescriptor> result = new ArrayList<>();
        for (int id : deviceIds()) {
            InputDevice device = InputDevice.getDevice(id);
            if (device == null || device.isVirtual()) continue;
            int sources = device.getSources();
            boolean gamepad = (sources & InputDevice.SOURCE_GAMEPAD) == InputDevice.SOURCE_GAMEPAD;
            boolean joystick = (sources & InputDevice.SOURCE_JOYSTICK) == InputDevice.SOURCE_JOYSTICK;
            if (!gamepad && !joystick) continue;
            Set<Integer> keys = new HashSet<>();
            boolean[] present = device.hasKeys(KNOWN_KEYS);
            for (int i = 0; i < KNOWN_KEYS.length; i++) if (present[i]) keys.add(KNOWN_KEYS[i]);
            Set<Integer> axes = new HashSet<>();
            for (InputDevice.MotionRange range : device.getMotionRanges())
                if ((range.getSource() & InputDevice.SOURCE_CLASS_JOYSTICK) != 0)
                    axes.add(range.getAxis());
            boolean external = Build.VERSION.SDK_INT >= 29 && device.isExternal();
            result.add(new GamepadDescriptor(id, device.getVendorId(), device.getProductId(),
                    device.getDescriptor(), device.getName(), external, gamepad, joystick,
                    keys, axes));
        }
        return result;
    }

    /**
     * Android can refuse the list for a moment while a game starts ("already registered an
     * InputDevicesChangedListener", once in 345 Thor launches), and the game then failed to start.
     * Try again briefly, then go on with none: a pad's first input scans again.
     */
    private static int[] deviceIds() {
        for (int attempt = 0; ; attempt++) {
            try {
                return InputDevice.getDeviceIds();
            } catch (SecurityException refused) {
                if (attempt == 4) {
                    Log.w(TAG, "Input devices unavailable; scanning again on first input", refused);
                    return new int[0];
                }
                SystemClock.sleep(25L << attempt);
            }
        }
    }
}
