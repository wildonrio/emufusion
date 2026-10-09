package com.thorium.preview.cheats.delivery;

import android.content.Context;
import android.content.SharedPreferences;
import android.net.Uri;
import android.os.SystemClock;

import com.thorium.preview.game.GameLaunchRequest;

import java.io.File;
import java.io.FileInputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Locale;

/**
 * The directories an engine reads its cheat files from, derived the same
 * way the sessions derive them (read-only mirror; the sessions stay the
 * owners of these rules).
 *
 * <ul>
 * <li>Engine root: {@code getDir("engine-system")/<engineId>} -- what
 * {@code LibretroEngineSpec.installRuntime},
 * {@code Phase2QualificationCatalog.installRuntimeAssets} and
 * {@code NativeAdapterSystemDirectory} all hand the core as its system
 * directory.</li>
 * <li>Per-game save directory for the hardware libretro route
 * ({@code PpssppGlesEngineSession}):
 * {@code files/engine-saves[-qa/<session>]/<engineId>/<sha256(content)[0:32]>}.
 * The hash is the one {@code GameContentIdentityCache} caches in
 * SharedPreferences {@code game-content-identities-v1}; the session hashes
 * a cold game itself, so this class only reads the cache and waits for it
 * rather than hashing a multi-gigabyte disc a second time.</li>
 * </ul>
 */
final class EngineRoots {
    private static final String IDENTITY_PREFS = "game-content-identities-v1";
    private static final int SAMPLE_BYTES = 64 * 1024;

    private EngineRoots() {}

    static File engineRoot(Context context, String engineId) {
        return new File(context.getDir("engine-system", Context.MODE_PRIVATE),
                engineId.trim().toLowerCase(Locale.US));
    }

    /** The content file, or null when the launch URI does not name a local file. */
    static File contentFile(Uri uri) {
        if (uri == null) return null;
        String raw = "file".equals(uri.getScheme()) ? uri.getPath() : uri.getQueryParameter("path");
        if (raw == null || raw.trim().isEmpty()) return null;
        try {
            File file = new File(raw).getCanonicalFile();
            return file.isFile() ? file : null;
        } catch (Exception unreadable) {
            return null;
        }
    }

    static String contentStem(File file) {
        if (file == null) return "";
        String name = file.getName();
        int dot = name.lastIndexOf('.');
        return dot > 0 && name.length() - dot <= 5 ? name.substring(0, dot) : name;
    }

    /**
     * The per-game save directory the hardware libretro sessions use, or
     * null when the content hash is not known within {@code waitMillis}.
     */
    static File gameSaveDirectory(Context context, GameLaunchRequest request, String engineId,
                                  File game, long waitMillis) {
        String hash = cachedContentHash(context, game, waitMillis);
        if (hash == null) return null;
        String saveRoot = request.qualificationSession.isEmpty() ? "engine-saves"
                : "engine-saves-qa/" + request.qualificationSession;
        return new File(context.getFilesDir(), saveRoot + "/" + engineId.trim().toLowerCase(Locale.US)
                + "/" + hash.substring(0, 32));
    }

    /**
     * Polls {@code GameContentIdentityCache}'s SharedPreferences entry for the
     * game. The session publishes it with apply(), which is visible to this
     * process immediately, as soon as its own hashing finishes.
     */
    static String cachedContentHash(Context context, File game, long waitMillis) {
        if (context == null || game == null) return null;
        String key;
        try {
            key = cacheKey(game);
        } catch (Exception unreadable) {
            return null;
        }
        SharedPreferences preferences = context.getSharedPreferences(IDENTITY_PREFS, Context.MODE_PRIVATE);
        long deadline = SystemClock.elapsedRealtime() + Math.max(0L, waitMillis);
        while (true) {
            String cached = preferences.getString(key, "");
            if (cached != null && cached.matches("[0-9a-f]{64}")) return cached;
            if (SystemClock.elapsedRealtime() >= deadline) return null;
            try { Thread.sleep(250L); } catch (InterruptedException interrupted) {
                Thread.currentThread().interrupt();
                return null;
            }
        }
    }

    // Mirrors GameContentIdentityCache.cacheKey byte for byte.
    private static String cacheKey(File file) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        String metadata = file.getCanonicalPath() + "\n" + file.length() + "\n" + file.lastModified();
        digest.update(metadata.getBytes(StandardCharsets.UTF_8));
        sample(digest, file, 0L);
        long tail = Math.max(0L, file.length() - SAMPLE_BYTES);
        if (tail > 0L) sample(digest, file, tail);
        return "content-" + OwnedFiles.hex(digest.digest());
    }

    private static void sample(MessageDigest digest, File file, long offset) throws Exception {
        InputStream input = new FileInputStream(file);
        try {
            long remaining = offset;
            while (remaining > 0L) {
                long skipped = input.skip(remaining);
                if (skipped <= 0L) {
                    if (input.read() < 0) return;
                    skipped = 1L;
                }
                remaining -= skipped;
            }
            byte[] buffer = new byte[SAMPLE_BYTES];
            int total = 0;
            while (total < buffer.length) {
                int count = input.read(buffer, total, buffer.length - total);
                if (count < 0) break;
                total += count;
            }
            digest.update(buffer, 0, total);
        } finally { input.close(); }
    }

    /** "GAMEIDR<rev>" for a raw GameCube/Wii image, mirroring the session's discGameIdentity. */
    static String discIdentity(String systemId, File game) {
        String system = systemId == null ? "" : systemId.toLowerCase(Locale.US);
        if (!(system.equals("gamecube") || system.equals("gc") || system.equals("wii")) || game == null)
            return "";
        try (java.io.RandomAccessFile input = new java.io.RandomAccessFile(game, "r")) {
            if (input.length() < 8) return "";
            byte[] header = new byte[8];
            input.readFully(header);
            String id = new String(header, 0, 6, StandardCharsets.US_ASCII);
            if (!id.matches("[A-Z0-9]{6}")) return "";
            return id + "R" + (header[7] & 0xff);
        } catch (Exception ignored) {
            return "";
        }
    }
}
