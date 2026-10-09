package com.thorium.preview.cheats;

import android.content.Context;

import com.thorium.lucent.cheats.Cheat;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Set;

/** Exact Game ID lookup for codes distributed with the pinned Dolphin core. */
final class DolphinCheatCatalog {
    static final String ASSET = "cheats/dolphin-cheats.json";
    private static volatile JSONObject cached;

    private DolphinCheatCatalog() {}

    static List<Cheat> forGame(Context context, String gameIdentity) {
        if (context == null || gameIdentity == null || gameIdentity.isEmpty())
            return Collections.emptyList();
        JSONObject root = load(context);
        if (root == null) return Collections.emptyList();
        Set<String> accepted = idsFor(gameIdentity);
        LinkedHashMap<String, Cheat> unique = new LinkedHashMap<>();
        JSONArray games = root.optJSONArray("games");
        if (games == null) return Collections.emptyList();
        for (int i = 0; i < games.length(); i++) {
            JSONObject game = games.optJSONObject(i);
            if (game == null || !accepted.contains(
                    game.optString("gameId", "").toUpperCase(Locale.US))) continue;
            JSONArray cheats = game.optJSONArray("cheats");
            if (cheats == null) continue;
            for (int c = 0; c < cheats.length(); c++) {
                JSONObject value = cheats.optJSONObject(c);
                if (value == null) continue;
                String code = value.optString("code", "").trim();
                String id = value.optString("id", "").trim();
                if (code.isEmpty() || id.isEmpty()) continue;
                String key = code.replaceAll("\\s+", " ").toUpperCase(Locale.US);
                if (unique.containsKey(key)) continue;
                try {
                    unique.put(key, new Cheat(id, value.optString("name", id),
                            value.optString("description", "Dolphin"), code));
                } catch (IllegalArgumentException ignored) {}
            }
        }
        return Collections.unmodifiableList(new ArrayList<>(unique.values()));
    }

    /** Dolphin merges revision, six-character, and three-character INIs. */
    private static Set<String> idsFor(String identity) {
        String clean = identity.trim().toUpperCase(Locale.US);
        Set<String> values = new HashSet<>();
        values.add(clean);
        int revision = clean.indexOf('R', 6);
        String base = revision == 6 ? clean.substring(0, 6) : clean;
        if (base.length() >= 6) {
            values.add(base.substring(0, 6));
            values.add(base.substring(0, 3));
        }
        return values;
    }

    private static JSONObject load(Context context) {
        JSONObject found = cached;
        if (found != null) return found;
        synchronized (DolphinCheatCatalog.class) {
            if (cached != null) return cached;
            try (InputStream input = context.getAssets().open(ASSET);
                 ByteArrayOutputStream output = new ByteArrayOutputStream()) {
                byte[] buffer = new byte[8192];
                int count;
                long total = 0;
                while ((count = input.read(buffer)) >= 0) {
                    total += count;
                    if (total > 8L * 1024L * 1024L) return null;
                    output.write(buffer, 0, count);
                }
                cached = new JSONObject(new String(output.toByteArray(),
                        StandardCharsets.UTF_8));
                return cached;
            } catch (Exception ignored) {
                return null;
            }
        }
    }
}
