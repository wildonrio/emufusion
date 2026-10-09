package com.thorium.preview.game;

import android.app.Activity;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;

/** Persists a recovery target while preserving the live Pegasus task whenever possible. */
public final class SessionReturnRouter {
    public static final String ACTION_RETURNED = "com.thorium.preview.GAME_SESSION_RETURNED";
    private static final String PREFS = "lucent-game-session";
    private static final String PEGASUS_ACTIVITY = "org.pegasus_frontend.android.MainActivity";

    private SessionReturnRouter() {}

    public static void remember(Context context, SessionReturnState state) {
        SharedPreferences.Editor edit = context.getSharedPreferences(PREFS, 0).edit();
        edit.putString("view", state.view)
                .putString("system", state.systemId)
                .putString("section", state.section)
                .putString("sort", state.sort)
                .putString("game", state.gameId)
                .putInt("system_index", state.systemIndex)
                .putInt("game_index", state.gameIndex)
                .putString("token", state.navigationToken)
                .apply();
    }

    public static SessionReturnState peek(Context context) {
        SharedPreferences preferences = context.getSharedPreferences(PREFS, 0);
        return new SessionReturnState(
                preferences.getString("view", ""),
                preferences.getString("system", ""),
                preferences.getString("section", ""),
                preferences.getString("sort", ""),
                preferences.getString("game", ""),
                preferences.getInt("system_index", -1),
                preferences.getInt("game_index", -1),
                preferences.getString("token", ""));
    }

    public static void finishToEmuFusion(Activity activity, SessionReturnState state) {
        remember(activity, state);
        Intent returned = new Intent(ACTION_RETURNED).setPackage(activity.getPackageName());
        state.putInto(returned);
        activity.sendBroadcast(returned);
        activity.setResult(Activity.RESULT_OK, returned);

        // The common path simply uncovers the still-live Pegasus activity and
        // therefore retains its exact QML navigation and scroll state.
        if (!activity.isTaskRoot()) {
            activity.finish();
            return;
        }

        // Recovery path for process/task recreation. The theme can consume the
        // persisted state or navigation token after Pegasus becomes active.
        Intent frontend = new Intent(Intent.ACTION_MAIN)
                .setComponent(new ComponentName(activity.getPackageName(), PEGASUS_ACTIVITY))
                .addCategory(Intent.CATEGORY_LAUNCHER)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_REORDER_TO_FRONT);
        state.putInto(frontend);
        activity.startActivity(frontend);
        activity.finish();
    }
}
