package com.thorium.preview;

import android.content.Context;
import android.content.SharedPreferences;

import com.thorium.lucent.emulators.CustomEmulatorSpec;
import com.thorium.lucent.emulators.ExternalEmulatorDelivery;
import com.thorium.lucent.metadata.EngineSystemIdResolver;

import org.json.JSONArray;
import org.json.JSONObject;

/**
 * The per-system "Custom" external emulator: a target the catalog has never
 * heard of, pointed at by the user through the guided setup in Settings.
 *
 * Stored per canonical system rather than globally, because the whole feature
 * is per-system — someone may run a custom Saturn build while every other
 * system stays on a catalogued emulator.
 *
 * Nothing is persisted until it has been proved twice over: the entry must be
 * well-formed ({@link CustomEmulatorSpec}, which also closes the
 * argument-injection surface in the generated {@code am start} string) AND the
 * named activity must actually exist and be exported on the device
 * ({@link InstalledPackages#hasExportedActivity}). Storing an unproved target
 * would reproduce exactly the failure this feature exists to remove: a game
 * that launches into nothing, with no explanation anywhere.
 */
final class CustomEmulatorStore {
    /** The reserved emulator id, shared with the pure validation layer. */
    static final String ID = CustomEmulatorSpec.ID;

    private static final String PREFS = "custom-emulators";
    private static final String PACKAGE = "package.";
    private static final String COMPONENT = "component.";
    private static final String DELIVERY = "delivery.";
    private static final String EXTRA_KEY = "extra.";
    private static final String LABEL = "label.";

    private CustomEmulatorStore() {}

    private static SharedPreferences prefs(Context context) {
        return context.getApplicationContext()
                .getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    /** True when this system has a stored, previously validated custom target. */
    static boolean has(Context context, String system) {
        String canonical = EngineSystemIdResolver.canonical(system);
        return !prefs(context).getString(PACKAGE + canonical, "").isEmpty();
    }

    /**
     * The stored custom target as a normal catalog option, so every existing
     * launch path — recipe building, install fallback, metadata rewriting —
     * treats it identically to a curated one. Returns null when nothing is
     * stored, or when what is stored no longer resolves on the device (the
     * user uninstalled it), which is the state the picker reports as "needs
     * setting up again" rather than launching into a missing app.
     */
    static EmulatorCatalog.Option option(Context context, String system) {
        String canonical = EngineSystemIdResolver.canonical(system);
        SharedPreferences prefs = prefs(context);
        String packageName = prefs.getString(PACKAGE + canonical, "");
        String component = prefs.getString(COMPONENT + canonical, "");
        String delivery = prefs.getString(DELIVERY + canonical, "");
        if (packageName.isEmpty() || component.isEmpty()
                || !ExternalEmulatorDelivery.known(delivery)) return null;
        if (!InstalledPackages.hasExportedActivity(context, packageName, component))
            return null;
        String label = prefs.getString(LABEL + canonical, "");
        return new EmulatorCatalog.Option(ID,
                label.isEmpty() ? "Custom emulator" : label,
                packageName, "", "custom", delivery, actionFor(delivery), component,
                prefs.getString(EXTRA_KEY + canonical, ""), null, "");
    }

    /**
     * Validates and, when everything checks out, stores a custom target.
     *
     * The returned JSON is the guided setup's entire vocabulary: {@code ok}
     * plus, on failure, a {@code problems} array of {field, message} pairs the
     * UI can print straight onto the form. Every rejection names the field it
     * belongs to so the user is never told merely that "something" is wrong.
     */
    static JSONObject save(Context context, String system, String packageName,
                           String activity, String delivery, String romExtraKey) {
        String canonical = EngineSystemIdResolver.canonical(system);
        JSONObject response = new JSONObject();
        JSONArray problems = new JSONArray();
        try {
            response.put("system", canonical);
            CustomEmulatorSpec spec = CustomEmulatorSpec.parse(packageName, activity,
                    delivery, romExtraKey, context.getPackageName());
            for (CustomEmulatorSpec.Problem problem : spec.problems())
                problems.put(new JSONObject()
                        .put("field", problem.field())
                        .put("message", problem.message()));

            // Only once the entry is well-formed is it worth asking the device
            // about it: the two device checks below are what turn "it does
            // nothing" into a specific, fixable sentence.
            if (spec.valid()) {
                String component = spec.component();
                if (!InstalledPackages.isInstalled(context, spec.packageName())) {
                    problems.put(new JSONObject().put("field", "package").put("message",
                            spec.packageName() + " is not installed. Install it first, " +
                            "then come back and confirm."));
                } else if (!InstalledPackages.hasExportedActivity(
                        context, spec.packageName(), component)) {
                    problems.put(new JSONObject().put("field", "activity").put("message",
                            component + " is not a screen this app lets other apps " +
                            "open. Check the name, or pick a different one."));
                } else {
                    prefs(context).edit()
                            .putString(PACKAGE + canonical, spec.packageName())
                            .putString(COMPONENT + canonical, component)
                            .putString(DELIVERY + canonical, spec.delivery())
                            .putString(EXTRA_KEY + canonical, spec.romExtraKey())
                            .putString(LABEL + canonical,
                                    applicationLabel(context, spec.packageName()))
                            .apply();
                    response.put("ok", true);
                    response.put("package", spec.packageName());
                    response.put("component", component);
                    response.put("delivery", spec.delivery());
                    response.put("problems", problems);
                    return response;
                }
            }
            response.put("ok", false);
            response.put("problems", problems);
        } catch (Exception ignored) {}
        return response;
    }

    /** Forgets a system's custom target, returning it to the catalog list. */
    static void clear(Context context, String system) {
        String canonical = EngineSystemIdResolver.canonical(system);
        prefs(context).edit()
                .remove(PACKAGE + canonical)
                .remove(COMPONENT + canonical)
                .remove(DELIVERY + canonical)
                .remove(EXTRA_KEY + canonical)
                .remove(LABEL + canonical)
                .apply();
    }

    /** The stored entry, for repopulating the setup form. Never null. */
    static JSONObject describe(Context context, String system) {
        String canonical = EngineSystemIdResolver.canonical(system);
        SharedPreferences prefs = prefs(context);
        JSONObject entry = new JSONObject();
        try {
            String packageName = prefs.getString(PACKAGE + canonical, "");
            entry.put("configured", !packageName.isEmpty());
            entry.put("package", packageName);
            entry.put("component", prefs.getString(COMPONENT + canonical, ""));
            entry.put("delivery", prefs.getString(DELIVERY + canonical, ""));
            entry.put("romExtraKey", prefs.getString(EXTRA_KEY + canonical, ""));
            entry.put("name", prefs.getString(LABEL + canonical, ""));
            // Distinguishes "set up but the app has since gone" from "never set
            // up", which need different words in the UI.
            entry.put("resolves", option(context, canonical) != null);
        } catch (Exception ignored) {}
        return entry;
    }

    /** The user-visible app name, so the picker shows what they installed. */
    private static String applicationLabel(Context context, String packageName) {
        try {
            android.content.pm.PackageManager manager = context.getPackageManager();
            CharSequence label = manager.getApplicationLabel(
                    manager.getApplicationInfo(packageName, 0));
            return label == null ? "" : label.toString();
        } catch (Exception unavailable) {
            return "";
        }
    }

    private static String actionFor(String delivery) {
        return ExternalEmulatorDelivery.FILE_PATH.equals(delivery)
                ? "android.intent.action.MAIN" : "android.intent.action.VIEW";
    }
}
