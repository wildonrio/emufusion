package com.thorium.preview;

import android.content.Context;
import android.content.pm.PackageManager;
import android.Manifest;
import android.os.Build;
import android.os.Environment;
import android.system.Os;
import android.util.Log;

import java.io.BufferedInputStream;
import java.io.BufferedOutputStream;
import java.io.BufferedReader;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.FileReader;
import java.io.FileWriter;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

/** Installs the bundled or downloaded Pegasus EmuFusion theme without touching ROMs. */
final class ThemeInstaller {
    private static final String TAG = "EmuFusionThemeInstaller";
    private static final String ASSET_ZIP = "emufusion-theme.zip";
    private static final String ASSET_VERSION = "emufusion-version.txt";
    private static final String ASSET_BUNDLED_FINGERPRINT =
            "emufusion-theme.sha256";
    private static final File PEGASUS = new File(Environment.getExternalStorageDirectory(),
            "pegasus-frontend");
    private static final File PEGASUS_CONFIG = new File(Environment.getExternalStorageDirectory(),
            "Android/data/org.pegasus_frontend.android/files/pegasus-frontend");
    private static final File APP_CONFIG = new File(Environment.getExternalStorageDirectory(),
            "Android/data/com.thorium.preview/files/pegasus-frontend");
    private static final File THEME = new File(PEGASUS, "themes/emufusion");
    private static final File VERSION = new File(THEME, ".emufusion-version");
    // Deliberately outside THEME: installing a newer downloaded theme replaces
    // that directory, but must not erase the record of which APK-bundled theme
    // was already considered. A later APK with different bundled bytes then
    // installs once; repeated starts of the same APK leave the theme alone.
    private static final File BUNDLED_FINGERPRINT = new File(PEGASUS,
            ".emufusion-bundled-theme.sha256");
    private static final File CONFIG_MIGRATION = new File(APP_CONFIG,
            ".emufusion-config-migrated");

    private ThemeInstaller() {}

    static boolean hasStorageAccess(Context context) {
        if (Build.VERSION.SDK_INT >= 30) return Environment.isExternalStorageManager();
        return Build.VERSION.SDK_INT < 23 || context.checkSelfPermission(
                Manifest.permission.WRITE_EXTERNAL_STORAGE) == PackageManager.PERMISSION_GRANTED;
    }

    static void installBundledIfNeeded(Context context) {
        installBundledIfNeeded(context, null);
    }

    static void installBundledIfNeeded(Context context, Runnable completion) {
        installBundled(context, false, completion, null);
    }

    /**
     * Installs a changed bundled theme and reports that exact event separately
     * from ordinary completion. Callers use {@code installedCompletion} to
     * refresh a frontend that may already have loaded the previous QML while
     * asynchronous extraction was in progress.
     */
    static void installBundledIfNeeded(Context context, Runnable completion,
                                       Runnable installedCompletion) {
        installBundled(context, false, completion, installedCompletion);
    }

    static void forceInstallBundled(Context context, Runnable completion) {
        installBundled(context, true, completion, null);
    }

    /** Installs EmuFusion before the embedded Pegasus activity draws its first frame. */
    static boolean installBundledNow(Context context) {
        try {
            installBundledBlocking(context, false);
            return isFrontendConfigured();
        } catch (Exception error) {
            Log.e(TAG, "Unable to install bundled theme before startup", error);
            return false;
        }
    }

    private static void installBundled(Context context, boolean force,
                                       Runnable completion,
                                       Runnable installedCompletion) {
        Thread worker = new Thread(() -> {
            boolean installed = false;
            try {
                installed = installBundledBlocking(context, force);
            } catch (Exception error) {
                Log.e(TAG, "Unable to install bundled theme", error);
            } finally {
                if (installed && installedCompletion != null)
                    installedCompletion.run();
                if (completion != null) completion.run();
            }
        }, "emufusion-theme-install");
        worker.setDaemon(true);
        worker.start();
    }

    // The Application's synchronous cold-start install and PreviewService's
    // asynchronous maintenance install can begin together after an APK update.
    // Serialize the fingerprint decision with the directory swap; otherwise
    // both can decide the bundle is new and the second swap may delete theme.qml
    // exactly while Pegasus is opening it.
    private static synchronized boolean installBundledBlocking(
            Context context, boolean force) throws Exception {
        if (!hasStorageAccess(context)) return false;
        // Ask Android to create this package's own external-files directory.
        // MANAGE_EXTERNAL_STORAGE does not grant access to another app's
        // Android/data directory, even when that app is not installed.
        if (context.getExternalFilesDir(null) == null)
            throw new java.io.IOException("EmuFusion external storage is unavailable");
        migrateLegacyTheme(context);
        boolean configurationMissing = !isFrontendConfigured();
        migratePegasusConfig();
        String bundled = readAssetText(context, ASSET_VERSION).trim();
        String bundledFingerprint = readAssetText(
                context, ASSET_BUNDLED_FINGERPRINT).trim();
        boolean firstEmuFusionInstall = !VERSION.isFile();
        boolean bundledChanged = !bundledFingerprint.isEmpty() &&
                !bundledFingerprint.equals(readText(BUNDLED_FINGERPRINT).trim());
        boolean installed = !bundled.isEmpty() &&
                (force || firstEmuFusionInstall || bundledChanged);
        if (installed) {
            try (InputStream input = context.getAssets().open(ASSET_ZIP)) {
                installZip(input, bundled);
            }
            if (!bundledFingerprint.isEmpty())
                writeText(BUNDLED_FINGERPRINT, bundledFingerprint + "\n");
        }
        // EmuFusion is the default, not a lock-in. Select it on first setup, but
        // preserve any other Pegasus theme the user chooses afterward. The
        // ROM-only provider rule remains enforced on every launch.
        updatePegasusSettings(firstEmuFusionInstall);
        return installed || configurationMissing;
    }

    /**
     * Moves the theme and the frontend state that is keyed by its folder name
     * from the pre-rename names (see {@link LegacyNames}) once: the installed
     * theme folder and its version marker (renamed in place, so an update is
     * not mistaken for a first install that would override the owner's chosen
     * theme), the bundled-theme fingerprint, the config-migration marker,
     * Pegasus's theme memory file with its keys, the selected-theme path in
     * both settings files, and the generated library metadata file names.
     * ROMs, media and other themes are never touched. Every step is a rename
     * or a small rewrite and is skipped once its new name exists.
     */
    static synchronized void migrateLegacyTheme(Context context) {
        if (!hasStorageAccess(context)) return;
        try {
            File themes = new File(PEGASUS, "themes");
            File legacyTheme = new File(themes, LegacyNames.THEME_DIRECTORY);
            if (legacyTheme.isDirectory() && !THEME.exists() && legacyTheme.renameTo(THEME))
                Log.i(TAG, "Theme folder moved to " + THEME.getName());
            renameIfAbsent(new File(THEME, LegacyNames.THEME_VERSION_MARKER), VERSION);
            renameIfAbsent(new File(PEGASUS, LegacyNames.BUNDLED_THEME_FINGERPRINT),
                    BUNDLED_FINGERPRINT);
            renameIfAbsent(new File(APP_CONFIG, LegacyNames.CONFIG_MIGRATION_MARKER),
                    CONFIG_MIGRATION);
            migrateThemeMemory(new File(APP_CONFIG, "theme_settings"));
            String legacyPath = legacyTheme.getAbsolutePath() + "/";
            rewriteSelectedTheme(new File(APP_CONFIG, "settings.txt"), legacyPath);
            rewriteSelectedTheme(new File(PEGASUS, "settings.txt"), legacyPath);
            renameGeneratedMetadata(new File(APP_CONFIG, "metafiles"));
            // The old folder only remains when it could not be renamed. Once
            // the new theme is complete it is a stale duplicate in Pegasus's
            // theme list (app-installed files, re-installable from the APK).
            if (legacyTheme.isDirectory() && new File(THEME, "theme.qml").isFile() &&
                    VERSION.isFile())
                deleteTree(legacyTheme);
        } catch (Exception failure) {
            Log.w(TAG, "Legacy theme migration deferred", failure);
        }
    }

    private static void renameIfAbsent(File legacy, File current) {
        if (legacy.isFile() && !current.exists() && !legacy.renameTo(current))
            Log.w(TAG, "Unable to rename " + legacy.getName());
    }

    /**
     * Pegasus keys theme memory by folder name: carry the file and rename its
     * keys. The first start after the update can still run the previous QML
     * for a moment (the folder is renamed before the new theme finishes
     * installing), which writes its old key names again; those are folded in
     * on the next start, a value saved under the new name winning.
     */
    private static void migrateThemeMemory(File directory) throws Exception {
        File legacy = new File(directory, LegacyNames.THEME_MEMORY_FILE);
        File current = new File(directory, THEME.getName() + ".json");
        org.json.JSONObject source;
        if (current.isFile()) source = new org.json.JSONObject(readText(current));
        else if (legacy.isFile()) source = new org.json.JSONObject(readText(legacy));
        else return;
        String prefix = LegacyNames.THEME_MEMORY_KEY_PREFIX;
        org.json.JSONObject migrated = new org.json.JSONObject();
        java.util.List<String> legacyKeys = new ArrayList<>();
        java.util.Iterator<String> keys = source.keys();
        while (keys.hasNext()) {
            String key = keys.next();
            if (key.startsWith(prefix) && key.length() > prefix.length() &&
                    Character.isUpperCase(key.charAt(prefix.length()))) legacyKeys.add(key);
            else migrated.put(key, source.get(key));
        }
        if (current.isFile() && legacyKeys.isEmpty() && !legacy.isFile()) return;
        for (String key : legacyKeys) {
            String renamed = "emufusion" + key.substring(prefix.length());
            if (!migrated.has(renamed)) migrated.put(renamed, source.get(key));
        }
        if (current.isFile() && legacy.isFile()) {
            // Both exist (an interrupted earlier move): keep what the current
            // file has and add only what the old file alone still holds.
            org.json.JSONObject old = new org.json.JSONObject(readText(legacy));
            java.util.Iterator<String> oldKeys = old.keys();
            while (oldKeys.hasNext()) {
                String key = oldKeys.next();
                String renamed = key.startsWith(prefix) && key.length() > prefix.length() &&
                        Character.isUpperCase(key.charAt(prefix.length())) ?
                        "emufusion" + key.substring(prefix.length()) : key;
                if (!migrated.has(renamed)) migrated.put(renamed, old.get(key));
            }
        }
        File temporary = new File(directory, "." + current.getName() + ".tmp");
        writeText(temporary, migrated.toString());
        if (current.isFile() && !current.delete())
            throw new java.io.IOException("Unable to replace theme memory");
        if (!temporary.renameTo(current))
            throw new java.io.IOException("Unable to commit migrated theme memory");
        if (legacy.isFile() && !legacy.delete())
            Log.w(TAG, "Unable to remove migrated theme memory file");
        Log.i(TAG, "Theme memory migrated keys=" + migrated.length() +
                " renamed=" + legacyKeys.size());
    }

    private static void rewriteSelectedTheme(File settings, String legacyPath) throws Exception {
        if (!settings.isFile()) return;
        String text = readText(settings);
        String legacyLine = "general.theme: " + legacyPath;
        if (!text.contains(legacyLine)) return;
        File temporary = new File(settings.getParentFile(), ".settings.emufusion.tmp");
        writeText(temporary, text.replace(legacyLine,
                "general.theme: " + THEME.getAbsolutePath() + "/"));
        if (settings.isFile() && !settings.delete())
            throw new java.io.IOException("Unable to replace frontend settings");
        if (!temporary.renameTo(settings))
            throw new java.io.IOException("Unable to commit frontend settings");
    }

    /** Library metadata the importer generated (and its backups), never user files. */
    private static void renameGeneratedMetadata(File directory) {
        File[] files = directory.listFiles();
        if (files == null) return;
        for (File file : files) {
            String name = file.getName();
            if (!file.isFile() || !name.startsWith(LegacyNames.AUTO_METADATA_PREFIX)) continue;
            File current = new File(directory, ImportManager.AUTO_METADATA_PREFIX +
                    name.substring(LegacyNames.AUTO_METADATA_PREFIX.length()));
            if (current.exists()) {
                // Generated again under the new name already: the old copy
                // would list every game twice.
                if (!file.delete()) Log.w(TAG, "Unable to remove stale metadata " + name);
            } else if (!file.renameTo(current)) {
                Log.w(TAG, "Unable to rename metadata " + name);
            }
        }
    }

    /**
     * Carries the existing Pegasus library, play history and theme memory into
     * the unified package once. ROMs and media are referenced in place and are
     * never copied, moved or deleted by this migration.
     */
    private static synchronized void migratePegasusConfig() throws Exception {
        if (CONFIG_MIGRATION.isFile() || !PEGASUS_CONFIG.isDirectory()) return;
        copyConfigTree(PEGASUS_CONFIG, APP_CONFIG);
        writeText(CONFIG_MIGRATION, "migrated from org.pegasus_frontend.android\n");
    }

    static synchronized void installZip(File zip, String version) throws Exception {
        try (InputStream input = new FileInputStream(zip)) {
            installZip(input, version);
        }
    }

    static synchronized void installZip(InputStream source, String version) throws Exception {
        PEGASUS.mkdirs();
        File themes = new File(PEGASUS, "themes");
        themes.mkdirs();
        File staging = new File(themes, ".emufusion-installing");
        deleteTree(staging);
        if (!staging.mkdirs() && !staging.isDirectory())
            throw new java.io.IOException("Unable to create the theme staging directory");
        String stagingPath = staging.getCanonicalPath() + File.separator;
        try (ZipInputStream zip = new ZipInputStream(new BufferedInputStream(source))) {
            ZipEntry entry;
            byte[] buffer = new byte[128 * 1024];
            while ((entry = zip.getNextEntry()) != null) {
                String relative = entry.getName();
                if (relative.startsWith("emufusion/")) relative = relative.substring(10);
                if (relative.isEmpty()) continue;
                File output = new File(staging, relative);
                String canonical = output.getCanonicalPath();
                if (!canonical.startsWith(stagingPath))
                    throw new java.io.IOException("Unsafe theme archive path");
                if (entry.isDirectory()) {
                    output.mkdirs();
                    continue;
                }
                File parent = output.getParentFile();
                if (parent != null) parent.mkdirs();
                try (BufferedOutputStream out = new BufferedOutputStream(
                        new FileOutputStream(output))) {
                    int count;
                    long total = 0;
                    while ((count = zip.read(buffer)) >= 0) {
                        total += count;
                        if (total > 512L * 1024L * 1024L)
                            throw new java.io.IOException("Theme entry is unexpectedly large");
                        out.write(buffer, 0, count);
                    }
                }
            }
        }
        if (!new File(staging, "theme.qml").isFile() ||
                !new File(staging, "theme.cfg").isFile()) {
            deleteTree(staging);
            throw new java.io.IOException("Theme archive is incomplete");
        }
        publishStagedTheme(staging);
        writeText(VERSION, version == null ? "unknown" : version.trim());
    }

    /**
     * Publishes a fully validated theme without ever removing the live
     * theme.qml path.
     *
     * <p>Pegasus and the installer run concurrently after an APK update. A
     * directory-level delete/swap therefore leaves a real interval in which
     * Pegasus can open neither the old nor the new theme.qml. Every staged
     * regular file is already on the same external-storage filesystem, so a
     * POSIX rename replaces its live counterpart atomically. Assets and
     * theme.cfg are committed first; theme.qml is the final publication point.
     * Old files not referenced by the new theme are deliberately retained so
     * an already-loaded old QML document cannot lose an asset mid-session.
     */
    private static void publishStagedTheme(File staging) throws Exception {
        if (!THEME.mkdirs() && !THEME.isDirectory())
            throw new java.io.IOException("Unable to create the live theme directory");
        publishStagedChildren(staging, staging);
        publishStagedFile(staging, "theme.cfg");
        publishStagedFile(staging, "theme.qml");
        deleteTree(staging);
    }

    private static void publishStagedChildren(
            File stagingRoot, File directory) throws Exception {
        File[] children = directory.listFiles();
        if (children == null)
            throw new java.io.IOException("Unable to enumerate staged theme files");
        String rootPath = stagingRoot.getCanonicalPath() + File.separator;
        for (File child : children) {
            String canonical = child.getCanonicalPath();
            if (!canonical.startsWith(rootPath))
                throw new java.io.IOException("Unsafe staged theme path");
            String relative = canonical.substring(rootPath.length());
            if (directory.equals(stagingRoot) && ("theme.qml".equals(relative) ||
                    "theme.cfg".equals(relative))) continue;
            if (child.isDirectory()) {
                File target = new File(THEME, relative);
                if (!target.mkdirs() && !target.isDirectory())
                    throw new java.io.IOException("Unable to create theme directory " + relative);
                publishStagedChildren(stagingRoot, child);
            } else {
                publishStagedFile(stagingRoot, relative);
            }
        }
    }

    private static void publishStagedFile(File stagingRoot, String relative) throws Exception {
        File source = new File(stagingRoot, relative);
        if (!source.isFile())
            throw new java.io.IOException("Missing staged theme file " + relative);
        File target = new File(THEME, relative);
        long replacedTimestamp = target.isFile() ? target.lastModified() : 0L;
        File parent = target.getParentFile();
        if (parent != null && !parent.mkdirs() && !parent.isDirectory())
            throw new java.io.IOException("Unable to create theme file parent " + relative);
        Os.rename(source.getAbsolutePath(), target.getAbsolutePath());
        if ("theme.qml".equals(relative)) {
            // Qt's QML disk cache keys external documents partly by path,
            // size, and modification time. A ZIP/file rename can preserve a
            // timestamp even when theme.qml's bytes changed, which leaves the
            // previous menu text visible after an APK update. Advance the live
            // document beyond both wall time and the file it replaced so the
            // next frontend process must compile the newly published source.
            long successor = replacedTimestamp >= Long.MAX_VALUE - 1L
                    ? replacedTimestamp : replacedTimestamp + 1L;
            long cacheBuster = Math.max(System.currentTimeMillis(), successor);
            if (!target.setLastModified(cacheBuster))
                throw new java.io.IOException("Unable to invalidate the EmuFusion theme cache");
        }
    }

    static String installedVersion() {
        return readText(VERSION).trim();
    }

    /** A version marker alone does not prove that first-run setup completed. */
    static boolean isFrontendConfigured() {
        if (installedVersion().isEmpty() || !new File(THEME, "theme.qml").isFile()
                || !new File(THEME, "theme.cfg").isFile()) return false;
        for (String line : readText(new File(APP_CONFIG, "settings.txt")).split("\n")) {
            if (line.startsWith("general.theme:") &&
                    !line.substring("general.theme:".length()).trim().isEmpty()) return true;
        }
        return false;
    }

    private static void updatePegasusSettings(boolean selectEmuFusion) throws Exception {
        // Modern Pegasus Android builds keep runtime settings under their
        // app-specific external directory. Disable the Android Apps provider:
        // EmuFusion is deliberately a ROM library, never an application launcher.
        // The old Pegasus directory is a read-only migration source, not a
        // required write target. On a clean Android phone its creation fails
        // before either of our own settings files can be written.
        updateSettings(new File(APP_CONFIG, "settings.txt"), selectEmuFusion);
        updateSettings(new File(PEGASUS, "settings.txt"), selectEmuFusion);
    }

    private static void updateSettings(File settings, boolean selectEmuFusion) throws Exception {
        List<String> lines = new ArrayList<>();
        boolean themeReplaced = false;
        boolean appsReplaced = false;
        if (settings.isFile()) {
            try (BufferedReader reader = new BufferedReader(new FileReader(settings))) {
                String line;
                while ((line = reader.readLine()) != null) {
                    if (line.startsWith("general.theme:")) {
                        if (selectEmuFusion && !themeReplaced) {
                            lines.add("general.theme: " + THEME.getAbsolutePath() + "/");
                            themeReplaced = true;
                        } else if (!selectEmuFusion &&
                                !line.substring("general.theme:".length()).trim().isEmpty()) {
                            lines.add(line);
                            themeReplaced = true;
                        }
                    } else if (line.startsWith("providers.androidapps.enabled:")) {
                        if (!appsReplaced) {
                            lines.add("providers.androidapps.enabled: false");
                            appsReplaced = true;
                        }
                    } else lines.add(line);
                }
            }
        }
        // Repair an interrupted first install even if .emufusion-version already
        // exists. A deliberately selected nonempty custom theme stays intact.
        if (!themeReplaced)
            lines.add(0, "general.theme: " + THEME.getAbsolutePath() + "/");
        if (!appsReplaced) lines.add("providers.androidapps.enabled: false");
        File parent = settings.getParentFile();
        if (parent != null) parent.mkdirs();
        File temporary = new File(settings.getParentFile(), ".settings.emufusion.tmp");
        try (FileWriter writer = new FileWriter(temporary, false)) {
            for (String line : lines) writer.write(line + "\n");
        }
        if (settings.isFile() && !settings.delete())
            throw new java.io.IOException("Unable to replace EmuFusion settings");
        if (!temporary.renameTo(settings))
            throw new java.io.IOException("Unable to commit EmuFusion settings");
    }

    private static String readAssetText(Context context, String name) throws Exception {
        StringBuilder out = new StringBuilder();
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(
                context.getAssets().open(name), StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) out.append(line).append('\n');
        }
        return out.toString();
    }

    private static String readText(File file) {
        if (!file.isFile()) return "";
        StringBuilder out = new StringBuilder();
        try (BufferedReader reader = new BufferedReader(new FileReader(file))) {
            String line;
            while ((line = reader.readLine()) != null) out.append(line).append('\n');
        } catch (Exception ignored) {}
        return out.toString();
    }

    private static void writeText(File file, String text) throws Exception {
        File parent = file.getParentFile();
        if (parent != null) parent.mkdirs();
        try (FileWriter writer = new FileWriter(file, false)) {
            writer.write(text == null ? "" : text);
        }
    }

    private static void copyTree(File source, File target) throws Exception {
        if (source.isDirectory()) {
            target.mkdirs();
            File[] children = source.listFiles();
            if (children != null)
                for (File child : children) copyTree(child, new File(target, child.getName()));
            return;
        }
        File parent = target.getParentFile();
        if (parent != null) parent.mkdirs();
        try (InputStream in = new BufferedInputStream(new FileInputStream(source));
             BufferedOutputStream out = new BufferedOutputStream(new FileOutputStream(target))) {
            byte[] buffer = new byte[128 * 1024];
            int count;
            while ((count = in.read(buffer)) >= 0) out.write(buffer, 0, count);
        }
    }

    private static void copyConfigTree(File source, File target) throws Exception {
        if (source.isDirectory()) {
            target.mkdirs();
            File[] children = source.listFiles();
            if (children != null) {
                for (File child : children) {
                    if ("lastrun.log".equals(child.getName())) continue;
                    copyConfigTree(child, new File(target, child.getName()));
                }
            }
            return;
        }
        copyTree(source, target);
    }

    private static void deleteTree(File file) {
        if (file == null || !file.exists()) return;
        if (file.isDirectory()) {
            File[] children = file.listFiles();
            if (children != null) for (File child : children) deleteTree(child);
        }
        file.delete();
    }
}
