package com.thorium.preview.game;

import android.content.Context;
import android.content.SharedPreferences;
import android.util.Log;

import com.thorium.preview.LibretroHost;

/** One running game's Widescreen Hack: the player's choice, remembered per game. */
public final class WidescreenSession {
    private static final String TAG = "WidescreenSession";
    private static final String PREFS = "widescreen-hack-v1";

    public final WidescreenRecipes.Recipe recipe;
    private final SharedPreferences prefs;
    private final String prefKey;
    private volatile boolean enabled;
    // Frame thread only.
    private int appliedWidth = -1;

    WidescreenSession(Context context, WidescreenRecipes.Recipe recipe, String gameTitle,
                      String qualificationSession) {
        this.recipe = recipe;
        prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        prefKey = prefKey(recipe, gameTitle, qualificationSession);
        enabled = prefs.getBoolean(prefKey, false);
    }

    private static String prefKey(WidescreenRecipes.Recipe recipe, String gameTitle,
                                  String qualificationSession) {
        return (qualificationSession == null || qualificationSession.isEmpty()
                ? "" : "qa:" + qualificationSession + ":") + recipe.system + "/" +
                com.thorium.emufusion.metadata.TitleMatcher.normalize(gameTitle);
    }

    /** The player's choice for this game, before any session exists. */
    static boolean remembered(Context context, WidescreenRecipes.Recipe recipe, String gameTitle,
                              String qualificationSession) {
        return context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getBoolean(
                prefKey(recipe, gameTitle, qualificationSession), false);
    }

    public boolean isEnabled() { return enabled; }

    public void setEnabled(boolean on) {
        enabled = on;
        // Written at once when the game restarts on it: the next launch reads this file.
        if (recipe.relaunch) prefs.edit().putBoolean(prefKey, on).commit();
        else prefs.edit().putBoolean(prefKey, on).apply();
    }

    /** Called before each core frame; the core picks a new width up on that frame. */
    void applyBeforeFrame(LibretroHost host, int surfaceWidth, int surfaceHeight) {
        if (recipe.relaunch) return;
        int width = enabled ? recipe.widthFor(surfaceWidth, surfaceHeight) : 0;
        if (width == appliedWidth) return;
        if (host.setCoreOption(recipe.widthOption, Integer.toString(width))) {
            appliedWidth = width;
            Log.i(TAG, "Widescreen " + recipe.key + " width=" + width +
                    " surface=" + surfaceWidth + "x" + surfaceHeight);
        }
    }
}
