package com.thorium.preview;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;

/** Direct-game fallback for an internal native adapter's prerequisite failure. */
public final class ExternalGameFallback {
    private ExternalGameFallback() {}

    /**
     * Launches the installed, already-selected/default Switch emulator through
     * the exact same content-URI trampoline as normal external metadata.
     * Returns false rather than opening an emulator menu or inventing a target.
     */
    public static boolean launchSwitch(Context context, String path) {
        if (context == null || path == null || path.trim().isEmpty() ||
                !ExternalEmulationSession.stopControlEnabled(context)) return false;
        EmulatorCatalog.Option option = switchOption(context);
        if (option == null) return false;
        String installed = option.installedPackage(context);
        if (installed.isEmpty()) return false;
        Intent request = new Intent(RomLaunchActivity.ACTION_LAUNCH_FILE)
                .setClass(context, RomLaunchActivity.class)
                .putExtra("path", path)
                .putExtra("target_package", installed)
                .putExtra("target_activity", option.component)
                .putExtra("target_action", option.action);
        if (!(context instanceof Activity))
            request.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        try {
            context.startActivity(request);
            return true;
        } catch (RuntimeException ignored) {
            return false;
        }
    }

    public static boolean canLaunchSwitch(Context context) {
        if (!ExternalEmulationSession.stopControlEnabled(context)) return false;
        EmulatorCatalog.Option option = switchOption(context);
        return option != null && !option.installedPackage(context).isEmpty();
    }

    private static EmulatorCatalog.Option switchOption(Context context) {
        // A prior in-window failure does not authorize launching another app.
        // Recheck the user's explicit choice even when an external emulator is
        // installed and its accessibility return control is already enabled.
        if (context == null || !EngineRouteStore.isExplicit(context, "switch") ||
                !EngineRouteStore.EXTERNAL.equals(
                        EngineRouteStore.resolve(context, "switch"))) return null;
        String chosen = EngineRouteStore.chosenEmulator(context, "switch");
        EmulatorCatalog.Option option = EmulatorCatalog.effectiveOption(
                context, "switch", chosen);
        if (option == null || !option.supported() ||
                !"content-uri".equals(option.delivery)) return null;
        return option;
    }
}
