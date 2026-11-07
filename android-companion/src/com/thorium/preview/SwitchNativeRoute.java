package com.thorium.preview;

import android.content.ComponentName;
import android.content.Context;
import android.content.pm.PackageManager;
import android.os.Build;

import com.thorium.emufusion.metadata.EngineSystemIdResolver;

/**
 * The route of the Nintendo Switch (Native) and Nintendo Switch 2 systems, the one route that
 * does not follow GameLaunchRouter's same-window contract. Their host runs the game's own threads
 * and global state and can only end by ending its process, so it has an Activity in a process of
 * its own; it is still inside this package and starts no other app.
 *
 * Switch 2 games on this route are not yet tested: none has ever run on it.
 *
 * A build made with EMUFUSION_INCLUDE_NXNATIVE=0 declares no Activity, and these systems have no
 * route. The host library needs Android 11.
 */
final class SwitchNativeRoute {
    private static final String ACTIVITY = "com.thorium.nxnative.NxActivity";
    private static final int MINIMUM_SDK = 30;

    private SwitchNativeRoute() {}

    static boolean handles(String system) {
        String canonical = EngineSystemIdResolver.canonical(system);
        return "switchnative".equals(canonical) || "switch2".equals(canonical);
    }

    static boolean bundled(Context context) {
        if (Build.VERSION.SDK_INT < MINIMUM_SDK) return false;
        try {
            context.getPackageManager().getActivityInfo(
                    new ComponentName(context.getPackageName(), ACTIVITY), 0);
            return true;
        } catch (PackageManager.NameNotFoundException absent) {
            return false;
        }
    }

    static String command(Context context) {
        return "am start -n " + context.getPackageName() + "/" + ACTIVITY
                + " --es nxpack \"{file.path}\"";
    }
}
