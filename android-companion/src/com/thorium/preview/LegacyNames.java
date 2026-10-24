package com.thorium.preview;

import android.content.Context;
import android.content.SharedPreferences;
import android.os.Build;
import android.util.Log;

import java.io.File;
import java.util.Map;
import java.util.Set;

/**
 * Names this app used before it was renamed EmuFusion, kept in this one place
 * only so an update carries the owner's settings and files across the rename.
 * Nothing writes these names any more; each migration moves an old value or
 * file to its new name once and leaves the new name alone afterwards.
 */
public final class LegacyNames {
    private static final String TAG = "EmuFusionLegacyNames";
    private static final String OLD = "lucent";

    static final String BROWSER_PREFERENCES = OLD + "_browser";
    static final String LEGAL_PREFERENCES = OLD + "-legal";
    static final String SOUND_EFFECTS_KEY = OLD + "_sfx_enabled";
    static final String THEME_DIRECTORY = OLD;
    static final String THEME_VERSION_MARKER = "." + OLD + "-version";
    static final String BUNDLED_THEME_FINGERPRINT = "." + OLD + "-bundled-theme.sha256";
    static final String CONFIG_MIGRATION_MARKER = "." + OLD + "-config-migrated";
    static final String THEME_MEMORY_FILE = OLD + ".json";
    /** QML memory keys were OLD + "Name"; they are now "emufusion" + "Name". */
    static final String THEME_MEMORY_KEY_PREFIX = OLD;
    static final String AUTO_METADATA_PREFIX = "99-" + OLD + "-auto-";
    static final String METADATA_ID_FIELD = "x-" + OLD + "-id";
    /** Provisioning markers (".OLD-firmware-source", ...) in each engine root. */
    private static final String ENGINE_MARKER_PREFIX = "." + OLD + "-";
    /** The downloaded update APK before the rename; only ever deleted. */
    static final String UPDATE_DOWNLOAD = "pegasus-" + OLD + "-update.apk";
    /** Launch-time core-option file each launch regenerates under its new name. */
    private static final String CORE_OPTION_OVERRIDES = OLD + "-core-overrides.txt";

    private LegacyNames() {}

    /**
     * Copies every value of an old preference file into its renamed file when
     * the new one is still empty, then removes the old file.
     */
    static void movePreferences(Context context, String from, String to) {
        try {
            SharedPreferences old = context.getSharedPreferences(from, Context.MODE_PRIVATE);
            Map<String, ?> values = old.getAll();
            if (values.isEmpty()) return;
            SharedPreferences target = context.getSharedPreferences(to, Context.MODE_PRIVATE);
            if (!target.getAll().isEmpty()) return;
            SharedPreferences.Editor editor = target.edit();
            for (Map.Entry<String, ?> entry : values.entrySet()) {
                Object value = entry.getValue();
                String key = entry.getKey();
                if (value instanceof Boolean) editor.putBoolean(key, (Boolean) value);
                else if (value instanceof Integer) editor.putInt(key, (Integer) value);
                else if (value instanceof Long) editor.putLong(key, (Long) value);
                else if (value instanceof Float) editor.putFloat(key, (Float) value);
                else if (value instanceof String) editor.putString(key, (String) value);
                else if (value instanceof Set) {
                    @SuppressWarnings("unchecked") Set<String> set = (Set<String>) value;
                    editor.putStringSet(key, set);
                }
            }
            // A failed commit keeps the old file; the next start tries again.
            if (!editor.commit()) return;
            if (Build.VERSION.SDK_INT >= 24) context.deleteSharedPreferences(from);
            else old.edit().clear().commit();
            Log.i(TAG, "Moved preferences " + from + " -> " + to + " entries=" + values.size());
        } catch (RuntimeException failure) {
            Log.w(TAG, "Preference move deferred " + from, failure);
        }
    }

    /** Renames one boolean key inside a preference file, keeping a newer value. */
    static void moveBoolean(SharedPreferences preferences, String from, String to,
                            boolean fallback) {
        if (!preferences.contains(from)) return;
        SharedPreferences.Editor editor = preferences.edit();
        if (!preferences.contains(to)) editor.putBoolean(to, preferences.getBoolean(from, fallback));
        editor.remove(from).commit();
    }

    /**
     * Renames the provisioning markers in each engine's private system root
     * (keys, firmware and runtime-asset sources), so the engines are not
     * provisioned again after the rename. Only marker files are touched.
     */
    static void moveEngineMarkers(File engineSystemRoot) {
        File[] engines = engineSystemRoot == null ? null : engineSystemRoot.listFiles();
        if (engines == null) return;
        for (File engine : engines) {
            File[] files = engine.isDirectory() ? engine.listFiles() : null;
            if (files == null) continue;
            for (File file : files) {
                String name = file.getName();
                if (file.isFile() && name.equals(CORE_OPTION_OVERRIDES)) {
                    // Generated at every launch; a stale copy is never read again.
                    if (!file.delete()) Log.w(TAG, "Unable to remove " + name);
                    continue;
                }
                renameMarker(file);
            }
        }
    }

    /**
     * Renames per-game markers engines keep beside their saves (ScummVM's
     * {@code .<old>-scummvm-<hash>.resume} Quick Resume slot), in
     * {@code files/engine-saves/<engine>/<game>/} and the QA namespaces
     * {@code files/engine-saves-qa/<session>/<engine>/<game>/}. Saves are never touched.
     */
    static void moveSaveMarkers(File filesDir) {
        if (filesDir == null) return;
        for (File engine : children(new File(filesDir, "engine-saves")))
            for (File game : children(engine)) renameMarkers(game);
        for (File session : children(new File(filesDir, "engine-saves-qa")))
            for (File engine : children(session))
                for (File game : children(engine)) renameMarkers(game);
    }

    private static File[] children(File directory) {
        File[] files = directory.isDirectory() ? directory.listFiles() : null;
        return files == null ? new File[0] : files;
    }

    private static void renameMarkers(File directory) {
        for (File file : children(directory)) renameMarker(file);
    }

    private static void renameMarker(File file) {
        String name = file.getName();
        if (!file.isFile() || !name.startsWith(ENGINE_MARKER_PREFIX)) return;
        File current = new File(file.getParentFile(),
                ".emufusion-" + name.substring(ENGINE_MARKER_PREFIX.length()));
        if (!current.exists() && !file.renameTo(current))
            Log.w(TAG, "Unable to rename marker " + name);
    }
}
