package com.thorium.preview;

import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.pm.ResolveInfo;

import java.util.List;

/**
 * "Is this emulator installed?" — the one question the whole Settings route
 * picker turns on, and the one that is quietly wrong by default on modern
 * Android.
 *
 * From Android 11 the platform filters package queries: an app that targets
 * API 30+ sees only itself, its own dependencies, and whatever it declares in
 * {@code <queries>}. Everything else is answered exactly as if it were not
 * installed — {@link PackageManager#getPackageInfo} throws NameNotFoundException,
 * {@code getLaunchIntentForPackage} returns null, no error is logged, and no
 * permission prompt appears. A picker built on a bare getPackageInfo therefore
 * degrades into "nothing is ever installed, tap forever", which is
 * indistinguishable from the user failing to install anything.
 *
 * EmuFusion's manifest still declares targetSdkVersion 28, so filtering is not
 * active today. That is precisely why this is worth writing down: the day
 * someone raises the target — which any Play submission would force — every
 * emulator on the device silently becomes "not installed" unless the
 * declarations are already in place. They are, in AndroidManifest.xml:
 *
 *   - one {@code <queries><package>} entry per catalog package id, generated
 *     from engines/external-emulators.json by
 *     tools/sync_external_emulator_queries.py and enforced by
 *     tools/tests/test_external_emulator_routing.py; and
 *   - one {@code <queries><intent>} MAIN/LAUNCHER filter, which is what makes a
 *     CUSTOM emulator visible at all. A user-supplied package cannot appear in
 *     a static list by definition, so without the intent filter the guided
 *     custom setup could never confirm the app the user just installed.
 *
 * QUERY_ALL_PACKAGES is deliberately not requested: Play treats it as a
 * restricted permission needing a declared exception, and the two declarations
 * above answer the question without it.
 */
final class InstalledPackages {

    private InstalledPackages() {}

    /**
     * True when the package is present and visible to EmuFusion.
     *
     * Two probes rather than one because they fail differently under
     * filtering: getPackageInfo answers for anything named in
     * {@code <queries><package>}, while the launcher-intent resolve answers for
     * anything the MAIN/LAUNCHER intent filter exposes. A custom emulator only
     * satisfies the second. Neither probe can produce a false positive — both
     * consult the real installed-package state — so trying both only ever
     * recovers a true "installed" that filtering would have hidden.
     */
    static boolean isInstalled(Context context, String packageName) {
        if (context == null || packageName == null || packageName.isEmpty()) return false;
        PackageManager manager = context.getPackageManager();
        try {
            manager.getPackageInfo(packageName, 0);
            return true;
        } catch (Exception filteredOrAbsent) {
            // Ambiguous by design: absent and invisible look the same here.
        }
        return hasLauncherActivity(manager, packageName);
    }

    /** The launcher-intent probe on its own, for the visibility fallback. */
    private static boolean hasLauncherActivity(PackageManager manager, String packageName) {
        try {
            Intent launcher = new Intent(Intent.ACTION_MAIN)
                    .addCategory(Intent.CATEGORY_LAUNCHER)
                    .setPackage(packageName);
            List<ResolveInfo> matches = manager.queryIntentActivities(launcher, 0);
            if (matches != null && !matches.isEmpty()) return true;
            return manager.getLaunchIntentForPackage(packageName) != null;
        } catch (Exception unavailable) {
            return false;
        }
    }

    /**
     * The first of {@code candidates} that is installed, or "".
     *
     * Emulators ship under several ids at once — paid and free, stable and
     * nightly, store and sideload — so the order of the catalog's package list
     * is the preference order, not a set.
     */
    static String firstInstalled(Context context, Iterable<String> candidates) {
        if (candidates == null) return "";
        for (String candidate : candidates)
            if (isInstalled(context, candidate)) return candidate;
        return "";
    }

    /**
     * True when the package declares that exact activity as a launchable
     * component. The guided custom setup uses this to separate "you typed the
     * wrong screen name" from "that app is not installed", which are the two
     * mistakes a custom entry actually produces and which otherwise both
     * present as a game that does nothing when launched.
     *
     * Answers false when the component exists but is not exported: EmuFusion
     * cannot start another app's private activity, so accepting it would
     * persist a preference that fails only later, at launch.
     */
    static boolean hasExportedActivity(Context context, String packageName, String component) {
        if (context == null || packageName == null || packageName.isEmpty()
                || component == null || component.isEmpty()) return false;
        try {
            android.content.pm.ActivityInfo info = context.getPackageManager()
                    .getActivityInfo(new android.content.ComponentName(
                            packageName, component), 0);
            return info != null && info.exported;
        } catch (Exception missingOrFiltered) {
            return false;
        }
    }
}
