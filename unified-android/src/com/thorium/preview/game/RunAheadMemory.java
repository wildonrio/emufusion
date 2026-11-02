package com.thorium.preview.game;

import android.content.Context;
import android.content.SharedPreferences;

/**
 * Engines whose savestates did not replay the same frames, so run-ahead was
 * refused for what the core does. Each session re-ran the replay check and,
 * on BlastEm, turned run-ahead on and off again within two seconds: two
 * picture hitches at the start of every Mega Drive game (Thor, 2026-11-01).
 * Remembered per engine until the app is updated (new cores are checked
 * afresh); refusals for speed are not remembered.
 */
final class RunAheadMemory {
    private static final String PREFERENCES = "emufusion_runahead";
    private static final String PREFIX = "refused.";

    private RunAheadMemory() {}

    static boolean refused(Context context, String engineId) {
        long installed = apkLastUpdateTime(context);
        if (context == null || engineId == null || installed == 0L) return false;
        try {
            return preferences(context).getLong(PREFIX + engineId, 0L) == installed;
        } catch (RuntimeException ignored) {
            return false;
        }
    }

    static void remember(Context context, String engineId) {
        long installed = apkLastUpdateTime(context);
        if (context == null || engineId == null || installed == 0L) return;
        try {
            preferences(context).edit().putLong(PREFIX + engineId, installed).apply();
        } catch (RuntimeException ignored) {
            // Best effort: the next session checks again.
        }
    }

    private static SharedPreferences preferences(Context context) {
        return context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE);
    }

    private static long apkLastUpdateTime(Context context) {
        if (context == null) return 0L;
        try {
            return context.getPackageManager()
                    .getPackageInfo(context.getPackageName(), 0).lastUpdateTime;
        } catch (Exception ignored) {
            return 0L;
        }
    }
}
