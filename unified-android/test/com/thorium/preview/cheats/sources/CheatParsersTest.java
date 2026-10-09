package com.thorium.preview.cheats.sources;

import java.util.List;
import java.util.Map;

/** One synthetic document per upstream format; no network, no device. */
public final class CheatParsersTest {
    public static void main(String[] args) {
        retroArch();
        duckStation();
        mupen();
        project64();
        pnach();
        cwcheat();
        gecko();
        dmnt();
        sharkive();
        switchVersions();
        rpcs3();
        dreamcast();
        fbneo();
        mame();
        cemu();
        System.out.println("CheatParsersTest passed");
    }

    private static void retroArch() {
        List<ParsedCheat> rows = RetroArchChtParser.parse(
                "cheats = 3\ncheat0_desc = \"Infinite Lives\"\ncheat0_code = \"AATOZE\"\n"
                + "cheat1_desc = \"Needs value\"\ncheat1_code = \"1234:??\"\n"
                + "cheat2_desc = \"\"\ncheat2_code = \"7E0DBE:63\"\n");
        check(rows.size() == 2, "retroarch: placeholder row must be dropped: " + rows.size());
        check("Infinite Lives".equals(rows.get(0).name), "retroarch: name");
        check("Cheat 3".equals(rows.get(1).name), "retroarch: blank description label");
    }

    private static void duckStation() {
        List<ParsedCheat> rows = DuckStationChtParser.parse(
                "[Infinite Health]\nType = Gameshark\nActivation = EndFrame\nAuthor = x\n"
                + "Description = Never die\n800A1234 0063\n800A1236 0063\n\n"
                + "[Select Level]\nType = Gameshark\nActivation = Manual\nOption = Level 1:1\n800A0000 ????\n\n"
                + "[Widescreen 16:9]\nType = Gameshark\nGroup = Graphics\n800B0000 0001\n");
        check(rows.size() == 2, "duckstation: option cheat skipped: " + rows.size());
        check("800A1234 0063+800A1236 0063".equals(rows.get(0).code), "duckstation: code join: " + rows.get(0).code);
        check("Never die".equals(rows.get(0).description), "duckstation: description");
        check(rows.get(0).tags.contains("gameshark"), "duckstation: type tag");
        check(rows.get(1).tags.contains("widescreen"), "duckstation: widescreen tag");
        check(rows.get(1).tags.contains("graphics"), "duckstation: group tag");
    }

    private static void mupen() {
        Map<String, MupenCheatParser.Game> games = MupenCheatParser.parse(
                "# comment\ncrc 5C3F3A1B-53C2B9FA-C:45\ngn Banjo-Kazooie (U)\n"
                + "cn Infinite Lives\ncd Note here\n 8037BE3A 0009\n"
                + "cn Choose Level\n 8037BE40 ???? 0:\"A\",1:\"B\"\n"
                + "crc 11111111-22222222-C:4A\ngn Other\ncn Only\n 80000000 0001\n");
        MupenCheatParser.Game banjo = games.get("5C3F3A1B-53C2B9FA-C:45");
        check(banjo != null && banjo.cheats.size() == 1, "mupen: one usable cheat");
        check("8037BE3A 0009".equals(banjo.cheats.get(0).code), "mupen: code");
        check("Note here".equals(banjo.cheats.get(0).description), "mupen: note");
        check(games.size() == 2, "mupen: both games parsed");
    }

    private static void project64() {
        Project64ChtParser.Document document = Project64ChtParser.parse(
                "[5C3F3A1B-53C2B9FA-C:45]\nName=Banjo-Kazooie\n$Infinite Lives\nNote=Try it\n8037BE3A 0009\n"
                + "$Level Select\n8037BE40 ????\n"
                + "Cheat0=\"Legacy Row\",80123456 0009,80123458 0001\nCheat0_N=legacy note\n"
                + "Cheat1=\"Legacy Option\",80123460 ????\nCheat1_O=$01 One,$02 Two\n");
        check("5C3F3A1B-53C2B9FA-C:45".equals(document.crc), "pj64: crc header");
        check("Banjo-Kazooie".equals(document.title), "pj64: title");
        check(document.cheats.size() == 2, "pj64: option rows skipped: " + document.cheats.size());
        check("8037BE3A 0009".equals(document.cheats.get(0).code), "pj64: block code");
        check("80123456 0009+80123458 0001".equals(document.cheats.get(1).code), "pj64: legacy code");
        check("legacy note".equals(document.cheats.get(1).description), "pj64: legacy note");
    }

    private static void pnach() {
        List<ParsedCheat> rows = PnachParser.parse(
                "gametitle=Shadow of the Colossus (SCUS-97472)\n"
                + "[Widescreen 16:9]\nauthor=Someone\ndescription=Widens the FOV\ngsaspectratio=16:9\n"
                + "patch=1,EE,2034C7A0,extended,3F400000\npatch=1,EE,2034C7A4,extended,3F400000\n"
                + "[No Interlacing]\npatch=1,EE,00123456,extended,00000000\n");
        check(rows.size() == 2, "pnach: sections: " + rows.size());
        check("Widescreen 16:9".equals(rows.get(0).name), "pnach: section name");
        check(rows.get(0).tags.contains("widescreen"), "pnach: widescreen tag: " + rows.get(0).tags);
        check(rows.get(0).tags.contains("widescreen-16:9"), "pnach: group tag kept: " + rows.get(0).tags);
        check(rows.get(0).code.startsWith("patch=1,EE,2034C7A0") && rows.get(0).code.contains("\n"),
                "pnach: patch lines kept verbatim on separate lines");
        check("Widens the FOV".equals(rows.get(0).description), "pnach: description");

        List<ParsedCheat> comments = PnachParser.parse(
                "gametitle=Game\ncomment=cheats\n//Infinite Health\npatch=1,EE,20000000,extended,00000063\n"
                + "//Max Money\npatch=1,EE,20000004,extended,0098967F\npatch=1,EE,20000008,extended,00000001\n");
        check(comments.size() == 2, "pnach: comment-named cheats: " + comments.size());
        check("Max Money".equals(comments.get(1).name), "pnach: second comment name");
        check(comments.get(1).code.split("\n").length == 2, "pnach: two patch rows in second cheat");

        List<ParsedCheat> bare = PnachParser.parse("patch=1,EE,20000000,extended,00000001\n", "SLUS-12345_ABCDEF01");
        check(bare.size() == 1 && "SLUS-12345_ABCDEF01".equals(bare.get(0).name), "pnach: default name");

        // Real pcsx2_patches files interleave comments between a section's
        // patch lines (e.g. SLES-50044_55EDA5A0.pnach's "Widescreen 16:9"),
        // which must not split the bracketed section into partial switches.
        List<ParsedCheat> interleaved = PnachParser.parse(
                "[Widescreen 16:9]\n"
                + "// General Widescreen Fixes\n"
                + "patch=1,EE,2034C7A0,extended,3F400000\n"
                + "patch=1,EE,2034C7A4,extended,3F400000\n"
                + "patch=1,EE,2034C7A8,extended,3F400000\n"
                + "// 16:9\n"
                + "patch=1,EE,2034C7AC,extended,3F400000\n");
        check(interleaved.size() == 1, "pnach: interleaved comment stays one switch: " + interleaved.size());
        check(interleaved.get(0).code.split("\n").length == 4,
                "pnach: all four patch lines kept in one switch: " + interleaved.get(0).code);
        check("Widescreen 16:9".equals(interleaved.get(0).name), "pnach: section name survives interleaved comment");
    }

    private static void cwcheat() {
        Map<String, CwCheatParser.Game> games = CwCheatParser.parse(
                "_S .All\n_G test\n_C0 skip me\n_L 0x00000000 0x00000000\n"
                + "_S ULUS-10041\n_G God of War\n_C0 Infinite Health\n_L 0x20123456 0x00000063\n_L 0x2012345A 0x00000063\n"
                + "_C1 Enabled by default\n_L 0x20000000 0x00000001\n"
                + "_S ULES01234\n_G Other\n_C0 A\n_L 0x20000000 0x00000002\n");
        check(!games.containsKey(".ALL") && !games.containsKey(".All"), "cwcheat: .All block skipped");
        CwCheatParser.Game gow = games.get("ULUS-10041");
        check(gow != null && gow.cheats.size() == 2, "cwcheat: two cheats");
        check("_L 0x20123456 0x00000063+_L 0x2012345A 0x00000063".equals(gow.cheats.get(0).code),
                "cwcheat: code shape: " + gow.cheats.get(0).code);
        check(games.containsKey("ULES-01234"), "cwcheat: serial normalised with a dash");
        check("God of War".equals(gow.title), "cwcheat: title");
    }

    private static void gecko() {
        GeckoTxtParser.Document document = GeckoTxtParser.parse(
                "RMCE01\nMario Kart Wii\n\nInfinite Items [Author]\n04001234 00000001\n04001238 00000002\nUse with care\n\n"
                + "Widescreen Fix [Someone]\nC2123456 00000002\n3C60803E 60634E30\n60000000 00000000\n");
        check("RMCE01".equals(document.gameId), "gecko: id");
        check("Mario Kart Wii".equals(document.title), "gecko: title");
        check(document.cheats.size() == 2, "gecko: two blocks");
        check("Infinite Items".equals(document.cheats.get(0).name), "gecko: author stripped from name");
        check(document.cheats.get(0).description.contains("Use with care") && document.cheats.get(0).description.contains("Author"),
                "gecko: note and author");
        check("04001234 00000001+04001238 00000002".equals(document.cheats.get(0).code), "gecko: code join");
        check(document.cheats.get(1).tags.contains("widescreen"), "gecko: widescreen tag");

        // rc24's "Everlasting Items v1 [Anarion]" (RMCE01): a button-activator
        // placeholder line ("2834XXXX YYYYZZZZ") must be recognised as a code
        // line -- not demoted to a note -- so the unresolved-variable check
        // drops the whole cheat instead of shipping it missing that line.
        GeckoTxtParser.Document placeholder = GeckoTxtParser.parse(
                "RMCE01\nMario Kart Wii\n\nEverlasting Items v1 [Anarion]\n"
                + "046FE200 80040078\n2834XXXX YYYYZZZZ\nC26FE200 00000003\n60000000 00000000\n");
        check(placeholder.cheats.isEmpty(), "gecko: placeholder activator line drops the cheat: " + placeholder.cheats);
    }

    private static void dmnt() {
        List<ParsedCheat> rows = DmntCheatParser.parse(
                "{Master}\n04000000 00000000 00000000\n\n[Infinite Health]\n04000000 01234567 0000270F\n"
                + "580F0000 01234567\n[Empty]\n");
        check(rows.size() == 2, "dmnt: master + one, empty dropped: " + rows.size());
        check(rows.get(0).tags.contains("master"), "dmnt: master tag");
        check(rows.get(1).code.contains("\n"), "dmnt: lines kept");
    }

    private static void sharkive() {
        String json = "{\"0004000000030100\":{\"Infinite Lives\":[\"D3000000 00000000\",\"00123456 00000063\"],"
                + "\"Broken\":[]},\"00040000000AAAAA\":{\"Other\":[\"00000000 00000001\"]}}";
        List<ParsedCheat> rows = SharkiveJsonParser.for3dsTitle(json, "0004000000030100");
        check(rows.size() == 1, "sharkive 3ds: empty cheat dropped: " + rows.size());
        check("D3000000 00000000\n00123456 00000063".equals(rows.get(0).code), "sharkive 3ds: code");
        check(SharkiveJsonParser.for3dsTitle(json, "0004000000030100".toLowerCase()).size() == 1, "sharkive: case-insensitive title");
        String sw = "{\"0100000000010000\":{\"ABCDEF0123456789\":{\"Moon Jump\":[\"04000000 00000000 00000001\"]}}}";
        Map<String, List<ParsedCheat>> builds = SharkiveJsonParser.forSwitchTitle(sw, "0100000000010000");
        check(builds.size() == 1 && builds.containsKey("ABCDEF0123456789"), "sharkive switch: build id key");
    }

    private static void switchVersions() {
        List<String> ids = SwitchVersionsParser.buildIdsFor(
                "{\"0100000000010000\":{\"0\":\"ab12cd34ef567890\",\"65536\":\"1111111111111111\"}}",
                "0100000000010000");
        check(ids.size() == 2 && ids.contains("AB12CD34EF567890"), "versions: build ids upper-cased: " + ids);
    }

    private static void rpcs3() {
        // Patch names sit directly under the hash key (RPCS3 1.2 real-world
        // layout, matching Aps3ePatchWriter.renderPatches) -- there is no
        // intermediate "Patches:" map.
        String yaml = "Version: 1.2\n\n"
                + "PPU-abc123def:\n"
                + "  \"60 FPS\":\n"
                + "    Games:\n"
                + "      \"Demon's Souls\":\n"
                + "        BLUS30443: [ 01.00, 01.01 ] # comment\n"
                + "        BLES00932: [ All ]\n"
                + "    Author: someone\n"
                + "    Notes: Unlocks the frame rate\n"
                + "    Group: fps\n"
                + "    Patch:\n"
                + "      - [ be32, 0x00a1e3d8, 0x3f800000 ]\n"
                + "      - [ be32, 0x00a1e3dc, 0x00000000 ]\n"
                + "  \"Unused\":\n"
                + "    Games:\n"
                + "      \"Other\":\n"
                + "        BLUS99999: [ All ]\n"
                + "    Patch:\n"
                + "      - [ be32, 0x00000000, 0x00000000 ]\n"
                + "PPU-111:\n"
                + "  \"Skip Intro\":\n"
                + "    Games:\n"
                + "      \"Other Game\":\n"
                + "        NPUB30443: [ 01.00 ]\n"
                + "    Patch:\n"
                + "      - [ be32, 0x00000010, 0x60000000 ]\n";
        List<Rpcs3PatchYamlParser.Patch> patches = Rpcs3PatchYamlParser.forSerial(yaml, "BLUS-30443");
        check(patches.size() == 1, "rpcs3: one patch for the serial: " + patches.size());
        Rpcs3PatchYamlParser.Patch patch = patches.get(0);
        check("60 FPS".equals(patch.name) && "PPU-abc123def".equals(patch.hash), "rpcs3: name/hash");
        check(patch.serials.get("BLUS30443").contains("01.01"), "rpcs3: versions: " + patch.serials);
        check(patch.yaml.contains("Patch:") && patch.yaml.contains("0x00a1e3d8"), "rpcs3: yaml re-emitted: " + patch.yaml);
        check("fps".equals(patch.group), "rpcs3: group read from 'Group' key: " + patch.group);
        ParsedCheat parsed = Rpcs3PatchYamlParser.toParsed(patch, "BLUS30443");
        check(parsed.tags.contains("ppu:ppu-abc123def") && parsed.tags.contains("serial:blus30443")
                && parsed.tags.contains("version:01.00") && parsed.tags.contains("60fps")
                && parsed.tags.contains("fps"), "rpcs3: tags: " + parsed.tags);
        check(Rpcs3PatchYamlParser.forSerial(yaml, "NPUB30443").size() == 1, "rpcs3: second hash's direct patch");
        Object reparsed = MiniYaml.parse(patch.yaml);
        check(reparsed instanceof Map && ((Map<?, ?>) reparsed).containsKey("60 FPS"), "rpcs3: emitted yaml round-trips");
    }

    private static void dreamcast() {
        DreamcastMarkdownParser.Document document = DreamcastMarkdownParser.parse(
                "# Sonic Adventure (USA)\n\n## Infinite Lives\n\n```\n0B1A2C3D 00000009\n```\n\n"
                + "### Widescreen 16:9\nSome note\n0C000000 3F400000\n");
        check("Sonic Adventure (USA)".equals(document.title), "dreamcast: title");
        check(document.cheats.size() == 2, "dreamcast: two headings");
        check("0B1A2C3D 00000009".equals(document.cheats.get(0).code), "dreamcast: code");
        check(document.cheats.get(1).tags.contains("widescreen") && "Some note".equals(document.cheats.get(1).description),
                "dreamcast: tag + note");

        // Real bucanero/dreamcast-cheats files (4x4-evolution-(usa).md) spell
        // CodeBreaker/Xploder codes as a single 16-hex token, sometimes
        // continued on its own bare 8-hex line -- the space-separated
        // "XXXXXXXX YYYYYYYY" shape never appears.
        DreamcastMarkdownParser.Document real = DreamcastMarkdownParser.parse(
                "# 4x4 Evolution (USA)\n\n## Low Lap Time\n\n```\nBD976840C06E50C1\nC8845C2D\n```\n");
        check(real.cheats.size() == 1, "dreamcast: real 16-hex format yields a cheat: " + real.cheats.size());
        check("BD976840C06E50C1+C8845C2D".equals(real.cheats.get(0).code),
                "dreamcast: 16-hex token plus 8-hex continuation joined: " + real.cheats.get(0).code);
    }

    private static void fbneo() {
        List<ParsedCheat> rows = FbNeoIniParser.parse(
                "cheat \"Infinite Lives\"\ndefault 0\n0 \"Disabled\"\n1 \"Enabled\", 0, 0x00E0B4, 0x03\n\n"
                + "cheat \"Select Weapon\"\ndefault 0\n0 \"Off\"\n1 \"Sword\", 0, 0x00E100, 0x01\n2 \"Bow\", 0, 0x00E100, 0x02\n");
        check(rows.size() == 3, "fbneo: one + two options: " + rows.size());
        check("Infinite Lives".equals(rows.get(0).name), "fbneo: single option keeps cheat name");
        check("Select Weapon: Bow".equals(rows.get(2).name), "fbneo: multi option labelled");
        check(rows.get(0).code.contains("0x00E0B4"), "fbneo: option line kept");
    }

    private static void mame() {
        List<ParsedCheat> rows = MameCheatXmlParser.parse(
                "<?xml version=\"1.0\"?>\n<mamecheat version=\"1\">\n"
                + "  <cheat desc=\"Infinite Lives\">\n    <comment>Player &amp; 1</comment>\n"
                + "    <script state=\"run\"><action>maincpu.pb@E0B4=03</action></script>\n  </cheat>\n"
                + "  <cheat desc=\"Comment only\"><comment>nothing</comment></cheat>\n"
                + "  <cheat desc=\"Select Level\"><parameter min=\"0\" max=\"9\"/>"
                + "<script state=\"run\"><action>maincpu.pb@E0B5=param</action></script></cheat>\n"
                + "</mamecheat>\n");
        check(rows.size() == 2, "mame: action-less cheat dropped: " + rows.size());
        check("Player & 1".equals(rows.get(0).description), "mame: comment unescaped");
        check(rows.get(0).code.startsWith("<cheat desc=\"Infinite Lives\">"), "mame: element kept verbatim");
        check(rows.get(1).tags.contains("parameter"), "mame: parameter tagged");
    }

    private static void cemu() {
        CemuGraphicPackParser.Pack pack = CemuGraphicPackParser.parseRules(
                "[Definition]\ntitleIds = 00050000101C9300,00050000101C9400\nname = \"Infinite Hearts\"\n"
                + "path = \"The Legend of Zelda: Breath of the Wild/Cheats/Infinite Hearts\"\n"
                + "description = Never run out of hearts|Second line\nversion = 6\n\n[Preset]\nname = x\n");
        check(pack.titleIds.size() == 2 && "Infinite Hearts".equals(pack.name), "cemu: definition");
        check(CemuGraphicPackParser.covers(pack, "00050000101c9300"), "cemu: title id covered case-insensitively");
        check(CemuGraphicPackParser.covers(pack, "0005000E101C9300"), "cemu: update title shares low bits");
        check(!CemuGraphicPackParser.covers(pack, "0005000010101000"), "cemu: other title rejected");
        java.util.Map<String, String> files = new java.util.LinkedHashMap<>();
        files.put("patches.txt", "[BotWv208]\nmoduleMatches = 0x6267BFD0\n0x0033A470 = li r3, 0\n");
        files.put("rules.txt", "[Definition]\ntitleIds = 00050000101C9300\nname = \"Infinite Hearts\"\n");
        ParsedCheat parsed = CemuGraphicPackParser.toParsed("InfiniteHearts", pack, files);
        check(parsed != null && parsed.code.startsWith(CemuGraphicPackParser.FILE_MARKER + "rules.txt"), "cemu: rules first");
        java.util.Map<String, String> back = CemuGraphicPackParser.filesOf(parsed.code);
        check(back.size() == 2 && back.get("patches.txt").contains("moduleMatches"), "cemu: files round-trip: " + back.keySet());
        check(parsed.tags.contains("cheats"), "cemu: category tag: " + parsed.tags);
    }

    static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
}
