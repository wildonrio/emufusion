package com.thorium.preview.cheats.delivery;

import com.thorium.lucent.cheats.Cheat;
import com.thorium.preview.cheats.sources.MiniYaml;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Host proof of every boot writer's output text and file discipline:
 * exact bytes per engine format, idempotence, ownership, removal.
 */
public final class BootCheatWritersTest {
    private static File root;

    public static void main(String[] args) throws Exception {
        root = Files.createTempDirectory("emufusion-boot-writers").toFile();
        try {
            ownedFiles();
            dolphin();
            ppsspp();
            pcsx2();
            azahar();
            eden();
            aps3e();
            cemu();
            flycast();
            writerTable();
            deliveryPolicy();
            System.out.println("Boot cheat writer tests passed");
        } finally {
            delete(root);
        }
    }

    // ---- fixtures

    private static DeliveryCheat row(String id, String name, String description, String code,
                                     String delivery, String... tags) {
        return new DeliveryCheat(new Cheat(id, name, description, code), "test-source", delivery,
                Arrays.asList(tags), "");
    }

    private static BootCheatRequest request(String engine, String system, File engineRoot,
                                            File saveDir, Map<String, String> identity,
                                            List<DeliveryCheat> rows, String... enabled) {
        return new BootCheatRequest(engine, system, "Test Game", "Test Game (USA)", engineRoot,
                saveDir, identity, rows, new HashSet<>(Arrays.asList(enabled)));
    }

    private static Map<String, String> identity(String... pairs) {
        Map<String, String> map = new HashMap<>();
        for (int i = 0; i + 1 < pairs.length; i += 2) map.put(pairs[i], pairs[i + 1]);
        return map;
    }

    private static File dir(String name) {
        File directory = new File(root, name);
        directory.mkdirs();
        return directory;
    }

    private static String read(File file) throws Exception {
        return new String(Files.readAllBytes(file.toPath()), StandardCharsets.UTF_8);
    }

    private static void write(File file, String text) throws Exception {
        file.getParentFile().mkdirs();
        Files.write(file.toPath(), text.getBytes(StandardCharsets.UTF_8));
    }

    // ---- OwnedFiles

    private static void ownedFiles() throws Exception {
        File base = dir("owned");
        File file = new File(base, "a.txt");
        check(OwnedFiles.write(file, "one\n", OwnedFiles.Ownership.EXACT), "first write");
        check(read(file).equals("one\n"), "content written");
        check(OwnedFiles.sidecar(file).isFile(), "sidecar recorded");
        long stamp = file.lastModified();
        check(OwnedFiles.write(file, "one\n", OwnedFiles.Ownership.EXACT), "identical rewrite");
        check(OwnedFiles.write(file, "two\n", OwnedFiles.Ownership.EXACT), "changed rewrite");
        check(read(file).equals("two\n"), "content replaced");
        // Someone else edited it: exact ownership refuses, created ownership accepts.
        write(file, "edited by hand\n");
        check(!OwnedFiles.write(file, "three\n", OwnedFiles.Ownership.EXACT),
                "hand-edited file is left alone under EXACT");
        check(read(file).equals("edited by hand\n"), "hand edit survives");
        check(OwnedFiles.write(file, "three\n", OwnedFiles.Ownership.CREATED),
                "engine-rewritten file is ours under CREATED");
        // A file with no sidecar is never ours.
        File foreign = new File(base, "foreign.txt");
        write(foreign, "theirs\n");
        check(!OwnedFiles.write(foreign, "mine\n", OwnedFiles.Ownership.CREATED), "foreign file refused");
        check(!OwnedFiles.remove(foreign, OwnedFiles.Ownership.CREATED), "foreign file not removed");
        check(foreign.isFile(), "foreign file still there");
        check(OwnedFiles.remove(file, OwnedFiles.Ownership.CREATED), "owned file removed");
        check(!file.exists() && !OwnedFiles.sidecar(file).exists(), "file and sidecar gone");
        check(OwnedFiles.inside(base, new File(base, "x/y.txt")), "inside root");
        check(!OwnedFiles.inside(base, new File(base, "../escape.txt")), "traversal is outside");
        check(OwnedFiles.safeName("Game: Title/../x").equals("Game_ Title_.._x"), "safe file stem");
        check(!new File(base, "a.txt.part").exists(), "no .part left behind");
    }

    // ---- Dolphin

    private static void dolphin() throws Exception {
        File save = dir("dolphin-save");
        List<DeliveryCheat> rows = new ArrayList<>();
        rows.add(row("ar1", "Max Rupees", "Dolphin ActionReplay • GALE01",
                "04123456 00000001+04123458 00000002", "live"));
        rows.add(row("g1", "Widescreen 16:9", "codes.rc24.xyz • GALE01",
                "C2001234 00000002+3C608000 60000000+60000000 00000000", "live", "gecko", "widescreen"));
        rows.add(row("g2", "Widescreen 16:9", "second with the same name",
                "04001234 00000001", "live", "gecko"));
        rows.add(row("bad", "Broken", "", "not a code", "live", "gecko"));
        rows.add(row("enc", "Encrypted", "", "ABCD-EFGH-12345+ZZZZ-YYYY-00000", "live"));
        BootCheatRequest request = request("dolphin", "gamecube", dir("dolphin-root"), save,
                identity("gameId", "GALE01", "discIdentity", "GALE01R0"), rows, "ar1", "g2", "bad");
        List<File> touched = new DolphinGameSettingsWriter().write(request);
        File ini = new File(save, "User/GameSettings/GALE01.ini");
        check(touched.contains(ini), "dolphin ini written");
        String text = read(ini);
        String expected = "# Written by EmuFusion cheat delivery for GALE01. Regenerated before every launch; change the selection in EmuFusion.\n"
                + "[ActionReplay]\n"
                + "$Max Rupees\n04123456 00000001\n04123458 00000002\n"
                + "$Encrypted\nABCD-EFGH-12345\nZZZZ-YYYY-00000\n"
                + "[Gecko]\n"
                + "$Widescreen 16:9\nC2001234 00000002\n3C608000 60000000\n60000000 00000000\n"
                + "$Widescreen 16:9 (2)\n04001234 00000001\n";
        check(text.equals(expected), "dolphin ini text\n" + text);
        check(!text.contains("_Enabled"), "no _Enabled section: every code loads disabled and the "
                + "live session's own retro_cheat_set turns the current selection on (else a stale "
                + "_Enabled entry survives retro_cheat_reset and a disabled code keeps activating)");
        // Idempotent: same request, same bytes, still owned.
        new DolphinGameSettingsWriter().write(request);
        check(read(ini).equals(expected), "dolphin ini idempotent");
        // The selection plays no part in this file any more: every code is
        // always listed, regardless of which ones are enabled right now.
        new DolphinGameSettingsWriter().write(request.withEnabledIds(new HashSet<String>()));
        check(read(ini).equals(expected), "same codes regardless of selection");
        // No rows at all: the owned file is removed.
        new DolphinGameSettingsWriter().write(request("dolphin", "gamecube", dir("dolphin-root"), save,
                identity("gameId", "GALE01"), new ArrayList<DeliveryCheat>()));
        check(!ini.exists(), "dolphin ini removed with no rows");
        // Without a game id or save directory nothing is written.
        check(new DolphinGameSettingsWriter().write(request("dolphin", "gamecube", dir("dolphin-root"),
                null, identity("gameId", "GALE01"), rows, "ar1")).isEmpty(), "no save dir, no write");
        // Kind detection: a gamecube row with nothing to say is AR, a wii one Gecko.
        check(DolphinGameSettingsWriter.kindOf(row("x", "n", "", "04000000 00000000", "live"), "wii")
                == DolphinGameSettingsWriter.Kind.GECKO, "wii defaults to gecko");
        check(DolphinGameSettingsWriter.kindOf(row("x", "n", "", "04000000 00000000", "live"), "gamecube")
                == DolphinGameSettingsWriter.Kind.ACTION_REPLAY, "gamecube defaults to AR");
    }

    // ---- PPSSPP

    private static void ppsspp() throws Exception {
        File save = dir("ppsspp-save");
        List<DeliveryCheat> rows = new ArrayList<>();
        rows.add(row("c1", "Infinite Health", "", "_L 0x20123456 0x000003E7+_L 0x2012345A 0x000003E7", "live"));
        rows.add(row("c2", "16:9 Widescreen", "", "0x20456789 0x3F400000", "live", "widescreen"));
        rows.add(row("c3", "Broken", "", "_L 0x2045 0x3F400000", "live"));
        BootCheatRequest request = request("ppsspp", "psp", dir("ppsspp-root"), save,
                identity("serial", "ULUS-10041"), rows, "c2", "c3");
        List<File> touched = new PpssppCheatWriter().write(request);
        File ini = new File(save, "PSP/Cheats/ULUS10041.ini");
        check(touched.contains(ini), "cwcheat ini written");
        String expected = "_S ULUS10041\n_G Test Game\n"
                + "_C0 Infinite Health\n_L 0x20123456 0x000003E7\n_L 0x2012345A 0x000003E7\n"
                + "_C1 16:9 Widescreen\n_L 0x20456789 0x3F400000\n";
        check(read(ini).equals(expected), "cwcheat text\n" + read(ini));
        // PPSSPP's live path rewrites the file itself; the next boot write must still be ours.
        write(ini, "_S ULUS10041\n_C1 0\n_L 0x20456789 0x3F400000\n");
        new PpssppCheatWriter().write(request);
        check(read(ini).equals(expected), "core-rewritten file reclaimed");
        // Serial from the file name when the identity has none.
        BootCheatRequest byStem = new BootCheatRequest("ppsspp", "psp", "", "Game [US] [ULES-54321]",
                dir("ppsspp-root"), save, null, rows, new HashSet<String>());
        check(PpssppCheatWriter.discId(byStem).equals("ULES54321"), "serial from stem");
    }

    // ---- PCSX2

    private static void pcsx2() throws Exception {
        File engineRoot = dir("armsx2");
        List<DeliveryCheat> rows = new ArrayList<>();
        rows.add(row("w", "Widescreen 16:9", "pcsx2-patches", "patch=1,EE,00123456,extended,00000001\npatch=1,EE,0012345A,extended,3FAAAAAB", "boot", "widescreen"));
        rows.add(row("h", "Infinite Health", "", "patch=1,EE,20ABCDEF,word,000003E7", "boot"));
        rows.add(row("bad", "Broken", "", "poke 1234", "boot"));
        BootCheatRequest request = request("armsx2", "ps2", engineRoot, null,
                identity("serial", "SCUS-97472", "crc", "7D6F5B0E,abcdef01"), rows, "w", "bad");
        List<File> touched = new Pcsx2PnachWriter().write(request);
        File first = new File(engineRoot, "pcsx2/cheats/SCUS-97472_7D6F5B0E.pnach");
        File second = new File(engineRoot, "pcsx2/cheats/SCUS-97472_ABCDEF01.pnach");
        check(touched.contains(first) && touched.contains(second), "one pnach per crc");
        String expected = "// Written by EmuFusion cheat delivery. Regenerated before every launch; change the selection in EmuFusion.\n"
                + "gametitle=Test Game\n"
                + "// Widescreen 16:9 (test-source)\n"
                + "patch=1,EE,00123456,extended,00000001\npatch=1,EE,0012345A,extended,3FAAAAAB\n";
        check(read(first).equals(expected), "pnach text\n" + read(first));
        check(read(second).equals(expected), "same text per crc");
        // A crc that stops being relevant loses its owned file.
        BootCheatRequest fewer = request("armsx2", "ps2", engineRoot, null,
                identity("serial", "SCUS-97472", "crc", "7D6F5B0E"), rows, "w");
        new Pcsx2PnachWriter().write(fewer);
        check(first.isFile() && !second.isFile(), "stale crc file removed");
        // No crc: the serial-wide fallback name.
        BootCheatRequest noCrc = request("armsx2", "ps2", engineRoot, null,
                identity("serial", "SCUS-97472"), rows, "h");
        new Pcsx2PnachWriter().write(noCrc);
        check(new File(engineRoot, "pcsx2/cheats/SCUS-97472_00000000.pnach").isFile(), "serial-wide fallback");
        check(!first.isFile(), "crc file retired when only the fallback applies");
        // No serial, only crc.
        BootCheatRequest crcOnly = new BootCheatRequest("armsx2", "ps2", "T", "disc", engineRoot, null,
                identity("crc", "0000ABCD"), rows, new HashSet<>(Arrays.asList("h")));
        new Pcsx2PnachWriter().write(crcOnly);
        check(new File(engineRoot, "pcsx2/cheats/0000ABCD.pnach").isFile(), "crc-only name");
        // Nothing enabled: owned files go.
        new Pcsx2PnachWriter().write(noCrc.withEnabledIds(new HashSet<String>()));
        check(!new File(engineRoot, "pcsx2/cheats/SCUS-97472_00000000.pnach").exists(), "removed when nothing enabled");
        // PCSX2 itself strips a trailing "// ..." end-of-line comment; pcsx2_patches
        // ships plenty of lines like this and they must not be dropped whole.
        DeliveryCheat commented = row("c", "Widescreen", "", "patch=1,EE,0018c6a0,word,4481f000 // 00000000", "boot");
        List<String> commentedBody = Pcsx2PnachWriter.body(commented);
        check(commentedBody != null && commentedBody.size() == 1
                && commentedBody.get(0).equals("patch=1,EE,0018c6a0,word,4481f000"),
                "trailing // comment stripped: " + commentedBody);
        DeliveryCheat mixed = row("m", "Mixed", "", "patch=1,EE,00123456,word,00000001 // a\n"
                + "// full line comment\npatch=1,EE,00123457,word,00000002", "boot");
        List<String> mixedBody = Pcsx2PnachWriter.body(mixed);
        check(mixedBody != null && mixedBody.size() == 2
                && mixedBody.get(0).equals("patch=1,EE,00123456,word,00000001")
                && mixedBody.get(1).equals("patch=1,EE,00123457,word,00000002"),
                "full-line and trailing comments both handled: " + mixedBody);
        // "leshort"/"leword"/"ledouble" are not real PCSX2 patch_data_type
        // values (pcsx2/Patch.h only has byte/short/word/double/extended/
        // beshort/beword/bedouble/bytes) and must be rejected, not silently
        // accepted and then dropped at boot with no error shown anywhere.
        DeliveryCheat leshort = row("le1", "Bogus leshort", "", "patch=1,EE,00112233,leshort,0001", "boot");
        check(Pcsx2PnachWriter.body(leshort) == null, "leshort type rejected");
        DeliveryCheat leword = row("le2", "Bogus leword", "", "patch=1,EE,00112233,leword,00000001", "boot");
        check(Pcsx2PnachWriter.body(leword) == null, "leword type rejected");
        DeliveryCheat ledouble = row("le3", "Bogus ledouble", "", "patch=1,EE,00112233,ledouble,0000000000000001", "boot");
        check(Pcsx2PnachWriter.body(ledouble) == null, "ledouble type rejected");
    }

    // ---- Azahar

    private static void azahar() throws Exception {
        File save = dir("azahar-save");
        List<DeliveryCheat> rows = new ArrayList<>();
        rows.add(row("a", "Max Money", "", "D3000000 10000000\n00300000 0098967F", "boot"));
        rows.add(row("b", "Off", "", "00300004 00000001", "boot"));
        BootCheatRequest request = request("azahar", "3ds", dir("azahar-root"), save,
                identity("titleId", "0004000000030100"), rows, "a");
        new AzaharCheatWriter().write(request);
        File file = new File(save, "Azahar/cheats/0004000000030100.txt");
        check(file.isFile(), "gateway file written");
        check(read(file).equals("[Max Money]\n*citra_enabled\nD3000000 10000000\n00300000 0098967F\n\n"),
                "gateway text\n" + read(file));
        new AzaharCheatWriter().write(request.withEnabledIds(new HashSet<String>()));
        check(!file.exists(), "gateway file removed when nothing enabled");
    }

    // ---- Eden

    private static void eden() throws Exception {
        File engineRoot = dir("eden");
        List<DeliveryCheat> rows = new ArrayList<>();
        rows.add(row("all", "Infinite Hearts", "", "04000000 12345678 00000005\n04000000 1234567C 00000005", "boot"));
        rows.add(row("one", "60 FPS", "", "58000000 01234567 89ABCDEF", "boot", "buildid:1122334455667788"));
        rows.add(row("bad", "Broken", "", "0400000 1234", "boot"));
        BootCheatRequest request = request("eden", "switch", engineRoot, null,
                identity("titleId", "01007EF00011E000", "buildIds", "ABCDEF0123456789AABBCCDD,1122334455667788"),
                rows, "all", "one", "bad");
        new EdenCheatWriter().write(request);
        File cheats = new File(engineRoot, "load/01007EF00011E000/EmuFusionCheats/cheats");
        File first = new File(cheats, "ABCDEF0123456789.txt");
        File second = new File(cheats, "1122334455667788.txt");
        check(first.isFile() && second.isFile(), "one file per build id, truncated to 16 hex");
        check(read(first).equals("[Infinite Hearts]\n04000000 12345678 00000005\n04000000 1234567C 00000005\n\n"),
                "untagged row in every build\n" + read(first));
        check(read(second).equals("[Infinite Hearts]\n04000000 12345678 00000005\n04000000 1234567C 00000005\n\n"
                + "[60 FPS]\n58000000 01234567 89ABCDEF\n\n"), "tagged row only in its build\n" + read(second));
        // Listed by name: a case-insensitive host filesystem would answer exists() for either spelling.
        Set<String> names = new HashSet<>(Arrays.asList(cheats.list()));
        names.removeIf(name -> name.startsWith("."));
        check(names.equals(new HashSet<>(Arrays.asList("ABCDEF0123456789.txt", "1122334455667788.txt"))),
                "only upper-case build files: " + names);
        new EdenCheatWriter().write(request.withEnabledIds(new HashSet<String>()));
        check(!first.exists() && !second.exists(), "files removed when nothing enabled");
        check(!cheats.exists(), "empty mod directory removed");
    }

    // ---- aPS3e

    private static void aps3e() throws Exception {
        File engineRoot = dir("aps3e");
        String hash = "PPU-0123456789abcdef0123456789abcdef01234567";
        String yaml = "\"Unlock FPS\":\n  Games:\n    \"Test Game\":\n      BLUS30443: [ All ]\n"
                + "  Author: someone\n  Notes: fast\n  Patch Version: 1.0\n  Patch:\n"
                + "    - [ be32, 0x00123456, 0x00000001 ]\n    - [ bef32, 0x0012345A, 60.0 ]\n";
        List<DeliveryCheat> rows = new ArrayList<>();
        rows.add(row("fps", "Unlock FPS", "fast (by someone)", yaml, "boot",
                "ppu:" + hash, "serial:BLUS30443", "version:01.00"));
        rows.add(row("plus", "Skip Intro", "", hash + "+[ be32, 0x00200000, 0x60000000 ]", "boot"));
        rows.add(row("nohash", "Orphan", "", "[ be32, 0x00200000, 0x60000000 ]", "boot"));
        rows.add(row("bad", "Broken", "", "[ be32, junk ]", "boot", "ppu:" + hash));
        BootCheatRequest request = request("aps3e", "ps3", engineRoot, null,
                identity("serial", "BLUS30443", "appVersion", "01.00"), rows, "fps", "plus", "nohash", "bad");
        new Aps3ePatchWriter().write(request);
        File patches = new File(engineRoot, "config/patches/imported_patch.yml");
        File config = new File(engineRoot, "config/patch_config.yml");
        check(patches.isFile() && config.isFile(), "patch yaml and config written");
        String expectedPatches = "# Written by EmuFusion cheat delivery. Regenerated before every launch; change the selection in EmuFusion.\n"
                + "Version: 1.2\n\n"
                + hash + ":\n"
                + "  \"Unlock FPS\":\n    Games:\n      \"Test Game\":\n        BLUS30443: [ \"01.00\" ]\n"
                + "    Author: \"test-source\"\n    Notes: \"fast (by someone)\"\n    Patch Version: \"1.0\"\n    Patch:\n"
                + "      - [ be32, 0x00123456, 0x00000001 ]\n      - [ bef32, 0x0012345A, 60.0 ]\n"
                + "  \"Skip Intro\":\n    Games:\n      \"Test Game\":\n        BLUS30443: [ \"01.00\" ]\n"
                + "    Author: \"test-source\"\n    Patch Version: \"1.0\"\n    Patch:\n"
                + "      - [ be32, 0x00200000, 0x60000000 ]\n";
        check(read(patches).equals(expectedPatches), "patch yaml\n" + read(patches));
        String expectedConfig = "# Written by EmuFusion cheat delivery.\n" + hash + ":\n"
                + "  \"Unlock FPS\":\n    \"Test Game\":\n      BLUS30443:\n        \"01.00\":\n          Enabled: true\n"
                + "  \"Skip Intro\":\n    \"Test Game\":\n      BLUS30443:\n        \"01.00\":\n          Enabled: true\n";
        check(read(config).equals(expectedConfig), "patch config\n" + read(config));
        // aPS3e's own patch manager rewrites this same file for hashes that
        // have nothing to do with EmuFusion (a different game's patch); our
        // own regeneration must carry that entry over rather than erase it.
        String foreignHash = "PPU-fedcba9876543210fedcba9876543210fedcba98";
        write(config, read(config) + foreignHash + ":\n  \"Other Game Patch\":\n"
                + "    \"Other Game\":\n      BLUS99999:\n        \"All\":\n          Enabled: true\n");
        new Aps3ePatchWriter().write(request);
        String merged = read(config);
        check(merged.contains("# Preserved:") && merged.startsWith(expectedConfig),
                "own entries kept, foreign entries appended after a marker\n" + merged);
        Object parsedMerged = MiniYaml.parse(merged);
        check(parsedMerged instanceof Map, "merged config still parses");
        Map<?, ?> mergedMap = (Map<?, ?>) parsedMerged;
        check(mergedMap.containsKey(hash), "own hash still present after merge");
        Object foreignNode = mergedMap.get(foreignHash);
        check(foreignNode instanceof Map, "foreign hash preserved: " + mergedMap.keySet());
        Object patchNode = ((Map<?, ?>) foreignNode).get("Other Game Patch");
        check(patchNode instanceof Map, "foreign patch name preserved: " + foreignNode);
        // A hash EmuFusion does still own for this launch is regenerated by
        // us, not merged from whatever aPS3e last wrote for it.
        write(config, "\"stale\": true\n" + hash + ":\n  \"Stale Entry\":\n    x: 1\n");
        new Aps3ePatchWriter().write(request);
        check(!read(config).contains("Stale Entry") && read(config).contains("Unlock FPS"),
                "own hash regenerated, not merged\n" + read(config));
        // Foreign entries alone still get a config file even when nothing of
        // ours is enabled -- deleting the file would drop them too.
        write(config, read(config) + foreignHash + ":\n  \"Other Game Patch\":\n    x: 1\n");
        new Aps3ePatchWriter().write(request.withEnabledIds(new HashSet<String>()));
        check(config.isFile() && read(config).contains(foreignHash) && !patches.exists(),
                "config kept for a foreign entry with nothing of ours enabled; patches removed");
        // Back to a clean baseline (no foreign residue) for the rest of this test.
        config.delete();
        OwnedFiles.sidecar(config).delete();
        new Aps3ePatchWriter().write(request);
        check(read(config).equals(expectedConfig), "config back to a clean baseline after the merge tests");
        // Without an app version everything is keyed All.
        BootCheatRequest anyVersion = request("aps3e", "ps3", engineRoot, null,
                identity("serial", "BLUS30443"), rows, "plus");
        new Aps3ePatchWriter().write(anyVersion);
        check(read(patches).contains("BLUS30443: [ \"All\" ]") && read(config).contains("        \"All\":\n"),
                "All when the version is unknown");
        new Aps3ePatchWriter().write(anyVersion.withEnabledIds(new HashSet<String>()));
        check(!patches.exists() && !config.exists(), "yaml removed when nothing enabled");
        check(Aps3ePatchWriter.patchLine("be32 0x1 0x2").equals("[ be32, 0x1, 0x2 ]"), "loose spelling");
        check(Aps3ePatchWriter.patchLine("[ be32, 0x1, \"x\"y ]") == null, "quote injection refused");
    }

    // ---- Cemu

    private static void cemu() throws Exception {
        File engineRoot = dir("cemu");
        String pack = "#### file: rules.txt\n[Definition]\ntitleIds = 00050000101C9300,00050000101C9400\n"
                + "name = Infinite Stamina\npath = \"Zelda/Cheats/Infinite Stamina\"\nversion = 6\n"
                + "#### file: patch_stamina.asm\n[Stamina_V208]\nmoduleMatches = 0x6267BFD0\n0x02F2A8E4 = li r3, 1\n";
        List<DeliveryCheat> rows = new ArrayList<>();
        rows.add(row("pack1", "Infinite Stamina", "", pack, "boot"));
        rows.add(row("raw", "Raw Code", "", "0x02F2A8E8 = li r3, 2", "boot", "modulematches=0x6267BFD0"));
        rows.add(row("orphan", "No Module", "", "0x02F2A8EC = li r3, 3", "boot"));
        rows.add(row("escape", "Bad File", "", "#### file: ../rules.txt\n[Definition]\n", "boot"));
        BootCheatRequest request = request("cemu", "wiiu", engineRoot, null,
                identity("titleId", "00050000101C9300"), rows, "pack1", "raw", "orphan", "escape");
        File settings = new File(engineRoot, "settings.xml");
        write(settings, "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<content>\n\t<vsync>2</vsync>\n\t<GraphicPack>\n"
                + "\t\t<Entry filename=\"graphicPacks/EmuFusion_old/rules.txt\"/>\n"
                + "\t\t<Entry filename=\"graphicPacks/downloadedGraphicPacks/Zelda/Mods/x/rules.txt\">\n"
                + "\t\t\t<Preset><category>Quality</category><preset>High</preset></Preset>\n\t\t</Entry>\n"
                + "\t</GraphicPack>\n</content>\n");
        File old = new File(engineRoot, "graphicPacks/EmuFusion_old");
        old.mkdirs();
        write(new File(old, "rules.txt"), "[Definition]\n");
        new CemuGraphicPackWriter().write(request);
        File packDir = new File(engineRoot, "graphicPacks/EmuFusion_pack1");
        check(read(new File(packDir, "rules.txt")).equals("[Definition]\ntitleIds = 00050000101C9300,00050000101C9400\n"
                + "name = Infinite Stamina\npath = \"Zelda/Cheats/Infinite Stamina\"\nversion = 6\n"), "pack rules verbatim");
        check(read(new File(packDir, "patch_stamina.asm")).equals("[Stamina_V208]\nmoduleMatches = 0x6267BFD0\n0x02F2A8E4 = li r3, 1\n"),
                "pack asm verbatim");
        File rawDir = new File(engineRoot, "graphicPacks/EmuFusion_raw");
        check(read(new File(rawDir, "rules.txt")).equals("[Definition]\ntitleIds = 00050000101C9300\nname = Raw Code\n"
                + "path = \"EmuFusion/Test Game/Cheats/Raw Code\"\ndescription = Written by EmuFusion cheat delivery.\n"
                + "version = 6\ndefault = true\n"), "synthesized rules\n" + read(new File(rawDir, "rules.txt")));
        check(read(new File(rawDir, CemuGraphicPackWriter.PATCH_FILE)).equals("[EmuFusion]\nmoduleMatches = 0x6267BFD0\n0x02F2A8E8 = li r3, 2\n"),
                "synthesized patch");
        check(!new File(engineRoot, "graphicPacks/EmuFusion_orphan").exists(), "row without a module skipped");
        check(!new File(engineRoot, "graphicPacks/EmuFusion_escape").exists(), "traversal file name refused");
        check(!old.exists(), "stale EmuFusion pack removed");
        String xml = read(settings);
        String expected = "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<content>\n\t<vsync>2</vsync>\n\t<GraphicPack>\n"
                + "\t\t<Entry filename=\"graphicPacks/downloadedGraphicPacks/Zelda/Mods/x/rules.txt\">\n"
                + "\t\t\t<Preset><category>Quality</category><preset>High</preset></Preset>\n\t\t</Entry>\n"
                + "\t\t<Entry filename=\"graphicPacks/EmuFusion_pack1/rules.txt\"/>\n"
                + "\t\t<Entry filename=\"graphicPacks/EmuFusion_raw/rules.txt\"/>\n"
                + "\t</GraphicPack>\n</content>\n";
        check(xml.equals(expected), "settings.xml edited only in EmuFusion entries\n" + xml);
        // Disable everything: packs and entries go, the rest of the XML is untouched.
        new CemuGraphicPackWriter().write(request.withEnabledIds(new HashSet<String>()));
        check(!packDir.exists() && !rawDir.exists(), "packs removed");
        check(read(settings).equals("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<content>\n\t<vsync>2</vsync>\n\t<GraphicPack>\n"
                + "\t\t<Entry filename=\"graphicPacks/downloadedGraphicPacks/Zelda/Mods/x/rules.txt\">\n"
                + "\t\t\t<Preset><category>Quality</category><preset>High</preset></Preset>\n\t\t</Entry>\n"
                + "\t</GraphicPack>\n</content>\n"), "foreign entry kept\n" + read(settings));
        // A missing settings.xml is created minimal.
        settings.delete();
        new CemuGraphicPackWriter().write(request);
        check(read(settings).equals("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<content>\n\t<GraphicPack>\n"
                + "\t\t<Entry filename=\"graphicPacks/EmuFusion_pack1/rules.txt\"/>\n"
                + "\t\t<Entry filename=\"graphicPacks/EmuFusion_raw/rules.txt\"/>\n"
                + "\t</GraphicPack>\n</content>\n"), "minimal settings.xml\n" + read(settings));
    }

    // ---- Flycast

    private static void flycast() throws Exception {
        File engineRoot = dir("flycast");
        List<DeliveryCheat> rows = new ArrayList<>();
        rows.add(row("lives", "Infinite Lives", "", "0201F5A0 00000063+0101F5A4 00000010", "boot"));
        rows.add(row("off", "Byte poke", "", "0001F5A8 000000FF", "boot"));
        rows.add(row("bad", "Unsupported type", "", "0F01F5A8 000000FF", "boot"));
        BootCheatRequest request = new BootCheatRequest("flycast", "dreamcast", "T", "Sonic Adventure (USA)",
                engineRoot, null, identity("productId", "T-8101N"), rows, new HashSet<>(Arrays.asList("lives")));
        new FlycastCheatWriter().write(request);
        File file = new File(engineRoot, "dc/cheats/Sonic Adventure (USA).cht");
        check(file.isFile(), "flycast cht written: " + file);
        String text = read(file);
        check(text.startsWith("cheat0_desc = Infinite Lives (1/2)\ncheat0_address = 128416\n"), "first poke\n" + text);
        check(text.contains("cheat0_memory_search_size = 2\ncheat0_value = 99\n"), "32-bit value");
        check(text.contains("cheat1_address = 128420\n") && text.contains("cheat1_memory_search_size = 1\n")
                && text.contains("cheat1_enable = true\n"), "16-bit poke enabled");
        check(text.contains("cheat2_desc = Byte poke\n") && text.contains("cheat2_enable = false\n")
                && text.contains("cheat2_memory_search_size = 0\n"), "8-bit poke disabled");
        check(text.endsWith("cheats = 3\n"), "count last");
        check(!text.contains("Unsupported type"), "unknown code type skipped");
    }

    // ---- tables

    private static void writerTable() {
        for (String engine : new String[] {"dolphin", "ppsspp", "armsx2", "azahar", "eden", "aps3e", "cemu", "flycast"})
            check(BootCheatWriters.forEngine(engine) != null, "writer for " + engine);
        check(BootCheatWriters.forEngine("mame") == null, "no writer for mame");
        check(BootCheatWriters.forEngine("Dolphin ") != null, "engine id normalised");
    }

    private static void deliveryPolicy() {
        check(CheatDelivery.resolve("mesen", "").equals("live"), "live engine default");
        check(CheatDelivery.resolve("armsx2", "").equals("boot"), "boot engine default");
        check(CheatDelivery.resolve("armsx2", "live").equals("boot"), "live claim on boot engine");
        check(CheatDelivery.resolve("dolphin", "boot").equals("boot"), "boot claim on dolphin honoured");
        check(CheatDelivery.resolve("mesen", "boot").equals("live"), "boot claim on writer-less live engine");
        check(CheatDelivery.resolve("mame", "live").equals("unsupported"), "no path at all");
        check(CheatDelivery.resolve("armsx2", "unsupported").equals("unsupported"), "explicit unsupported kept");
        check(CheatDelivery.widescreenByCheat("wii") && CheatDelivery.widescreenByCheat("psp")
                && !CheatDelivery.widescreenByCheat("n64"), "widescreen-by-cheat systems");
        check(CheatDelivery.needsSaveDirectory("dolphin") && !CheatDelivery.needsSaveDirectory("eden"), "save dir engines");
        DeliveryCheat boot = row("b", "Name", "provenance", "00000000 00000000", "boot");
        check(boot.displayDescription().equals("provenance • applies on next launch"), "boot note");
        DeliveryCheat already = row("b", "Name", "provenance • applies on next launch", "00000000 00000000", "boot");
        check(already.displayDescription().equals("provenance • applies on next launch"), "note not doubled");
        check(row("u", "Name", "", "0", "unsupported").displayDescription()
                .equals("not applied by the packaged engine yet"), "unsupported note");
        check(row("w", "Wide Screen Fix", "", "0", "live").isWidescreen(), "widescreen by name");
        check(row("w", "Camera", "", "0", "live", "widescreen").isWidescreen(), "widescreen by tag");
        check(!row("w", "Camera", "", "0", "live").isWidescreen(), "not widescreen");
    }

    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }

    private static void delete(File file) {
        File[] children = file.listFiles();
        if (children != null) for (File child : children) delete(child);
        file.delete();
    }
}
