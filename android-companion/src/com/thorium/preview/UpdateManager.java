package com.thorium.preview;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.content.pm.Signature;
import android.net.Uri;
import android.os.Build;
import android.provider.Settings;
import android.util.Log;
import android.view.Display;

import com.thorium.preview.cheats.CheatArchive;
import com.thorium.preview.cheats.CheatControl;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedInputStream;
import java.io.BufferedOutputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Locale;
import java.util.concurrent.atomic.AtomicBoolean;

/** GitHub-backed theme and APK updater with a small JSON status surface. */
final class UpdateManager {
    private static final String TAG = "LucentUpdater";
    private static final String MANIFEST_URL =
            "https://raw.githubusercontent.com/wildonrio/pegasus-lucent/main/release-manifest.json";
    // The publishing repository owns the immutable release assets. Reading its
    // latest-release record means uploading a new GitHub release is sufficient;
    // the app does not wait for somebody to hand-edit release-manifest.json.
    private static final String[] RELEASE_API_URLS = new String[]{
            "https://api.github.com/repos/wildonrio/pegasus-lucent/releases/latest"
    };
    private static final String[] RELEASE_DOWNLOAD_PREFIXES = new String[]{
            "https://github.com/wildonrio/pegasus-lucent/releases/download/"
    };
    private static final String UPDATE_PREFERENCES = "updates-ui";
    private static final String PENDING_INSTALL = "automaticInstallPending";
    private static final String DEFERRED_INSTALL = "installDeferredUntilLibrary";
    private static final String LAST_AUTOMATIC_CHECK = "lastAutomaticCheckAt";
    // Re-check on library return once this long has passed since the last
    // automatic check, so a long-running service still finds new releases.
    private static final long RECHECK_INTERVAL_MS = 6L * 60L * 60L * 1000L;
    private static final long MAX_THEME = 512L * 1024L * 1024L;
    private static final long MAX_APK = 768L * 1024L * 1024L;
    private static final long MAX_CHEATS = CheatArchive.MAX_ARCHIVE_BYTES;

    /** Reports whether a game is on screen; Android's installer must not cover it. */
    interface GameplayGate {
        boolean gameplayActive();
    }

    private final Context context;
    private final AtomicBoolean running = new AtomicBoolean(false);
    private volatile GameplayGate gameplayGate;
    private final Object statusLock = new Object();
    private JSONObject status = status("idle", 0, "Updater ready", false, false);
    private volatile JSONObject latest;

    private static final class AppRelease {
        final String version;
        final String url;
        final String sha256;

        AppRelease(String version, String url, String sha256) {
            this.version = version;
            this.url = url;
            this.sha256 = sha256;
        }
    }

    UpdateManager(Context context) {
        this.context = context.getApplicationContext();
        // A process can be killed while a network request is in flight. Never
        // resurrect that persisted progress state as though work were still
        // running: there is no worker left to complete it. Terminal states are
        // safe to restore; interrupted work becomes an explicit retry state.
        android.content.SharedPreferences saved =
                this.context.getSharedPreferences(UPDATE_PREFERENCES, 0);
        String previous = saved.getString("state", "idle");
        boolean interrupted = "checking".equals(previous) ||
                "theme".equals(previous) || "cheats".equals(previous) ||
                "software".equals(previous);
        if (interrupted) {
            setStatus("interrupted", 1,
                    "Previous update check was interrupted — tap Check for Updates to retry",
                    false, false);
        } else if (!"idle".equals(previous)) {
            setStatus(previous, 1,
                    saved.getString("message", "Updater ready"),
                    saved.getBoolean("appAvailable", false),
                    saved.getBoolean("installReady", false));
        }
    }

    void setGameplayGate(GameplayGate gate) {
        gameplayGate = gate;
    }

    /**
     * Called when the owner returns to the library. Opens Android's installer
     * for an update that finished downloading during gameplay, otherwise
     * re-checks once RECHECK_INTERVAL_MS has passed since the last automatic
     * check.
     */
    void onLibraryVisible() {
        SharedPreferences saved = context.getSharedPreferences(UPDATE_PREFERENCES, 0);
        if (saved.getBoolean(DEFERRED_INSTALL, false)) {
            saved.edit().remove(DEFERRED_INSTALL).apply();
            installDownloadedApk(true);
            return;
        }
        long last = saved.getLong(LAST_AUTOMATIC_CHECK, 0L);
        if (System.currentTimeMillis() - last >= RECHECK_INTERVAL_MS) checkAsync(false);
    }

    void checkAsync(boolean userInitiated) {
        // Every installed build, including the debug-signed personal builds,
        // checks automatically. Updates are delivered by GitHub releases.
        if (!running.compareAndSet(false, true)) return;
        if (!userInitiated) {
            context.getSharedPreferences(UPDATE_PREFERENCES, 0).edit()
                    .putLong(LAST_AUTOMATIC_CHECK, System.currentTimeMillis()).apply();
        }
        setStatus("checking", 0.05, "Checking GitHub for updates…", false, false);
        Thread worker = new Thread(() -> {
            try {
                check(userInitiated);
            } catch (Exception error) {
                Log.e(TAG, "Update check failed", error);
                setStatus("error", 1, "Update check failed safely", false, false);
            } finally {
                running.set(false);
            }
        }, "lucent-update-check");
        worker.setDaemon(true);
        worker.start();
    }

    String statusJson() {
        synchronized (statusLock) { return status.toString(); }
    }

    void installDownloadedApk() {
        installDownloadedApk(false);
    }

    /**
     * Completes the one-time permission handoff without making the owner find
     * the APK in Downloads. Android resumes EmuFusion after its per-app
     * "install unknown apps" screen; the installer is opened immediately.
     */
    static void resumePendingInstall(Activity activity) {
        if (activity == null || activity.isFinishing() || activity.isDestroyed()) return;
        if (activity.getWindowManager().getDefaultDisplay().getDisplayId()
                != Display.DEFAULT_DISPLAY) return;
        Context context = activity.getApplicationContext();
        SharedPreferences saved = context.getSharedPreferences(UPDATE_PREFERENCES, 0);
        if (!saved.getBoolean(PENDING_INSTALL, false)) return;
        if (Build.VERSION.SDK_INT >= 26 &&
                !context.getPackageManager().canRequestPackageInstalls()) return;
        File apk = updateFile(context);
        if (!apk.isFile()) {
            saved.edit().remove(PENDING_INSTALL).apply();
            return;
        }
        try {
            validateDownloadedApk(context, apk);
        } catch (Exception invalid) {
            apk.delete();
            saved.edit().remove(PENDING_INSTALL).apply();
            Log.e(TAG, "Pending update failed package validation", invalid);
            return;
        }
        try {
            openInstaller(context);
            saved.edit()
                    .putBoolean(PENDING_INSTALL, false)
                    .putString("state", "installing")
                    .putString("message", "Android installer opened")
                    .putLong("updatedAt", System.currentTimeMillis())
                    .putBoolean("appAvailable", true)
                    .putBoolean("installReady", false)
                    .apply();
        } catch (RuntimeException error) {
            Log.w(TAG, "Unable to resume automatic installer", error);
        }
    }

    private void installDownloadedApk(boolean automatic) {
        try {
            File apk = updateFile();
            if (!apk.isFile()) {
                context.getSharedPreferences(UPDATE_PREFERENCES, 0).edit()
                        .remove(PENDING_INSTALL).apply();
                setStatus("complete", 1,
                        "No downloaded update is available — run Check for Updates first",
                        false, false);
                return;
            }
            try {
                validateDownloadedApk(context, apk);
            } catch (Exception invalid) {
                apk.delete();
                context.getSharedPreferences(UPDATE_PREFERENCES, 0).edit()
                        .remove(PENDING_INSTALL).apply();
                Log.e(TAG, "Downloaded update failed package validation", invalid);
                setStatus("error", 1, "Downloaded update failed identity verification",
                        false, false);
                return;
            }
            // Keep this flag while Android shows its one-time source permission.
            // The application lifecycle callback consumes it on return.
            context.getSharedPreferences(UPDATE_PREFERENCES, 0).edit()
                    .putBoolean(PENDING_INSTALL, true).apply();
            if (Build.VERSION.SDK_INT >= 26 &&
                    !context.getPackageManager().canRequestPackageInstalls()) {
                Intent permission = new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                        Uri.parse("package:" + context.getPackageName()))
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                context.startActivity(permission);
                setStatus("permission", 1,
                        "Allow installs from EmuFusion — Android's installer opens automatically",
                        true, true);
                return;
            }
            openInstaller(context);
            context.getSharedPreferences(UPDATE_PREFERENCES, 0).edit()
                    .putBoolean(PENDING_INSTALL, false).apply();
            setStatus("installing", 1,
                    automatic ? "Update downloaded — confirm Install in Android"
                            : "Android installer opened",
                    true, false);
        } catch (Exception error) {
            Log.e(TAG, "Unable to open installer", error);
            setStatus("available", 1,
                    "Update downloaded; Android could not open the installer automatically",
                    true, true);
        }
    }

    private void check(boolean userInitiated) throws Exception {
        // Prefer the latest GitHub release itself. GitHub supplies a SHA-256
        // digest for each release asset, so a newly uploaded version becomes
        // discoverable even if the legacy theme manifest is unavailable. Do
        // not fetch that optional document first: its timeout or malformed
        // response must not strand a device on an older APK.
        AppRelease githubRelease = null;
        for (String apiUrl : RELEASE_API_URLS) {
            try {
                JSONObject release = new JSONObject(new String(
                        fetch(apiUrl, 2L * 1024L * 1024L), StandardCharsets.UTF_8));
                AppRelease candidate = appRelease(release);
                if (candidate != null && (githubRelease == null ||
                        isVersionNewer(candidate.version, githubRelease.version)))
                    githubRelease = candidate;
            } catch (Exception error) {
                Log.w(TAG, "Latest GitHub release lookup failed for " + apiUrl, error);
            }
        }
        long currentCode = currentVersionCode();
        String installedVersion = currentVersionName();
        boolean githubNew = githubRelease != null &&
                isVersionNewer(githubRelease.version, installedVersion);
        // Fetch the legacy channel only when it might still have an APK or
        // content update to offer. If both channels fail, propagate the error;
        // an offline check is not evidence that the app is up to date.
        JSONObject manifest = githubNew ? new JSONObject() : new JSONObject(new String(
                fetch(MANIFEST_URL, 2L * 1024L * 1024L), StandardCharsets.UTF_8));
        latest = manifest;
        int manifestCode = manifest.optInt("companionVersionCode", (int) currentCode);
        boolean manifestNew = !githubNew && manifestCode > currentCode;
        boolean appNew = githubNew || manifestNew;
        String appUrl = githubNew ? githubRelease.url :
                manifest.optString("companionApkUrl", "");
        String apkSha = githubNew ? githubRelease.sha256 :
                manifest.optString("companionSha256", "").trim();

        // An app update takes priority over optional content. In particular,
        // a missing theme/cheat checksum or a failed content download must not
        // prevent delivery of the APK that may fix this older installation.
        // APK checksum and package/signing/version checks remain mandatory.
        if (appNew) {
            if (apkSha.isEmpty()) {
                setStatus("error", 1, "Update manifest is missing a checksum", false, false);
                return;
            }
            File apk = updateFile();
            // A declined or deferred install leaves the verified APK in place;
            // the next check offers it again without another full download.
            if (!downloadedMatches(apk, apkSha)) {
                setStatus("software", 0.68, "Downloading the latest app update…", true, false);
                download(appUrl, apk, MAX_APK, apkSha);
            }
            try {
                validateDownloadedApk(context, apk);
            } catch (Exception invalid) {
                apk.delete();
                throw invalid;
            }
            if (gameplayActive()) {
                deferInstallUntilLibrary();
                setStatus("available", 1,
                        "Update downloaded — installs when you return to the library",
                        true, true);
                return;
            }
            setStatus("available", 1,
                    "Software update downloaded — opening Android installer", true, true);
            installDownloadedApk(true);
            return;
        }

        String remoteTheme = manifest.optString("themeVersion", "");
        boolean themeNew = isVersionNewer(remoteTheme, ThemeInstaller.installedVersion());
        String remoteCheats = manifest.optString("cheatCatalogVersion", "").trim();
        String installedCheats = context.getSharedPreferences(UPDATE_PREFERENCES, 0)
                .getString("cheatCatalogVersion", "");
        File installedCheatArchive = CheatControl.downloadedArchive(context);
        boolean cheatsNew = !remoteCheats.isEmpty() &&
                (!remoteCheats.equals(installedCheats) || !installedCheatArchive.isFile());

        // Content-only updates still require every applicable checksum before
        // downloading anything. They are retried on the next check after an
        // APK update; the bundled theme is already delivered inside the APK.
        String themeSha = manifest.optString("themeSha256", "").trim();
        String cheatsSha = manifest.optString("cheatCatalogSha256", "").trim();
        if ((themeNew && themeSha.isEmpty()) || (cheatsNew && cheatsSha.isEmpty())) {
            setStatus("error", 1, "Update manifest is missing a checksum", false, false);
            return;
        }

        if (themeNew) {
            setStatus("theme", 0.18, "Downloading the latest EmuFusion theme…",
                    appNew, false);
            File theme = new File(context.getCacheDir(), "pegasus-lucent-theme.zip");
            download(manifest.optString("themeZipUrl"), theme, MAX_THEME, themeSha);
            setStatus("theme", 0.62, "Installing the theme update…", appNew, false);
            ThemeInstaller.installZip(theme, remoteTheme);
            theme.delete();
        }

        if (cheatsNew) {
            setStatus("cheats", 0.64, "Downloading the latest cheat catalog…",
                    appNew, false);
            File staged = new File(context.getCacheDir(), "libretro-cheats.zip");
            download(manifest.optString("cheatCatalogUrl", ""), staged,
                    MAX_CHEATS, cheatsSha);
            CheatArchive.verify(staged);
            installCheatArchive(staged, installedCheatArchive);
            context.getSharedPreferences(UPDATE_PREFERENCES, 0).edit()
                    .putString("cheatCatalogVersion", remoteCheats).apply();
        }

        String message = themeNew && cheatsNew ?
                "Theme and cheat catalog updated successfully" :
                (cheatsNew ? "Cheat catalog updated successfully" :
                (themeNew ? "Theme updated successfully" :
                (userInitiated ? "EmuFusion is up to date" : "Updates checked")));
        setStatus("complete", 1, message, false, false);
    }

    private static AppRelease appRelease(JSONObject release) {
        if (release == null || release.optBoolean("draft", true) ||
                release.optBoolean("prerelease", true)) return null;
        String tag = release.optString("tag_name", "").trim();
        String version = tag.startsWith("v") || tag.startsWith("V") ?
                tag.substring(1) : tag;
        if (version.isEmpty()) return null;
        String[] acceptedNames = new String[]{
                "lucent-unified-" + version + ".apk",
                "lucent-" + version + ".apk",
                "emufusion-" + version + ".apk"
        };
        JSONArray assets = release.optJSONArray("assets");
        if (assets == null) return null;
        for (String accepted : acceptedNames) {
            for (int index = 0; index < assets.length(); index++) {
                JSONObject asset = assets.optJSONObject(index);
                if (asset == null || !accepted.equals(asset.optString("name", ""))) continue;
                String url = asset.optString("browser_download_url", "");
                String digest = asset.optString("digest", "");
                if (!trustedReleaseUrl(url) ||
                        !digest.matches("(?i)^sha256:[0-9a-f]{64}$")) return null;
                return new AppRelease(version, url, digest.substring(7).toLowerCase(Locale.US));
            }
        }
        return null;
    }

    private static boolean trustedReleaseUrl(String url) {
        for (String prefix : RELEASE_DOWNLOAD_PREFIXES) {
            if (url.startsWith(prefix)) return true;
        }
        return false;
    }

    private boolean gameplayActive() {
        GameplayGate gate = gameplayGate;
        return gate != null && gate.gameplayActive();
    }

    private void deferInstallUntilLibrary() {
        context.getSharedPreferences(UPDATE_PREFERENCES, 0).edit()
                .putBoolean(DEFERRED_INSTALL, true).apply();
    }

    private static boolean downloadedMatches(File apk, String expectedSha) {
        if (apk == null || !apk.isFile() || expectedSha == null) return false;
        try (InputStream input = new BufferedInputStream(new java.io.FileInputStream(apk))) {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] buffer = new byte[128 * 1024];
            int count;
            while ((count = input.read(buffer)) >= 0) digest.update(buffer, 0, count);
            return hex(digest.digest()).equalsIgnoreCase(expectedSha.trim());
        } catch (Exception unreadable) {
            return false;
        }
    }

    private long currentVersionCode() {
        try {
            PackageInfo info = context.getPackageManager().getPackageInfo(context.getPackageName(), 0);
            return Build.VERSION.SDK_INT >= 28 ? info.getLongVersionCode() : info.versionCode;
        } catch (Exception ignored) { return 0; }
    }

    private String currentVersionName() {
        try {
            PackageInfo info = context.getPackageManager().getPackageInfo(context.getPackageName(), 0);
            return info.versionName == null ? "" : info.versionName;
        } catch (Exception ignored) { return ""; }
    }

    /** Package name, monotonic version code, and signing identity are checked
     * in addition to the GitHub digest. A compromised/misconfigured release
     * cannot turn this updater into a general APK installer. */
    private static void validateDownloadedApk(Context context, File apk) throws Exception {
        PackageManager manager = context.getPackageManager();
        int flags = Build.VERSION.SDK_INT >= 28 ?
                PackageManager.GET_SIGNING_CERTIFICATES : PackageManager.GET_SIGNATURES;
        PackageInfo candidate = manager.getPackageArchiveInfo(apk.getAbsolutePath(), flags);
        PackageInfo installed = manager.getPackageInfo(context.getPackageName(), flags);
        if (candidate == null || !context.getPackageName().equals(candidate.packageName))
            throw new java.io.IOException("Update APK package identity does not match EmuFusion");
        long candidateCode = Build.VERSION.SDK_INT >= 28 ?
                candidate.getLongVersionCode() : candidate.versionCode;
        long installedCode = Build.VERSION.SDK_INT >= 28 ?
                installed.getLongVersionCode() : installed.versionCode;
        if (candidateCode <= installedCode)
            throw new java.io.IOException("Update APK version is not newer than the installed app");
        Signature[] candidateSigners = signatures(candidate);
        Signature[] installedSigners = signatures(installed);
        if (!sharesSigner(candidateSigners, installedSigners))
            throw new java.io.IOException("Update APK signing identity does not match EmuFusion");
    }

    @SuppressWarnings("deprecation")
    private static Signature[] signatures(PackageInfo info) {
        if (Build.VERSION.SDK_INT >= 28) {
            if (info == null || info.signingInfo == null) return null;
            return info.signingInfo.hasMultipleSigners() ?
                    info.signingInfo.getApkContentsSigners() :
                    info.signingInfo.getSigningCertificateHistory();
        }
        return info == null ? null : info.signatures;
    }

    private static boolean sharesSigner(Signature[] left, Signature[] right) {
        if (left == null || right == null || left.length == 0 || right.length == 0)
            return false;
        for (Signature a : left) {
            for (Signature b : right) {
                if (MessageDigest.isEqual(a.toByteArray(), b.toByteArray())) return true;
            }
        }
        return false;
    }

    private static boolean isVersionNewer(String candidate, String installed) {
        if (candidate == null || candidate.trim().isEmpty()) return false;
        if (installed == null || installed.trim().isEmpty()) return true;
        String[] left = candidate.trim().split("[^0-9]+");
        String[] right = installed.trim().split("[^0-9]+");
        int count = Math.max(left.length, right.length);
        for (int index = 0; index < count; index++) {
            int a = versionPart(left, index);
            int b = versionPart(right, index);
            if (a != b) return a > b;
        }
        return false;
    }

    private static int versionPart(String[] parts, int index) {
        if (index >= parts.length || parts[index].isEmpty()) return 0;
        try { return Integer.parseInt(parts[index]); }
        catch (NumberFormatException ignored) { return 0; }
    }

    private File updateFile() {
        return updateFile(context);
    }

    private static File updateFile(Context context) {
        File folder = context.getExternalFilesDir("updates");
        if (folder == null) folder = new File(context.getCacheDir(), "updates");
        if (folder != null) folder.mkdirs();
        return new File(folder, UpdateFileProvider.FILE_NAME);
    }

    private static void openInstaller(Context context) {
        Uri uri = Uri.parse("content://" + context.getPackageName() +
                ".updates/" + UpdateFileProvider.FILE_NAME);
        Intent install = new Intent(Intent.ACTION_VIEW)
                .setDataAndType(uri, "application/vnd.android.package-archive")
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK |
                        Intent.FLAG_GRANT_READ_URI_PERMISSION);
        context.startActivity(install);
    }

    private static byte[] fetch(String url, long maximum) throws Exception {
        HttpURLConnection connection = (HttpURLConnection) new URL(url).openConnection();
        connection.setConnectTimeout(15000);
        connection.setReadTimeout(30000);
        connection.setInstanceFollowRedirects(true);
        connection.setRequestProperty("User-Agent", "Lucent-Updater/1.0");
        try (InputStream input = new BufferedInputStream(connection.getInputStream());
             ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[32 * 1024];
            int count;
            long total = 0;
            while ((count = input.read(buffer)) >= 0) {
                total += count;
                if (total > maximum) throw new java.io.IOException("Update response is too large");
                output.write(buffer, 0, count);
            }
            return output.toByteArray();
        } finally { connection.disconnect(); }
    }

    private static void download(String url, File target, long maximum, String expectedSha)
            throws Exception {
        if (url == null || url.isEmpty() || !url.startsWith("https://"))
            throw new java.io.IOException("Missing secure update URL");
        // Never accept a download that cannot be verified against the
        // manifest, regardless of which caller forgot to require the field.
        if (expectedSha == null || expectedSha.trim().isEmpty())
            throw new java.io.IOException("Update manifest is missing a checksum");
        File parent = target.getParentFile();
        if (parent != null) parent.mkdirs();
        File partial = new File(target.getAbsolutePath() + ".partial");
        HttpURLConnection connection = (HttpURLConnection) new URL(url).openConnection();
        connection.setConnectTimeout(20000);
        connection.setReadTimeout(60000);
        connection.setInstanceFollowRedirects(true);
        connection.setRequestProperty("User-Agent", "Lucent-Updater/1.0");
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (InputStream input = new BufferedInputStream(connection.getInputStream());
             BufferedOutputStream output = new BufferedOutputStream(new FileOutputStream(partial))) {
            byte[] buffer = new byte[128 * 1024];
            int count;
            long total = 0;
            while ((count = input.read(buffer)) >= 0) {
                total += count;
                if (total > maximum) throw new java.io.IOException("Update is too large");
                digest.update(buffer, 0, count);
                output.write(buffer, 0, count);
            }
        } finally { connection.disconnect(); }
        String actual = hex(digest.digest());
        if (!actual.equalsIgnoreCase(expectedSha.trim())) {
            partial.delete();
            throw new java.io.IOException("Update checksum does not match");
        }
        if (target.isFile()) target.delete();
        if (!partial.renameTo(target))
            throw new java.io.IOException("Unable to commit update download");
    }

    private static void installCheatArchive(File staged, File target) throws Exception {
        File parent = target.getParentFile();
        if (parent != null && !parent.isDirectory() && !parent.mkdirs())
            throw new java.io.IOException("Unable to create cheat catalog directory");
        File incoming = new File(target.getAbsolutePath() + ".new");
        if (incoming.isFile() && !incoming.delete())
            throw new java.io.IOException("Unable to clear stale cheat catalog staging");
        if (!staged.renameTo(incoming))
            throw new java.io.IOException("Unable to stage cheat catalog");
        CheatArchive.verify(incoming);
        File previous = new File(target.getAbsolutePath() + ".previous");
        if (previous.isFile()) previous.delete();
        if (target.isFile() && !target.renameTo(previous)) {
            incoming.delete();
            throw new java.io.IOException("Unable to preserve previous cheat catalog");
        }
        if (!incoming.renameTo(target)) {
            if (previous.isFile()) previous.renameTo(target);
            throw new java.io.IOException("Unable to commit cheat catalog");
        }
        previous.delete();
    }

    private void setStatus(String state, double progress, String message,
                           boolean appAvailable, boolean installReady) {
        synchronized (statusLock) {
            status = status(state, progress, message, appAvailable, installReady);
        }
        // The dashboard and foreground service are separate Android
        // components. Persist the small terminal/progress state so the visible
        // checklist never depends on a localhost timing race to turn green.
        context.getSharedPreferences(UPDATE_PREFERENCES, 0).edit()
                .putString("state", state)
                .putString("message", message)
                .putLong("updatedAt", System.currentTimeMillis())
                .putBoolean("appAvailable", appAvailable)
                .putBoolean("installReady", installReady)
                .apply();
    }

    private static JSONObject status(String state, double progress, String message,
                                     boolean appAvailable, boolean installReady) {
        JSONObject value = new JSONObject();
        try {
            value.put("state", state);
            value.put("progress", Math.max(0, Math.min(1, progress)));
            value.put("message", message);
            value.put("appAvailable", appAvailable);
            value.put("installReady", installReady);
            value.put("running", "checking".equals(state) || "theme".equals(state) ||
                    "cheats".equals(state) || "software".equals(state));
            value.put("themeVersion", ThemeInstaller.installedVersion());
        } catch (Exception ignored) {}
        return value;
    }

    private static String hex(byte[] bytes) {
        StringBuilder out = new StringBuilder(bytes.length * 2);
        for (byte value : bytes) out.append(String.format(Locale.US, "%02x", value & 0xff));
        return out.toString();
    }
}
