package com.thorium.preview.cheats;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.RandomAccessFile;
import java.nio.charset.StandardCharsets;
import java.util.Collections;
import java.util.HashMap;
import java.util.LinkedHashSet;
import java.util.Map;
import java.util.Set;

/**
 * Durable record of which cheats the user switched on, per game.
 *
 * <p>Written atomically (temp file, fsync, rename): a half-written selection
 * that parsed as valid JSON would silently enable a different set of cheats on
 * the next launch, which is worse than losing the change.
 */
public final class CheatStore {

    private final File file;
    private final Map<String, Set<String>> byGame = new HashMap<>();

    public CheatStore(File file) {
        if (file == null) throw new IllegalArgumentException("store file required");
        this.file = file;
        load();
    }

    /** Enabled cheat ids for a game; empty when the game has never been touched. */
    public Set<String> enabledFor(String gameKey) {
        Set<String> found = byGame.get(gameKey);
        return found == null ? Collections.<String>emptySet()
                : Collections.unmodifiableSet(found);
    }

    public void save(String gameKey, Set<String> enabledIds) {
        if (gameKey == null) return;
        if (enabledIds == null || enabledIds.isEmpty()) byGame.remove(gameKey);
        else byGame.put(gameKey, new LinkedHashSet<>(enabledIds));
        persist();
    }

    private void load() {
        byGame.clear();
        if (!file.isFile()) return;
        try {
            byte[] raw = new byte[(int) Math.min(file.length(), 4L * 1024 * 1024)];
            try (RandomAccessFile input = new RandomAccessFile(file, "r")) {
                input.readFully(raw);
            }
            JSONObject root = new JSONObject(new String(raw, StandardCharsets.UTF_8));
            JSONObject games = root.optJSONObject("games");
            if (games == null) return;
            for (java.util.Iterator<String> keys = games.keys(); keys.hasNext(); ) {
                String gameKey = keys.next();
                JSONArray ids = games.optJSONArray(gameKey);
                if (ids == null) continue;
                Set<String> enabled = new LinkedHashSet<>();
                for (int i = 0; i < ids.length(); i++) {
                    String id = ids.optString(i, "");
                    if (!id.isEmpty()) enabled.add(id);
                }
                if (!enabled.isEmpty()) byGame.put(gameKey, enabled);
            }
        } catch (IOException | JSONException | RuntimeException unreadable) {
            // A corrupt store means "no cheats selected", never a crash on boot.
            byGame.clear();
        }
    }

    private void persist() {
        File temp = new File(file.getPath() + ".tmp");
        try {
            JSONObject games = new JSONObject();
            for (Map.Entry<String, Set<String>> entry : byGame.entrySet())
                games.put(entry.getKey(), new JSONArray(entry.getValue()));
            JSONObject root = new JSONObject();
            root.put("schemaVersion", 1);
            root.put("games", games);
            byte[] encoded = root.toString().getBytes(StandardCharsets.UTF_8);
            File parent = file.getParentFile();
            if (parent != null) parent.mkdirs();
            try (FileOutputStream out = new FileOutputStream(temp)) {
                out.write(encoded);
                out.flush();
                out.getFD().sync();
            }
            if (!temp.renameTo(file)) {
                // Rename is the atomic step; without it the old file still
                // holds a complete, valid selection.
                temp.delete();
            }
        } catch (IOException | JSONException | RuntimeException failure) {
            temp.delete();
        }
    }
}
