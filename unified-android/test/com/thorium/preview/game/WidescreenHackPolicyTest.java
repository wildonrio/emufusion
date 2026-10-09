package com.thorium.preview.game;

import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Covers the pure halves of the widescreen hack: the per-system table
 * ({@link WidescreenHackTable}, which {@code WidescreenHackPolicy} delegates
 * to) and the override file ({@link CoreOptionOverrideFile}). No Android
 * Context is needed.
 */
public final class WidescreenHackPolicyTest {
    public static void main(String[] args) throws Exception {
        availabilityTable();
        overrideTable();
        overrideFileRoundTrip();
        overrideFileBounds();
        System.out.println("WidescreenHackPolicyTest passed");
    }

    private static void availabilityTable() {
        expectEquals("hack", WidescreenHackTable.availability("n64"));
        expectEquals("hack", WidescreenHackTable.availability("psx"));
        expectEquals("hack", WidescreenHackTable.availability("ps2"));
        expectEquals("hack", WidescreenHackTable.availability("gamecube"));
        expectEquals("hack", WidescreenHackTable.availability("wii"));
        expectEquals("hack", WidescreenHackTable.availability("dreamcast"));
        expectEquals("cheats", WidescreenHackTable.availability("psp"));
        expectEquals("native", WidescreenHackTable.availability("wiiu"));
        expectEquals("native", WidescreenHackTable.availability("switch"));
        expectEquals("native", WidescreenHackTable.availability("ps3"));
        expectEquals("unavailable", WidescreenHackTable.availability("3ds"));
        expectEquals("unavailable", WidescreenHackTable.availability("nds"));
        expectEquals("unavailable", WidescreenHackTable.availability("snes"));
        expectEquals("unavailable", WidescreenHackTable.availability(null));
        expectEquals("hack", WidescreenHackTable.availability(" N64 "));
        expect(WidescreenHackTable.isHackApplicable("psp"));
        expect(!WidescreenHackTable.isHackApplicable("switch"));
        expect(!WidescreenHackTable.isHackApplicable("nds"));
        expectEquals(12, WidescreenHackTable.SYSTEMS.size());
        for (String system : WidescreenHackTable.SYSTEMS)
            expect(!"unavailable".equals(WidescreenHackTable.availability(system)) ||
                    "3ds".equals(system) || "nds".equals(system));
    }

    private static void overrideTable() {
        Map<String, String> n64 =
                WidescreenHackTable.coreOptionOverrides("n64", "mupen64plus-next", true);
        expectEquals("16:9 adjusted", n64.get("mupen64plus-aspect"));
        expectEquals("1920x1080", n64.get("mupen64plus-169screensize"));
        expectEquals(2, n64.size());
        expect(WidescreenHackTable.coreOptionOverrides("n64", "mupen64plus-next", false)
                .isEmpty());

        Map<String, String> psx =
                WidescreenHackTable.coreOptionOverrides("psx", "swanstation", true);
        expectEquals("true", psx.get("swanstation_GPU_WidescreenHack"));
        expectEquals("16:9", psx.get("swanstation_Display_AspectRatio"));
        expect(WidescreenHackTable.coreOptionOverrides("psx", "swanstation", false)
                .isEmpty());

        Map<String, String> ps2 =
                WidescreenHackTable.coreOptionOverrides("ps2", "armsx2", true);
        expectEquals("enabled", ps2.get("armsx2_widescreen_patches"));
        expectEquals("16:9", ps2.get("armsx2_aspect_ratio"));
        expectEquals("enabled", ps2.get("armsx2_cheats"));
        // Boot pnach cheats stay enabled for armsx2 even with the hack off.
        Map<String, String> ps2Off =
                WidescreenHackTable.coreOptionOverrides("ps2", "armsx2", false);
        expectEquals("enabled", ps2Off.get("armsx2_cheats"));
        expect(!ps2Off.containsKey("armsx2_widescreen_patches"));
        // The alternative PS2 core has no widescreen option.
        expect(WidescreenHackTable.coreOptionOverrides("ps2", "play", true).isEmpty());

        Map<String, String> gc =
                WidescreenHackTable.coreOptionOverrides("gamecube", "dolphin", true);
        expectEquals("enabled", gc.get("dolphin_widescreen_hack"));
        expectEquals("enabled", gc.get("dolphin_cheats_enabled"));
        Map<String, String> wiiOff =
                WidescreenHackTable.coreOptionOverrides("wii", "dolphin", false);
        // Live cheats stay enabled for Dolphin even with the hack off.
        expectEquals("enabled", wiiOff.get("dolphin_cheats_enabled"));
        expect(!wiiOff.containsKey("dolphin_widescreen_hack"));
        Map<String, String> wiiCoded =
                WidescreenHackTable.coreOptionOverrides("wii", "dolphin", true, true);
        // A per-game 16:9 code replaces the generic projection hack.
        expect(!wiiCoded.containsKey("dolphin_widescreen_hack"));
        expectEquals("enabled", wiiCoded.get("dolphin_cheats_enabled"));

        Map<String, String> dc =
                WidescreenHackTable.coreOptionOverrides("dreamcast", "flycast", true);
        expectEquals("enabled", dc.get("reicast_widescreen_cheats"));
        expectEquals("enabled", dc.get("reicast_widescreen_hack"));
        expect(WidescreenHackTable.coreOptionOverrides("dreamcast", "flycast", false)
                .isEmpty());

        Map<String, String> psp =
                WidescreenHackTable.coreOptionOverrides("psp", "ppsspp", true);
        expectEquals("enabled", psp.get("ppsspp_cheats"));
        expectEquals(1, psp.size());
        expectEquals("enabled", WidescreenHackTable
                .coreOptionOverrides("psp", "ppsspp", false).get("ppsspp_cheats"));

        // Native and unavailable systems, and unknown engines, get nothing.
        expect(WidescreenHackTable.coreOptionOverrides("switch", "eden", true).isEmpty());
        expect(WidescreenHackTable.coreOptionOverrides("wiiu", "cemu", true).isEmpty());
        expect(WidescreenHackTable.coreOptionOverrides("nds", "melonds-ds", true).isEmpty());
        expect(WidescreenHackTable.coreOptionOverrides("snes", "mesen-s", true).isEmpty());
        // A system/engine mismatch must not leak another system's keys.
        expect(WidescreenHackTable.coreOptionOverrides("psx", "mupen64plus-next", true)
                .isEmpty());
        // Every key and value in the table is writable to the override file.
        for (String system : WidescreenHackTable.SYSTEMS)
            for (String engine : new String[] {"mupen64plus-next", "swanstation",
                    "armsx2", "dolphin", "flycast", "ppsspp"})
                for (Map.Entry<String, String> entry : WidescreenHackTable
                        .coreOptionOverrides(system, engine, true).entrySet()) {
                    expect(CoreOptionOverrideFile.isValidKey(entry.getKey()));
                    expect(CoreOptionOverrideFile.isValidValue(entry.getValue()));
                }
    }

    private static void overrideFileRoundTrip() throws Exception {
        File root = File.createTempFile("lucent-overrides", "");
        expect(root.delete());
        File engineRoot = new File(root, "mupen64plus-next");
        File file = CoreOptionOverrideFile.in(engineRoot);
        expectEquals("lucent-core-overrides.txt", file.getName());
        expect(CoreOptionOverrideFile.read(file).isEmpty());

        Map<String, String> overrides =
                WidescreenHackTable.coreOptionOverrides("n64", "mupen64plus-next", true);
        CoreOptionOverrideFile.write(file, overrides);
        expect(file.isFile());
        expect(!new File(file.getPath() + ".part").exists());
        Map<String, String> back = CoreOptionOverrideFile.read(file);
        expectEquals(overrides, back);
        String text = new String(java.nio.file.Files.readAllBytes(file.toPath()),
                StandardCharsets.UTF_8);
        expect(text.startsWith("#"));
        expect(text.contains("mupen64plus-aspect=16:9 adjusted\n"));
        expect(text.contains("mupen64plus-169screensize=1920x1080\n"));

        // Rewriting replaces the previous content atomically.
        LinkedHashMap<String, String> replacement = new LinkedHashMap<>();
        replacement.put("dolphin_cheats_enabled", "enabled");
        CoreOptionOverrideFile.write(file, replacement);
        expectEquals(replacement, CoreOptionOverrideFile.read(file));

        // An empty map removes the file: "no overrides" == "no file".
        CoreOptionOverrideFile.write(file, new LinkedHashMap<String, String>());
        expect(!file.exists());
        expect(CoreOptionOverrideFile.delete(file));
        cleanup(root);
    }

    private static void overrideFileBounds() throws Exception {
        // Parsing tolerates comments, CRLF, blanks, and rejects bad keys.
        Map<String, String> parsed = CoreOptionOverrideFile.parse(
                "# comment\r\n\r\n  mupen64plus-aspect = 16:9 adjusted \r\n" +
                "bad key=1\n=novalue\nnovalue=\nok_key=a=b\n../evil=1\n" +
                "ctrl=a\tb\n");
        expectEquals("16:9 adjusted", parsed.get("mupen64plus-aspect"));
        expectEquals("a=b", parsed.get("ok_key"));
        expectEquals(2, parsed.size());

        // Serialisation skips invalid entries and caps the count.
        LinkedHashMap<String, String> many = new LinkedHashMap<>();
        many.put("bad key", "x");
        many.put("empty", "");
        for (int index = 0; index < CoreOptionOverrideFile.MAX_ENTRIES + 10; index++)
            many.put("key" + index, "value" + index);
        Map<String, String> reparsed =
                CoreOptionOverrideFile.parse(CoreOptionOverrideFile.serialise(many));
        expectEquals(CoreOptionOverrideFile.MAX_ENTRIES, reparsed.size());
        expect(!reparsed.containsKey("bad key"));
        expect(!reparsed.containsKey("empty"));

        // An oversized file on disk reads as empty rather than being parsed.
        File root = File.createTempFile("lucent-overrides-big", "");
        expect(root.delete());
        expect(root.mkdirs());
        File big = CoreOptionOverrideFile.in(root);
        FileOutputStream output = new FileOutputStream(big);
        try {
            byte[] line = "k=v\n".getBytes(StandardCharsets.UTF_8);
            for (int written = 0; written <= CoreOptionOverrideFile.MAX_FILE_BYTES;
                    written += line.length)
                output.write(line);
        } finally {
            output.close();
        }
        expect(CoreOptionOverrideFile.read(big).isEmpty());
        cleanup(root);

        StringBuilder longKey = new StringBuilder();
        for (int index = 0; index <= CoreOptionOverrideFile.MAX_KEY_LENGTH; index++)
            longKey.append('k');
        expect(!CoreOptionOverrideFile.isValidKey(longKey.toString()));
        expect(CoreOptionOverrideFile.isValidKey("mupen64plus-169screensize"));
        expect(CoreOptionOverrideFile.isValidKey("swanstation_GPU_WidescreenHack"));
        expect(!CoreOptionOverrideFile.isValidKey("a/b"));
        expect(!CoreOptionOverrideFile.isValidValue("line\nbreak"));
        expect(CoreOptionOverrideFile.isValidValue("Auto 4:3/3:2"));
    }

    private static void cleanup(File root) {
        File[] children = root.listFiles();
        if (children != null)
            for (File child : children) cleanup(child);
        root.delete();
    }

    private static void expect(boolean condition) {
        if (!condition) throw new AssertionError("expectation failed");
    }

    private static void expectEquals(Object expected, Object actual) {
        if (expected == null ? actual != null : !expected.equals(actual))
            throw new AssertionError("expected=" + expected + " actual=" + actual);
    }
}
