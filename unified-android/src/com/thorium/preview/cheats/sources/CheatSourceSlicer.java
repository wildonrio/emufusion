package com.thorium.preview.cheats.sources;

import com.thorium.lucent.cheats.Cheat;
import com.thorium.lucent.cheats.CheatDatabase;
import com.thorium.preview.cheats.CheatArchive;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.Enumeration;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;

/**
 * Slices one game's rows out of each source's bulk download.
 *
 * <p>Archives are read through {@link ZipFile} without expansion; entry
 * names are validated, entry sizes bounded, and everything the parsers see
 * is text. A source that cannot be fetched, does not know the game, or
 * carries nothing usable simply contributes no rows. Delivery is decided per
 * system (design §5): {@code live} for the cores with a working
 * {@code retro_cheat_set}, {@code boot} for the engines fed by files before
 * launch, {@code unsupported} otherwise.
 */
public final class CheatSourceSlicer {
    static final long MAX_ENTRY_BYTES = 8L * 1024L * 1024L;
    static final long MAX_PACK_BYTES = 2L * 1024L * 1024L;
    static final int MAX_ENTRIES = 200_000;
    private static final Set<String> LIVE_SYSTEMS = new HashSet<>(Arrays.asList(
            "nes", "snes", "gb", "gbc", "gba", "mastersystem", "gamegear", "sg1000", "psx",
            "nds", "zxspectrum", "jaguar", "n64", "psp", "gamecube", "wii", "dreamcast"));
    // dreamcast/flycast's retro_cheat_set/reset are wired to a real GameShark
    // bridge (engines/patches/flycast-libretro-cheat-support.patch), and
    // CheatDelivery.LIVE_ENGINES plus PpssppGlesEngineSession.
    // supportsLiveCheats() now include "flycast" to match, so a dreamcast row
    // resolving to DELIVERY_LIVE here reflects what the running engine can
    // actually do.
    private static final Set<String> BOOT_SYSTEMS = new HashSet<>(Arrays.asList(
            "ps2", "3ds", "switch", "ps3", "wiiu"));
    private static final Pattern PNACH_NAME = Pattern.compile(
            "(?i)^(?:([A-Z]{4}[-_]?[0-9]{5})_)?([0-9A-F]{8})\\.pnach$");
    private static final Pattern DUCKSTATION_NAME = Pattern.compile(
            "(?i)^([A-Z]{4}[-_]?[0-9]{5})(?:-[0-9A-F]{8,16})?\\.cht$");
    private static final Pattern SWITCH_ENTRY = Pattern.compile(
            "(?i)(?:^|/)contents/([0-9A-F]{16})/cheats/([0-9A-F]{16})\\.txt$");
    private static final Pattern MAME_VERSION = Pattern.compile("([0-9]{3,4})");

    private static final Map<String, Object> PARSE_MEMO = new LinkedHashMap<String, Object>(8, 0.75f, true) {
        @Override protected boolean removeEldestEntry(Map.Entry<String, Object> eldest) { return size() > 6; }
    };

    private final CheatFetch fetch;
    private final File libretroArchive;

    public CheatSourceSlicer(CheatFetch fetch, File libretroArchive) {
        this.fetch = fetch;
        this.libretroArchive = libretroArchive;
    }

    public static String deliveryFor(String canonicalSystem) {
        if (LIVE_SYSTEMS.contains(canonicalSystem)) return DownloadedCheat.DELIVERY_LIVE;
        if (BOOT_SYSTEMS.contains(canonicalSystem)) return DownloadedCheat.DELIVERY_BOOT;
        return DownloadedCheat.DELIVERY_UNSUPPORTED;
    }

    /**
     * @param identity mutable: sources may add what they learn (Switch build ids)
     * @param contentName the ROM file name with its extension and tags
     */
    public List<DownloadedCheat> slice(CheatSource source, String canonicalSystem,
                                       Map<String, String> identity, String title,
                                       String contentName, String originalName) {
        if (source == null || canonicalSystem == null) return Collections.emptyList();
        try {
            switch (source.id) {
                case CheatSourceRegistry.LIBRETRO: return libretro(source, canonicalSystem, identity, title, contentName, originalName);
                case CheatSourceRegistry.MUPEN64PLUS: return mupen(source, canonicalSystem, identity);
                case CheatSourceRegistry.PROJECT64: return project64(source, canonicalSystem, identity, title, contentName, originalName);
                case CheatSourceRegistry.DUCKSTATION: return duckstation(source, canonicalSystem, identity);
                case CheatSourceRegistry.PCSX2_PATCHES: return pcsx2Patches(source, canonicalSystem, identity);
                case CheatSourceRegistry.PCSX2_CHEATS: return pcsx2Cheats(source, canonicalSystem, identity);
                case CheatSourceRegistry.CWCHEAT: return cwcheat(source, canonicalSystem, identity);
                case CheatSourceRegistry.RC24_GECKO: return rc24(source, canonicalSystem, identity);
                case CheatSourceRegistry.CEMU_PACKS: return cemu(source, canonicalSystem, identity, title, contentName);
                case CheatSourceRegistry.SHARKIVE_3DS: return sharkive3ds(source, canonicalSystem, identity);
                case CheatSourceRegistry.SWITCH_CHEATS_DB: return switchCheatsDb(source, canonicalSystem, identity);
                case CheatSourceRegistry.SHARKIVE_SWITCH: return sharkiveSwitch(source, canonicalSystem, identity);
                case CheatSourceRegistry.RPCS3_PATCHES: return rpcs3(source, canonicalSystem, identity, true);
                case CheatSourceRegistry.ARTEMIS_RPCS3: return rpcs3(source, canonicalSystem, identity, false);
                case CheatSourceRegistry.DREAMCAST_MD: return dreamcast(source, canonicalSystem, identity, title, contentName, originalName);
                case CheatSourceRegistry.FBNEO: return fbneo(source, canonicalSystem, identity, contentName);
                case CheatSourceRegistry.MAME: return mame(source, canonicalSystem, identity, contentName);
                default: return Collections.emptyList();
            }
        } catch (IOException | RuntimeException failed) {
            return Collections.emptyList();
        }
    }

    // ---- per source ---------------------------------------------------------

    private List<DownloadedCheat> libretro(CheatSource source, String system, Map<String, String> identity,
                                           String title, String contentName, String originalName) {
        if (libretroArchive == null || !libretroArchive.isFile()) return Collections.emptyList();
        List<Cheat> rows = CheatArchive.forGame(libretroArchive, system, title, contentName);
        if (rows.isEmpty() && originalName != null && !originalName.isEmpty()
                && !originalName.equals(contentName))
            rows = CheatArchive.forGame(libretroArchive, system, CheatGameIdentity.stem(originalName), originalName);
        // Second pass: an exact CRC32 (cartridge) or CHD raw-data hash (disc)
        // match against the No-Intro/Redump DAT universe wins outright over
        // the filename heuristics above once they have both come up empty --
        // it resolves the same canonical title libretro's .cht files are
        // named after, so it feeds straight back into the same lookup.
        if (rows.isEmpty()) {
            String resolvedTitle = DiscDatIndex.resolveTitle(fetch, system, identity);
            if (!resolvedTitle.isEmpty())
                rows = CheatArchive.forGame(libretroArchive, system, resolvedTitle, resolvedTitle);
        }
        List<DownloadedCheat> result = new ArrayList<>();
        for (Cheat cheat : rows) {
            result.add(new DownloadedCheat(cheat, source.id, deliveryFor(system),
                    ParsedCheat.impliedTags(cheat.name), source.format));
        }
        return result;
    }

    private List<DownloadedCheat> mupen(CheatSource source, String system, Map<String, String> identity) {
        String key = identity.get("n64Key");
        if (key == null || key.isEmpty()) return Collections.emptyList();
        File file = fetch.fetch(source, source.url);
        if (file == null) return Collections.emptyList();
        @SuppressWarnings("unchecked")
        Map<String, MupenCheatParser.Game> games = (Map<String, MupenCheatParser.Game>) memo(file, "mupen");
        if (games == null) {
            String text = CheatSourceFetcher.readText(file, source.maxBytes);
            if (text == null) return Collections.emptyList();
            games = MupenCheatParser.parse(text);
            remember(file, "mupen", games);
        }
        MupenCheatParser.Game game = games.get(key.toUpperCase(Locale.US));
        if (game == null) return Collections.emptyList();
        return rows(source, system, game.cheats, source.name + " • " + key);
    }

    private List<DownloadedCheat> project64(CheatSource source, String system, Map<String, String> identity,
                                            String title, String contentName, String originalName) {
        String listing = fetchText(source, source.auxiliaryUrl);
        if (listing == null) return Collections.emptyList();
        String key = identity.get("n64Key");
        List<String> candidates = new ArrayList<>();
        for (Object row : JsonLite.array(parseJson(listing))) {
            Map<String, Object> entry = JsonLite.object(row);
            String name = JsonLite.string(entry.get("name"));
            if (!name.toLowerCase(Locale.US).endsWith(".cht")) continue;
            String fileStem = CheatGameIdentity.stem(name);
            if (CheatGameIdentity.sameTitle(fileStem, title) || CheatGameIdentity.sameTitle(fileStem, contentName)
                    || CheatGameIdentity.sameTitle(fileStem, originalName)
                    || looseTitleMatch(fileStem, title)) {
                candidates.add(name);
                if (candidates.size() >= 4) break;
            }
        }
        List<DownloadedCheat> result = new ArrayList<>();
        for (String name : candidates) {
            String url = source.url.replace("<FILE>", encodePath(name));
            String text = fetchText(source, url);
            if (text == null) continue;
            Project64ChtParser.Document document = Project64ChtParser.parse(text);
            if (key != null && !key.isEmpty() && !document.crc.isEmpty() && !document.crc.equalsIgnoreCase(key))
                continue;
            result.addAll(rows(source, system, document.cheats, source.name + " • " + name));
        }
        return result;
    }

    private List<DownloadedCheat> duckstation(CheatSource source, String system, Map<String, String> identity)
            throws IOException {
        String serial = CwCheatParser.normaliseSerial(identity.get("serial"));
        if (serial.isEmpty()) return Collections.emptyList();
        File zip = fetch.fetch(source, source.url);
        if (zip == null) return Collections.emptyList();
        List<DownloadedCheat> result = new ArrayList<>();
        try (ZipFile archive = new ZipFile(zip)) {
            for (ZipEntry entry : entries(archive)) {
                String base = baseName(entry.getName());
                Matcher match = DUCKSTATION_NAME.matcher(base);
                if (!match.matches() || !CwCheatParser.normaliseSerial(match.group(1)).equals(serial)) continue;
                String text = readEntry(archive, entry, MAX_ENTRY_BYTES);
                if (text == null) continue;
                result.addAll(rows(source, system, DuckStationChtParser.parse(text), source.name + " • " + base));
            }
        }
        return result;
    }

    private List<DownloadedCheat> pcsx2Patches(CheatSource source, String system, Map<String, String> identity)
            throws IOException {
        String serial = CwCheatParser.normaliseSerial(identity.get("serial"));
        String crc = upper(identity.get("crc"));
        if (serial.isEmpty() && crc.isEmpty()) return Collections.emptyList();
        File zip = fetch.fetch(source, source.url);
        if (zip == null) return Collections.emptyList();
        List<DownloadedCheat> result = new ArrayList<>();
        try (ZipFile archive = new ZipFile(zip)) {
            for (ZipEntry entry : entries(archive)) {
                String base = baseName(entry.getName());
                Matcher match = PNACH_NAME.matcher(base);
                if (!match.matches()) continue;
                String entrySerial = match.group(1) == null ? "" : CwCheatParser.normaliseSerial(match.group(1));
                String entryCrc = match.group(2).toUpperCase(Locale.US);
                boolean hit = !crc.isEmpty() ? entryCrc.equals(crc)
                        && (entrySerial.isEmpty() || serial.isEmpty() || entrySerial.equals(serial))
                        : !entrySerial.isEmpty() && entrySerial.equals(serial);
                if (!hit) continue;
                String text = readEntry(archive, entry, MAX_ENTRY_BYTES);
                if (text == null) continue;
                List<ParsedCheat> parsed = PnachParser.parse(text, "");
                List<String> extra = new ArrayList<>();
                extra.add("crc:" + entryCrc);
                result.addAll(rows(source, system, tagged(parsed, extra), source.name + " • " + base));
            }
        }
        return result;
    }

    private List<DownloadedCheat> pcsx2Cheats(CheatSource source, String system, Map<String, String> identity)
            throws IOException {
        String crc = upper(identity.get("crc"));
        String serial = CwCheatParser.normaliseSerial(identity.get("serial"));
        if (crc.isEmpty() && serial.isEmpty()) return Collections.emptyList();
        File zip = fetch.fetch(source, source.url);
        if (zip == null) return Collections.emptyList();
        List<DownloadedCheat> result = new ArrayList<>();
        try (ZipFile archive = new ZipFile(zip)) {
            for (ZipEntry entry : entries(archive)) {
                String base = baseName(entry.getName());
                Matcher match = PNACH_NAME.matcher(base);
                if (!match.matches()) continue;
                String entryCrc = match.group(2).toUpperCase(Locale.US);
                String entrySerial = match.group(1) == null ? "" : CwCheatParser.normaliseSerial(match.group(1));
                boolean hit = (!crc.isEmpty() && entryCrc.equals(crc))
                        || (crc.isEmpty() && !entrySerial.isEmpty() && entrySerial.equals(serial));
                if (!hit) continue;
                String text = readEntry(archive, entry, MAX_ENTRY_BYTES);
                if (text == null) continue;
                List<String> extra = new ArrayList<>();
                extra.add("crc:" + entryCrc);
                result.addAll(rows(source, system, tagged(PnachParser.parse(text, ""), extra),
                        source.name + " • " + base));
            }
        }
        return result;
    }

    private List<DownloadedCheat> cwcheat(CheatSource source, String system, Map<String, String> identity) {
        String serial = CwCheatParser.normaliseSerial(identity.get("serial"));
        if (serial.isEmpty()) return Collections.emptyList();
        File file = fetch.fetch(source, source.url);
        if (file == null) return Collections.emptyList();
        @SuppressWarnings("unchecked")
        Map<String, CwCheatParser.Game> games = (Map<String, CwCheatParser.Game>) memo(file, "cwcheat");
        if (games == null) {
            String text = CheatSourceFetcher.readText(file, source.maxBytes);
            if (text == null) return Collections.emptyList();
            games = CwCheatParser.parse(text);
            remember(file, "cwcheat", games);
        }
        CwCheatParser.Game game = games.get(serial);
        if (game == null) return Collections.emptyList();
        return rows(source, system, game.cheats, source.name + " • " + serial);
    }

    private List<DownloadedCheat> rc24(CheatSource source, String system, Map<String, String> identity) {
        String gameId = upper(identity.get("gameId"));
        if (!gameId.matches("[A-Z0-9]{6}")) return Collections.emptyList();
        String text = fetchText(source, source.url.replace("<GAMEID>", gameId));
        if (text == null || text.trim().isEmpty() || text.trim().startsWith("<")) return Collections.emptyList();
        GeckoTxtParser.Document document = GeckoTxtParser.parse(text);
        if (!document.gameId.isEmpty() && !document.gameId.equals(gameId)) return Collections.emptyList();
        return rows(source, system, document.cheats, source.name + " • " + gameId);
    }

    private List<DownloadedCheat> cemu(CheatSource source, String system, Map<String, String> identity,
                                       String title, String contentName) throws IOException {
        String titleId = upper(identity.get("titleId"));
        String assetUrl = latestGithubAsset(source, source.url, "(?i)^graphicPacks.*\\.zip$");
        if (assetUrl == null) return Collections.emptyList();
        File zip = fetch.fetch(source, assetUrl);
        if (zip == null) return Collections.emptyList();
        List<DownloadedCheat> result = new ArrayList<>();
        try (ZipFile archive = new ZipFile(zip)) {
            List<ZipEntry> all = entries(archive);
            for (ZipEntry entry : all) {
                if (!entry.getName().endsWith("/rules.txt")) continue;
                String rules = readEntry(archive, entry, 512L * 1024L);
                if (rules == null) continue;
                CemuGraphicPackParser.Pack pack = CemuGraphicPackParser.parseRules(rules);
                String directory = entry.getName().substring(0, entry.getName().length() - "/rules.txt".length());
                boolean hit = !titleId.isEmpty() ? CemuGraphicPackParser.covers(pack, titleId)
                        : packMatchesTitle(directory, pack, title, contentName);
                if (!hit) continue;
                Map<String, String> files = new TreeMap<>();
                files.put("rules.txt", rules);
                long total = rules.length();
                String prefix = directory + "/";
                for (ZipEntry sibling : all) {
                    if (sibling.isDirectory() || !sibling.getName().startsWith(prefix) || sibling == entry) continue;
                    String relative = sibling.getName().substring(prefix.length());
                    if (relative.contains("/") || !isTextName(relative)) continue;
                    if (total + sibling.getSize() > MAX_PACK_BYTES) break;
                    String body = readEntry(archive, sibling, 512L * 1024L);
                    if (body == null) continue;
                    files.put(relative, body);
                    total += body.length();
                }
                ParsedCheat parsed = CemuGraphicPackParser.toParsed(lastSegment(directory), pack, files);
                if (parsed == null) continue;
                result.addAll(rows(source, system, Collections.singletonList(parsed),
                        source.name + " • " + (pack.path.isEmpty() ? directory : pack.path)));
            }
        }
        return result;
    }

    private List<DownloadedCheat> sharkive3ds(CheatSource source, String system, Map<String, String> identity) {
        String titleId = upper(identity.get("titleId"));
        if (titleId.isEmpty()) return Collections.emptyList();
        String text = fetchText(source, source.url);
        if (text == null) return Collections.emptyList();
        return rows(source, system, SharkiveJsonParser.for3dsTitle(text, titleId), source.name + " • " + titleId);
    }

    private List<DownloadedCheat> switchCheatsDb(CheatSource source, String system, Map<String, String> identity)
            throws IOException {
        String titleId = upper(identity.get("titleId"));
        if (titleId.isEmpty()) return Collections.emptyList();
        String versions = fetchText(source, source.auxiliaryUrl);
        List<String> buildIds = versions == null ? new ArrayList<String>()
                : SwitchVersionsParser.buildIdsFor(versions, titleId);
        File zip = fetch.fetch(source, source.url);
        List<DownloadedCheat> result = new ArrayList<>();
        if (zip != null) {
            try (ZipFile archive = new ZipFile(zip)) {
                for (ZipEntry entry : entries(archive)) {
                    Matcher match = SWITCH_ENTRY.matcher(entry.getName());
                    if (!match.matches() || !match.group(1).equalsIgnoreCase(titleId)) continue;
                    String buildId = match.group(2).toUpperCase(Locale.US);
                    if (!buildIds.contains(buildId)) buildIds.add(buildId);
                    String text = readEntry(archive, entry, MAX_ENTRY_BYTES);
                    if (text == null) continue;
                    List<String> extra = new ArrayList<>();
                    extra.add("buildid:" + buildId);
                    result.addAll(rows(source, system, tagged(DmntCheatParser.parse(text), extra),
                            source.name + " • " + titleId + "/" + buildId));
                }
            }
        }
        mergeBuildIds(identity, buildIds);
        return result;
    }

    private List<DownloadedCheat> sharkiveSwitch(CheatSource source, String system, Map<String, String> identity) {
        String titleId = upper(identity.get("titleId"));
        if (titleId.isEmpty()) return Collections.emptyList();
        String text = fetchText(source, source.url);
        if (text == null) return Collections.emptyList();
        List<DownloadedCheat> result = new ArrayList<>();
        List<String> buildIds = new ArrayList<>();
        for (Map.Entry<String, List<ParsedCheat>> build : SharkiveJsonParser.forSwitchTitle(text, titleId).entrySet()) {
            buildIds.add(build.getKey());
            List<String> extra = new ArrayList<>();
            extra.add("buildid:" + build.getKey());
            result.addAll(rows(source, system, tagged(build.getValue(), extra),
                    source.name + " • " + titleId + "/" + build.getKey()));
        }
        mergeBuildIds(identity, buildIds);
        return result;
    }

    private List<DownloadedCheat> rpcs3(CheatSource source, String system, Map<String, String> identity,
                                        boolean apiEnvelope) {
        String serial = Rpcs3PatchYamlParser.normaliseSerial(identity.get("serial"));
        if (serial.isEmpty()) return Collections.emptyList();
        File file = fetch.fetch(source, source.url);
        if (file == null) return Collections.emptyList();
        @SuppressWarnings("unchecked")
        List<Rpcs3PatchYamlParser.Patch> patches = (List<Rpcs3PatchYamlParser.Patch>) memo(file, "rpcs3");
        if (patches == null) {
            String text = CheatSourceFetcher.readText(file, source.maxBytes);
            if (text == null) return Collections.emptyList();
            if (apiEnvelope) {
                Map<String, Object> envelope = JsonLite.parseObject(text);
                text = JsonLite.string(envelope.get("patch"));
            }
            patches = Rpcs3PatchYamlParser.parse(text);
            remember(file, "rpcs3", patches);
        }
        List<ParsedCheat> parsed = new ArrayList<>();
        for (Rpcs3PatchYamlParser.Patch patch : patches)
            if (patch.serials.containsKey(serial)) parsed.add(Rpcs3PatchYamlParser.toParsed(patch, serial));
        return rows(source, system, parsed, source.name + " • " + serial);
    }

    private List<DownloadedCheat> dreamcast(CheatSource source, String system, Map<String, String> identity,
                                            String title, String contentName, String originalName) throws IOException {
        File zip = fetch.fetch(source, source.url);
        if (zip == null) return Collections.emptyList();
        List<DownloadedCheat> result = new ArrayList<>();
        try (ZipFile archive = new ZipFile(zip)) {
            for (ZipEntry entry : entries(archive)) {
                String base = baseName(entry.getName());
                if (!base.toLowerCase(Locale.US).endsWith(".md")) continue;
                String slug = CheatGameIdentity.stem(base).replace('-', ' ').replace('_', ' ');
                if (!(CheatGameIdentity.sameTitle(slug, title) || CheatGameIdentity.sameTitle(slug, contentName)
                        || CheatGameIdentity.sameTitle(slug, originalName) || looseTitleMatch(slug, title)))
                    continue;
                String text = readEntry(archive, entry, MAX_ENTRY_BYTES);
                if (text == null) continue;
                DreamcastMarkdownParser.Document document = DreamcastMarkdownParser.parse(text);
                result.addAll(rows(source, system, document.cheats, source.name + " • " + base));
            }
        }
        return result;
    }

    private List<DownloadedCheat> fbneo(CheatSource source, String system, Map<String, String> identity,
                                        String contentName) throws IOException {
        String romset = romset(identity, contentName);
        if (romset.isEmpty()) return Collections.emptyList();
        File zip = fetch.fetch(source, source.url);
        if (zip == null) return Collections.emptyList();
        try (ZipFile archive = new ZipFile(zip)) {
            for (ZipEntry entry : entries(archive)) {
                String base = baseName(entry.getName());
                if (!base.equalsIgnoreCase(romset + ".ini")) continue;
                String text = readEntry(archive, entry, MAX_ENTRY_BYTES);
                if (text == null) continue;
                return rows(source, system, FbNeoIniParser.parse(text), source.name + " • " + base);
            }
        }
        return Collections.emptyList();
    }

    private List<DownloadedCheat> mame(CheatSource source, String system, Map<String, String> identity,
                                       String contentName) throws IOException {
        String romset = romset(identity, contentName);
        if (romset.isEmpty()) return Collections.emptyList();
        String latest = fetchText(source, source.auxiliaryUrl);
        if (latest == null) return Collections.emptyList();
        Matcher version = MAME_VERSION.matcher(latest.trim());
        if (!version.find()) return Collections.emptyList();
        File zip = fetch.fetch(source, source.url.replace("<VERSION>", version.group(1)));
        if (zip == null) return Collections.emptyList();
        try (ZipFile archive = new ZipFile(zip)) {
            for (ZipEntry entry : entries(archive)) {
                String base = baseName(entry.getName());
                if (!base.equalsIgnoreCase(romset + ".xml")) continue;
                String text = readEntry(archive, entry, MAX_ENTRY_BYTES);
                if (text == null) continue;
                return rows(source, system, MameCheatXmlParser.parse(text), source.name + " • " + base);
            }
        }
        return Collections.emptyList();
    }

    // ---- shared ---------------------------------------------------------------

    private static List<DownloadedCheat> rows(CheatSource source, String system, List<ParsedCheat> parsed,
                                              String provenance) {
        List<DownloadedCheat> result = new ArrayList<>();
        String delivery = deliveryFor(system);
        LinkedHashMap<String, DownloadedCheat> unique = new LinkedHashMap<>();
        for (ParsedCheat cheat : parsed) {
            if (cheat == null || cheat.code.isEmpty()) continue;
            String id = CheatIdFactory.id(prefixFor(source.id), system, cheat.code);
            if (unique.containsKey(id)) continue;
            String description = cheat.description.isEmpty() ? provenance : provenance + " • " + cheat.description;
            try {
                unique.put(id, new DownloadedCheat(new Cheat(id, cheat.name, description, cheat.code),
                        source.id, delivery, cheat.tags, source.format));
            } catch (IllegalArgumentException unusable) {
                // skip
            }
            if (unique.size() >= CodeText.MAX_CHEATS_PER_GAME) break;
        }
        result.addAll(unique.values());
        return result;
    }

    /** "libretro-database" rows keep {@code CheatArchive}'s "libretro-" prefix so ids agree. */
    static String prefixFor(String sourceId) {
        return CheatSourceRegistry.LIBRETRO.equals(sourceId) ? "libretro" : sourceId;
    }

    private static List<ParsedCheat> tagged(List<ParsedCheat> parsed, List<String> extra) {
        List<ParsedCheat> result = new ArrayList<>(parsed.size());
        for (ParsedCheat cheat : parsed) result.add(cheat.withTags(extra));
        return result;
    }

    private static void mergeBuildIds(Map<String, String> identity, List<String> buildIds) {
        if (identity == null || buildIds.isEmpty()) return;
        List<String> merged = CheatGameIdentity.split(identity.get("buildIds"));
        for (String id : buildIds) if (!merged.contains(id)) merged.add(id);
        StringBuilder out = new StringBuilder();
        for (String id : merged) { if (out.length() > 0) out.append(','); out.append(id); }
        identity.put("buildIds", out.toString());
    }

    private static String romset(Map<String, String> identity, String contentName) {
        String romset = identity.get("romset");
        if (romset == null || romset.isEmpty()) romset = CheatGameIdentity.stem(contentName);
        return romset == null ? "" : romset.trim().toLowerCase(Locale.US);
    }

    private static boolean packMatchesTitle(String directory, CemuGraphicPackParser.Pack pack,
                                            String title, String contentName) {
        String[] parts = directory.split("/");
        String game = parts.length >= 3 ? parts[parts.length - 3] : parts[0];
        String pathGame = pack.path.replace("\\", "/").split("/")[0];
        return CheatGameIdentity.sameTitle(game, title) || CheatGameIdentity.sameTitle(pathGame, title)
                || CheatGameIdentity.sameTitle(game, contentName) || looseTitleMatch(pathGame, title);
    }

    /** "Zelda - Breath of the Wild" vs "The Legend of Zelda: Breath of the Wild" style tolerance. */
    static boolean looseTitleMatch(String candidate, String title) {
        String a = CheatDatabase.normalise(candidate);
        String b = CheatDatabase.normalise(title);
        if (a.isEmpty() || b.isEmpty()) return false;
        if (a.equals(b)) return true;
        String shorter = a.length() < b.length() ? a : b;
        String longer = a.length() < b.length() ? b : a;
        return shorter.length() >= 8 && longer.startsWith(shorter);
    }

    private String fetchText(CheatSource source, String url) {
        if (url == null || url.isEmpty()) return null;
        File file = fetch.fetch(source, url);
        return file == null ? null : CheatSourceFetcher.readText(file, source.maxBytes);
    }

    /** Resolves a GitHub "releases/latest" API document to the asset matching {@code pattern}. */
    private String latestGithubAsset(CheatSource source, String apiUrl, String pattern) {
        String json = fetchText(source, apiUrl);
        if (json == null) return null;
        Map<String, Object> release = JsonLite.parseObject(json);
        for (Object asset : JsonLite.array(release.get("assets"))) {
            Map<String, Object> row = JsonLite.object(asset);
            String name = JsonLite.string(row.get("name"));
            String url = JsonLite.string(row.get("browser_download_url"));
            if (name.matches(pattern) && url.startsWith("https://")) return url;
        }
        return null;
    }

    private static Object parseJson(String text) {
        try { return JsonLite.parse(text); } catch (RuntimeException malformed) { return null; }
    }

    static List<ZipEntry> entries(ZipFile archive) throws IOException {
        List<ZipEntry> result = new ArrayList<>();
        Enumeration<? extends ZipEntry> values = archive.entries();
        while (values.hasMoreElements()) {
            ZipEntry entry = values.nextElement();
            if (result.size() >= MAX_ENTRIES) throw new IOException("too many archive entries");
            if (!safeEntryName(entry.getName())) throw new IOException("unsafe archive entry");
            if (!entry.isDirectory()) result.add(entry);
        }
        return result;
    }

    static String readEntry(ZipFile archive, ZipEntry entry, long cap) throws IOException {
        if (entry.getSize() > cap) return null;
        try (InputStream input = archive.getInputStream(entry);
             ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[16 * 1024];
            long total = 0;
            int read;
            while ((read = input.read(buffer)) >= 0) {
                total += read;
                if (total > cap) return null;
                output.write(buffer, 0, read);
            }
            return new String(output.toByteArray(), StandardCharsets.UTF_8);
        }
    }

    static boolean safeEntryName(String name) {
        return name != null && !name.isEmpty() && !name.startsWith("/") && !name.startsWith("\\")
                && !name.contains("../") && !name.contains("..\\") && !name.contains(":")
                && name.indexOf('\0') < 0;
    }

    private static boolean isTextName(String name) {
        String lower = name.toLowerCase(Locale.US);
        return lower.endsWith(".txt") || lower.endsWith(".asm") || lower.endsWith(".ini")
                || lower.endsWith(".md") || lower.endsWith(".glsl");
    }

    private static String baseName(String path) {
        int slash = path.lastIndexOf('/');
        return slash < 0 ? path : path.substring(slash + 1);
    }

    private static String lastSegment(String path) { return baseName(path); }

    private static String upper(String value) {
        return value == null ? "" : value.trim().toUpperCase(Locale.US);
    }

    private static String encodePath(String name) {
        StringBuilder out = new StringBuilder();
        for (byte b : name.getBytes(StandardCharsets.UTF_8)) {
            int ch = b & 0xff;
            if ((ch >= 'A' && ch <= 'Z') || (ch >= 'a' && ch <= 'z') || (ch >= '0' && ch <= '9')
                    || ch == '-' || ch == '_' || ch == '.' || ch == '~')
                out.append((char) ch);
            else out.append(String.format(Locale.US, "%%%02X", ch));
        }
        return out.toString();
    }

    private static Object memo(File file, String kind) {
        synchronized (PARSE_MEMO) { return PARSE_MEMO.get(memoKey(file, kind)); }
    }

    private static void remember(File file, String kind, Object value) {
        synchronized (PARSE_MEMO) { PARSE_MEMO.put(memoKey(file, kind), value); }
    }

    private static String memoKey(File file, String kind) {
        return kind + "|" + file.getAbsolutePath() + "|" + file.length() + "|" + file.lastModified();
    }
}
