package com.thorium.preview.game;

import android.content.Context;
import android.content.SharedPreferences;

import java.util.Locale;

/**
 * Owner preference for verified built-in emulator widescreen options.
 *
 * Two independent switches live in the same preference file:
 * <ul>
 * <li>{@code enabled} (default true): the historic "widescreen enhancements"
 *     flag. It only selects Dolphin's emulated Wii SYSCONF 16:9 mode, a
 *     native in-game option, and keeps that meaning and default.</li>
 * <li>{@code hackEnabled} (default false) plus per-system overrides
 *     {@code hack.<system>} in {@code on|off|auto}: the geometry-expanding
 *     widescreen hack described in
 *     {@code docs/cheats-everywhere-and-widescreen-design.md} section 7 and
 *     resolved per launch by {@link WidescreenHackPolicy}. {@code auto}
 *     (the default for every system) follows the global {@code hackEnabled}
 *     flag; {@code on}/{@code off} pin one system regardless of it.</li>
 * </ul>
 */
public final class WidescreenSettings {
    private static final String PREFERENCES = "widescreen-enhancements";
    private static final String ENABLED = "enabled";
    private static final String HACK_ENABLED = "hackEnabled";
    private static final String HACK_SYSTEM_PREFIX = "hack.";

    public static final String HACK_MODE_ON = "on";
    public static final String HACK_MODE_OFF = "off";
    public static final String HACK_MODE_AUTO = "auto";

    private WidescreenSettings() {}

    /** Defaults on for a 16:9 device, including existing installations. */
    public static boolean isEnabled(Context context) {
        return context == null || preferences(context).getBoolean(ENABLED, true);
    }

    public static synchronized void setEnabled(Context context, boolean enabled) {
        if (context == null) return;
        // The settings HTTP response is the launch boundary, so persist before
        // acknowledging instead of exposing an in-memory value ahead of disk.
        preferences(context).edit().putBoolean(ENABLED, enabled).commit();
    }

    /** The geometry-expanding hack is opt-in: it defaults off everywhere. */
    public static boolean isHackEnabled(Context context) {
        return context != null && preferences(context).getBoolean(HACK_ENABLED, false);
    }

    public static synchronized void setHackEnabled(Context context, boolean enabled) {
        if (context == null) return;
        preferences(context).edit().putBoolean(HACK_ENABLED, enabled).commit();
    }

    /**
     * Per-system override for the hack: {@code on}, {@code off}, or
     * {@code auto} (follow {@link #isHackEnabled}). Unknown or absent values
     * read as {@code auto}; system ids are matched case-insensitively.
     */
    public static String hackMode(Context context, String systemId) {
        String key = hackModeKey(systemId);
        if (context == null || key == null) return HACK_MODE_AUTO;
        return normaliseHackMode(preferences(context).getString(key, HACK_MODE_AUTO));
    }

    /** Stores a per-system override; {@code auto} removes the stored key. */
    public static synchronized void setHackMode(Context context, String systemId, String mode) {
        String key = hackModeKey(systemId);
        if (context == null || key == null) return;
        String normalised = normaliseHackMode(mode);
        SharedPreferences.Editor editor = preferences(context).edit();
        if (HACK_MODE_AUTO.equals(normalised)) editor.remove(key);
        else editor.putString(key, normalised);
        editor.commit();
    }

    /** Pure: maps any text to exactly one of {@code on|off|auto}. */
    public static String normaliseHackMode(String mode) {
        if (mode == null) return HACK_MODE_AUTO;
        String value = mode.trim().toLowerCase(Locale.US);
        if (HACK_MODE_ON.equals(value) || "1".equals(value) || "true".equals(value))
            return HACK_MODE_ON;
        if (HACK_MODE_OFF.equals(value) || "0".equals(value) || "false".equals(value))
            return HACK_MODE_OFF;
        return HACK_MODE_AUTO;
    }

    /** Pure: true only for the three accepted spellings (after trimming). */
    public static boolean isValidHackMode(String mode) {
        if (mode == null) return false;
        String value = mode.trim().toLowerCase(Locale.US);
        return HACK_MODE_ON.equals(value) || HACK_MODE_OFF.equals(value) ||
                HACK_MODE_AUTO.equals(value);
    }

    private static String hackModeKey(String systemId) {
        if (systemId == null) return null;
        String system = systemId.trim().toLowerCase(Locale.US);
        if (system.isEmpty()) return null;
        return HACK_SYSTEM_PREFIX + system;
    }

    private static SharedPreferences preferences(Context context) {
        return context.getApplicationContext().getSharedPreferences(
                PREFERENCES, Context.MODE_PRIVATE);
    }
}
