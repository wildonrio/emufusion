package com.thorium.preview.cheats.sources;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.zip.CRC32;

/**
 * {@link CheatGameIdentity#crc32} and the {@link DiscDatIndex} No-Intro/Redump
 * DAT lookup it feeds: a real CRC32 computation over a temp file, and a
 * synthetic (but real-shaped, Logiqx) DAT fetched through a fake
 * {@link CheatFetch} -- never a real DAT download.
 */
public final class CheatIdentityCrcTest {
    public static void main(String[] args) throws Exception {
        crc32MatchesJavaUtilZip();
        crc32BoundedAndTolerant();
        crc32RespectsWallClockBudget();
        identifyPopulatesRomCrc32ForCartSystemsOnly();
        identifyRomCrc32BudgetIsLazyAndBounded();
        datParsingHandlesMultiRomGamesAndEntities();
        resolveTitlePrefersCrcOverDiscHashOrder();
        resolveTitleMissesAreQuiet();
        System.out.println("CheatIdentityCrcTest passed");
    }

    private static void crc32MatchesJavaUtilZip() throws IOException {
        File dir = Files.createTempDirectory("lucent-crc").toFile();
        File file = new File(dir, "game.nes");
        byte[] data = new byte[70_000];
        for (int i = 0; i < data.length; i++) data[i] = (byte) (i * 31 + 7);
        write(file, data);
        CRC32 reference = new CRC32();
        reference.update(data);
        String expected = String.format(java.util.Locale.US, "%08X", reference.getValue());
        check(expected.equals(CheatGameIdentity.crc32(file)), "crc32 matches java.util.zip.CRC32: "
                + CheatGameIdentity.crc32(file) + " vs " + expected);
    }

    private static void crc32BoundedAndTolerant() throws IOException {
        check(CheatGameIdentity.crc32(null).isEmpty(), "null file");
        File dir = Files.createTempDirectory("lucent-crc-2").toFile();
        File missing = new File(dir, "does-not-exist.nes");
        check(CheatGameIdentity.crc32(missing).isEmpty(), "missing file");
        File empty = new File(dir, "empty.nes");
        write(empty, new byte[0]);
        check(CheatGameIdentity.crc32(empty).isEmpty(), "empty file yields no crc, never zip's crc of nothing");
        File directory = new File(dir, "adir");
        directory.mkdirs();
        check(CheatGameIdentity.crc32(directory).isEmpty(), "a directory is never hashed");
    }

    private static void crc32RespectsWallClockBudget() throws IOException {
        File dir = Files.createTempDirectory("lucent-crc-budget").toFile();
        File file = new File(dir, "game.nes");
        write(file, new byte[70_000]);
        String unbounded = CheatGameIdentity.crc32(file);
        check(!unbounded.isEmpty(), "unbounded crc32 still works");
        check(unbounded.equals(CheatGameIdentity.crc32(file, -1L)),
                "a negative budget behaves exactly like the unbounded overload");
        check(CheatGameIdentity.crc32(file, 0L).isEmpty(),
                "a zero budget skips the hash entirely rather than computing it");
        check(CheatGameIdentity.crc32(file, 60_000L).equals(unbounded),
                "a generous budget still yields the real hash");
    }

    private static void identifyRomCrc32BudgetIsLazyAndBounded() throws IOException {
        File dir = Files.createTempDirectory("lucent-crc-4").toFile();
        File rom = new File(dir, "Kirby (World).nes");
        write(rom, new byte[50_000]);
        Map<String, String> exhausted = CheatGameIdentity.identify("nes", rom, "", 0L);
        check(!exhausted.containsKey("romCrc32"),
                "identify() with an exhausted budget never spends time hashing a cart rom: " + exhausted);
        check("Kirby (World)".equals(exhausted.get("stem")), "cheap fields still populate under a zero budget");
        Map<String, String> patient = CheatGameIdentity.identify("nes", rom, "", 60_000L);
        check(!patient.get("romCrc32").isEmpty(),
                "identify() with a generous remaining budget still hashes the cart rom: " + patient);
    }

    private static void identifyPopulatesRomCrc32ForCartSystemsOnly() throws IOException {
        File dir = Files.createTempDirectory("lucent-crc-3").toFile();
        File rom = new File(dir, "Super Mario Bros. (World).nes");
        byte[] data = "not a real ines rom, just needs bytes to crc".getBytes(StandardCharsets.US_ASCII);
        write(rom, data);
        String expected = CheatGameIdentity.crc32(rom);
        Map<String, String> nes = CheatGameIdentity.identify("nes", rom, "");
        check(expected.equals(nes.get("romCrc32")), "nes identity carries romCrc32: " + nes);

        // A serial-keyed disc system never gets a whole-file CRC32: it is
        // not what a Redump DAT is keyed by (per-track hashes), and would
        // never legitimately match anything.
        File notCart = new File(dir, "game.iso");
        write(notCart, data);
        Map<String, String> psx = CheatGameIdentity.identify("psx", notCart, "");
        check(!psx.containsKey("romCrc32"), "psx never gets a whole-file crc32: " + psx);
    }

    private static void datParsingHandlesMultiRomGamesAndEntities() {
        String dat = "<?xml version=\"1.0\"?>\n<datafile>\n"
                + "<game name=\"Kirby&apos;s Adventure (USA)\">\n"
                + "  <rom name=\"Kirby's Adventure (USA).nes\" size=\"262160\" crc=\"CF6238FE\" md5=\"11\" sha1=\"22\"/>\n"
                + "</game>\n"
                + "<game name=\"Multi-Disc Thing (USA) (Disc 1)\">\n"
                + "  <rom name=\"track01.bin\" size=\"1\" crc=\"AAAAAAAA\" md5=\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\" "
                + "sha1=\"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\"/>\n"
                + "  <rom name=\"track02.bin\" size=\"1\" crc=\"BBBBBBBB\" md5=\"cccccccccccccccccccccccccccccccc\" "
                + "sha1=\"dddddddddddddddddddddddddddddddddddddddd\"/>\n"
                + "</game>\n"
                + "</datafile>\n";
        Map<String, String> table = DiscDatIndex.parseDat(dat);
        check("Kirby's Adventure (USA)".equals(table.get("CF6238FE")), "xml entity unescaped in game name: " + table);
        check("Multi-Disc Thing (USA) (Disc 1)".equals(table.get("AAAAAAAA"))
                        && "Multi-Disc Thing (USA) (Disc 1)".equals(table.get("BBBBBBBB")),
                "every rom under a game maps back to that game: " + table);
        check("Multi-Disc Thing (USA) (Disc 1)".equals(
                table.get("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA".toUpperCase(java.util.Locale.US))),
                "md5 also keyed: " + table);
        check("Multi-Disc Thing (USA) (Disc 1)".equals(
                table.get("BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB".toUpperCase(java.util.Locale.US))),
                "sha1 also keyed: " + table);
    }

    private static void resolveTitlePrefersCrcOverDiscHashOrder() {
        final Map<String, File> cache = new HashMap<>();
        CheatFetch fetch = new CheatFetch() {
            @Override public File fetch(CheatSource source, String url) { return cache.get(url); }
        };
        String noIntroUrl = DiscDatIndex.noIntroUrl("snes");
        String redumpUrl = DiscDatIndex.redumpUrl("psx");
        check(!noIntroUrl.isEmpty() && noIntroUrl.startsWith("https://"), "snes has a no-intro dat url: " + noIntroUrl);
        check(!redumpUrl.isEmpty() && redumpUrl.startsWith("https://"), "psx has a redump dat url: " + redumpUrl);

        writeDatFile(cache, noIntroUrl, "<datafile><game name=\"Chrono Trigger (USA)\">"
                + "<rom name=\"Chrono Trigger (USA).sfc\" size=\"4194304\" crc=\"7CC03F1F\"/></game></datafile>");
        Map<String, String> byCrc = new LinkedHashMap<>();
        byCrc.put("romCrc32", "7cc03f1f"); // lower-case on purpose: resolveTitle must upper-case it itself
        check("Chrono Trigger (USA)".equals(DiscDatIndex.resolveTitle(fetch, "snes", byCrc)),
                "resolves a snes title by no-intro crc, case-insensitively");

        writeDatFile(cache, redumpUrl, "<datafile><game name=\"Final Fantasy VII (USA) (Disc 1)\">"
                + "<rom name=\"Final Fantasy VII (USA) (Disc 1).bin\" size=\"1\" "
                + "sha1=\"da39a3ee5e6b4b0d3255bfef95601890afd80709\"/></game></datafile>");
        Map<String, String> byHash = new LinkedHashMap<>();
        byHash.put("chdRawHash", "da39a3ee5e6b4b0d3255bfef95601890afd80709");
        check("Final Fantasy VII (USA) (Disc 1)".equals(DiscDatIndex.resolveTitle(fetch, "psx", byHash)),
                "resolves a psx title by redump sha1 (chd raw hash)");

        // A cartridge crc match, when present, is tried before falling
        // through to a disc hash for the same identity map.
        Map<String, String> both = new LinkedHashMap<>();
        both.put("romCrc32", "7CC03F1F");
        both.put("chdRawHash", "0000000000000000000000000000000000000000");
        check("Chrono Trigger (USA)".equals(DiscDatIndex.resolveTitle(fetch, "snes", both)),
                "crc32 pass is tried first when both identities are present");
    }

    private static void resolveTitleMissesAreQuiet() {
        CheatFetch neverFetches = new CheatFetch() {
            @Override public File fetch(CheatSource source, String url) { return null; }
        };
        check(DiscDatIndex.resolveTitle(null, "snes", new LinkedHashMap<String, String>()).isEmpty(), "null fetch");
        check(DiscDatIndex.resolveTitle(neverFetches, "snes", null).isEmpty(), "null identity");
        check(DiscDatIndex.resolveTitle(neverFetches, "snes", new LinkedHashMap<String, String>()).isEmpty(),
                "no identity keys");
        check(DiscDatIndex.resolveTitle(neverFetches, "xbox360", identity("romCrc32", "12345678")).isEmpty(),
                "a system with no dat mapping never even tries to fetch");
        check(DiscDatIndex.lookupNoIntro(neverFetches, "snes", "not-8-hex").isEmpty(), "malformed crc rejected");
        check(DiscDatIndex.lookupRedump(neverFetches, "psx", "not-a-hash").isEmpty(), "malformed hash rejected");
    }

    private static Map<String, String> identity(String... pairs) {
        Map<String, String> map = new LinkedHashMap<>();
        for (int i = 0; i + 1 < pairs.length; i += 2) map.put(pairs[i], pairs[i + 1]);
        return map;
    }

    private static void writeDatFile(Map<String, File> cache, String url, String content) {
        try {
            File dir = Files.createTempDirectory("lucent-dat").toFile();
            File file = new File(dir, "index.dat");
            write(file, content.getBytes(StandardCharsets.UTF_8));
            cache.put(url, file);
        } catch (IOException impossible) {
            throw new IllegalStateException(impossible);
        }
    }

    private static void write(File file, byte[] data) throws IOException {
        try (FileOutputStream out = new FileOutputStream(file)) { out.write(data); }
    }

    static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
}
