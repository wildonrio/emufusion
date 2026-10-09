package com.thorium.preview.cheats.sources;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Locale;

/**
 * Stable cheat ids for downloaded rows.
 *
 * <p>The user's selection is persisted by id, so an id must survive a
 * re-download, a re-import, and a source republishing the same code under a
 * different name. It is therefore derived from the canonical system and the
 * whitespace-normalised code body only, prefixed by the source id so two
 * sources carrying one code stay distinguishable before deduplication.
 * The "libretro" prefix reproduces {@code CheatArchive}'s ids exactly, which
 * is what lets a per-game file carry archive rows without forking the user's
 * saved toggles.
 */
public final class CheatIdFactory {
    private CheatIdFactory() {}

    public static String id(String source, String canonicalSystem, String code) {
        String prefix = source == null || source.trim().isEmpty() ? "downloaded" : source.trim();
        return prefix + "-" + shortHash((canonicalSystem == null ? "" : canonicalSystem)
                + "\n" + normalise(code));
    }

    /** Collapses whitespace and case so equal codes compare equal. */
    public static String normalise(String code) {
        if (code == null) return "";
        return code.trim().replaceAll("\\s+", " ").toUpperCase(Locale.US);
    }

    /** The first 24 hex characters of SHA-256. */
    public static String shortHash(String value) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256")
                    .digest(value.getBytes(StandardCharsets.UTF_8));
            StringBuilder result = new StringBuilder(24);
            for (int i = 0; i < 12; i++)
                result.append(String.format(Locale.US, "%02x", digest[i] & 0xff));
            return result.toString();
        } catch (Exception impossible) {
            throw new IllegalStateException(impossible);
        }
    }
}
