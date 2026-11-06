package com.thorium.preview.game;

import android.content.Context;
import android.util.Log;

import com.thorium.emufusion.metadata.EngineSystemIdResolver;
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
    private static final String STRATEGY_TESTING = "testing";
    private static final String FALLBACK_KEY = "*";
    private static final String QA_ALL_SYSTEMS_GLOBAL = "emufusion_qa_widescreen_all";
    private static volatile Map<String, Recipe> table;

    /** How one game is widened. */
    public static final class Recipe {
        public final String system;
        public final String key;
        public final String engine;
        /** The option carrying the picture width; 0 means the original picture. */
        public final String widthOption;
        /** The option takes the picture's aspect x 1000: the engine's width depends on its video mode. */
        public final boolean widthIsAspect;
        public final int baseWidth;
        public final int height;
        public final float pixelAspect;
        public final float maxAspect;
        /** Only a game the core reports at exactly baseWidth x height can widen: a Game Gear
         * cartridge in Master System mode already shows all the console draws. */
        public final boolean exactBase;
        /** Core options applied at launch, on or off: scene and HUD rules live here. */
        public final Map<String, String> options;
        /** For an engine that reads widescreen only at startup: the choice takes a restart. */
        public final boolean relaunch;
        /** Core options at launch when the player has widescreen on, and off. */
        public final Map<String, String> onOptions;
        public final Map<String, String> offOptions;

        Recipe(String system, String key, String engine, String widthOption, boolean widthIsAspect,
               int baseWidth, int height, float pixelAspect, float maxAspect, boolean exactBase,
               Map<String, String> options, boolean relaunch,
               Map<String, String> onOptions, Map<String, String> offOptions) {
            this.system = system;
            this.key = key;
            this.engine = engine;
            this.widthOption = widthOption;
            this.widthIsAspect = widthIsAspect;
            this.baseWidth = baseWidth;
            this.height = height;
            this.pixelAspect = pixelAspect;
            this.maxAspect = maxAspect;
            this.exactBase = exactBase;
            this.options = Collections.unmodifiableMap(options);
            this.relaunch = relaunch;
            this.onOptions = Collections.unmodifiableMap(onOptions);
            this.offOptions = Collections.unmodifiableMap(offOptions);
        }

        /** Whether this recipe can widen a game the core reports at this size. */
        public boolean fitsCore(int coreWidth, int coreHeight) {
            return !exactBase || (coreWidth == baseWidth && coreHeight == height);
        }

        /** The picture's aspect with widescreen off. */
        public float originalAspect() { return pixelAspect * baseWidth / height; }

        /** Picture width filling this surface, or 0 when the surface has no room to widen. */
        public int widthFor(int surfaceWidth, int surfaceHeight) {
            if (surfaceWidth <= 0 || surfaceHeight <= 0) return 0;
            float aspect = Math.min((float) surfaceWidth / surfaceHeight, maxAspect);
            if (widthIsAspect) return aspect > originalAspect() ? Math.round(aspect * 1000f) : 0;
            int width = Math.round(height * aspect / pixelAspect) & ~1;
            return width > baseWidth ? width : 0;
        }
    }

    private WidescreenRecipes() {}

    /** "Legend of Zelda, The - Link's Awakening" and "The Legend of Zelda: Link's Awakening" match. */
    static String gameKey(String title) {
        return TitleMatcher.normalize(title).replaceAll("\\bthe\\b", " ").trim().replaceAll(" +", " ");
    }

    /** The recipe for this game, or null when it must not be touched. */
    public static Recipe find(Context context, String systemId, String gameName) {
        if (context == null || systemId == null || gameName == null) return null;
        Map<String, Recipe> recipes = table(context);
        // The library says gc where the engines say gamecube.
        String system = EngineSystemIdResolver.canonical(systemId);
        String key = system + "/" + gameKey(gameName);
        if (recipes.containsKey(key)) return recipes.get(key);
        // No entry of its own: the system's recipe for the rest of its library, if it has one.
        return recipes.get(system + "/" + FALLBACK_KEY);
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
        boolean qaAll = android.provider.Settings.Global.getInt(
                context.getContentResolver(), QA_ALL_SYSTEMS_GLOBAL, 0) != 0;
        try (InputStream input = context.getAssets().open(ASSET)) {
            ByteArrayOutputStream bytes = new ByteArrayOutputStream();
            byte[] buffer = new byte[16384];
            for (int read; (read = input.read(buffer)) > 0; ) bytes.write(buffer, 0, read);
            parse(new JSONObject(new String(bytes.toByteArray(), StandardCharsets.UTF_8)), result, qaAll);
        } catch (Exception unreadable) {
            // A damaged table leaves every game as it was.
            Log.w(TAG, "Widescreen recipes unavailable", unreadable);
        }
        return Collections.unmodifiableMap(result);
    }

    static void parse(JSONObject root, Map<String, Recipe> into, boolean qaAll) throws Exception {
        JSONObject systems = root.getJSONObject("systems");
        for (Iterator<String> names = systems.keys(); names.hasNext(); ) {
            String system = names.next();
            JSONObject entry = systems.getJSONObject(system);
            // A system reaches players only once it has passed on a real device.
            if (!entry.optBoolean("release", false) && !qaAll) continue;
            JSONObject games = entry.getJSONObject("games");
            for (Iterator<String> keys = games.keys(); keys.hasNext(); ) {
                String title = keys.next();
                JSONObject game = games.getJSONObject(title);
                String key = gameKey(title);
                // Tested and left alone: keep the key, so the system's fallback can't take it.
                String strategy = game.optString("strategy");
                // "testing": widens only on a QA run, so a title can be judged before players get it.
                into.put(system + "/" + key, STRATEGY_WIDEN.equals(strategy) ||
                        (qaAll && STRATEGY_TESTING.equals(strategy))
                        ? recipe(system, key, entry, game) : null);
            }
            JSONObject fallback = entry.optJSONObject("fallback");
            if (fallback != null && STRATEGY_WIDEN.equals(fallback.optString("strategy")))
                into.put(system + "/" + FALLBACK_KEY, recipe(system, FALLBACK_KEY, entry, fallback));
        }
    }

    private static Recipe recipe(String system, String key, JSONObject entry, JSONObject game)
            throws Exception {
        Map<String, String> options = new LinkedHashMap<>();
        copyStrings(entry.optJSONObject("options"), options);
        copyStrings(game.optJSONObject("options"), options);
        Map<String, String> onOptions = new LinkedHashMap<>();
        copyStrings(entry.optJSONObject("onOptions"), onOptions);
        copyStrings(game.optJSONObject("onOptions"), onOptions);
        Map<String, String> offOptions = new LinkedHashMap<>();
        copyStrings(entry.optJSONObject("offOptions"), offOptions);
        copyStrings(game.optJSONObject("offOptions"), offOptions);
        return new Recipe(system, key,
                game.optString("engine", entry.getString("engine")),
                entry.optString("widthOption", ""), entry.optBoolean("widthIsAspect", false),
                entry.getInt("baseWidth"), entry.getInt("height"),
                (float) entry.getDouble("pixelAspect"),
                (float) game.optDouble("maxAspect", entry.optDouble("maxAspect", 2.4)),
                entry.optBoolean("exactBase", false),
                options, entry.optBoolean("relaunch", false), onOptions, offOptions);
    }

    private static void copyStrings(JSONObject from, Map<String, String> into) throws Exception {
        if (from == null) return;
        for (Iterator<String> keys = from.keys(); keys.hasNext(); ) {
            String key = keys.next();
            into.put(key, from.getString(key));
        }
    }
}
