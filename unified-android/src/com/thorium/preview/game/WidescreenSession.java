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

    WidescreenSession(Context context, WidescreenRecipes.Recipe recipe, String qualificationSession) {
        this.recipe = recipe;
        prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        prefKey = (qualificationSession == null || qualificationSession.isEmpty()
                ? "" : "qa:" + qualificationSession + ":") + recipe.system + "/" + recipe.key;
        enabled = prefs.getBoolean(prefKey, false);
    }

    public boolean isEnabled() { return enabled; }

    public void setEnabled(boolean on) {
        enabled = on;
        prefs.edit().putBoolean(prefKey, on).apply();
    }

    /** Called before each core frame; the core picks a new width up on that frame. */
    void applyBeforeFrame(LibretroHost host, int surfaceWidth, int surfaceHeight) {
        int width = enabled ? recipe.widthFor(surfaceWidth, surfaceHeight) : 0;
        if (width == appliedWidth) return;
        if (host.setCoreOption(recipe.widthOption, Integer.toString(width))) {
            appliedWidth = width;
            Log.i(TAG, "Widescreen " + recipe.key + " width=" + width +
                    " surface=" + surfaceWidth + "x" + surfaceHeight);
        }
    }
}
