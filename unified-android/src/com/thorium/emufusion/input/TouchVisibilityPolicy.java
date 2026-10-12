package com.thorium.emufusion.input;

import java.util.Collection;

public final class TouchVisibilityPolicy {
    private TouchVisibilityPolicy() {}

    public static boolean shouldShow(boolean hostIsKnownGamingHandheld,
            Collection<GamepadDescriptor> connected, DeviceCatalog catalog) {
        if (hostIsKnownGamingHandheld) return false;
        for (GamepadDescriptor device : connected) {
            DeviceProfile profile = catalog.match(device);
            if (profile.builtInGamingDevice || device.isCompleteGamepad()) return false;
        }
        return true;
    }
}
