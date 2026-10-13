package com.thorium.preview.game;

import android.content.Context;
import android.content.SharedPreferences;

import com.thorium.emufusion.video.FrameGenerationBackendPolicy;

/** Process-wide owner preference for internal-emulator frame generation. */
public final class FrameGenerationSettings {
    private static final String PREFERENCES = "display-frame-generation";
    private static final String MODE_VERSION = "mode-version";
    // Version 3 deliberately forces one more OFF migration. Version 2 shipped
    // while the UI could display OFF before its asynchronous service write had
    // completed, so carrying that value forward is not trustworthy.
    private static final int CURRENT_MODE_VERSION = 3;
    private static final String ENABLED = "enabled";
    private static final String MODE = "mode";

    /**
     * Output frames per real frame the generator may produce. On fills the
     * panel up to 3x, so 40-55 fps games reach 120 Hz (owner, 2026-10-12: the
     * high-end systems matter most and mostly run 30-55 fps; the 2x ceiling
     * left Link's Awakening at 60). The "Allow 4x" option (stored as
     * AUTO_TRIPLE) raises it to {@link #FOUR_X_MULTIPLIER} so 30 fps games
     * reach 120 too.
     */
    public static final int MAX_MULTIPLIER = 3;
    public static final int FOUR_X_MULTIPLIER = 4;

    private FrameGenerationSettings() {}

    /** One explicit owner choice. No package, shell global, or probe may override it. */
    public enum Mode {
        OFF("off"),
        /**
         * Built-in backend with the owner's lock-to-30 tier policy: 60->120
         * when the game holds 60, otherwise locked 30->60 (20->40 below 30).
         * Opt-in like the others; OFF stays the default and migration target.
         */
        AUTO("auto"),
        /**
         * On with "Allow 4x": AUTO's ceiling raised to 4x (30->120, 15->60).
         * The stored value keeps its original name so existing choices carry
         * over (it was "Allow triple" before 3x became On's default).
         */
        AUTO_TRIPLE("auto-triple");

        private final String storedValue;

        Mode(String storedValue) { this.storedValue = storedValue; }

        public String storedValue() { return storedValue; }

        /** Frame generation On, with or without tripling. */
        public boolean usesBuiltInBackend() {
            return this == AUTO || this == AUTO_TRIPLE;
        }

        /** AUTO (either ceiling) alone selects the lock-to-30 tier policy. */
        public boolean usesLockToThirtyTierPolicy() {
            return this == AUTO || this == AUTO_TRIPLE;
        }

        /** Output frames per real frame this mode may generate. */
        public int maxMultiplier() {
            return this == AUTO_TRIPLE ? FOUR_X_MULTIPLIER : MAX_MULTIPLIER;
        }

        /** Beyond 2x needs the timeline scheduler; the one-midpoint lattice cannot. */
        public boolean requiresTimelineScheduler() { return maxMultiplier() > 2; }

        public static Mode parse(String value) {
            if (value != null) {
                String normalized = value.trim().toLowerCase(java.util.Locale.US);
                for (Mode candidate : values())
                    if (candidate.storedValue.equals(normalized)) return candidate;
                // The menu is On/Off (owner, 2026-10-11). Earlier selections
                // of the retired Built-in (Alpha) and LSFG modes meant "on".
                if (normalized.equals("on") || normalized.equals("built-in-alpha") ||
                        normalized.equals("lsfg"))
                    return AUTO;
            }
            return OFF;
        }
    }

    /**
     * Returns the explicit mode. An old Boolean or pre-versioned selector is
     * deliberately migrated to OFF: after the reported Direct-path failure,
     * upgrading the APK must never silently preserve an experimental backend.
     */
    public static synchronized Mode mode(Context context) {
        if (context == null) return Mode.OFF;
        SharedPreferences prefs = preferences(context);
        if (prefs.getInt(MODE_VERSION, 0) != CURRENT_MODE_VERSION) {
            persistMode(prefs, Mode.OFF);
            return Mode.OFF;
        }
        String stored = prefs.getString(MODE, Mode.OFF.storedValue());
        Mode parsed = Mode.parse(stored);
        // Unknown/corrupt strings and a stale legacy Boolean are canonicalized
        // synchronously. A successful service response therefore means the
        // complete durable tuple says OFF, not merely that this reader chose a
        // safe fallback in memory.
        if (!parsed.storedValue().equals(stored) ||
                prefs.getBoolean(ENABLED, false) != (parsed != Mode.OFF)) {
            parsed = Mode.OFF;
            persistMode(prefs, parsed);
        }
        return parsed;
    }

    public static boolean isEnabled(Context context) {
        return mode(context) != Mode.OFF;
    }

    public static synchronized void setMode(Context context, Mode mode) {
        if (context == null) return;
        Mode safe = mode == null ? Mode.OFF : mode;
        persistMode(preferences(context), safe);
        if (safe == Mode.OFF) InWindowGameHost.requestFrameGenerationOff();
    }

    private static void persistMode(SharedPreferences prefs, Mode mode) {
        // commit(), rather than apply(), makes the HTTP acknowledgement a real
        // transaction boundary: the frontend may launch only after this tuple
        // is durably visible to every surface/session reader.
        prefs.edit()
                .putInt(MODE_VERSION, CURRENT_MODE_VERSION)
                .putString(MODE, mode.storedValue())
                .putBoolean(ENABLED, mode != Mode.OFF)
                .commit();
    }

    public static void setMode(Context context, String mode) {
        setMode(context, Mode.parse(mode));
    }

    /** Legacy Boolean callers may turn generation off, but can never enable it. */
    public static void setEnabled(Context context, boolean enabled) {
        setMode(context, Mode.OFF);
    }

    /**
     * Freezes the selected backend at the session boundary: Off is always
     * Direct; On (with or without tripling) is EmuFusion's own generator.
     */
    public static FrameGenerationBackendPolicy.Selection selectBackendForSession(
            Context context) {
        return selectBackendForSession(context, mode(context));
    }

    /** Resolves a mode already captured at the immutable launch boundary. */
    public static FrameGenerationBackendPolicy.Selection selectBackendForSession(
            Context context, Mode launchMode) {
        Mode selected = launchMode == null ? Mode.OFF : launchMode;
        if (selected.usesBuiltInBackend())
            return FrameGenerationBackendPolicy.select(true,
                    FrameGenerationBackendPolicy.Assessment.unavailable(
                            "no external backend"),
                    FrameGenerationBackendPolicy.Assessment.ready());
        return FrameGenerationBackendPolicy.select(false,
                FrameGenerationBackendPolicy.Assessment.unavailable(
                        "frame generation is off"),
                FrameGenerationBackendPolicy.Assessment.unavailable(
                        "frame generation is off"));
    }

    private static SharedPreferences preferences(Context context) {
        return context.getApplicationContext()
                .getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE);
    }
}
