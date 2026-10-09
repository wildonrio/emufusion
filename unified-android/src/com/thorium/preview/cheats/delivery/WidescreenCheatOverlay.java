package com.thorium.preview.cheats.delivery;

import com.thorium.lucent.cheats.CheatSelection;
import com.thorium.preview.cheats.CheatStore;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

/**
 * The widescreen hack expressed as cheats, for the systems where the true
 * geometry change is a catalogue code (GameCube, Wii, PSP).
 *
 * <p>Switching the hack on enables exactly one widescreen row for the game
 * -- {@link WidescreenCheatPick} chooses among however many variants the
 * merged catalogue offers, since they are mutually exclusive fixes for the
 * same thing -- and remembers which id it touched in
 * {@code files/cheats/widescreen-auto.json}; switching it off disables that
 * one, and never one the user enabled by hand. The record is what keeps the
 * two directions symmetrical, and what lets a later launch keep the same
 * variant on rather than re-picking.
 */
final class WidescreenCheatOverlay {
    static final String FILE_NAME = "widescreen-auto.json";

    private WidescreenCheatOverlay() {}

    /**
     * Brings the stored selection in line with the hack setting.
     *
     * @return the enabled ids after the change
     */
    static Set<String> apply(File cheatDirectory, CheatStore store, String gameKey,
                             List<DeliveryCheat> rows, CheatSelection selection, boolean hackOn) {
        File record = new File(cheatDirectory, FILE_NAME);
        Set<String> previouslyAuto = readRecord(record, gameKey);
        Set<String> auto = new LinkedHashSet<>();
        boolean changed = false;
        if (hackOn) {
            List<DeliveryCheat> candidates = WidescreenCheatPick.candidates(rows);
            String chosen = WidescreenCheatPick.choose(candidates, previouslyAuto, selection);
            if (chosen != null) {
                if (!selection.isEnabled(chosen)) {
                    selection.setEnabled(chosen, true);
                    changed = true;
                }
                auto.add(chosen);
            }
            // Retire a sibling variant this overlay enabled on an earlier
            // launch now that a different one was chosen; a variant the
            // player switched on by hand was never recorded here, so it is
            // never touched.
            for (String id : previouslyAuto) {
                if (id.equals(chosen)) continue;
                if (selection.isEnabled(id)) {
                    selection.setEnabled(id, false);
                    changed = true;
                }
            }
        } else {
            for (String id : previouslyAuto) {
                if (selection.isEnabled(id)) {
                    selection.setEnabled(id, false);
                    changed = true;
                }
            }
        }
        if (changed) store.save(gameKey, selection.enabledIds());
        if (!auto.equals(previouslyAuto)) writeRecord(record, gameKey, auto);
        return selection.enabledIds();
    }

    static Set<String> readRecord(File record, String gameKey) {
        Set<String> ids = new LinkedHashSet<>();
        if (!record.isFile()) return ids;
        try {
            JSONObject root = new JSONObject(OwnedFiles.readText(record, 1024 * 1024));
            JSONArray list = root.optJSONObject("games") == null ? null
                    : root.optJSONObject("games").optJSONArray(gameKey);
            if (list == null) return ids;
            for (int i = 0; i < list.length(); i++) {
                String id = list.optString(i, "");
                if (!id.isEmpty()) ids.add(id);
            }
        } catch (IOException | JSONException | RuntimeException unreadable) {
            ids.clear();
        }
        return ids;
    }

    static void writeRecord(File record, String gameKey, Set<String> ids) {
        try {
            JSONObject root;
            try {
                root = record.isFile() ? new JSONObject(OwnedFiles.readText(record, 1024 * 1024))
                        : new JSONObject();
            } catch (JSONException | IOException corrupt) {
                root = new JSONObject();
            }
            JSONObject games = root.optJSONObject("games");
            if (games == null) games = new JSONObject();
            if (ids.isEmpty()) games.remove(gameKey);
            else games.put(gameKey, new JSONArray(ids));
            root.put("schemaVersion", 1);
            root.put("games", games);
            File parent = record.getParentFile();
            if (parent != null) parent.mkdirs();
            File temp = new File(record.getPath() + ".tmp");
            try (FileOutputStream out = new FileOutputStream(temp)) {
                out.write(root.toString().getBytes(StandardCharsets.UTF_8));
                out.flush();
                out.getFD().sync();
            }
            if (!temp.renameTo(record)) temp.delete();
        } catch (IOException | JSONException | RuntimeException failure) {
            // The record is a convenience for symmetry; losing it costs one
            // manual toggle, never a launch.
        }
    }
}
