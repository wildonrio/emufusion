package com.thorium.preview;

import android.content.Context;

import com.thorium.lucent.emulators.ExternalEmulator;
import com.thorium.lucent.emulators.ExternalEmulatorDelivery;
import com.thorium.lucent.emulators.ExternalEmulatorDirectory;
import com.thorium.lucent.metadata.EngineSystemIdResolver;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.List;

/**
 * Everything the Settings "Internal or External" screen asks Java for.
 *
 * The product rule it serves, restated because every method below depends on
 * it: Settings reveals a system only after the library has indexed at least
 * one game for it. Internal emulation is the default when that system has a
 * currently eligible bundled engine; otherwise the imported system exposes
 * only its external route. This class only ever reports and records that
 * choice — resolution itself stays in EngineRouteStore, which remains the
 * single source of truth.
 *
 * The tap flow the user actually performs lives in {@link #link}: one action,
 * whose behaviour depends on whether the emulator is installed. Tapping a
 * missing emulator opens its install source; tapping it again after installing
 * binds it to that system. Two taps, no state for the UI to track, and no way
 * to bind something that is not there.
 */
final class RoutePicker {

    private RoutePicker() {}

    // ---- Reads ---------------------------------------------------------------

    /**
     * Every imported system with its current route, for the settings list.
     * A catalog entry is not user-visible product inventory: until a matching
     * game exists in the live library, the system and all of its emulator
     * choices remain absent from Settings.
     */
    static String systemsJson(Context context, java.util.Set<String> activeFolders) {
        JSONObject response = new JSONObject();
        JSONArray rows = new JSONArray();
        try {
            for (GameSystems.SystemDef system : GameSystems.all()) {
                if (activeFolders == null || !activeFolders.contains(system.folder))
                    continue;
                String canonical = EngineSystemIdResolver.canonical(system.folder);
                boolean internalAvailable =
                        EngineRouteStore.hasInternalEngine(context, canonical);
                String route = EngineRouteStore.resolve(context, canonical);
                EmulatorCatalog.Option effective = EmulatorCatalog.effectiveOption(
                        context, canonical,
                        EngineRouteStore.chosenEmulator(context, canonical));
                boolean external = EngineRouteStore.EXTERNAL.equals(route);
                boolean installed = effective != null && effective.supported()
                        && !effective.installedPackage(context).isEmpty();
                boolean stopReady = ExternalEmulationSession.stopControlEnabled(context);
                JSONObject row = new JSONObject();
                row.put("system", canonical);
                row.put("folder", system.folder);
                row.put("collection", system.collection);
                row.put("active", true);
                row.put("internalAvailable", internalAvailable);
                row.put("route", route);
                row.put("explicit", EngineRouteStore.isExplicit(context, canonical));
                row.put("emulator", external && effective != null ? effective.id : "");
                row.put("emulatorName", external && effective != null ? effective.name : "");
                // "Ready" means launching a game now does something: internal
                // always does; external needs its emulator present.
                row.put("ready", !external || (installed && stopReady));
                row.put("externalStopReady", stopReady);
                rows.put(row);
            }
            response.put("systems", rows);
        } catch (Exception ignored) {}
        return response.toString();
    }

    /**
     * The full picker payload for one system: the Internal choice, every
     * external candidate with its live install state and install destination,
     * and the custom entry.
     */
    static String optionsJson(Context context, String system) {
        String canonical = EngineSystemIdResolver.canonical(system);
        ExternalEmulatorDirectory directory = ExternalEmulatorDirectoryLoader.load(context);
        JSONObject response = new JSONObject();
        try {
            GameSystems.SystemDef definition = GameSystems.byFolder(system);
            if (definition == null) for (GameSystems.SystemDef candidate : GameSystems.all())
                if (EngineSystemIdResolver.canonical(candidate.folder).equals(canonical)) {
                    definition = candidate;
                    break;
                }
            String chosen = EngineRouteStore.chosenEmulator(context, canonical);
            String route = EngineRouteStore.resolve(context, canonical);
            response.put("system", canonical);
            response.put("collection", definition == null ? canonical : definition.collection);
            response.put("internalAvailable",
                    EngineRouteStore.hasInternalEngine(context, canonical));
            response.put("route", route);
            response.put("explicit", EngineRouteStore.isExplicit(context, canonical));
            response.put("chosen", chosen);
            response.put("externalStopReady",
                    ExternalEmulationSession.stopControlEnabled(context));
            // Named verbatim in the UI so choosing External for a system with
            // nothing to offer explains itself instead of showing a blank list.
            response.put("unsupportedReason", directory.unsupportedReason(canonical));

            JSONArray options = new JSONArray();
            for (EmulatorCatalog.Option option : EmulatorCatalog.optionsForSystem(canonical)) {
                if (!option.supported()) continue;
                ExternalEmulatorDirectory.Choice listed =
                        directory.choice(canonical, option.id);
                ExternalEmulator app = listed == null ? null : listed.emulator();
                String installed = option.installedPackage(context);
                JSONObject entry = new JSONObject();
                entry.put("id", option.id);
                entry.put("name", app == null ? option.name : app.name());
                entry.put("installed", !installed.isEmpty());
                entry.put("installedPackage", installed);
                entry.put("selected", option.id.equalsIgnoreCase(chosen));
                entry.put("delivery", option.delivery);
                entry.put("deliveryLabel",
                        ExternalEmulatorDelivery.describe(option.delivery));
                entry.put("install", installJson(option, app));
                // Honest by default: false until a human has confirmed the
                // package id really is that emulator.
                entry.put("verified", app != null && app.verified());
                options.put(entry);
            }
            response.put("options", options);

            JSONObject custom = CustomEmulatorStore.describe(context, canonical);
            custom.put("selected", CustomEmulatorStore.ID.equalsIgnoreCase(chosen));
            custom.put("deliveryOptions", deliveryOptions());
            response.put("custom", custom);
        } catch (Exception ignored) {}
        return response.toString();
    }

    /**
     * The effective route and chosen emulator without the option list — what a
     * caller needs to label one system, or to re-read after a change, without
     * paying for a package-manager query per candidate.
     */
    private static JSONObject resolvedRoute(Context context, String system) {
        String canonical = EngineSystemIdResolver.canonical(system);
        JSONObject response = new JSONObject();
        try {
            String chosen = EngineRouteStore.chosenEmulator(context, canonical);
            EmulatorCatalog.Option effective =
                    EmulatorCatalog.effectiveOption(context, canonical, chosen);
            response.put("system", canonical);
            response.put("route", EngineRouteStore.resolve(context, canonical));
            response.put("explicit", EngineRouteStore.isExplicit(context, canonical));
            response.put("internalAvailable",
                    EngineRouteStore.hasInternalEngine(context, canonical));
            response.put("chosen", chosen);
            response.put("emulator", effective == null ? "" : effective.id);
            response.put("emulatorName", effective == null ? "" : effective.name);
            response.put("externalStopReady",
                    ExternalEmulationSession.stopControlEnabled(context));
        } catch (Exception ignored) {}
        return response;
    }

    static String resolveJson(Context context, String system) {
        return resolvedRoute(context, system).toString();
    }

    /** The three delivery choices, each with wording the guided setup shows. */
    private static JSONArray deliveryOptions() {
        JSONArray kinds = new JSONArray();
        try {
            for (String delivery : new String[] {
                    ExternalEmulatorDelivery.FILE_PATH,
                    ExternalEmulatorDelivery.ACTION_VIEW,
                    ExternalEmulatorDelivery.CONTENT_URI}) {
                kinds.put(new JSONObject()
                        .put("id", delivery)
                        .put("label", ExternalEmulatorDelivery.describe(delivery))
                        // Only the file-path form needs a name for the ROM.
                        .put("needsKey",
                                ExternalEmulatorDelivery.FILE_PATH.equals(delivery)));
            }
        } catch (Exception ignored) {}
        return kinds;
    }

    /**
     * Where a missing emulator is reached. The directory's explicit kind/url is
     * preferred; the compiled catalog's own source is the fallback so an
     * unreadable asset still leaves every emulator installable.
     */
    private static JSONObject installJson(EmulatorCatalog.Option option,
                                          ExternalEmulator app) {
        JSONObject install = new JSONObject();
        try {
            if (app != null) {
                install.put("kind", app.installKind());
                install.put("url", app.installUrl());
                install.put("package", app.primaryPackage());
            } else {
                String uri = EmulatorCatalog.installUri(option);
                install.put("kind", uri.startsWith("market://")
                        ? ExternalEmulator.INSTALL_PLAY : ExternalEmulator.INSTALL_WEB);
                install.put("url", uri);
                List<String> packages = option.packages;
                install.put("package", packages.isEmpty() ? "" : packages.get(0));
            }
            // The Play app is the only thing that can actually install from a
            // Play listing, so a play-kind row carries the market:// form as
            // well; the https url stays as the fallback for a device with no
            // Play Store, where it opens in EmuFusion's own browser instead.
            String packageId = install.optString("package", "");
            if (ExternalEmulator.INSTALL_PLAY.equals(install.optString("kind"))
                    && !packageId.isEmpty())
                install.put("marketUrl", "market://details?id=" + packageId);
        } catch (Exception ignored) {}
        return install;
    }

    // ---- Writes --------------------------------------------------------------

    /**
     * Records an explicit route. Refusals are reported with a reason rather
     * than a bare false, because every one of them is a sentence the UI has to
     * be able to show: there is no engine, there is no emulator, the custom
     * entry has not been set up.
     */
    static JSONObject setRoute(Context context, String system, String route,
                               String emulator) {
        String canonical = EngineSystemIdResolver.canonical(system);
        JSONObject response = new JSONObject();
        try {
            response.put("system", canonical);
            if (EngineRouteStore.EXTERNAL.equalsIgnoreCase(route) &&
                    !ExternalEmulationSession.stopControlEnabled(context)) {
                response.put("ok", false);
                response.put("authorizationRequired", true);
                response.put("reason", "Authorize EmuFusion's external game return once, then select this option again.");
                return response;
            }
            boolean ok = EngineRouteStore.setRoute(context, canonical, route, emulator);
            response.put("ok", ok);
            if (!ok) response.put("reason", refusal(context, canonical, route, emulator));
            response.put("route", EngineRouteStore.resolve(context, canonical));
            response.put("chosen", EngineRouteStore.chosenEmulator(context, canonical));
        } catch (Exception ignored) {}
        return response;
    }

    private static String refusal(Context context, String canonical, String route,
                                  String emulator) {
        if (EngineRouteStore.INTERNAL.equalsIgnoreCase(route))
            return "There is no built-in engine for this system yet.";
        if (CustomEmulatorStore.ID.equalsIgnoreCase(emulator == null ? "" : emulator.trim()))
            return CustomEmulatorStore.has(context, canonical)
                    ? "That custom emulator is no longer installed. Set it up again."
                    : "Set up the custom emulator first.";
        if (!EmulatorCatalog.hasExternalOption(canonical))
            return "No standalone Android emulator is available for this system.";
        return "That emulator is not one of this system's options.";
    }

    static JSONObject clearRoute(Context context, String system) {
        String canonical = EngineSystemIdResolver.canonical(system);
        JSONObject response;
        try {
            EngineRouteStore.clearRoute(context, canonical);
            // Share the /route/resolve projection so the mutation response and
            // its read-back cannot drift as fields are added. The route store
            // remains the only place that decides what "automatic" means.
            response = resolvedRoute(context, canonical);
            response.put("ok", true);
        } catch (Exception error) {
            response = new JSONObject();
            try {
                response.put("ok", false);
                response.put("system", canonical);
                response.put("reason", "The automatic route could not be restored.");
            } catch (Exception ignored) {}
        }
        return response;
    }

    /**
     * The tap.
     *
     * Installed → the emulator becomes this system's external emulator and the
     * route switches to External, for this system only.
     *
     * Not installed → nothing is recorded and the caller is told where to send
     * the user. Coming back and tapping the same row runs this again, finds the
     * package present, and binds it. That re-check is the whole point: install
     * state is read fresh on every tap, never cached from the first one.
     */
    static JSONObject link(Context context, String system, String emulatorId) {
        String canonical = EngineSystemIdResolver.canonical(system);
        JSONObject response = new JSONObject();
        try {
            response.put("system", canonical);
            response.put("emulator", emulatorId);
            EmulatorCatalog.Option option =
                    EmulatorCatalog.resolvedOptionForId(context, canonical, emulatorId);
            if (option == null || !option.supported()) {
                response.put("ok", false);
                response.put("linked", false);
                response.put("reason", CustomEmulatorStore.ID.equalsIgnoreCase(
                        emulatorId == null ? "" : emulatorId.trim())
                        ? "Set up the custom emulator first."
                        : "That emulator is not one of this system's options.");
                return response;
            }
            response.put("name", option.name);
            String installed = option.installedPackage(context);
            if (installed.isEmpty()) {
                ExternalEmulatorDirectory.Choice listed = ExternalEmulatorDirectoryLoader
                        .load(context).choice(canonical, option.id);
                response.put("ok", true);
                response.put("linked", false);
                response.put("install",
                        installJson(option, listed == null ? null : listed.emulator()));
                response.put("message", option.name + " is not installed yet.");
                return response;
            }
            if (!ExternalEmulationSession.stopControlEnabled(context)) {
                response.put("ok", true);
                response.put("linked", false);
                response.put("authorizationRequired", true);
                response.put("message", "Authorize EmuFusion's external game return once, then select this emulator again.");
                return response;
            }
            boolean stored = EngineRouteStore.setRoute(
                    context, canonical, EngineRouteStore.EXTERNAL, option.id);
            response.put("ok", stored);
            response.put("linked", stored);
            response.put("installedPackage", installed);
            response.put("route", EngineRouteStore.resolve(context, canonical));
            if (!stored)
                response.put("reason", refusal(context, canonical,
                        EngineRouteStore.EXTERNAL, option.id));
        } catch (Exception ignored) {}
        return response;
    }
}
