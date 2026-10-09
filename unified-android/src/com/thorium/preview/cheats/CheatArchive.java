package com.thorium.preview.cheats;

import com.thorium.lucent.cheats.Cheat;
import com.thorium.lucent.metadata.EngineSystemIdResolver;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Enumeration;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;

/**
 * Read-only adapter for RetroArch's official {@code cheats.zip} asset.
 *
 * <p>The archive currently contains tens of thousands of game files and more
 * than 170 MiB of text when expanded. It is deliberately kept compressed and
 * queried per game; expanding or parsing the whole collection at startup
 * would waste storage and heap on titles the owner does not have.</p>
 */
public final class CheatArchive {
    public static final String FILE_NAME = "libretro-cheats.zip";
    public static final long MAX_ARCHIVE_BYTES = 128L * 1024L * 1024L;
    private static final long MAX_ENTRY_BYTES = 4L * 1024L * 1024L;
    private static final long MAX_TOTAL_BYTES = 512L * 1024L * 1024L;
    private static final int MIN_CHEAT_FILES = 1_000;
    private static final int MAX_ENTRIES = 100_000;
    private static final int MAX_CHEATS_PER_GAME = 65_536;
    private static final Pattern FIELD = Pattern.compile(
            "^\\s*cheat([0-9]+)_(desc|code)\\s*=\\s*(.*?)\\s*$",
            Pattern.CASE_INSENSITIVE);
    private static final Pattern SERIAL = Pattern.compile(
            "(?i)(?:^|[^A-Z0-9])([A-Z]{4})-?([0-9]{5})(?:[^A-Z0-9]|$)");
    private static final Pattern BRACKET_TAG = Pattern.compile("\\[[^\\]]*\\]");
    private static final Pattern PAREN_TAG = Pattern.compile("\\(([^()]*)\\)");
    private static final Pattern FILE_EXTENSION = Pattern.compile(
            "(?i)\\.(?:zip|7z|rar|iso|cso|chd|pbp|cue|bin|rom|gba|gbc|gb|nes|sfc|smc|nds)$");

    private static final Map<String, String> SYSTEM_FOLDERS;
    static {
        Map<String, String> values = new HashMap<>();
        values.put("nes", "Nintendo - Nintendo Entertainment System");
        values.put("snes", "Nintendo - Super Nintendo Entertainment System");
        values.put("gb", "Nintendo - Game Boy");
        values.put("gbc", "Nintendo - Game Boy Color");
        values.put("gba", "Nintendo - Game Boy Advance");
        values.put("mastersystem", "Sega - Master System - Mark III");
        values.put("gamegear", "Sega - Game Gear");
        values.put("colecovision", "Coleco - ColecoVision");
        values.put("intellivision", "Mattel - Intellivision");
        values.put("psx", "Sony - PlayStation");
        values.put("nds", "Nintendo - Nintendo DS");
        values.put("zxspectrum", "Sinclair - ZX Spectrum +3");
        values.put("arcade", "FBNeo - Arcade Games");
        values.put("neogeo", "FBNeo - Arcade Games");
        values.put("atari2600", "Atari - 2600");
        values.put("atari5200", "Atari - 5200");
        values.put("atari800", "Atari - 8-bit Family");
        values.put("atari7800", "Atari - 7800");
        values.put("pcengine", "NEC - PC Engine - TurboGrafx 16");
        values.put("pcenginecd", "NEC - PC Engine CD - TurboGrafx-CD");
        values.put("megadrive", "Sega - Mega Drive - Genesis");
        values.put("segacd", "Sega - Mega-CD - Sega CD");
        values.put("sega32x", "Sega - 32X");
        values.put("n64", "Nintendo - Nintendo 64");
        values.put("dos", "DOS");
        values.put("dreamcast", "Sega - Dreamcast");
        values.put("saturn", "Sega - Saturn");
        values.put("psp", "Sony - PlayStation Portable");
        values.put("jaguar", "Atari - Jaguar");
        // Verified present in the live buildbot.libretro.com/assets/frontend/cheats.zip
        // (2026-09-06): "sg1000" was already declared as a covered system by
        // CheatSourceRegistry's LIBRETRO row but had no folder mapping here,
        // so it silently never resolved anything. "msx" had neither a
        // systems-list entry nor a folder mapping; both are added together
        // here and in CheatSourceRegistry.java so CheatSource.covers("msx")
        // actually selects this source (the non-fMSX-core folder, matching
        // the "msx" canonical id's bluemsx-based libretro core).
        values.put("sg1000", "Sega - SG-1000");
        values.put("msx", "Microsoft - MSX - MSX2 - MSX2P - MSX Turbo R");
        SYSTEM_FOLDERS = Collections.unmodifiableMap(values);
    }

    private CheatArchive() {}

    public static File file(File cheatDirectory) {
        return new File(cheatDirectory, FILE_NAME);
    }

    /** Rejects corrupt, path-traversing, unexpectedly small, or zip-bomb-like assets. */
    public static void verify(File archive) throws IOException {
        if (archive == null || !archive.isFile() || archive.length() <= 0 ||
                archive.length() > MAX_ARCHIVE_BYTES)
            throw new IOException("cheat archive has an invalid size");
        int entries = 0;
        int cheats = 0;
        long expanded = 0;
        boolean nes = false;
        boolean psp = false;
        try (ZipFile zip = new ZipFile(archive)) {
            Enumeration<? extends ZipEntry> values = zip.entries();
            while (values.hasMoreElements()) {
                ZipEntry entry = values.nextElement();
                if (++entries > MAX_ENTRIES) throw new IOException("too many archive entries");
                String name = entry.getName();
                if (!safeEntryName(name)) throw new IOException("unsafe archive entry");
                long size = entry.getSize();
                if (size < 0 || size > MAX_ENTRY_BYTES)
                    throw new IOException("cheat entry has an invalid size");
                expanded += size;
                if (expanded > MAX_TOTAL_BYTES)
                    throw new IOException("cheat archive expands beyond its bound");
                if (!entry.isDirectory() && name.toLowerCase(Locale.US).endsWith(".cht")) {
                    cheats++;
                    if (name.startsWith(SYSTEM_FOLDERS.get("nes") + "/")) nes = true;
                    if (name.startsWith(SYSTEM_FOLDERS.get("psp") + "/")) psp = true;
                }
            }
        }
        if (cheats < MIN_CHEAT_FILES || !nes || !psp)
            throw new IOException("archive is not the expected multi-system cheat catalog");
    }

    /**
     * Returns every usable code for the title, merging region/format files and
     * deduplicating identical code bodies. Variant provenance remains visible
     * in the detail text because a code authored for another revision may not
     * work on the owner's dump.
     */
    public static List<Cheat> forGame(File archive, String system, String title,
                                      String contentName) {
        if (archive == null || !archive.isFile()) return Collections.emptyList();
        String canonical = EngineSystemIdResolver.canonical(system);
        String folder = SYSTEM_FOLDERS.get(canonical);
        if (folder == null) return Collections.emptyList();
        String titleKey = catalogKey(title);
        String contentKey = catalogKey(contentName);
        String requestedSerial = serial(title + " " + contentName);
        if (titleKey.isEmpty() && contentKey.isEmpty()) return Collections.emptyList();

        List<ZipEntry> matches = new ArrayList<>();
        List<ZipEntry> exactVariants = new ArrayList<>();
        String contentVariant = variantKey(contentName);
        try (ZipFile zip = new ZipFile(archive)) {
            Enumeration<? extends ZipEntry> values = zip.entries();
            String prefix = folder + "/";
            while (values.hasMoreElements()) {
                ZipEntry entry = values.nextElement();
                String name = entry.getName();
                if (entry.isDirectory() || !name.startsWith(prefix) ||
                        !name.toLowerCase(Locale.US).endsWith(".cht")) continue;
                String stem = name.substring(prefix.length(), name.length() - 4);
                String entrySerial = serial(stem);
                if (!requestedSerial.isEmpty()) {
                    if (requestedSerial.equals(entrySerial)) matches.add(entry);
                    continue;
                }
                String key = catalogKey(stem);
                if ((!contentKey.isEmpty() && contentKey.equals(key)) ||
                        (!titleKey.isEmpty() && titleKey.equals(key))) {
                    matches.add(entry);
                    if (!contentVariant.isEmpty() &&
                            contentVariant.equals(variantKey(stem))) exactVariants.add(entry);
                }
            }
            if (!exactVariants.isEmpty()) matches = exactVariants;
            if (matches.isEmpty()) return Collections.emptyList();

            LinkedHashMap<String, Cheat> unique = new LinkedHashMap<>();
            for (ZipEntry entry : matches) {
                String variant = entry.getName().substring(prefix.length(),
                        entry.getName().length() - 4);
                for (Parsed parsed : parse(readEntry(zip, entry))) {
                    String dedupe = normalizedCode(parsed.code);
                    if (dedupe.isEmpty() || unique.containsKey(dedupe)) continue;
                    String detail = "Libretro Database • " + variant;
                    unique.put(dedupe, new Cheat("libretro-" + shortHash(canonical + "\n" + dedupe),
                            parsed.name, detail, parsed.code));
                    if (unique.size() >= MAX_CHEATS_PER_GAME) break;
                }
                if (unique.size() >= MAX_CHEATS_PER_GAME) break;
            }
            return Collections.unmodifiableList(new ArrayList<>(unique.values()));
        } catch (IOException | RuntimeException ignored) {
            // A failed remote catalogue never prevents the game from starting;
            // the bundled/user catalog remains available to the caller.
            return Collections.emptyList();
        }
    }

    private static final class Parsed {
        final String name;
        final String code;
        Parsed(String name, String code) { this.name = name; this.code = code; }
    }

    static List<Parsed> parse(String text) {
        Map<Integer, String> descriptions = new HashMap<>();
        Map<Integer, String> codes = new HashMap<>();
        for (String line : text.split("\\r?\\n")) {
            Matcher match = FIELD.matcher(line);
            if (!match.matches()) continue;
            int index;
            try { index = Integer.parseInt(match.group(1)); }
            catch (NumberFormatException ignored) { continue; }
            String value = unquote(match.group(3));
            if ("desc".equalsIgnoreCase(match.group(2))) descriptions.put(index, value);
            else codes.put(index, value);
        }
        List<Integer> order = new ArrayList<>(codes.keySet());
        Collections.sort(order);
        List<Parsed> result = new ArrayList<>();
        for (Integer index : order) {
            String code = cleanCode(codes.get(index));
            if (code.isEmpty() || hasUnresolvedVariable(code)) continue;
            String name = descriptions.get(index);
            if (name == null || name.trim().isEmpty()) name = "Cheat " + (index + 1);
            result.add(new Parsed(name.trim(), code));
        }
        return result;
    }

    private static String readEntry(ZipFile zip, ZipEntry entry) throws IOException {
        if (entry.getSize() < 0 || entry.getSize() > MAX_ENTRY_BYTES)
            throw new IOException("cheat file is too large");
        try (InputStream input = zip.getInputStream(entry);
             ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[8192];
            int read;
            long total = 0;
            while ((read = input.read(buffer)) >= 0) {
                total += read;
                if (total > MAX_ENTRY_BYTES) throw new IOException("cheat file is too large");
                output.write(buffer, 0, read);
            }
            return new String(output.toByteArray(), StandardCharsets.UTF_8);
        }
    }

    private static String cleanCode(String value) {
        if (value == null) return "";
        String code = value.trim();
        if (code.isEmpty() || code.length() > 64 * 1024) return "";
        for (int i = 0; i < code.length(); i++) {
            char ch = code.charAt(i);
            if (ch == 0 || (ch < 0x20 && ch != '\t')) return "";
        }
        return code;
    }

    private static boolean hasUnresolvedVariable(String code) {
        String upper = code.toUpperCase(Locale.US);
        return upper.contains("??") || upper.matches(".*(^|[^A-Z])X{2,}([^A-Z]|$).*");
    }

    private static String normalizedCode(String code) {
        if (code == null) return "";
        return code.trim().replaceAll("\\s+", " ").toUpperCase(Locale.US);
    }

    /**
     * Removes dump metadata without erasing semantic variants. In particular,
     * "Game (USA)" and "Game (Europe)" are variants of one title, while
     * "Game (Demo)" remains a different executable from "Game".
     */
    private static String catalogKey(String value) {
        if (value == null) return "";
        String clean = FILE_EXTENSION.matcher(value.trim()).replaceFirst("");
        clean = BRACKET_TAG.matcher(clean).replaceAll(" ");
        Matcher tags = PAREN_TAG.matcher(clean);
        StringBuffer output = new StringBuffer();
        while (tags.find()) {
            String qualifier = tags.group(1).trim();
            tags.appendReplacement(output, Matcher.quoteReplacement(
                    isDumpQualifier(qualifier) ? " " : " " + qualifier + " "));
        }
        tags.appendTail(output);
        return output.toString().toLowerCase(Locale.US)
                .replaceAll("[^a-z0-9]+", "");
    }

    private static boolean isDumpQualifier(String value) {
        String clean = value.toLowerCase(Locale.US)
                .replaceAll("[^a-z0-9]+", "");
        if (clean.matches("(?:usa|us|europe|eu|eur|world|japan|jp|jpn|korea|kr|"
                + "australia|au|asia|china|cn|taiwan|tw|brazil|br|canada|ca|"
                + "france|fr|germany|de|italy|it|spain|es|russia|ru|uk)")) return true;
        return clean.matches("(?:rev|revision|ver|version|disc|disk|side)[a-z0-9]*") ||
                isCodeQualifier(clean);
    }

    /** Keeps region/revision identity but ignores which cheat device named a file. */
    private static String variantKey(String value) {
        if (value == null) return "";
        String clean = FILE_EXTENSION.matcher(value.trim()).replaceFirst("");
        Matcher tags = PAREN_TAG.matcher(clean);
        StringBuffer output = new StringBuffer();
        while (tags.find()) {
            String qualifier = tags.group(1).trim();
            String normalized = qualifier.toLowerCase(Locale.US)
                    .replaceAll("[^a-z0-9]+", "");
            tags.appendReplacement(output, Matcher.quoteReplacement(
                    isCodeQualifier(normalized) ? " " : " " + qualifier + " "));
        }
        tags.appendTail(output);
        return output.toString().toLowerCase(Locale.US)
                .replaceAll("[^a-z0-9]+", "");
    }

    private static boolean isCodeQualifier(String normalized) {
        return normalized.matches(
                "(?:codebreaker|gameshark|gamegenie|actionreplay|ar|cheat|trainer)");
    }

    private static String serial(String value) {
        if (value == null) return "";
        Matcher match = SERIAL.matcher(value);
        return match.find() ? (match.group(1) + match.group(2)).toUpperCase(Locale.US) : "";
    }

    private static String unquote(String value) {
        String clean = value == null ? "" : value.trim();
        if (clean.length() >= 2 && clean.charAt(0) == '"' &&
                clean.charAt(clean.length() - 1) == '"')
            clean = clean.substring(1, clean.length() - 1);
        return clean.replace("\\\"", "\"").replace("\\\\", "\\");
    }

    private static boolean safeEntryName(String name) {
        return name != null && !name.isEmpty() && !name.startsWith("/") &&
                !name.startsWith("\\") && !name.contains("../") &&
                !name.contains("..\\") && !name.contains(":") &&
                name.indexOf('\0') < 0;
    }

    private static String shortHash(String value) {
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
