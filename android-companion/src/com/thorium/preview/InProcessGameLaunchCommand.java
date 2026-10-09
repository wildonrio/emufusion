package com.thorium.preview;

import android.app.Activity;
import android.content.Intent;
import android.util.Log;

import com.thorium.preview.game.InWindowGameHost;

/** Intercepts EmuFusion's internal `am start` syntax before any Activity starts. */
public final class InProcessGameLaunchCommand {
    private static final String TAG = "LucentLaunchCommand";
    private static final String COMPONENT =
            "com.thorium.preview/org.pegasus_frontend.android.MainActivity";

    private InProcessGameLaunchCommand() {}

    /**
     * Returns true only when this command belongs to EmuFusion's internal game
     * route. The inherited Pegasus launcher falls through unchanged for every
     * other Android command. A recognized but invalid internal command is
     * consumed and rejected; it must never fall through to startActivity.
     */
    public static boolean tryLaunch(String[] arguments) {
        if (arguments == null || arguments.length == 0 ||
                !"start".equalsIgnoreCase(arguments[0])) return false;
        String action = "";
        String component = "";
        Intent request = new Intent();
        for (int index = 1; index < arguments.length; index++) {
            String token = arguments[index] == null ? "" : arguments[index];
            if (("-a".equals(token) || "--action".equals(token)) &&
                    index + 1 < arguments.length) {
                action = clean(arguments[++index]);
            } else if (("-n".equals(token) || "--component".equals(token)) &&
                    index + 1 < arguments.length) {
                component = clean(arguments[++index]);
            } else if ("--es".equals(token) && index + 2 < arguments.length) {
                String key = clean(arguments[++index]);
                String value = arguments[++index] == null ? "" : arguments[index];
                if (!key.isEmpty()) request.putExtra(key, value);
            }
        }
        if (!InWindowGameHost.ACTION_LAUNCH.equals(action)) return false;
        if (!COMPONENT.equals(component)) {
            Log.e(TAG, "Rejected internal launch with a foreign component");
            return true;
        }
        Activity activity = LucentApplication.currentMainActivity();
        if (activity == null) {
            Log.e(TAG, "Rejected internal launch because MainActivity is not live");
            return true;
        }
        request.setAction(action);
        Log.i(TAG, "Intercepted lifecycle-neutral menu launch");
        activity.runOnUiThread(() -> {
            if (!InWindowGameHost.handleIntent(activity, request))
                Log.e(TAG, "Internal launch action was not handled");
        });
        return true;
    }

    private static String clean(String value) {
        return value == null ? "" : value.trim();
    }
}
