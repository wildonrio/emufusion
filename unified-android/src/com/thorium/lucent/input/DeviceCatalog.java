package com.thorium.lucent.input;

import java.util.ArrayList;
import java.util.Collections;
import java.util.EnumMap;
import java.util.List;
import java.util.Map;

/** Curated known-device matching followed by a capability-based generic fallback. */
public final class DeviceCatalog {
    private final List<DeviceProfile> profiles;
    private final DeviceProfile fallback;

    public DeviceCatalog(List<DeviceProfile> profiles, DeviceProfile fallback) {
        this.profiles = Collections.unmodifiableList(new ArrayList<>(profiles));
        this.fallback = fallback;
    }

    public DeviceProfile match(GamepadDescriptor descriptor) {
        for (DeviceProfile profile : profiles) if (profile.matches(descriptor)) return profile;
        return fallback;
    }

    public static DeviceCatalog standard() {
        Map<CanonicalControl, InputSignal> standard = standardMapping();
        Map<CanonicalControl, InputSignal> odinStyle = odinStyleMapping();
        Map<CanonicalControl, InputSignal> unknownAynStyle = withoutFaceButtons(standard);
        List<DeviceProfile> profiles = new ArrayList<>();
        // Built-in Android handheld controls. Names supplement capability checks;
        // the runtime persists the final match using descriptor + VID/PID.
        //
        // AYN's controller-style switch changes the face-button KeyEvents and
        // the product ID. Canonical controls describe physical positions, so
        // normalize both known identities before the generic name profile.
        profiles.add(profile("ayn-odin-style", 0x2020, 0x0111,
                ".*", true, odinStyle));
        profiles.add(profile("ayn-xbox-style", 0x2020, 0x0112,
                ".*", true, standard));
        // An unknown AYN style must not silently guess the four positions.
        // D-pad, sticks and shoulders remain usable, and an explicit remap can
        // add face controls for a new firmware/product identity.
        profiles.add(profile("ayn-unknown-controller-style", 0x2020, -1,
                ".*", true, unknownAynStyle));
        profiles.add(profile("ayn-handheld", -1, -1, "AYN|Odin|Thor", true, standard));
        profiles.add(profile("retroid-handheld", -1, -1, "Retroid|Pocket Flip", true, standard));
        profiles.add(profile("logitech-g-cloud", -1, -1, "G Cloud|Logitech G Cloud", true, standard));
        profiles.add(profile("razer-edge", 0x1532, -1, "Razer Edge", true, standard));
        profiles.add(profile("ayaneo-pocket", -1, -1, "AYANEO|Pocket Air|Pocket S", true, standard));
        profiles.add(profile("anbernic-handheld", -1, -1, "ANBERNIC|RG[0-9]", true, standard));
        // Common detachable and wireless pads.
        profiles.add(profile("xbox", 0x045e, -1, ".*", false, standard));
        profiles.add(profile("playstation", 0x054c, -1, ".*", false, standard));
        profiles.add(profile("nintendo", 0x057e, -1, ".*", false, standard));
        profiles.add(profile("eightbitdo", 0x2dc8, -1, ".*", false, standard));
        profiles.add(profile("razer-kishi", 0x1532, -1, ".*", false, standard));
        profiles.add(profile("gamesir", -1, -1, "GameSir|Gamesir", false, standard));
        profiles.add(profile("backbone", -1, -1, "Backbone", false, standard));
        return new DeviceCatalog(profiles,
                profile("android-standard", -1, -1, ".*", false, standard));
    }

    public static Map<CanonicalControl, InputSignal> standardMapping() {
        EnumMap<CanonicalControl, InputSignal> map = new EnumMap<>(CanonicalControl.class);
        map.put(CanonicalControl.DPAD_UP, InputSignal.key(AndroidInputCodes.DPAD_UP));
        map.put(CanonicalControl.DPAD_DOWN, InputSignal.key(AndroidInputCodes.DPAD_DOWN));
        map.put(CanonicalControl.DPAD_LEFT, InputSignal.key(AndroidInputCodes.DPAD_LEFT));
        map.put(CanonicalControl.DPAD_RIGHT, InputSignal.key(AndroidInputCodes.DPAD_RIGHT));
        map.put(CanonicalControl.SOUTH, InputSignal.key(AndroidInputCodes.BUTTON_A));
        map.put(CanonicalControl.EAST, InputSignal.key(AndroidInputCodes.BUTTON_B));
        map.put(CanonicalControl.WEST, InputSignal.key(AndroidInputCodes.BUTTON_X));
        map.put(CanonicalControl.NORTH, InputSignal.key(AndroidInputCodes.BUTTON_Y));
        map.put(CanonicalControl.L1, InputSignal.key(AndroidInputCodes.BUTTON_L1));
        map.put(CanonicalControl.R1, InputSignal.key(AndroidInputCodes.BUTTON_R1));
        map.put(CanonicalControl.L2, InputSignal.key(AndroidInputCodes.BUTTON_L2));
        map.put(CanonicalControl.R2, InputSignal.key(AndroidInputCodes.BUTTON_R2));
        map.put(CanonicalControl.L3, InputSignal.key(AndroidInputCodes.BUTTON_THUMBL));
        map.put(CanonicalControl.R3, InputSignal.key(AndroidInputCodes.BUTTON_THUMBR));
        map.put(CanonicalControl.START, InputSignal.key(AndroidInputCodes.BUTTON_START));
        map.put(CanonicalControl.SELECT, InputSignal.key(AndroidInputCodes.BUTTON_SELECT));
        map.put(CanonicalControl.GUIDE, InputSignal.key(AndroidInputCodes.BUTTON_MODE));
        map.put(CanonicalControl.LEFT_X_NEGATIVE, InputSignal.axis(AndroidInputCodes.AXIS_X, -1));
        map.put(CanonicalControl.LEFT_X_POSITIVE, InputSignal.axis(AndroidInputCodes.AXIS_X, 1));
        map.put(CanonicalControl.LEFT_Y_NEGATIVE, InputSignal.axis(AndroidInputCodes.AXIS_Y, -1));
        map.put(CanonicalControl.LEFT_Y_POSITIVE, InputSignal.axis(AndroidInputCodes.AXIS_Y, 1));
        map.put(CanonicalControl.RIGHT_X_NEGATIVE, InputSignal.axis(AndroidInputCodes.AXIS_Z, -1));
        map.put(CanonicalControl.RIGHT_X_POSITIVE, InputSignal.axis(AndroidInputCodes.AXIS_Z, 1));
        map.put(CanonicalControl.RIGHT_Y_NEGATIVE, InputSignal.axis(AndroidInputCodes.AXIS_RZ, -1));
        map.put(CanonicalControl.RIGHT_Y_POSITIVE, InputSignal.axis(AndroidInputCodes.AXIS_RZ, 1));
        return map;
    }

    private static Map<CanonicalControl, InputSignal> odinStyleMapping() {
        EnumMap<CanonicalControl, InputSignal> map =
                new EnumMap<>(standardMapping());
        map.put(CanonicalControl.SOUTH, InputSignal.key(AndroidInputCodes.BUTTON_B));
        map.put(CanonicalControl.EAST, InputSignal.key(AndroidInputCodes.BUTTON_A));
        map.put(CanonicalControl.WEST, InputSignal.key(AndroidInputCodes.BUTTON_Y));
        map.put(CanonicalControl.NORTH, InputSignal.key(AndroidInputCodes.BUTTON_X));
        return map;
    }

    private static Map<CanonicalControl, InputSignal> withoutFaceButtons(
            Map<CanonicalControl, InputSignal> source) {
        EnumMap<CanonicalControl, InputSignal> map = new EnumMap<>(source);
        map.remove(CanonicalControl.SOUTH);
        map.remove(CanonicalControl.EAST);
        map.remove(CanonicalControl.WEST);
        map.remove(CanonicalControl.NORTH);
        return map;
    }

    private static DeviceProfile profile(String id, int vendor, int product, String name,
            boolean handheld, Map<CanonicalControl, InputSignal> mapping) {
        return new DeviceProfile(id, vendor, product, name, handheld, mapping);
    }
}
