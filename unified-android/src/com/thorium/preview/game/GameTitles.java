package com.thorium.preview.game;

import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.util.Locale;

/**
 * Display title for a launched file when the frontend did not pass one.
 *
 * <p>Most systems are a single file named after the game. Folder-format
 * games are not: a PS3 disc folder always launches
 * {@code PS3_GAME/USRDIR/EBOOT.BIN} (the pause menu said "EBOOT"), and a Wii U
 * title folder launches {@code code/<anything>.rpx}. For those the disc's own
 * PARAM.SFO title, else the game folder's name, is used.
 */
final class GameTitles {
    private static final int MAX_SFO_BYTES = 64 * 1024;

    private GameTitles() {}

    static String forFile(File file) {
        String name = file.getName();
        int dot = name.lastIndexOf('.');
        String base = dot > 0 ? name.substring(0, dot) : name;
        File parent = file.getParentFile();
        File grandparent = parent == null ? null : parent.getParentFile();
        if ("EBOOT".equalsIgnoreCase(base) && parent != null && grandparent != null &&
                "USRDIR".equalsIgnoreCase(parent.getName()) &&
                "PS3_GAME".equalsIgnoreCase(grandparent.getName())) {
            String title = sfoTitle(new File(grandparent, "PARAM.SFO"));
            if (!title.isEmpty()) return title;
            return folderTitle(grandparent.getParentFile(), base);
        }
        if (name.toLowerCase(Locale.ROOT).endsWith(".rpx") && parent != null &&
                "code".equalsIgnoreCase(parent.getName())) {
            return folderTitle(grandparent, base);
        }
        return base;
    }

    /** "Ico & Shadow ... Collection, The (World) (En,Fr,Es)" -> "The Ico & ... Collection". */
    static String folderTitle(File folder, String fallback) {
        if (folder == null) return fallback;
        String title = folder.getName().replaceAll("\\s*[\\(\\[][^\\)\\]]*[\\)\\]]", "").trim();
        int comma = title.lastIndexOf(", ");
        if (comma > 0) {
            String article = title.substring(comma + 2);
            if (article.matches("(?i)the|a|an")) title = article + " " + title.substring(0, comma);
        }
        return title.isEmpty() ? fallback : title;
    }

    /** TITLE from a PS3 PARAM.SFO, or "" when absent or malformed. */
    static String sfoTitle(File sfo) {
        if (!sfo.isFile() || sfo.length() > MAX_SFO_BYTES) return "";
        byte[] bytes = new byte[(int) sfo.length()];
        try (InputStream in = new FileInputStream(sfo)) {
            int read = 0;
            while (read < bytes.length) {
                int n = in.read(bytes, read, bytes.length - read);
                if (n < 0) return "";
                read += n;
            }
        } catch (IOException error) {
            return "";
        }
        try {
            ByteBuffer data = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN);
            if (data.getInt(0) != 0x46535000) return "";          // "\0PSF"
            int keys = data.getInt(8), values = data.getInt(12), count = data.getInt(16);
            for (int i = 0; i < count; i++) {
                int entry = 20 + i * 16;
                int keyStart = keys + (data.getShort(entry) & 0xffff);
                int keyEnd = keyStart;
                while (keyEnd < bytes.length && bytes[keyEnd] != 0) keyEnd++;
                if (!"TITLE".equals(new String(bytes, keyStart, keyEnd - keyStart,
                        StandardCharsets.UTF_8))) continue;
                int length = data.getInt(entry + 4);
                int start = values + data.getInt(entry + 12);
                int end = start;
                while (end < start + length && end < bytes.length && bytes[end] != 0) end++;
                return new String(bytes, start, end - start, StandardCharsets.UTF_8)
                        .replaceAll("\\s+", " ").trim();
            }
        } catch (RuntimeException malformed) {
            return "";
        }
        return "";
    }
}
