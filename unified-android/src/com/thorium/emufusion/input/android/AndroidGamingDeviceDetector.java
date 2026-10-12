package com.thorium.emufusion.input.android;

import android.os.Build;

import java.util.Locale;

public final class AndroidGamingDeviceDetector {
    private AndroidGamingDeviceDetector() {}

    public static boolean isKnownGamingHandheld() {
        String identity = (Build.MANUFACTURER + " " + Build.BRAND + " " + Build.MODEL + " " +
                Build.DEVICE).toLowerCase(Locale.ROOT);
        return identity.matches(".*(ayn|odin|thor|retroid|anbernic|ayaneo|g cloud|razer edge).*" );
    }
}
