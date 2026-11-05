package com.thorium.preview.game;

import android.content.Context;
import android.util.Log;

import com.thorium.emufusion.metadata.TitleMatcher;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.Collections;
import java.util.HashMap;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * The Widescreen Hack's per-game table (docs/widescreen/WIDESCREEN-HACK-PLAN.md).
 *
 * <p>A game is looked up by its normalized title, so every region and revision of it
 * shares one entry. Only a game whose entry widens gets a recipe: a game with no entry,
 * or one tested and marked fixed-screen or already widescreen, is left exactly as it was.
 */
public final class WidescreenRecipes {
    private static final String TAG = "WidescreenRecipes";
    static final String ASSET = "widescreen-recipes.json";
    private static final String STRATEGY_WIDEN = "widen";
    private static volatile Map<String, Recipe> table;

    /** How one game is widened. */
    public static final class Recipe {
        public final String system;
        public final String key;
        public final String engine;
        /** The option carrying the picture width; 0 means the original picture. */
        public final String widthOption;
        public final int baseWidth;
        public final int height;
        public final float pixelAspect;
        public final float maxAspect;
        /** Core options applied at launch, on or off: scene and HUD rules live here. */
        public final Map<String, String> options;

        Recipe(String system, String key, String engine, String widthOption, int baseWidth,
               int height, float pixelAspect, float maxAspect, Map<String, String> options) {
            this.system = system;
            this.key = key;
            this.engine = engine;
            this.widthOption = widthOption;
            this.baseWidth = baseWidth;
            this.height = height;
            this.pixelAspect = pixelAspect;
            this.maxAspect = maxAspect;
            this.options = Collections.unmodifiableMap(options);
        }

        /** The picture's aspect with widescreen off. */
        public float originalAspect() { return pixelAspect * baseWidth / height; }

        /** Picture width filling this surface, or 0 when the surface has no room to widen. */
        public int widthFor(int surfaceWidth, int surfaceHeight) {
            if (surfaceWidth <= 0 || surfaceHeight <= 0) return 0;
            float aspect = Math.min((float) surfaceWidth / surfaceHeight, maxAspect);
            int width = Math.round(height * aspect / pixelAspect) & ~1;
            return width > baseWidth ? width : 0;
        }
    }

    private WidescreenRecipes() {}

    /** The recipe for this game, or null when it must not be touched. */
    public static Recipe find(Context context, String systemId, String gameName) {
        if (context == null || systemId == null || gameName == null) return null;
        return table(context).get(systemId + "/" + TitleMatcher.normalize(gameName));
    }

    private static Map<String, Recipe> table(Context context) {
        Map<String, Recipe> loaded = table;
        if (loaded != null) return loaded;
        synchronized (WidescreenRecipes.class) {
            if (table == null) table = load(context.getApplicationContext());
            return table;
        }
    }

    private static Map<String, Recipe> load(Context context) {
        Map<String, Recipe> result = new HashMap<>();
        try (InputStream input = context.getAssets().open(ASSET)) {
            ByteArrayOutputStream bytes = new ByteArrayOutputStream();
            byte[] buffer = new byte[16384];
            for (int read; (read = input.read(buffer)) > 0; ) bytes.write(buffer, 0, read);
            parse(new JSONObject(new String(bytes.toByteArray(), StandardCharsets.UTF_8)), result);
        } catch (Exception unreadable) {
            // A damaged table leaves every game as it was.
            Log.w(TAG, "Widescreen recipes unavailable", unreadable);
        }
        return Collections.unmodifiableMap(result);
    }

    static void parse(JSONObject root, Map<String, Recipe> into) throws Exception {
        JSONObject systems = root.getJSONObject("systems");
        for (Iterator<String> names = systems.keys(); names.hasNext(); ) {
            String system = names.next();
            JSONObject entry = systems.getJSONObject(system);
            JSONObject games = entry.getJSONObject("games");
            for (Iterator<String> keys = games.keys(); keys.hasNext(); ) {
                String title = keys.next();
                JSONObject game = games.getJSONObject(title);
                if (!STRATEGY_WIDEN.equals(game.optString("strategy"))) continue;
                Map<String, String> options = new LinkedHashMap<>();
                copyStrings(entry.optJSONObject("options"), options);
                copyStrings(game.optJSONObject("options"), options);
                String key = TitleMatcher.normalize(title);
                into.put(system + "/" + key, new Recipe(system, key,
                        game.optString("engine", entry.getString("engine")),
                        entry.getString("widthOption"),
                        entry.getInt("baseWidth"), entry.getInt("height"),
                        (float) entry.getDouble("pixelAspect"),
                        (float) game.optDouble("maxAspect", entry.optDouble("maxAspect", 2.4)),
                        options));
            }
        }
    }

    private static void copyStrings(JSONObject from, Map<String, String> into) throws Exception {
        if (from == null) return;
        for (Iterator<String> keys = from.keys(); keys.hasNext(); ) {
            String key = keys.next();
            into.put(key, from.getString(key));
        }
    }
}
