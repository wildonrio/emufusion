package com.thorium.preview.cheats;

import android.content.Context;
import android.util.Log;

import com.thorium.lucent.cheats.Cheat;
import com.thorium.lucent.cheats.CheatDatabase;
import com.thorium.lucent.metadata.EngineSystemIdResolver;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Loads the cheat catalogue: the bundled database first, then a user file that
 * overrides it per game.
 *
 * <p>The parser lives here rather than in {@link CheatDatabase} so the model and
 * its title matching stay free of Android and org.json, and therefore testable
 * on the host with no SDK.
 *
 * <p>A malformed game or cheat is skipped rather than failing the load: one bad
 * code must not cost the user every other game's cheats.
 */
public final class CheatCatalog {

    private static final String TAG = "EmuFusionCheats";
    /** Packaged with the app; the shipped starting point. */
    public static final String BUNDLED_ASSET = "cheats/cheat-database.json";
    /** Dropped in by the user; entries here replace bundled ones per game. */
    public static final String USER_FILE = "cheats.json";

    private CheatCatalog() {}

    public static CheatDatabase load(Context context, File userDirectory) {
        Map<CheatDatabase.GameId, List<Cheat>> games = new HashMap<>(bundled(context));
        if (userDirectory != null) {
            File user = new File(userDirectory, USER_FILE);
            if (user.isFile()) merge(games, readFile(user));
        }
        return CheatDatabase.of(games);
    }

    /**
     * Resolves one game without expanding the downloaded multi-system archive.
     * Bundled and downloaded rows are aggregated and deduplicated by their
     * normalized code body. A user-authored entry remains an explicit override
     * for that game, preserving the pre-download behavior of {@link #load}.
     */
    public static List<Cheat> forGame(Context context, File userDirectory,
                                      String system, String title,
                                      String contentName) {
        return forGame(context, userDirectory, system, title, contentName, "");
    }

    public static List<Cheat> forGame(Context context, File userDirectory,
                                      String system, String title,
                                      String contentName, String contentIdentity) {
        String canonical = EngineSystemIdResolver.canonical(system);
        CheatDatabase.GameId id = new CheatDatabase.GameId(canonical,
                title == null ? "" : title);

        Map<CheatDatabase.GameId, List<Cheat>> bundled = bundled(context);
        List<Cheat> aggregate = new ArrayList<>();
        List<Cheat> starting = bundled.get(id);
        if (starting == null) {
            // GameId equality is intentionally literal while CheatDatabase's
            // public lookup is normalized. Use the model for the actual query.
            starting = CheatDatabase.of(bundled).forGame(canonical, title);
        }
        if (starting != null) aggregate.addAll(starting);

        if ("gamecube".equals(canonical) || "wii".equals(canonical))
            aggregate.addAll(DolphinCheatCatalog.forGame(context, contentIdentity));

        if (userDirectory != null) {
            aggregate.addAll(CheatArchive.forGame(
                    CheatArchive.file(userDirectory), canonical, title, contentName));
            // The per-game file the metadata update downloaded (design
            // 2026-09-06 section 4): merged like every other source, before
            // the user's explicit override, so the engine sessions, the
            // companion list and the in-game panel all see it unchanged.
            aggregate.addAll(downloadedFor(context, canonical, title, contentName));
            File user = new File(userDirectory, USER_FILE);
            if (user.isFile()) {
                Map<CheatDatabase.GameId, List<Cheat>> overrides = new HashMap<>();
                merge(overrides, readFile(user));
                List<Cheat> replacement = CheatDatabase.of(overrides)
                        .forGame(canonical, title);
                if (!replacement.isEmpty()) return deduplicate(replacement);
            }
        }
        return deduplicate(aggregate);
    }

    private static List<Cheat> deduplicate(List<Cheat> values) {
        LinkedHashMap<String, Cheat> unique = new LinkedHashMap<>();
        for (Cheat cheat : values) {
            if (cheat == null) continue;
            String key = cheat.code.trim().replaceAll("\\s+", " ")
                    .toUpperCase(java.util.Locale.US);
            if (!key.isEmpty() && !unique.containsKey(key)) unique.put(key, cheat);
        }
        return java.util.Collections.unmodifiableList(
                new ArrayList<>(unique.values()));
    }

    /**
     * The bundled asset, parsed once per process. It is a constant of the
     * installed APK, and every {@code /cheats/list} request and every engine
     * launch used to re-read and re-parse it on whichever thread asked.
     */
    private static volatile Map<CheatDatabase.GameId, List<Cheat>> bundledCache;

    private static Map<CheatDatabase.GameId, List<Cheat>> bundled(Context context) {
        Map<CheatDatabase.GameId, List<Cheat>> cached = bundledCache;
        if (cached != null) return cached;
        synchronized (CheatCatalog.class) {
            if (bundledCache == null) {
                Map<CheatDatabase.GameId, List<Cheat>> parsed = new HashMap<>();
                merge(parsed, readAsset(context, BUNDLED_ASSET));
                // A null context (host tests) yields nothing; do not cache
                // that as the app's answer.
                if (context == null) return parsed;
                bundledCache = java.util.Collections.unmodifiableMap(parsed);
            }
            return bundledCache;
        }
    }

    /**
     * Rows from {@code files/cheats/downloaded/<system>/<title>.json}, trying
     * the content file's stem when the title file is absent: the downloader
     * ran on the file name the game had at import, and a later rename in
     * the library must not hide the cheats it fetched.
     */
    private static List<Cheat> downloadedFor(Context context, String canonical, String title,
                                             String contentName) {
        if (context == null) return java.util.Collections.emptyList();
        try {
            List<Cheat> rows = com.thorium.preview.cheats.sources.DownloadedCheatFile.read(
                    com.thorium.preview.cheats.sources.DownloadedCheatFile.pathFor(
                            context, canonical, title));
            if (rows.isEmpty() && contentName != null && !contentName.isEmpty())
                rows = com.thorium.preview.cheats.sources.DownloadedCheatFile.read(
                        com.thorium.preview.cheats.sources.DownloadedCheatFile.pathFor(
                                context, canonical, contentName));
            return rows == null ? java.util.Collections.<Cheat>emptyList() : rows;
        } catch (RuntimeException unreadable) {
            Log.w(TAG, "Downloaded cheat file unusable for " + title, unreadable);
            return java.util.Collections.emptyList();
        }
    }

    static void merge(Map<CheatDatabase.GameId, List<Cheat>> into, String json) {
        if (json == null || json.trim().isEmpty()) return;
        try {
            JSONArray games = new JSONObject(json).optJSONArray("games");
            if (games == null) return;
            for (int i = 0; i < games.length(); i++) {
                JSONObject game = games.optJSONObject(i);
                if (game == null) continue;
                String system = game.optString("system", "");
                String title = game.optString("title", "");
                if (system.isEmpty() || title.isEmpty()) continue;
                JSONArray entries = game.optJSONArray("cheats");
                if (entries == null) continue;
                List<Cheat> cheats = new ArrayList<>();
                for (int c = 0; c < entries.length(); c++) {
                    JSONObject entry = entries.optJSONObject(c);
                    if (entry == null) continue;
                    try {
                        cheats.add(new Cheat(entry.optString("id", ""),
                                entry.optString("name", ""),
                                entry.optString("description", ""),
                                entry.optString("code", "")));
                    } catch (IllegalArgumentException unusable) {
                        Log.w(TAG, "Skipped unusable cheat in " + title);
                    }
                }
                // A later source replaces an earlier one wholesale for that
                // game: merging two lists would resurrect entries the user
                // deliberately removed in their own file.
                //
                // The system is canonicalised on the way in because lookups
                // use the engine-facing id a launch carries. Cheat files are
                // written by hand and by other frontends, so "genesis", "gc"
                // and "ds" are at least as common as the canonical spelling,
                // and an unresolved alias is a game whose cheats simply never
                // appear with no error anywhere to explain it.
                if (!cheats.isEmpty())
                    into.put(new CheatDatabase.GameId(
                            EngineSystemIdResolver.canonical(system), title), cheats);
            }
        } catch (JSONException malformed) {
            Log.w(TAG, "Cheat database is not valid JSON; ignoring it", malformed);
        }
    }

    private static String readAsset(Context context, String name) {
        if (context == null) return null;
        try (InputStream input = context.getAssets().open(name)) {
            return readAll(input);
        } catch (IOException absent) {
            // Shipping without a bundled database is legitimate.
            return null;
        }
    }

    private static String readFile(File file) {
        try (InputStream input = new FileInputStream(file)) {
            return readAll(input);
        } catch (IOException unreadable) {
            Log.w(TAG, "Could not read " + file, unreadable);
            return null;
        }
    }

    private static String readAll(InputStream input) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        byte[] chunk = new byte[8192];
        int read;
        long total = 0;
        while ((read = input.read(chunk)) > 0) {
            total += read;
            // A cheat database is text; anything past this is not one, and
            // reading it would be an easy way to exhaust memory at startup.
            if (total > 8L * 1024 * 1024) throw new IOException("cheat database too large");
            out.write(chunk, 0, read);
        }
        return new String(out.toByteArray(), StandardCharsets.UTF_8);
    }
}
