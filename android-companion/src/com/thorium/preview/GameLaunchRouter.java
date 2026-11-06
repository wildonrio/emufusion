package com.thorium.preview;

import android.content.Context;

import com.thorium.preview.game.InWindowGameHost;
import com.thorium.preview.game.InternalEngineCatalog;
import com.thorium.preview.game.NativeAdapterCatalog;
import com.thorium.preview.game.Phase2QualificationCatalog;
import com.thorium.emufusion.metadata.EngineSystemIdResolver;
import com.thorium.emufusion.metadata.MetadataGameLaunchCommand;

/**
 * Builds EmuFusion's only supported game-launch route.
 *
 * A game may launch only when an approved in-process engine is packaged and
 * available for its system. Pegasus accepts only {@code am start} metadata on
 * Android, so EmuFusion intercepts its exact internal action inside the inherited
 * launchAmCommand method before startActivity. No Activity lifecycle
 * transition, router Activity, emulator Activity, second task, or external
 * package participates in emulation.
 */
public final class GameLaunchRouter {
    private GameLaunchRouter() {}

    public static boolean supportsSystem(Context context, String system) {
        if (isSwitchNative(system)) return switchNativeBundled(context);
        return !engineIdForSystem(context, system).isEmpty();
    }

    private static boolean isSwitchNative(String system) {
        String canonical = EngineSystemIdResolver.canonical(system);
        return "switchnative".equals(canonical) || "switch2".equals(canonical);
    }

    /**
     * The one route that does not follow the same-window contract above. The Switch
     * (Native) and Switch 2 systems' host runs the game's own threads and global state
     * and can only end by ending its process, so it has an Activity in a process of its
     * own; it is still inside this package and starts no other app. A build made with
     * EMUFUSION_INCLUDE_NXNATIVE=0 declares no Activity, and these systems have no route.
     */
    private static boolean switchNativeBundled(Context context) {
        if (android.os.Build.VERSION.SDK_INT < 30) return false;
        try {
            context.getPackageManager().getActivityInfo(new android.content.ComponentName(
                    context.getPackageName(), SWITCH_NATIVE_ACTIVITY), 0);
            return true;
        } catch (android.content.pm.PackageManager.NameNotFoundException absent) {
            return false;
        }
    }

    private static final String SWITCH_NATIVE_ACTIVITY = "com.thorium.nxnative.NxActivity";

    public static String metadataCommand(Context context, String system) {
        String canonical = EngineSystemIdResolver.canonical(system);
        if (isSwitchNative(canonical)) {
            return "am start -n " + context.getPackageName() + "/" + SWITCH_NATIVE_ACTIVITY
                    + " --es nxpack \"{file.path}\"";
        }
        String engineId = engineIdForSystem(context, canonical);
        return MetadataGameLaunchCommand.build(
                canonical, engineId, InWindowGameHost.ACTION_LAUNCH);
    }

    private static String engineIdForSystem(Context context, String system) {
        String normalized = EngineSystemIdResolver.canonical(system);
        InternalEngineCatalog.Entry release =
                InternalEngineCatalog.availableForSystem(context, normalized);
        if (release != null) return release.id;
        String phase2 =
                Phase2QualificationCatalog.libraryEngineIdForSystem(context, normalized);
        if (!phase2.isEmpty()) return phase2;
        // Phase 3 native-adapter engines resolve INTERNAL only when the adapter
        // .so is bundled and hash-verified. Switch (Eden) and Wii U (Cemu) both
        // do so in an opted-in qualification build, each behind its own flag:
        // EMUFUSION_INCLUDE_PHASE3_EDEN=1 and EMUFUSION_INCLUDE_PHASE3_CEMU=1. A build
        // that omits a flag bundles no adapter for that engine, the catalog has
        // no entry. A missing bundled engine is not permission to switch apps.
        String nativeAdapter =
                NativeAdapterCatalog.libraryEngineIdForSystem(context, normalized);
        // Availability describes the verified APK, not this device's saved
        // readiness flag. A fresh install has no flag; hiding a bundled engine
        // here used to turn Switch launches into browser/download intents.
        // The adapter independently validates user-supplied inputs at launch.
        return nativeAdapter;
    }
}
