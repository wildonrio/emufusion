package com.thorium.preview.cheats.sources;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

/** Every source sliced from locally built archives through a fake fetch; no network. */
public final class CheatSourceSlicerTest {
    private static final Map<String, File> CACHE = new HashMap<>();
    private static File dir;

    public static void main(String[] args) throws Exception {
        dir = Files.createTempDirectory("lucent-slicer").toFile();
        CheatFetch fetch = new CheatFetch() {
            @Override public File fetch(CheatSource source, String url) { return CACHE.get(url); }
        };
        CheatSourceSlicer slicer = new CheatSourceSlicer(fetch, libretroArchive());

        Map<String, String> n64 = identity("n64Key", "5C3F3A1B-53C2B9FA-C:45");
        text(src(CheatSourceRegistry.MUPEN64PLUS).url, "mupen.txt",
                "crc 5C3F3A1B-53C2B9FA-C:45\ngn Banjo\ncn Infinite Lives\n 8037BE3A 0009\n");
        List<DownloadedCheat> mupen = slicer.slice(src(CheatSourceRegistry.MUPEN64PLUS), "n64", n64, "Banjo-Kazooie", "Banjo-Kazooie (USA).z64", "");
        check(mupen.size() == 1 && "live".equals(mupen.get(0).delivery), "mupen sliced by crc key: " + mupen);
        check(mupen.get(0).cheat.id.startsWith("mupen64plus-cheats-"), "source prefixed id");
        check(mupen.get(0).cheat.description.startsWith("Mupen64Plus mupencheat.txt • 5C3F3A1B"), "provenance: " + mupen.get(0).cheat.description);

        CheatSource pj64 = src(CheatSourceRegistry.PROJECT64);
        text(pj64.auxiliaryUrl, "listing.json", "[{\"name\":\"Banjo-Kazooie.cht\"},{\"name\":\"Other Game.cht\"}]");
        text(pj64.url.replace("<FILE>", "Banjo-Kazooie.cht"), "banjo.cht",
                "[5C3F3A1B-53C2B9FA-C:45]\nName=Banjo-Kazooie\n$Moon Jump\n8037BE40 0001\n");
        List<DownloadedCheat> pj = slicer.slice(pj64, "n64", n64, "Banjo-Kazooie", "Banjo-Kazooie (USA).z64", "");
        check(pj.size() == 1 && "Moon Jump".equals(pj.get(0).cheat.name), "pj64 sliced by title then crc-verified: " + pj);
        List<DownloadedCheat> wrongCrc = slicer.slice(pj64, "n64", identity("n64Key", "00000000-00000000-C:45"), "Banjo-Kazooie", "x.z64", "");
        check(wrongCrc.isEmpty(), "pj64 crc mismatch rejected");

        Map<String, byte[]> duck = new LinkedHashMap<>();
        duck.put("SLUS-00583.cht", bytes("[Infinite Health]\nType = Gameshark\n800A1234 0063\n"));
        duck.put("SLUS-00583-ABCDEF0123456789.cht", bytes("[Rev Only]\nType = Gameshark\n800A1236 0063\n"));
        duck.put("SLUS-99999.cht", bytes("[Other]\nType = Gameshark\n800A0000 0001\n"));
        zip(src(CheatSourceRegistry.DUCKSTATION).url, "duck.zip", duck);
        List<DownloadedCheat> ds = slicer.slice(src(CheatSourceRegistry.DUCKSTATION), "psx", identity("serial", "SLUS-00583"), "Crash", "Crash.chd", "");
        check(ds.size() == 2, "duckstation serial + revision files: " + ds.size());

        Map<String, byte[]> pnach = new LinkedHashMap<>();
        pnach.put("SCUS-97472_7D6F5B0E.pnach", bytes("gametitle=SotC\n[Widescreen 16:9]\ngsaspectratio=16:9\npatch=1,EE,2034C7A0,extended,3F400000\n[No Interlacing]\npatch=1,EE,00000000,extended,00000001\n"));
        pnach.put("SCUS-97472_11111111.pnach", bytes("[Widescreen 16:9]\npatch=1,EE,2034C7A0,extended,3F400001\n"));
        pnach.put("SLUS-00000_22222222.pnach", bytes("[X]\npatch=1,EE,1,extended,1\n"));
        zip(src(CheatSourceRegistry.PCSX2_PATCHES).url, "patches.zip", pnach);
        Map<String, String> ps2 = identity("serial", "SCUS-97472", "crc", "7D6F5B0E");
        List<DownloadedCheat> ws = slicer.slice(src(CheatSourceRegistry.PCSX2_PATCHES), "ps2", ps2, "Shadow of the Colossus", "sotc.iso", "");
        check(ws.size() == 2 && "boot".equals(ws.get(0).delivery), "pnach crc-exact: " + ws.size());
        check(ws.get(0).hasTag("widescreen") && ws.get(0).hasTag("crc:7d6f5b0e"), "pnach tags: " + ws.get(0).tags);
        List<DownloadedCheat> serialOnly = slicer.slice(src(CheatSourceRegistry.PCSX2_PATCHES), "ps2", identity("serial", "SCUS-97472"), "sotc", "sotc.chd", "");
        check(serialOnly.size() == 3, "pnach serial-only takes every crc variant: " + serialOnly.size());

        Map<String, byte[]> coll = new LinkedHashMap<>();
        coll.put("xs1l3n7x-pcsx2_cheats_collection-abc/cheats/7D6F5B0E.pnach", bytes("//Infinite Health\npatch=1,EE,20000000,extended,00000063\n"));
        zip(src(CheatSourceRegistry.PCSX2_CHEATS).url, "coll.zip", coll);
        List<DownloadedCheat> cheats = slicer.slice(src(CheatSourceRegistry.PCSX2_CHEATS), "ps2", ps2, "sotc", "sotc.iso", "");
        check(cheats.size() == 1 && "Infinite Health".equals(cheats.get(0).cheat.name), "pcsx2 cheats collection by crc");

        text(src(CheatSourceRegistry.CWCHEAT).url, "cheat.db", "_S ULUS-10041\n_G GoW\n_C0 Infinite Health\n_L 0x20123456 0x00000063\n");
        List<DownloadedCheat> cw = slicer.slice(src(CheatSourceRegistry.CWCHEAT), "psp", identity("serial", "ULUS-10041"), "God of War", "gow.cso", "");
        check(cw.size() == 1 && cw.get(0).cheat.code.startsWith("_L 0x20123456"), "cwcheat by serial: " + cw);

        text(src(CheatSourceRegistry.RC24_GECKO).url.replace("<GAMEID>", "RMCE01"), "rmce01.txt",
                "RMCE01\nMario Kart Wii\n\nInfinite Items [A]\n04001234 00000001\n");
        List<DownloadedCheat> gecko = slicer.slice(src(CheatSourceRegistry.RC24_GECKO), "wii", identity("gameId", "RMCE01"), "Mario Kart Wii", "mkw.rvz", "");
        check(gecko.size() == 1 && "live".equals(gecko.get(0).delivery), "rc24 per-game: " + gecko);
        check(slicer.slice(src(CheatSourceRegistry.RC24_GECKO), "wii", identity(), "x", "x.iso", "").isEmpty(), "rc24 needs a game id");

        CheatSource cemu = src(CheatSourceRegistry.CEMU_PACKS);
        text(cemu.url, "release.json", "{\"assets\":[{\"name\":\"graphicPacks981.zip\",\"browser_download_url\":\"https://example.test/graphicPacks981.zip\"}]}");
        Map<String, byte[]> packs = new LinkedHashMap<>();
        packs.put("BreathOfTheWild_InfiniteHearts/rules.txt", bytes("[Definition]\ntitleIds = 00050000101C9300,00050000101C9400\nname = \"Infinite Hearts\"\npath = \"The Legend of Zelda: Breath of the Wild/Cheats/Infinite Hearts\"\n"));
        packs.put("BreathOfTheWild_InfiniteHearts/patches.txt", bytes("[BotWv208]\nmoduleMatches = 0x6267BFD0\n"));
        packs.put("BreathOfTheWild_InfiniteHearts/shader.bin", new byte[] {0, 1, 2});
        packs.put("OtherGame_Cheat/rules.txt", bytes("[Definition]\ntitleIds = 0005000010101000\nname = \"Other\"\npath = \"Other/Cheats/Other\"\n"));
        zip("https://example.test/graphicPacks981.zip", "packs.zip", packs);
        List<DownloadedCheat> cemuRows = slicer.slice(cemu, "wiiu", identity("titleId", "00050000101C9400"), "Zelda", "U-King.rpx", "");
        check(cemuRows.size() == 1 && "Infinite Hearts".equals(cemuRows.get(0).cheat.name), "cemu pack by title id: " + cemuRows);
        Map<String, String> files = CemuGraphicPackParser.filesOf(cemuRows.get(0).cheat.code);
        check(files.containsKey("rules.txt") && files.containsKey("patches.txt") && !files.containsKey("shader.bin"), "cemu text files only: " + files.keySet());
        List<DownloadedCheat> byTitle = slicer.slice(cemu, "wiiu", identity(), "The Legend of Zelda: Breath of the Wild", "botw.wux", "");
        check(byTitle.size() == 1, "cemu falls back to title match for wux: " + byTitle.size());

        text(src(CheatSourceRegistry.SHARKIVE_3DS).url, "3ds.json", "{\"0004000000030100\":{\"Infinite Lives\":[\"D3000000 00000000\",\"00123456 00000063\"]}}");
        List<DownloadedCheat> sh = slicer.slice(src(CheatSourceRegistry.SHARKIVE_3DS), "3ds", identity("titleId", "0004000000030100"), "x", "x.3ds", "");
        check(sh.size() == 1 && "boot".equals(sh.get(0).delivery), "sharkive 3ds: " + sh);

        CheatSource swdb = src(CheatSourceRegistry.SWITCH_CHEATS_DB);
        text(swdb.auxiliaryUrl, "versions.json", "{\"0100000000010000\":{\"0\":\"AAAAAAAAAAAAAAAA\",\"65536\":\"BBBBBBBBBBBBBBBB\"}}");
        Map<String, byte[]> contents = new LinkedHashMap<>();
        contents.put("contents/0100000000010000/cheats/AAAAAAAAAAAAAAAA.txt", bytes("[Moon Jump]\n04000000 00000000 00000001\n"));
        contents.put("contents/0100000000010000/cheats/CCCCCCCCCCCCCCCC.txt", bytes("[Moon Jump v2]\n04000000 00000000 00000002\n"));
        contents.put("contents/0100999999999999/cheats/AAAAAAAAAAAAAAAA.txt", bytes("[Other]\n04000000 00000000 00000003\n"));
        zip(swdb.url, "contents.zip", contents);
        Map<String, String> sw = identity("titleId", "0100000000010000");
        List<DownloadedCheat> swRows = slicer.slice(swdb, "switch", sw, "Odyssey", "odyssey.nsp", "");
        check(swRows.size() == 2 && swRows.get(0).hasTag("buildid:aaaaaaaaaaaaaaaa"), "switch rows tagged by build id: " + swRows);
        check("AAAAAAAAAAAAAAAA,BBBBBBBBBBBBBBBB,CCCCCCCCCCCCCCCC".equals(sw.get("buildIds")), "build ids merged into identity: " + sw);

        text(src(CheatSourceRegistry.SHARKIVE_SWITCH).url, "switch.json", "{\"0100000000010000\":{\"DDDDDDDDDDDDDDDD\":{\"Inf HP\":[\"04000000 00000000 00000009\"]}}}");
        List<DownloadedCheat> shs = slicer.slice(src(CheatSourceRegistry.SHARKIVE_SWITCH), "switch", sw, "Odyssey", "odyssey.nsp", "");
        check(shs.size() == 1 && sw.get("buildIds").endsWith("DDDDDDDDDDDDDDDD"), "sharkive switch adds its build id: " + sw);

        // RPCS3 1.2 real-world layout: patch names sit directly under the
        // hash, with no intermediate "Patches:" map (Rpcs3PatchYamlParser).
        String yaml = "Version: 1.2\nPPU-abc:\n  \"60 FPS\":\n    Games:\n      \"Demon's Souls\":\n        BLUS30443: [ All ]\n    Patch:\n      - [ be32, 0x00a1e3d8, 0x3f800000 ]\n";
        text(src(CheatSourceRegistry.RPCS3_PATCHES).url, "rpcs3.json", JsonLite.write(map("return_code", 0L, "patch", yaml)));
        text(src(CheatSourceRegistry.ARTEMIS_RPCS3).url, "imported.yml", yaml.replace("60 FPS", "Infinite Souls").replace("PPU-abc", "PPU-def"));
        Map<String, String> ps3 = identity("serial", "BLUS30443");
        List<DownloadedCheat> official = slicer.slice(src(CheatSourceRegistry.RPCS3_PATCHES), "ps3", ps3, "Demon's Souls", "EBOOT.BIN", "");
        List<DownloadedCheat> artemis = slicer.slice(src(CheatSourceRegistry.ARTEMIS_RPCS3), "ps3", ps3, "Demon's Souls", "EBOOT.BIN", "");
        check(official.size() == 1 && official.get(0).hasTag("ppu:ppu-abc") && official.get(0).hasTag("60fps"), "rpcs3 api envelope: " + official);
        check(artemis.size() == 1 && "Infinite Souls".equals(artemis.get(0).cheat.name), "artemis raw yaml: " + artemis);

        Map<String, byte[]> md = new LinkedHashMap<>();
        md.put("bucanero-dreamcast-cheats-abc/sonic-adventure-(usa).md", bytes("# Sonic Adventure (USA)\n## Infinite Lives\n0B1A2C3D 00000009\n"));
        md.put("bucanero-dreamcast-cheats-abc/README.md", bytes("# Readme\n"));
        zip(src(CheatSourceRegistry.DREAMCAST_MD).url, "dc.zip", md);
        List<DownloadedCheat> dc = slicer.slice(src(CheatSourceRegistry.DREAMCAST_MD), "dreamcast", identity(), "Sonic Adventure", "Sonic Adventure (USA).gdi", "");
        // flycast's retro_cheat_set/reset are wired to a real GameShark bridge
        // (engines/patches/flycast-libretro-cheat-support.patch) and
        // CheatDelivery.LIVE_ENGINES/PpssppGlesEngineSession.supportsLiveCheats
        // both list "flycast", so a dreamcast row now resolves to "live" here,
        // matching what CheatDelivery decides at launch.
        check(dc.size() == 1 && "live".equals(dc.get(0).delivery), "dreamcast markdown by title: " + dc);

        Map<String, byte[]> fb = new LinkedHashMap<>();
        fb.put("finalburnneo-FBNeo-cheats-abc/cheats/mslug3.ini", bytes("cheat \"Infinite Lives\"\ndefault 0\n0 \"Disabled\"\n1 \"Enabled\", 0, 0x00E0B4, 0x03\n"));
        zip(src(CheatSourceRegistry.FBNEO).url, "fbneo.zip", fb);
        List<DownloadedCheat> fbRows = slicer.slice(src(CheatSourceRegistry.FBNEO), "arcade", identity("romset", "mslug3"), "Metal Slug 3", "mslug3.zip", "");
        check(fbRows.size() == 1 && "unsupported".equals(fbRows.get(0).delivery), "fbneo by romset, unsupported delivery: " + fbRows);

        CheatSource mame = src(CheatSourceRegistry.MAME);
        text(mame.auxiliaryUrl, "latest.txt", "0279\n");
        Map<String, byte[]> mx = new LinkedHashMap<>();
        mx.put("mslug3.xml", bytes("<mamecheat version=\"1\"><cheat desc=\"Infinite Lives\"><script state=\"run\"><action>maincpu.pb@E0B4=03</action></script></cheat></mamecheat>"));
        zip(mame.url.replace("<VERSION>", "0279"), "mame.zip", mx);
        List<DownloadedCheat> mameRows = slicer.slice(mame, "arcade", identity(), "Metal Slug 3", "mslug3.zip", "");
        check(mameRows.size() == 1 && "mame-xml".equals(mameRows.get(0).engineFormat), "mame via latest.txt: " + mameRows);

        List<DownloadedCheat> lib = slicer.slice(src(CheatSourceRegistry.LIBRETRO), "nes", identity(), "Super Mario Bros.", "Super Mario Bros. (World).nes", "");
        check(lib.size() == 1 && lib.get(0).cheat.id.startsWith("libretro-"), "libretro rows keep CheatArchive ids: " + lib);
        check(lib.get(0).cheat.id.equals(CheatIdFactory.id("libretro", "nes", "AATOZE")), "libretro id formula identical");

        // Renamed/obscure filename: title matching finds nothing, but a
        // No-Intro DAT crc32 match resolves the canonical name libretro's
        // .cht is filed under, and that second pass then succeeds.
        text(DiscDatIndex.noIntroUrl("nes"), "nes.dat",
                "<datafile><game name=\"Super Mario Bros. (World)\">\n"
                        + "<rom name=\"Super Mario Bros. (World).nes\" size=\"40976\" crc=\"3337EC46\" md5=\"aa\" sha1=\"bb\"/>\n"
                        + "</game></datafile>\n");
        Map<String, String> obscureCrc = identity("romCrc32", "3337EC46");
        List<DownloadedCheat> byCrc = slicer.slice(src(CheatSourceRegistry.LIBRETRO), "nes", obscureCrc,
                "not a real title", "dump0042.nes", "");
        check(byCrc.size() == 1 && byCrc.get(0).cheat.id.equals(CheatIdFactory.id("libretro", "nes", "AATOZE")),
                "libretro second pass resolves an obscure filename by DAT crc: " + byCrc);
        check(slicer.slice(src(CheatSourceRegistry.LIBRETRO), "nes", identity("romCrc32", "DEADBEEF"),
                "not a real title", "dump0043.nes", "").isEmpty(), "unmatched crc still yields nothing");

        DownloadedCheatDocument document = new DownloadedCheatDocument("ps2", "sotc");
        document.addAll(ws); document.addAll(cheats); document.addAll(ws);
        check(document.size() == 3 && document.sources.size() == 2, "document dedupes and records sources: " + document.sources);

        check(slicer.slice(src(CheatSourceRegistry.CWCHEAT), "psp", identity("serial", "ULUS-99999"), "x", "x.iso", "").isEmpty(), "unknown serial yields nothing");
        check(slicer.slice(src(CheatSourceRegistry.DUCKSTATION), "psx", identity(), "x", "x.iso", "").isEmpty(), "missing identity yields nothing");
        Map<String, byte[]> evil = new LinkedHashMap<>();
        evil.put("../SLUS-00583.cht", bytes("[x]\n800A1234 0063\n"));
        zip("https://evil.test/duck.zip", "evil.zip", evil);
        CheatSource evilSource = src(CheatSourceRegistry.DUCKSTATION);
        CACHE.put(evilSource.url, CACHE.get("https://evil.test/duck.zip"));
        check(slicer.slice(evilSource, "psx", identity("serial", "SLUS-00583"), "x", "x.iso", "").isEmpty(), "traversing entry name rejects the archive");
        System.out.println("CheatSourceSlicerTest passed");
    }

    private static CheatSource src(String id) { return CheatSourceRegistry.byId(id); }

    private static Map<String, String> identity(String... pairs) {
        Map<String, String> map = new LinkedHashMap<>();
        for (int i = 0; i + 1 < pairs.length; i += 2) map.put(pairs[i], pairs[i + 1]);
        return map;
    }

    private static Map<String, Object> map(Object... pairs) {
        Map<String, Object> map = new LinkedHashMap<>();
        for (int i = 0; i + 1 < pairs.length; i += 2) map.put((String) pairs[i], pairs[i + 1]);
        return map;
    }

    private static byte[] bytes(String text) { return text.getBytes(StandardCharsets.UTF_8); }

    private static void text(String url, String name, String content) throws IOException {
        File file = new File(dir, name);
        try (FileOutputStream out = new FileOutputStream(file)) { out.write(bytes(content)); }
        CACHE.put(url, file);
    }

    private static void zip(String url, String name, Map<String, byte[]> entries) throws IOException {
        File file = new File(dir, name);
        try (ZipOutputStream out = new ZipOutputStream(new FileOutputStream(file))) {
            for (Map.Entry<String, byte[]> entry : entries.entrySet()) {
                out.putNextEntry(new ZipEntry(entry.getKey()));
                out.write(entry.getValue());
                out.closeEntry();
            }
        }
        CACHE.put(url, file);
    }

    private static File libretroArchive() throws IOException {
        Map<String, byte[]> entries = new LinkedHashMap<>();
        entries.put("Nintendo - Nintendo Entertainment System/Super Mario Bros. (World).cht",
                bytes("cheats = 1\ncheat0_desc = \"Infinite Lives\"\ncheat0_code = \"AATOZE\"\n"));
        File file = new File(dir, "libretro-cheats.zip");
        try (ZipOutputStream out = new ZipOutputStream(new FileOutputStream(file))) {
            for (Map.Entry<String, byte[]> entry : entries.entrySet()) {
                out.putNextEntry(new ZipEntry(entry.getKey()));
                out.write(entry.getValue());
                out.closeEntry();
            }
        }
        return file;
    }

    static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
}
