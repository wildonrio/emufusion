package com.thorium.preview;

import java.io.BufferedInputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.Arrays;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.zip.CRC32;

/**
 * Names a cartridge ROM by its checksum: libretro-database's No-Intro DAT for
 * the system maps the dump's CRC32 to the exact name libretro's thumbnail
 * catalog files its artwork under.
 *
 * <p>ROM file names are often shortened or retitled ("Dr. Mario & Puzzle
 * League" is No-Intro's "2 Games in One! - Dr. Mario + Puzzle League (USA)",
 * "Dragons Heart" is "DragonHeart (USA, Europe)"), which no title matching
 * reaches. On the Thor, 233 of the 455 games recorded as having no box art in
 * any source had it under their No-Intro name (2026-10-24).</p>
 *
 * <p>Each system's DAT is named like its libretro catalog
 * (GameSystems' libretro name), so one rule covers every single-file
 * cartridge system below. Disc systems are identified per track and are not
 * handled here.</p>
 */
final class RomCatalogName {
    static final String DAT_BASE =
            "https://raw.githubusercontent.com/libretro/libretro-database/master/metadat/no-intro/";
    /** The largest No-Intro cartridge dumps (DS) are 512 MB. */
    static final long MAX_ROM_BYTES = 512L * 1024L * 1024L;
    /** GameSystems folders whose dumps No-Intro hashes as one whole file. */
    private static final Set<String> SYSTEMS = new HashSet<>(Arrays.asList(
            "nes", "snes", "gb", "gbc", "gba", "n64", "nds", "virtualboy",
            "megadrive", "mastersystem", "gamegear", "sg1000", "sega32x",
            "atari2600", "atari5200", "atari7800", "jaguar", "pcengine",
            "ngp", "wonderswan", "wonderswancolor", "colecovision",
            "intellivision", "odyssey2"));
    private static final Pattern XML_GAME = Pattern.compile("<game\\s+name=\"([^\"]*)\"");
    private static final Pattern XML_CRC = Pattern.compile("<rom\\b[^>]*\\bcrc=\"([0-9A-Fa-f]{8})\"");
    private static final Pattern CMP_NAME = Pattern.compile("^\\s*name\\s+\"(.*)\"\\s*$");
    private static final Pattern CMP_CRC = Pattern.compile("\\bcrc\\s+([0-9A-Fa-f]{8})\\b");

    private RomCatalogName() {}

    static boolean supported(String folder) {
        return folder != null && SYSTEMS.contains(folder);
    }

    /** The DAT for a system's libretro catalog name. */
    static String datUrl(String libretroName) {
        StringBuilder out = new StringBuilder(DAT_BASE);
        for (byte b : (libretroName + ".dat").getBytes(java.nio.charset.StandardCharsets.UTF_8)) {
            int ch = b & 0xff;
            if ((ch >= 'A' && ch <= 'Z') || (ch >= 'a' && ch <= 'z') || (ch >= '0' && ch <= '9') ||
                    ch == '-' || ch == '_' || ch == '.' || ch == '~') out.append((char) ch);
            else out.append(String.format(Locale.US, "%%%02X", ch));
        }
        return out.toString();
    }

    /**
     * CRC32 of the dump as No-Intro catalogs it, "" when unreadable or too
     * large. Copier and emulator headers are left out (iNES, SNES copier,
     * Atari 7800, PC Engine) and byte-swapped N64 images are read as the
     * big-endian original.
     */
    static String crc32(File rom, String folder) {
        if (rom == null || !rom.isFile()) return "";
        long length = rom.length();
        if (length <= 0 || length > MAX_ROM_BYTES) return "";
        CRC32 crc = new CRC32();
        try (InputStream input = new BufferedInputStream(new FileInputStream(rom), 256 * 1024)) {
            byte[] head = new byte[(int) Math.min(512, length)];
            int headLength = readFully(input, head);
            int skip = headerLength(folder, head, headLength, length);
            int swap = "n64".equals(folder) ? n64Order(head, headLength) : 0;
            byte[] buffer = new byte[256 * 1024];
            int used = 0;
            if (headLength > skip) {
                used = headLength - skip;
                System.arraycopy(head, skip, buffer, 0, used);
            }
            // The buffer is a whole number of 4-byte words, so a full one swaps
            // cleanly; only the final partial buffer can end mid-word.
            int count;
            while ((count = input.read(buffer, used, buffer.length - used)) >= 0) {
                used += count;
                if (used < buffer.length) continue;
                if (swap != 0) unswap(buffer, used, swap);
                crc.update(buffer, 0, used);
                used = 0;
            }
            if (swap != 0) unswap(buffer, used - used % 4, swap);
            crc.update(buffer, 0, used);
        } catch (IOException unreadable) {
            return "";
        }
        return String.format(Locale.US, "%08X", crc.getValue());
    }

    private static int readFully(InputStream input, byte[] target) throws IOException {
        int total = 0;
        while (total < target.length) {
            int count = input.read(target, total, target.length - total);
            if (count < 0) break;
            total += count;
        }
        return total;
    }

    private static int headerLength(String folder, byte[] head, int count, long length) {
        if ("nes".equals(folder) && count >= 16 && head[0] == 'N' && head[1] == 'E' &&
                head[2] == 'S' && head[3] == 0x1A) return 16;
        if ("atari7800".equals(folder) && count >= 128 &&
                "ATARI7800".equals(new String(head, 1, 9, java.nio.charset.StandardCharsets.US_ASCII)))
            return 128;
        if ("snes".equals(folder) && length % 1024 == 512 && count >= 512) return 512;
        if ("pcengine".equals(folder) && length % 8192 == 512 && count >= 512) return 512;
        return 0;
    }

    /** 0 for big-endian (.z64), 2 for 16-bit swapped (.v64), 4 for little-endian (.n64). */
    private static int n64Order(byte[] head, int count) {
        if (count < 4) return 0;
        int first = head[0] & 0xff, second = head[1] & 0xff;
        if (first == 0x37 && second == 0x80) return 2;
        if (first == 0x40 && second == 0x12) return 4;
        return 0;
    }

    private static void unswap(byte[] data, int length, int order) {
        for (int i = 0; i + 3 < length; i += 4) {
            byte a = data[i], b = data[i + 1], c = data[i + 2], d = data[i + 3];
            if (order == 2) { data[i] = b; data[i + 1] = a; data[i + 2] = d; data[i + 3] = c; }
            else { data[i] = d; data[i + 1] = c; data[i + 2] = b; data[i + 3] = a; }
        }
    }

    /**
     * CRC32 (upper case) to game name, from the clrmamepro text libretro
     * publishes or a Logiqx XML DAT. The first game listing a CRC keeps it.
     */
    static Map<String, String> parseDat(String text) {
        Map<String, String> names = new HashMap<>();
        if (text == null) return names;
        String game = "";
        boolean inGame = false;
        for (String line : text.split("\r?\n")) {
            String trimmed = line.trim();
            Matcher xml = XML_GAME.matcher(line);
            if (xml.find()) {
                game = unescapeXml(xml.group(1));
                inGame = true;
            } else if (trimmed.startsWith("game (") || trimmed.equals("game(")) {
                game = "";
                inGame = true;
                continue;
            } else if (inGame && game.isEmpty() && !trimmed.startsWith("rom")) {
                Matcher name = CMP_NAME.matcher(line);
                if (name.find()) {
                    game = name.group(1).replace("\\\"", "\"");
                    continue;
                }
            }
            if (game.isEmpty()) continue;
            Matcher crc = trimmed.startsWith("rom") ? CMP_CRC.matcher(line) : XML_CRC.matcher(line);
            if (crc.find()) names.putIfAbsent(crc.group(1).toUpperCase(Locale.US), game);
        }
        return names;
    }

    private static String unescapeXml(String value) {
        return value.replace("&quot;", "\"").replace("&apos;", "'")
                .replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&");
    }

    /** libretro's thumbnail file name for a game name: &*&#47;:`<>?\|" become _. */
    static String thumbnailName(String name) {
        return name.replaceAll("[&*/:`<>?\\\\|\"]", "_") + ".png";
    }

    /** The name without No-Intro's region, language and revision tags. */
    static String baseTitle(String name) {
        int tag = name.indexOf(" (");
        return (tag > 0 ? name.substring(0, tag) : name).trim();
    }
}
