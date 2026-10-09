package com.thorium.preview.cheats.delivery;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Locale;

/**
 * Atomic, bounded, ownership-checked text files inside an engine's tree.
 *
 * <p>An engine's cheat and patch files are the engine's own territory: the
 * user may have hand-placed one, and some cores rewrite theirs at runtime.
 * EmuFusion therefore records a hidden sidecar next to every file it
 * writes, and refuses to replace a file that either has no sidecar (someone
 * else's) or -- for engines that never rewrite the file -- no longer hashes
 * to what EmuFusion last wrote (someone edited it since).
 *
 * <p>Writes go to a {@code .part} file that is fsynced and renamed, so a
 * crash mid-write leaves either the previous complete file or none.
 */
public final class OwnedFiles {
    /** Larger than any real cheat file; a guard against runaway output. */
    public static final int MAX_BYTES = 4 * 1024 * 1024;

    /** How much drift from EmuFusion's last write still counts as EmuFusion's file. */
    public enum Ownership {
        /** Bytes must match the sidecar: the engine never rewrites this file. */
        EXACT,
        /** A sidecar is enough: the engine itself rewrites this file (PPSSPP's CWCheat ini). */
        CREATED
    }

    private OwnedFiles() {}

    static File sidecar(File file) {
        return new File(file.getParentFile(), ".EmuFusion-" + file.getName() + ".sha256");
    }

    /** True when EmuFusion may write {@code file} under the given rule. */
    public static boolean owns(File file, Ownership rule) throws IOException {
        if (!file.exists()) return true;
        if (!file.isFile()) return false;
        File sidecar = sidecar(file);
        if (!sidecar.isFile()) return false;
        if (rule == Ownership.CREATED) return true;
        String recorded = readText(sidecar, 256).trim();
        return !recorded.isEmpty() && recorded.equals(sha256(file));
    }

    /**
     * Writes {@code text} to {@code file} atomically.
     *
     * @return true when the file now holds the text; false when it belongs to
     *         someone else and was left untouched
     */
    public static boolean write(File file, String text, Ownership rule) throws IOException {
        if (file == null || text == null) throw new IllegalArgumentException("file and text required");
        byte[] bytes = text.getBytes(StandardCharsets.UTF_8);
        if (bytes.length > MAX_BYTES) throw new IOException("refusing to write " + bytes.length +
                " bytes to " + file + " (cap " + MAX_BYTES + ")");
        if (!owns(file, rule)) return false;
        File parent = file.getParentFile();
        if (parent != null && !parent.isDirectory() && !parent.mkdirs() && !parent.isDirectory())
            throw new IOException("cannot create " + parent);
        // Idempotent: identical content is a no-op, so an unchanged file keeps
        // its mtime and the engines that watch it do not reload for nothing.
        if (file.isFile() && file.length() == bytes.length && sha256(bytes).equals(sha256(file))
                && sidecar(file).isFile())
            return true;
        replace(file, bytes);
        replace(sidecar(file), (sha256(bytes) + "\n").getBytes(StandardCharsets.UTF_8));
        return true;
    }

    /** Removes {@code file} and its sidecar when EmuFusion owns it. */
    public static boolean remove(File file, Ownership rule) throws IOException {
        if (file == null || !file.exists()) return false;
        if (!owns(file, rule)) return false;
        boolean removed = file.delete();
        sidecar(file).delete();
        return removed;
    }

    /** True for a path that stays inside {@code root} once resolved. */
    public static boolean inside(File root, File candidate) throws IOException {
        String rootPath = root.getCanonicalPath();
        String path = candidate.getCanonicalPath();
        return path.equals(rootPath) || path.startsWith(rootPath + File.separator);
    }

    /**
     * A file name safe to place directly in an engine directory: separators,
     * shell-hostile punctuation and control characters become underscores;
     * the brackets and spaces ROM names carry survive, because flycast looks
     * a cheat file up by the content file's own name.
     */
    public static String safeName(String name) {
        if (name == null) return "";
        StringBuilder out = new StringBuilder(name.length());
        for (int i = 0; i < name.length() && out.length() < 120; i++) {
            char ch = name.charAt(i);
            boolean hostile = ch < 0x20 || ch == 0x7f || ch == '/' || ch == '\\' || ch == ':'
                    || ch == '*' || ch == '?' || ch == '"' || ch == '<' || ch == '>' || ch == '|';
            out.append(hostile ? '_' : ch);
        }
        String value = out.toString().trim();
        while (value.startsWith(".")) value = value.substring(1);
        return value;
    }

    public static String readText(File file, int maxBytes) throws IOException {
        if (file == null || !file.isFile()) return "";
        long length = file.length();
        if (length > maxBytes) throw new IOException(file + " exceeds " + maxBytes + " bytes");
        byte[] bytes = new byte[(int) length];
        try (InputStream input = new FileInputStream(file)) {
            int total = 0;
            while (total < bytes.length) {
                int count = input.read(bytes, total, bytes.length - total);
                if (count < 0) break;
                total += count;
            }
        }
        return new String(bytes, StandardCharsets.UTF_8);
    }

    private static void replace(File file, byte[] bytes) throws IOException {
        File part = new File(file.getPath() + ".part");
        try (FileOutputStream out = new FileOutputStream(part)) {
            out.write(bytes);
            out.flush();
            out.getFD().sync();
        }
        if (file.exists() && !file.delete()) {
            part.delete();
            throw new IOException("cannot replace " + file);
        }
        if (!part.renameTo(file)) {
            part.delete();
            throw new IOException("cannot rename " + part + " to " + file);
        }
    }

    public static String sha256(File file) throws IOException {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            try (InputStream input = new FileInputStream(file)) {
                byte[] buffer = new byte[64 * 1024];
                int count;
                long total = 0;
                while ((count = input.read(buffer)) >= 0) {
                    total += count;
                    if (total > MAX_BYTES) throw new IOException(file + " is too large to be ours");
                    if (count > 0) digest.update(buffer, 0, count);
                }
            }
            return hex(digest.digest());
        } catch (java.security.NoSuchAlgorithmException impossible) {
            throw new IOException(impossible);
        }
    }

    static String sha256(byte[] bytes) throws IOException {
        try {
            return hex(MessageDigest.getInstance("SHA-256").digest(bytes));
        } catch (java.security.NoSuchAlgorithmException impossible) {
            throw new IOException(impossible);
        }
    }

    static String sha256(String text) throws IOException {
        return sha256(text.getBytes(StandardCharsets.UTF_8));
    }

    static String hex(byte[] bytes) {
        StringBuilder out = new StringBuilder(bytes.length * 2);
        for (byte value : bytes) out.append(String.format(Locale.US, "%02x", value & 0xff));
        return out.toString();
    }
}
