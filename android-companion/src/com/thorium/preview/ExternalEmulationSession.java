package com.thorium.preview;

import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.provider.Settings;
import android.text.TextUtils;

import java.util.UUID;

/**
 * The exact standalone-emulator session EmuFusion most recently launched.
 *
 * <p>No ROM path, title, key, firmware name, or save claim is persisted.  The
 * record exists solely so the same-package accessibility service can reject
 * Stop presses from every package except the exact external target EmuFusion
 * launched, and can report honestly what its bounded return attempt proved.</p>
 */
public final class ExternalEmulationSession {
    private static final String PREFS = "external-emulation-session";
    private static final String SERVICE =
            "com.thorium.preview/.ExternalStopAccessibilityService";

    public static final class Snapshot {
        public final String token;
        public final String packageName;
        public final String component;
        public final long startedElapsedMs;
        public final boolean active;
        public final boolean returnRequested;
        public final boolean fallbackLaunchIssued;
        public final boolean externalClosedProven;
        public final boolean libraryForegroundProven;

        Snapshot(String token, String packageName, String component,
                 long startedElapsedMs, boolean active, boolean returnRequested,
                 boolean fallbackLaunchIssued, boolean externalClosedProven,
                 boolean libraryForegroundProven) {
            this.token = token;
            this.packageName = packageName;
            this.component = component;
            this.startedElapsedMs = startedElapsedMs;
            this.active = active;
            this.returnRequested = returnRequested;
            this.fallbackLaunchIssued = fallbackLaunchIssued;
            this.externalClosedProven = externalClosedProven;
            this.libraryForegroundProven = libraryForegroundProven;
        }
    }

    private ExternalEmulationSession() {}

    private static SharedPreferences prefs(Context context) {
        return context.getApplicationContext().getSharedPreferences(
                PREFS, Context.MODE_PRIVATE);
    }

    static String begin(Context context, String packageName, String component) {
        if (context == null || !safePackage(packageName) || component == null ||
                component.trim().isEmpty()) return "";
        String token = UUID.randomUUID().toString();
        prefs(context).edit()
                .putString("token", token)
                .putString("package", packageName.trim())
                .putString("component", component.trim())
                .putLong("startedElapsedMs", android.os.SystemClock.elapsedRealtime())
                .putBoolean("active", true)
                .putBoolean("returnRequested", false)
                .putBoolean("naturalBackAttempted", false)
                .putBoolean("fallbackLaunchIssued", false)
                .putBoolean("saveProven", false)
                .putBoolean("externalClosedProven", false)
                .putBoolean("libraryForegroundProven", false)
                .apply();
        return token;
    }

    static void abandon(Context context, String token) {
        Snapshot current = snapshot(context);
        if (current.active && current.token.equals(token))
            prefs(context).edit().putBoolean("active", false).apply();
    }

    public static Snapshot snapshot(Context context) {
        if (context == null) return new Snapshot(
                "", "", "", 0L, false, false, false, false, false);
        SharedPreferences value = prefs(context);
        return new Snapshot(
                value.getString("token", ""),
                value.getString("package", ""),
                value.getString("component", ""),
                value.getLong("startedElapsedMs", 0L),
                value.getBoolean("active", false),
                value.getBoolean("returnRequested", false),
                value.getBoolean("fallbackLaunchIssued", false),
                value.getBoolean("externalClosedProven", false),
                value.getBoolean("libraryForegroundProven", false));
    }

    static boolean matches(Context context, String token, String packageName) {
        Snapshot current = snapshot(context);
        return current.active && !current.token.isEmpty() &&
                current.token.equals(token) &&
                current.packageName.equals(packageName);
    }

    static void markNaturalReturnAttempt(Context context, String token) {
        Snapshot current = snapshot(context);
        if (!current.active || !current.token.equals(token)) return;
        // Android exposes no portable standalone-emulator save/close result.
        // Keep those claims false.  The service records only the operations it
        // actually issued and later marks the observable foreground return.
        prefs(context).edit()
                .putBoolean("returnRequested", true)
                .putBoolean("naturalBackAttempted", true)
                .putBoolean("saveProven", false)
                .putBoolean("externalClosedProven", false)
                .apply();
    }

    static void markLibraryForeground(Context context, String token) {
        Snapshot current = snapshot(context);
        if (!current.token.equals(token)) return;
        // A display-0 EmuFusion window observed after the natural Back request,
        // but before any fallback launch, proves the external gameplay window
        // naturally yielded. It does not prove a save or process termination.
        boolean naturalClosure = current.returnRequested &&
                !current.fallbackLaunchIssued;
        prefs(context).edit()
                .putBoolean("active", false)
                .putBoolean("libraryForegroundProven", true)
                .putBoolean("externalClosedProven", naturalClosure)
                .apply();
    }

    /** Whether Android has explicitly enabled this package's key-filter service. */
    public static boolean stopControlEnabled(Context context) {
        if (context == null) return false;
        String enabled = Settings.Secure.getString(
                context.getContentResolver(),
                Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES);
        if (TextUtils.isEmpty(enabled)) return false;
        String expected = new ComponentName(
                context, ExternalStopAccessibilityService.class)
                .flattenToString();
        for (String candidate : enabled.split(":")) {
            if (expected.equalsIgnoreCase(candidate) ||
                    SERVICE.equalsIgnoreCase(candidate)) return true;
            ComponentName parsed = ComponentName.unflattenFromString(candidate);
            if (parsed != null && context.getPackageName().equals(parsed.getPackageName()) &&
                    ExternalStopAccessibilityService.class.getName().equals(
                            parsed.getClassName())) return true;
        }
        return false;
    }

    /** Bring the existing EmuFusion task forward; never manufacture a save claim. */
    static boolean returnToLibrary(Context context, String token) {
        if (context == null) return false;
        Snapshot current = snapshot(context);
        if (!current.active || !current.token.equals(token)) return false;
        Intent intent = context.getPackageManager().getLaunchIntentForPackage(
                context.getPackageName());
        if (intent == null) return false;
        intent.setAction(Intent.ACTION_MAIN)
                .addCategory(Intent.CATEGORY_LAUNCHER)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK |
                        Intent.FLAG_ACTIVITY_REORDER_TO_FRONT |
                        Intent.FLAG_ACTIVITY_SINGLE_TOP);
        try {
            // Set before startActivity so the resulting accessibility event can
            // never be mistaken for a natural external-window closure.
            prefs(context).edit().putBoolean("fallbackLaunchIssued", true)
                    .putBoolean("externalClosedProven", false).apply();
            context.startActivity(intent);
            return true;
        } catch (RuntimeException ignored) {
            return false;
        }
    }

    private static boolean safePackage(String value) {
        return value != null && value.matches(
                "[A-Za-z][A-Za-z0-9_]*(?:\\.[A-Za-z][A-Za-z0-9_]*)+") &&
                !"com.thorium.preview".equals(value);
    }
}
