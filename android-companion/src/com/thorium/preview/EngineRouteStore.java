package com.thorium.preview;

import android.content.Context;
import android.content.SharedPreferences;

import com.thorium.lucent.metadata.EngineSystemIdResolver;

import java.util.Locale;

/**
 * Per-canonical-system launch-route preference and the single source of truth
 * for the metadata {@code launch:} command EmuFusion emits for a system.
 *
 * Product rule (supersedes the old "internal only" policy): internal emulation
 * is the DEFAULT for every system that has a bundled, release-qualified
 * in-process engine. External emulators are a per-system user choice and are
 * never selected automatically, even if an engine or its prerequisites are
 * unavailable. Missing setup must not redirect a game into a browser or other
 * app. Choosing External installs nothing on its own; the
 * external route only opens the emulator's install source when a matching ROM
 * is present and the emulator is missing.
 */
public final class EngineRouteStore {
    public static final String INTERNAL = "internal";
    public static final String EXTERNAL = "external";

    private static final String PREFS = "engine-routes";
    private static final String ROUTE_PREFIX = "route.";
    private static final String EMULATOR_PREFIX = "emulator.";

    private EngineRouteStore() {}

    private static SharedPreferences prefs(Context context) {
        return context.getApplicationContext()
                .getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    /** True when a bundled, release-qualified internal engine supports the system. */
    public static boolean hasInternalEngine(Context context, String system) {
        return GameLaunchRouter.supportsSystem(context,
                EngineSystemIdResolver.canonical(system));
    }

    /** True when the user has recorded an explicit route for the system. */
    public static boolean isExplicit(Context context, String system) {
        String stored = storedRoute(context, system);
        return INTERNAL.equals(stored) || EXTERNAL.equals(stored);
    }

    private static String storedRoute(Context context, String system) {
        return prefs(context).getString(
                ROUTE_PREFIX + EngineSystemIdResolver.canonical(system), "");
    }

    private static boolean isInternalOnly(String system) {
        return "ps3".equals(EngineSystemIdResolver.canonical(system));
    }

    /**
     * Internal is the default on every device. Only an explicit External choice
     * may leave EmuFusion; engine availability is validated separately.
     */
    public static String resolve(Context context, String system) {
        String canonical = EngineSystemIdResolver.canonical(system);
        // aPS3e is bundled into EmuFusion. A stale preference from an older
        // build must never hand PS3 content to the separate aPS3e package.
        if (isInternalOnly(canonical)) return INTERNAL;
        String stored = storedRoute(context, canonical);
        if (EXTERNAL.equals(stored)) return EXTERNAL;
        return INTERNAL;
    }

    /** The user's chosen external emulator id for a system, or "" for default order. */
    public static String chosenEmulator(Context context, String system) {
        return prefs(context).getString(
                EMULATOR_PREFIX + EngineSystemIdResolver.canonical(system), "");
    }

    /**
     * Records an explicit route. INTERNAL is rejected when no internal engine
     * supports the system; an external emulator id is only stored when it is a
     * real catalog entry for that system. Returns false when the request is
     * invalid so callers never persist an unlaunchable preference.
     */
    public static boolean setRoute(Context context, String system, String route,
                                   String emulatorId) {
        String canonical = EngineSystemIdResolver.canonical(system);
        String normalized = route == null ? "" :
                route.trim().toLowerCase(Locale.US);
        if (!INTERNAL.equals(normalized) && !EXTERNAL.equals(normalized)) return false;
        if (isInternalOnly(canonical) && !INTERNAL.equals(normalized)) return false;
        if (INTERNAL.equals(normalized) && !hasInternalEngine(context, canonical)) return false;
        // A user-defined custom target is a valid external option in its own
        // right, which is what lets a system the curated catalog cannot serve
        // at all still be pointed somewhere by hand.
        if (EXTERNAL.equals(normalized) && !EmulatorCatalog.hasExternalOption(canonical)
                && !CustomEmulatorStore.has(context, canonical))
            return false;

        SharedPreferences.Editor editor = prefs(context).edit();
        editor.putString(ROUTE_PREFIX + canonical, normalized);
        if (EXTERNAL.equals(normalized)) {
            String trimmed = emulatorId == null ? "" : emulatorId.trim();
            if (CustomEmulatorStore.ID.equalsIgnoreCase(trimmed)) {
                // Only storable once the guided setup has proved the target
                // resolves on this device, so "Custom" can never be selected
                // into a state where launching quietly does nothing.
                if (CustomEmulatorStore.option(context, canonical) == null) return false;
                editor.putString(EMULATOR_PREFIX + canonical, CustomEmulatorStore.ID);
            } else if (!trimmed.isEmpty()) {
                if (EmulatorCatalog.optionForId(canonical, trimmed) == null) return false;
                editor.putString(EMULATOR_PREFIX + canonical, trimmed);
            } else {
                editor.remove(EMULATOR_PREFIX + canonical);
            }
        } else { // INTERNAL clears any stale external emulator choice
            editor.remove(EMULATOR_PREFIX + canonical);
        }
        editor.apply();
        return true;
    }

    /** Clears an explicit route, returning the system to its default. */
    public static void clearRoute(Context context, String system) {
        String canonical = EngineSystemIdResolver.canonical(system);
        prefs(context).edit()
                .remove(ROUTE_PREFIX + canonical)
                .remove(EMULATOR_PREFIX + canonical)
                .apply();
    }

    /**
     * The metadata {@code launch:} command for a system, honouring the resolved
     * route. Both the importer's fresh metadata and the on-disk metadata
     * migration route through here so a route change re-emits the correct
     * command everywhere.
     *
     * INTERNAL reuses the stable in-process runtime router (Pegasus runs the
     * {@code am start} that MainActivity intercepts). EXTERNAL emits a normal
     * {@code am start} recipe that Pegasus executes to open the chosen
     * standalone emulator directly into gameplay. An unavailable engine on the
     * chosen route returns ""; it never grants permission to change that route.
     */
    public static String launchCommand(Context context, String system) {
        String canonical = EngineSystemIdResolver.canonical(system);
        if (isInternalOnly(canonical)) {
            return GameLaunchRouter.supportsSystem(context, canonical)
                    ? GameLaunchRouter.metadataCommand(context, canonical) : "";
        }
        if (INTERNAL.equals(resolve(context, canonical))) {
            return GameLaunchRouter.supportsSystem(context, canonical)
                    ? GameLaunchRouter.metadataCommand(context, canonical) : "";
        }
        return EmulatorCatalog.externalLaunchCommand(
                context, canonical, chosenEmulator(context, canonical));
    }
}
