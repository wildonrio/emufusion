package com.thorium.preview.cheats.delivery;

import android.content.Context;

/**
 * Owner preference for automatic frame-rate unlocks. On by default (owner,
 * 2026-10-10: unlock the frame rate wherever possible, before any frame
 * generation). Turning it off retires only codes the overlay enabled.
 */
public final class FrameRateUnlockPolicy {
    private static final String PREFERENCES = "frame-rate-unlock";
    private static final String ENABLED = "enabled";

    private FrameRateUnlockPolicy() {}

    public static boolean isEnabled(Context context) {
        if (context == null) return true;
        return context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
                .getBoolean(ENABLED, true);
    }

    public static void setEnabled(Context context, boolean enabled) {
        if (context == null) return;
        context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE).edit()
                .putBoolean(ENABLED, enabled).commit();
    }
}
