package com.thorium.preview.cheats.sources;

import java.io.File;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Resolves a canonical No-Intro/Redump title for a game's CRC32 (cartridge
 * dumps) or CHD raw-data hash (disc dumps), for use as a second, exact
 * matching pass in {@link CheatSourceSlicer} when normalised-title matching
 * against {@link CheatArchive} finds nothing.
 *
 * <p>Why DAT files over a bundled/best-effort crc-to-title table: the
 * libretro-database repository publishes the actual No-Intro and Redump DAT
 * XML per system (verified reachable at
 * {@code github.com/libretro/libretro-database/tree/master/metadat/{no-intro,redump}}
 * -- small text files, tens of KB to a few MB even for PS2/PS3), which is
 * exactly the canonical-name universe the {@code .cht} files themselves are
 * named after. Fetching the authoritative DAT and doing an exact
 * crc/md5/sha1 lookup is strictly more robust than hand-maintaining (or
 * periodically re-scraping) a separate crc-to-title table: it never drifts
 * from upstream, it is licensed the same permissive way the community
 * already treats these catalogs for personal/non-commercial cataloguing use,
 * and the fetch/cache/bounds machinery ({@link CheatSourceFetcher}) already
 * exists for exactly this shape of download. It also degrades identically to
 * every other source here: unreachable network, an absent DAT for an
 * uncommon system, or no entry for this dump all simply mean "no extra
 * title", never a failure the caller has to handle specially.
 */
public final class DiscDatIndex {
    private static final String NO_INTRO_BASE =
            "https://raw.githubusercontent.com/libretro/libretro-database/master/metadat/no-intro/";
    private static final String REDUMP_BASE =
            "https://raw.githubusercontent.com/libretro/libretro-database/master/metadat/redump/";
    private static final long MAX_DAT_BYTES = 8L * 1024L * 1024L;

    /** A source id/cache bucket for the DAT fetches; never shown in the sources toggle UI. */
    private static final CheatSource PSEUDO_SOURCE = new CheatSource(
            "disc-dat-index", "No-Intro/Redump DAT identity index (internal)",
            NO_INTRO_BASE, "", "No-Intro/Redump (community cataloguing database)",
            "crc-or-hash", "logiqx-dat", "internal", false, false, MAX_DAT_BYTES);

    /** canonical system -> No-Intro DAT filename, whole-file CRC32 keyed (single-file cart dumps). */
    static final Map<String, String> NO_INTRO_FILES;
    /** canonical system -> Redump DAT filename, per-track md5/sha1 keyed (single-track disc dumps). */
    static final Map<String, String> REDUMP_FILES;

    static {
        Map<String, String> noIntro = new LinkedHashMap<>();
        noIntro.put("nes", "Nintendo - Nintendo Entertainment System.dat");
        noIntro.put("snes", "Nintendo - Super Nintendo Entertainment System.dat");
        noIntro.put("gb", "Nintendo - Game Boy.dat");
        noIntro.put("gbc", "Nintendo - Game Boy Color.dat");
        noIntro.put("gba", "Nintendo - Game Boy Advance.dat");
        noIntro.put("megadrive", "Sega - Mega Drive - Genesis.dat");
        noIntro.put("mastersystem", "Sega - Master System - Mark III.dat");
        noIntro.put("gamegear", "Sega - Game Gear.dat");
        noIntro.put("sg1000", "Sega - SG-1000.dat");
        noIntro.put("atari2600", "Atari - 2600.dat");
        noIntro.put("atari5200", "Atari - 5200.dat");
        noIntro.put("atari7800", "Atari - 7800.dat");
        noIntro.put("atari800", "Atari - 8-bit Family.dat");
        noIntro.put("pcengine", "NEC - PC Engine - TurboGrafx 16.dat");
        noIntro.put("jaguar", "Atari - Jaguar.dat");
        noIntro.put("n64", "Nintendo - Nintendo 64.dat");
        noIntro.put("nds", "Nintendo - Nintendo DS.dat");
        noIntro.put("msx", "Microsoft - MSX.dat");
        noIntro.put("colecovision", "Coleco - ColecoVision.dat");
        noIntro.put("intellivision", "Mattel - Intellivision.dat");
        NO_INTRO_FILES = Collections.unmodifiableMap(noIntro);

        Map<String, String> redump = new LinkedHashMap<>();
        redump.put("psx", "Sony - PlayStation.dat");
        redump.put("ps2", "Sony - PlayStation 2.dat");
        redump.put("dreamcast", "Sega - Dreamcast.dat");
        redump.put("segacd", "Sega - Mega-CD - Sega CD.dat");
        redump.put("pcenginecd", "NEC - PC Engine CD - TurboGrafx-CD.dat");
        redump.put("saturn", "Sega - Saturn.dat");
        redump.put("neogeocd", "SNK - Neo Geo CD.dat");
        redump.put("3do", "The 3DO Company - 3DO.dat");
        redump.put("amigacd32", "Commodore - CD32.dat");
        REDUMP_FILES = Collections.unmodifiableMap(redump);
    }

    // <game name="...">                              (opening tag, name may contain XML entities)
    private static final Pattern GAME_OPEN = Pattern.compile("<game\\s+name=\"([^\"]*)\"");
    // <rom name="..." size="..." crc="..." md5="..." sha1="..." .../>  (attribute order is not fixed)
    private static final Pattern ROM_TAG = Pattern.compile("<rom\\b([^>]*)/?>");
    private static final Pattern ATTR = Pattern.compile("(\\w+)=\"([^\"]*)\"");

    /** file identity ("no-intro:<system>" etc.) -> parsed hash-to-title table; small, bounded by system count. */
    private static final Map<String, Map<String, String>> MEMO =
            new LinkedHashMap<String, Map<String, String>>(16, 0.75f, true) {
                @Override protected boolean removeEldestEntry(Map.Entry<String, Map<String, String>> eldest) {
                    return size() > 24;
                }
            };

    private DiscDatIndex() {}

    /**
     * Resolves a No-Intro/Redump title from whatever exact identity the caller
     * already established (CRC32 for a cartridge dump, CHD raw-data hash for
     * a disc dump); "" when the system has no DAT here, the DAT could not be
     * fetched, or nothing in it matches. Never throws.
     */
    public static String resolveTitle(CheatFetch fetch, String canonicalSystem, Map<String, String> identity) {
        if (fetch == null || canonicalSystem == null || identity == null) return "";
        String crc = identity.get("romCrc32");
        if (crc != null && !crc.isEmpty()) {
            String title = lookupNoIntro(fetch, canonicalSystem, crc.trim().toUpperCase(Locale.US));
            if (!title.isEmpty()) return title;
        }
        String discHash = identity.get("chdRawHash");
        if (discHash != null && !discHash.isEmpty()) {
            String title = lookupRedump(fetch, canonicalSystem, discHash.trim().toUpperCase(Locale.US));
            if (!title.isEmpty()) return title;
        }
        return "";
    }

    /** The exact URL a system's No-Intro DAT would be fetched from; "" when this system has none. */
    static String noIntroUrl(String canonicalSystem) {
        String file = NO_INTRO_FILES.get(canonicalSystem);
        return file == null ? "" : NO_INTRO_BASE + encode(file);
    }

    /** The exact URL a system's Redump DAT would be fetched from; "" when this system has none. */
    static String redumpUrl(String canonicalSystem) {
        String file = REDUMP_FILES.get(canonicalSystem);
        return file == null ? "" : REDUMP_BASE + encode(file);
    }

    static String lookupNoIntro(CheatFetch fetch, String canonicalSystem, String crcUpper) {
        String file = NO_INTRO_FILES.get(canonicalSystem);
        if (file == null || crcUpper == null || crcUpper.length() != 8) return "";
        Map<String, String> table = table(fetch, "no-intro", canonicalSystem, NO_INTRO_BASE + encode(file));
        String title = table.get(crcUpper);
        return title == null ? "" : title;
    }

    static String lookupRedump(CheatFetch fetch, String canonicalSystem, String hashUpper) {
        String file = REDUMP_FILES.get(canonicalSystem);
        if (file == null || hashUpper == null || (hashUpper.length() != 32 && hashUpper.length() != 40)) return "";
        Map<String, String> table = table(fetch, "redump", canonicalSystem, REDUMP_BASE + encode(file));
        String title = table.get(hashUpper);
        return title == null ? "" : title;
    }

    private static Map<String, String> table(CheatFetch fetch, String kind, String canonicalSystem, String url) {
        File file = fetch.fetch(PSEUDO_SOURCE, url);
        if (file == null) return Collections.emptyMap();
        String memoKey = kind + "|" + canonicalSystem + "|" + file.getAbsolutePath()
                + "|" + file.length() + "|" + file.lastModified();
        synchronized (MEMO) {
            Map<String, String> cached = MEMO.get(memoKey);
            if (cached != null) return cached;
        }
        String text = CheatSourceFetcher.readText(file, MAX_DAT_BYTES);
        Map<String, String> parsed = text == null ? Collections.<String, String>emptyMap() : parseDat(text);
        synchronized (MEMO) { MEMO.put(memoKey, parsed); }
        return parsed;
    }

    /**
     * Extracts {@code crc}/{@code md5}/{@code sha1} -> game name from a
     * Logiqx DAT. Assumes the standard one-tag-per-line pretty printing every
     * official No-Intro/Redump DAT uses; a DAT reflowed onto fewer lines
     * would simply yield fewer matches, never a crash or a wrong answer,
     * since a {@code <rom>} line only ever contributes a mapping once its
     * enclosing {@code <game name="...">} has been seen on an earlier line.
     */
    static Map<String, String> parseDat(String text) {
        Map<String, String> result = new LinkedHashMap<>();
        String currentGame = "";
        for (String line : CodeText.lines(text)) {
            Matcher game = GAME_OPEN.matcher(line);
            if (game.find()) currentGame = unescapeXml(game.group(1));
            if (currentGame.isEmpty()) continue;
            Matcher rom = ROM_TAG.matcher(line);
            while (rom.find()) {
                String attrs = rom.group(1);
                Matcher attr = ATTR.matcher(attrs);
                String crc = null, md5 = null, sha1 = null;
                while (attr.find()) {
                    String name = attr.group(1).toLowerCase(Locale.US);
                    String value = attr.group(2);
                    if ("crc".equals(name)) crc = value;
                    else if ("md5".equals(name)) md5 = value;
                    else if ("sha1".equals(name)) sha1 = value;
                }
                if (crc != null && crc.length() == 8 && crc.matches("(?i)[0-9a-f]{8}"))
                    result.put(crc.toUpperCase(Locale.US), currentGame);
                if (md5 != null && md5.length() == 32 && md5.matches("(?i)[0-9a-f]{32}"))
                    result.put(md5.toUpperCase(Locale.US), currentGame);
                if (sha1 != null && sha1.length() == 40 && sha1.matches("(?i)[0-9a-f]{40}"))
                    result.put(sha1.toUpperCase(Locale.US), currentGame);
            }
        }
        return result;
    }

    private static String unescapeXml(String value) {
        if (value == null || value.indexOf('&') < 0) return value == null ? "" : value;
        return value.replace("&quot;", "\"").replace("&apos;", "'")
                .replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&");
    }

    private static String encode(String name) {
        StringBuilder out = new StringBuilder();
        for (byte b : name.getBytes(java.nio.charset.StandardCharsets.UTF_8)) {
            int ch = b & 0xff;
            if ((ch >= 'A' && ch <= 'Z') || (ch >= 'a' && ch <= 'z') || (ch >= '0' && ch <= '9')
                    || ch == '-' || ch == '_' || ch == '.' || ch == '~')
                out.append((char) ch);
            else out.append(String.format(Locale.US, "%%%02X", ch));
        }
        return out.toString();
    }
}
