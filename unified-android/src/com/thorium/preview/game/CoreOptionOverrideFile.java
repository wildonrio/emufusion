package com.thorium.preview.game;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Reader/writer for {@code <engine root>/lucent-core-overrides.txt}, the
 * launch-time core-option override channel consumed by
 * {@code register_core_variable_defaults()} in
 * {@code native/lucent_libretro_host.c}.
 *
 * <p>Format: one {@code key=value} per line, UTF-8, {@code \n} line ends.
 * Blank lines and lines starting with {@code #} are ignored. Keys are
 * libretro core-option identifiers ({@code [A-Za-z0-9_.-]}, at most
 * {@link #MAX_KEY_LENGTH} bytes); values are the exact option tokens the core
 * advertises (printable, no control characters, at most
 * {@link #MAX_VALUE_LENGTH} bytes). The native host applies an override only
 * when the token exists in the core's own declared option list, so an
 * unknown or misspelled value can never reach an emulator.</p>
 *
 * <p>The file is bounded on both sides ({@link #MAX_ENTRIES} entries,
 * {@link #MAX_FILE_BYTES} bytes), written atomically ({@code .part} then
 * rename), and every method here is pure Java so the host test suite covers
 * it without an Android runtime.</p>
 */
public final class CoreOptionOverrideFile {
    /** File name inside the engine's system root; mirrored in the native host. */
    public static final String NAME = "lucent-core-overrides.txt";
    public static final int MAX_ENTRIES = 64;
    public static final int MAX_KEY_LENGTH = 255;
    public static final int MAX_VALUE_LENGTH = 1023;
    public static final int MAX_FILE_BYTES = 64 * 1024;

    private static final String HEADER =
            "# Lucent launch-time core-option overrides. Generated; do not edit.\n";

    private CoreOptionOverrideFile() {}

    /** The override file for an engine root. */
    public static File in(File engineRoot) {
        return new File(engineRoot, NAME);
    }

    /** Pure key validation shared with {@link #write}. */
    public static boolean isValidKey(String key) {
        if (key == null || key.isEmpty() || key.length() > MAX_KEY_LENGTH) return false;
        for (int index = 0; index < key.length(); index++) {
            char c = key.charAt(index);
            boolean ok = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
                    (c >= '0' && c <= '9') || c == '_' || c == '-' || c == '.';
            if (!ok) return false;
        }
        return true;
    }

    /** Pure value validation: printable text without line breaks or controls. */
    public static boolean isValidValue(String value) {
        if (value == null || value.isEmpty() || value.length() > MAX_VALUE_LENGTH) return false;
        for (int index = 0; index < value.length(); index++) {
            char c = value.charAt(index);
            if (c < 0x20 || c == 0x7f) return false;
        }
        return true;
    }

    /**
     * Serialises the overrides. Invalid keys or values are skipped rather than
     * written, so the output always parses back to a subset of the input.
     */
    public static String serialise(Map<String, String> overrides) {
        StringBuilder builder = new StringBuilder(HEADER);
        if (overrides == null) return builder.toString();
        int written = 0;
        for (Map.Entry<String, String> entry : overrides.entrySet()) {
            if (written >= MAX_ENTRIES) break;
            String key = entry.getKey();
            String value = entry.getValue() == null ? null : entry.getValue().trim();
            if (!isValidKey(key) || !isValidValue(value)) continue;
            builder.append(key).append('=').append(value).append('\n');
            written++;
        }
        return builder.toString();
    }

    /** Parses file text; tolerant of comments, blank lines, CRLF, and junk. */
    public static Map<String, String> parse(String text) {
        LinkedHashMap<String, String> overrides = new LinkedHashMap<>();
        if (text == null) return overrides;
        int start = 0;
        while (start < text.length() && overrides.size() < MAX_ENTRIES) {
            int end = text.indexOf('\n', start);
            if (end < 0) end = text.length();
            String line = text.substring(start, end).trim();
            start = end + 1;
            if (line.isEmpty() || line.charAt(0) == '#') continue;
            int separator = line.indexOf('=');
            if (separator <= 0) continue;
            String key = line.substring(0, separator).trim();
            String value = line.substring(separator + 1).trim();
            if (!isValidKey(key) || !isValidValue(value)) continue;
            overrides.put(key, value);
        }
        return overrides;
    }

    /** Reads the file; an absent, oversized, or unreadable file reads as empty. */
    public static Map<String, String> read(File file) {
        if (file == null || !file.isFile()) return Collections.emptyMap();
        if (file.length() > MAX_FILE_BYTES) return Collections.emptyMap();
        InputStream input = null;
        try {
            input = new FileInputStream(file);
            ByteArrayOutputStream bytes = new ByteArrayOutputStream();
            byte[] buffer = new byte[4096];
            int total = 0;
            int count;
            while ((count = input.read(buffer)) > 0) {
                total += count;
                if (total > MAX_FILE_BYTES) return Collections.emptyMap();
                bytes.write(buffer, 0, count);
            }
            return parse(new String(bytes.toByteArray(), StandardCharsets.UTF_8));
        } catch (IOException ignored) {
            return Collections.emptyMap();
        } finally {
            if (input != null) {
                try { input.close(); } catch (IOException ignored) { }
            }
        }
    }

    /**
     * Writes the overrides atomically. An empty map removes the file instead,
     * so "no overrides" and "no file" are the same state for the native host.
     */
    public static void write(File file, Map<String, String> overrides) throws IOException {
        if (file == null) throw new IOException("override file path is required");
        String text = serialise(overrides);
        if (parse(text).isEmpty()) {
            delete(file);
            return;
        }
        File parent = file.getParentFile();
        if (parent != null && !parent.isDirectory() && !parent.mkdirs())
            throw new IOException("cannot create " + parent);
        File part = new File(file.getPath() + ".part");
        OutputStream output = null;
        try {
            output = new FileOutputStream(part);
            output.write(text.getBytes(StandardCharsets.UTF_8));
            output.flush();
        } finally {
            if (output != null) output.close();
        }
        if (!part.renameTo(file)) {
            // A stale target can block rename on some filesystems; retry once.
            if (!file.delete() || !part.renameTo(file)) {
                part.delete();
                throw new IOException("cannot replace " + file);
            }
        }
    }

    /** Removes the file and any stale partial; true when nothing remains. */
    public static boolean delete(File file) {
        if (file == null) return true;
        File part = new File(file.getPath() + ".part");
        if (part.isFile()) part.delete();
        return !file.exists() || file.delete();
    }
}
