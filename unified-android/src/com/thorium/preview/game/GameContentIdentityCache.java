package com.thorium.preview.game;

import android.content.Context;
import android.content.SharedPreferences;

import java.io.File;
import java.io.FileInputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Locale;

/** Persistent exact game hashes keyed by a cheap file-change fingerprint. */
final class GameContentIdentityCache {
    private static final String PREFS = "game-content-identities-v1";
    private static final int SAMPLE_BYTES = 64 * 1024;

    private GameContentIdentityCache() {}

    static String sha256(Context context, File file) throws Exception {
        if (context == null || file == null || !file.isFile())
            throw new IllegalArgumentException("game content is required");
        String key = cacheKey(file);
        SharedPreferences preferences = context.getSharedPreferences(PREFS,
                Context.MODE_PRIVATE);
        String cached = preferences.getString(key, "");
        if (cached != null && cached.matches("[0-9a-f]{64}")) return cached;

        String computed = fullSha256(file);
        // apply() updates this process immediately and persists off the launch
        // thread. A lost write merely causes one later re-hash.
        preferences.edit().putString(key, computed).apply();
        return computed;
    }

    private static String cacheKey(File file) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        String metadata = file.getCanonicalPath() + "\n" + file.length() + "\n" +
                file.lastModified();
        digest.update(metadata.getBytes(StandardCharsets.UTF_8));
        sample(digest, file, 0L);
        long tail = Math.max(0L, file.length() - SAMPLE_BYTES);
        if (tail > 0L) sample(digest, file, tail);
        return "content-" + hex(digest.digest());
    }

    private static void sample(MessageDigest digest, File file, long offset)
            throws Exception {
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

    private static String fullSha256(File file) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        InputStream input = new FileInputStream(file);
        try {
            byte[] buffer = new byte[256 * 1024];
            int count;
            while ((count = input.read(buffer)) >= 0)
                if (count > 0) digest.update(buffer, 0, count);
        } finally { input.close(); }
        return hex(digest.digest());
    }

    private static String hex(byte[] bytes) {
        StringBuilder value = new StringBuilder(bytes.length * 2);
        for (byte item : bytes)
            value.append(String.format(Locale.US, "%02x", item & 0xff));
        return value.toString();
    }
}
