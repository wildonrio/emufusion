package com.thorium.preview.game;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.List;

/** Imports a user's System Card; never downloads or bundles console firmware. */
final class PcEngineCdFirmware {
    // Libretro's Beetle PCE FAST firmware contract:
    // https://docs.libretro.com/library/beetle_pce_fast/#bios
    static final String SYSTEM_CARD_3_MD5 = "38179df8f4ac870017db21ebcbf53114";
    private static final long MAX_BYTES = 1024 * 1024;
    private static final String[] SEARCH_PATHS = {
        "ROMs/pcenginecd/BIOS", "Games/pcenginecd/BIOS", "BIOS/pcenginecd",
        "ROMs/pcengine/BIOS", "Games/pcengine/BIOS",
        "ROMs/pcenginecd", "Games/pcenginecd", "BIOS"
    };

    static final class SetupException extends IllegalStateException {
        SetupException(String message) { super(message); }
    }

    private PcEngineCdFirmware() {}

    static String install(File system) throws Exception {
        return installMatching(system, NativeAdapterPrerequisites.permittedVolumeRoots(),
                SYSTEM_CARD_3_MD5);
    }

    /** Parameterized identity lets host tests exercise the importer with original test bytes. */
    static String installMatching(File system, List<File> volumes, String expectedMd5)
            throws Exception {
        File destination = new File(system, "syscard3.pce");
        if (matches(destination, expectedMd5)) return identity(destination);
        File source = null;
        for (File volume : volumes) {
            for (String path : SEARCH_PATHS) {
                source = find(new File(volume, path), expectedMd5, 0);
                if (source != null) break;
            }
            if (source != null) break;
        }
        if (source == null) throw new SetupException(
                "PC Engine CD needs your System Card 3 BIOS (syscard3.pce). " +
                "Place it in ROMs/pcenginecd/BIOS on internal or removable storage, " +
                "then try again. The file must match the supported System Card 3 image.");
        if (!system.isDirectory() && !system.mkdirs())
            throw new IOException("Cannot create PC Engine CD system directory");
        File temporary = File.createTempFile(".syscard3-", ".tmp", system);
        try {
            try (FileInputStream input = new FileInputStream(source);
                    FileOutputStream output = new FileOutputStream(temporary)) {
                byte[] buffer = new byte[16 * 1024];
                int count;
                long total = 0;
                while ((count = input.read(buffer)) != -1) {
                    total += count;
                    if (total > MAX_BYTES) throw new IOException("System Card changed during import");
                    output.write(buffer, 0, count);
                }
                output.getFD().sync();
            }
            if (!matches(temporary, expectedMd5))
                throw new IOException("System Card changed during import; try again");
            if (!temporary.renameTo(destination))
                throw new IOException("Cannot install PC Engine CD System Card");
            return identity(destination);
        } finally {
            if (temporary.exists()) temporary.delete();
        }
    }

    private static File find(File directory, String expectedMd5, int depth) throws Exception {
        if (depth > 2 || !directory.isDirectory()) return null;
        File[] files = directory.listFiles();
        if (files == null) return null;
        Arrays.sort(files, (left, right) -> left.getName().compareTo(right.getName()));
        for (File file : files) if (matches(file, expectedMd5)) return file;
        for (File file : files) if (file.isDirectory()) {
            File found = find(file, expectedMd5, depth + 1);
            if (found != null) return found;
        }
        return null;
    }

    private static boolean matches(File file, String expectedMd5) throws Exception {
        if (!file.isFile() || !file.canRead() || file.length() == 0 || file.length() > MAX_BYTES)
            return false;
        try { return expectedMd5.equals(digest(file, "MD5")); }
        catch (IOException unavailable) { return false; } // A removed card is not a native crash.
    }

    private static String identity(File installed) throws Exception {
        return "firmware:sha256:" + digest(installed, "SHA-256");
    }

    private static String digest(File file, String algorithm) throws Exception {
        MessageDigest digest = MessageDigest.getInstance(algorithm);
        try (FileInputStream input = new FileInputStream(file)) {
            byte[] buffer = new byte[16 * 1024];
            int count;
            while ((count = input.read(buffer)) != -1) digest.update(buffer, 0, count);
        }
        StringBuilder hex = new StringBuilder();
        for (byte value : digest.digest()) {
            hex.append(Character.forDigit((value >>> 4) & 15, 16));
            hex.append(Character.forDigit(value & 15, 16));
        }
        return hex.toString();
    }
}
