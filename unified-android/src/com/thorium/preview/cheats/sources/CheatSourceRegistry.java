package com.thorium.preview.cheats.sources;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * The cheat sources per system (design: docs/cheats-everywhere-and-widescreen-design.md §2).
 *
 * <p>Every source here is fetched to the owner's device on the owner's request
 * and is never bundled or redistributed by EmuFusion; the mirrored table in
 * {@code engines/cheats/sources.json} ("deviceFetched") records the same ids,
 * licences and URLs for review. Each source can be switched off in
 * {@code files/cheats/sources.json}; all are on by default.
 */
public final class CheatSourceRegistry {
    public static final String PREFERENCES_FILE = "sources.json";
    private static final long MIB = 1024L * 1024L;

    public static final String LIBRETRO = "libretro-database";
    public static final String MUPEN64PLUS = "mupen64plus-cheats";
    public static final String PROJECT64 = "project64-cheats";
    public static final String DUCKSTATION = "duckstation-chtdb";
    public static final String PCSX2_PATCHES = "pcsx2-patches";
    public static final String PCSX2_CHEATS = "pcsx2-cheats-collection";
    public static final String CWCHEAT = "cwcheat-database-plus";
    public static final String RC24_GECKO = "rc24-gecko-codes";
    public static final String CEMU_PACKS = "cemu-graphic-packs";
    public static final String SHARKIVE_3DS = "sharkive-3ds";
    public static final String SWITCH_CHEATS_DB = "switch-cheats-db";
    public static final String SHARKIVE_SWITCH = "sharkive-switch";
    public static final String RPCS3_PATCHES = "rpcs3-patches";
    public static final String ARTEMIS_RPCS3 = "artemis-rpcs3-patches";
    public static final String DREAMCAST_MD = "bucanero-dreamcast-cheats";
    public static final String FBNEO = "fbneo-cheats";
    public static final String MAME = "mame-cheats-spludlow";

    private static final List<CheatSource> SOURCES;
    private static final Map<String, CheatSource> BY_ID;

    static {
        List<CheatSource> table = new ArrayList<>();
        table.add(new CheatSource(LIBRETRO, "Libretro Database cheats",
                "https://buildbot.libretro.com/assets/frontend/cheats.zip", "",
                "CC-BY-SA-4.0", "title", "retroarch-cht",
                "nes snes gb gbc gba megadrive mastersystem gamegear sg1000 msx atari2600 atari5200 "
                        + "atari7800 atari800 pcengine pcenginecd saturn segacd sega32x jaguar "
                        + "colecovision intellivision n64 psx psp nds dreamcast zxspectrum dos "
                        + "arcade neogeo",
                false, true, 128L * MIB));
        table.add(new CheatSource(MUPEN64PLUS, "Mupen64Plus mupencheat.txt",
                "https://raw.githubusercontent.com/mupen64plus/mupen64plus-core/master/data/mupencheat.txt",
                "", "GPL-2.0", "n64-crc", "mupencheat", "n64", false, false, 8L * MIB));
        table.add(new CheatSource(PROJECT64, "Project64 Config/Cheats",
                "https://raw.githubusercontent.com/project64/project64/develop/Config/Cheats/<FILE>",
                "https://api.github.com/repos/project64/project64/contents/Config/Cheats",
                "GPL-2.0", "n64-crc", "project64-cht", "n64", true, false, 4L * MIB));
        table.add(new CheatSource(DUCKSTATION, "DuckStation chtdb",
                "https://github.com/duckstation/chtdb/releases/download/latest/cheats.zip", "",
                "per-author (repository scripts MIT)", "serial", "duckstation-cht", "psx",
                false, false, 32L * MIB));
        table.add(new CheatSource(PCSX2_PATCHES, "PCSX2 patches (widescreen, fixes)",
                "https://github.com/PCSX2/pcsx2_patches/releases/download/latest/patches.zip", "",
                "undeclared", "serial-crc", "pnach", "ps2", false, false, 32L * MIB));
        table.add(new CheatSource(PCSX2_CHEATS, "PCSX2 cheats collection (xs1l3n7x)",
                "https://api.github.com/repos/xs1l3n7x/pcsx2_cheats_collection/zipball", "",
                "undeclared", "crc", "pnach", "ps2", false, false, 48L * MIB));
        table.add(new CheatSource(CWCHEAT, "CWCheat Database Plus",
                "https://raw.githubusercontent.com/Saramagrean/CWCheat-Database-Plus-/master/cheat.db",
                "", "undeclared", "serial", "cwcheat", "psp", false, false, 32L * MIB));
        table.add(new CheatSource(RC24_GECKO, "GameHacking.org GC/Wii mirror (codes.rc24.xyz)",
                "https://codes.rc24.xyz/txt.php?txt=<GAMEID>", "",
                "per-author (GameHacking.org)", "game-id", "gecko-txt", "gamecube wii",
                true, false, 4L * MIB));
        table.add(new CheatSource(CEMU_PACKS, "Cemu community graphic packs",
                "https://api.github.com/repos/cemu-project/cemu_graphic_packs/releases/latest", "",
                "CC0-1.0", "title-id", "cemu-graphic-pack", "wiiu", false, false, 32L * MIB));
        table.add(new CheatSource(SHARKIVE_3DS, "FlagBrew Sharkive (3DS)",
                "https://github.com/FlagBrew/Sharkive/releases/latest/download/3ds.json", "",
                "GPL-3.0", "title-id", "gateway", "3ds", false, false, 32L * MIB));
        table.add(new CheatSource(SWITCH_CHEATS_DB, "switch-cheats-db (HamletDuFromage)",
                "https://github.com/HamletDuFromage/switch-cheats-db/releases/latest/download/contents_complete.zip",
                "https://raw.githubusercontent.com/HamletDuFromage/switch-cheats-db/master/versions.json",
                "undeclared", "title-id+build-id", "dmnt", "switch", false, false, 64L * MIB));
        table.add(new CheatSource(SHARKIVE_SWITCH, "FlagBrew Sharkive (Switch)",
                "https://github.com/FlagBrew/Sharkive/releases/latest/download/switch.json", "",
                "GPL-3.0", "title-id+build-id", "dmnt", "switch", false, false, 32L * MIB));
        table.add(new CheatSource(RPCS3_PATCHES, "RPCS3 patch feed",
                "https://rpcs3.net/compatibility?patch&api=v1&v=1.2", "",
                "GPL-2.0", "serial", "rpcs3-patch-yaml", "ps3", false, false, 16L * MIB));
        table.add(new CheatSource(ARTEMIS_RPCS3, "Artemis patch collection for RPCS3",
                "https://api.github.com/repos/chidreams/Artemis-Patch-Collection-RPCS3/contents/imported_patch.yml",
                "", "MIT", "serial", "rpcs3-patch-yaml", "ps3", false, false, 16L * MIB));
        table.add(new CheatSource(DREAMCAST_MD, "bucanero dreamcast-cheats",
                "https://api.github.com/repos/bucanero/dreamcast-cheats/zipball", "",
                "GPL-3.0", "title", "dreamcast-markdown", "dreamcast", false, false, 16L * MIB));
        table.add(new CheatSource(FBNEO, "FBNeo cheats",
                "https://api.github.com/repos/finalburnneo/FBNeo-cheats/zipball", "",
                "undeclared", "romset", "fbneo-ini", "arcade neogeo", false, false, 32L * MIB));
        table.add(new CheatSource(MAME, "Pugsy's MAME cheats (spludlow mirror)",
                "https://mame.spludlow.co.uk/data/mame-cheats/<VERSION>.zip",
                "https://mame.spludlow.co.uk/data/mame-cheats/latest.txt",
                "freeware (Pugsy's MAME cheat collection)", "romset", "mame-xml",
                "arcade neogeo", false, false, 64L * MIB));
        SOURCES = Collections.unmodifiableList(table);
        Map<String, CheatSource> byId = new LinkedHashMap<>();
        for (CheatSource source : table) byId.put(source.id, source);
        BY_ID = Collections.unmodifiableMap(byId);
    }

    private CheatSourceRegistry() {}

    public static List<CheatSource> all() { return SOURCES; }

    public static CheatSource byId(String id) { return id == null ? null : BY_ID.get(id); }

    /** Sources covering the system, in precedence order (earlier rows win deduplication). */
    public static List<CheatSource> forSystem(String canonicalSystem) {
        List<CheatSource> result = new ArrayList<>();
        for (CheatSource source : SOURCES) if (source.covers(canonicalSystem)) result.add(source);
        return Collections.unmodifiableList(result);
    }

    /** The preference file: {@code files/cheats/sources.json}. */
    public static File preferencesFile(File cheatDirectory) {
        return new File(cheatDirectory, PREFERENCES_FILE);
    }

    /** A source is on unless the preference file switches it off. */
    public static boolean enabled(File preferences, CheatSource source) {
        if (source == null) return false;
        Map<String, Boolean> overrides = readPreferences(preferences);
        Boolean value = overrides.get(source.id);
        return value == null ? source.enabledByDefault : value;
    }

    public static List<CheatSource> enabledForSystem(File preferences, String canonicalSystem) {
        Map<String, Boolean> overrides = readPreferences(preferences);
        List<CheatSource> result = new ArrayList<>();
        for (CheatSource source : forSystem(canonicalSystem)) {
            Boolean value = overrides.get(source.id);
            if (value == null ? source.enabledByDefault : value) result.add(source);
        }
        return Collections.unmodifiableList(result);
    }

    /**
     * Reads {@code {"schemaVersion":1,"sources":{"<id>":{"enabled":false}}}};
     * a {@code "disabled":["<id>"]} list is accepted too. Corruption reads as
     * "no overrides".
     */
    public static Map<String, Boolean> readPreferences(File preferences) {
        Map<String, Boolean> result = new LinkedHashMap<>();
        if (preferences == null || !preferences.isFile() || preferences.length() > 1024L * 1024L)
            return result;
        String text;
        try (InputStream input = new FileInputStream(preferences)) {
            text = DownloadedCheatCodec.readAll(input, 1024L * 1024L);
        } catch (IOException unreadable) {
            return result;
        }
        Map<String, Object> root = JsonLite.parseObject(text);
        for (Map.Entry<String, Object> entry : JsonLite.object(root.get("sources")).entrySet()) {
            Object value = entry.getValue();
            if (value instanceof Map) {
                Object enabled = JsonLite.object(value).get("enabled");
                if (enabled != null) result.put(entry.getKey(), JsonLite.bool(enabled, true));
            } else if (value != null) {
                result.put(entry.getKey(), JsonLite.bool(value, true));
            }
        }
        for (Object id : JsonLite.array(root.get("disabled")))
            result.put(JsonLite.string(id), Boolean.FALSE);
        return result;
    }

    /** Persists one switch, keeping the other entries; atomic. */
    public static void setEnabled(File preferences, String sourceId, boolean enabled)
            throws IOException {
        if (preferences == null || sourceId == null || sourceId.isEmpty())
            throw new IOException("preference target required");
        Map<String, Boolean> overrides = readPreferences(preferences);
        overrides.put(sourceId, enabled);
        Map<String, Object> root = new LinkedHashMap<>();
        root.put("schemaVersion", 1L);
        Map<String, Object> sources = new LinkedHashMap<>();
        for (Map.Entry<String, Boolean> entry : overrides.entrySet()) {
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("enabled", entry.getValue());
            sources.put(entry.getKey(), row);
        }
        root.put("sources", sources);
        File parent = preferences.getParentFile();
        if (parent != null && !parent.isDirectory()) parent.mkdirs();
        File part = new File(preferences.getAbsolutePath() + ".part");
        try (FileOutputStream out = new FileOutputStream(part)) {
            out.write(JsonLite.write(root).getBytes(StandardCharsets.UTF_8));
            out.getFD().sync();
        }
        if (preferences.exists()) preferences.delete();
        if (!part.renameTo(preferences)) throw new IOException("cannot write " + preferences);
    }

    /** Status as a JSON string for a control-plane listing. */
    public static String describe(File preferences) {
        Map<String, Boolean> overrides = readPreferences(preferences);
        List<Object> rows = new ArrayList<>();
        for (CheatSource source : SOURCES) {
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("id", source.id);
            row.put("name", source.name);
            row.put("license", source.license);
            row.put("systems", new ArrayList<Object>(source.systems));
            Boolean value = overrides.get(source.id);
            row.put("enabled", value == null ? source.enabledByDefault : value);
            row.put("bundled", source.bundled);
            row.put("redistribution", source.redistribution);
            rows.add(row);
        }
        Map<String, Object> root = new LinkedHashMap<>();
        root.put("ok", Boolean.TRUE);
        root.put("sources", rows);
        return JsonLite.write(root);
    }
}
