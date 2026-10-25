package com.thorium.emufusion.metadata;

import java.io.File;
import java.net.URLDecoder;
import java.text.Normalizer;
import java.util.AbstractList;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.BitSet;
import java.util.Collection;
import java.util.HashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;

/**
 * Decides which catalog asset belongs to a game title.
 *
 * <p>The importer used to treat every alias of a title as equally good: a set
 * of normalized spellings was built for the requested game, any catalog entry
 * matching <em>any</em> of them was accepted, and the winner was chosen purely
 * by region tag. That is how "Bass Masters Classic: Pro Edition" ended up
 * wearing plain "Bass Masters Classic"'s box and "Jurassic Park: Rampage
 * Edition" wore plain "Jurassic Park"'s: in both cases the exact full-title
 * artwork sat in the same listing and was passed over, because the
 * subtitle-stripped alias tied with it and sorted first.
 *
 * <p>Aliases are ranked here instead of pooled:
 *
 * <ul>
 *   <li>a full-title match always beats a subtitle-stripped one;
 *   <li>a subtitle-stripped match is only considered when nothing else in the
 *       listing matched at all;
 *   <li>and it is refused outright when another game in the same collection
 *       already carries that shorter name, or when the shorter name is a
 *       series prefix shared by several distinct catalog entries — in both
 *       cases the shorter name's artwork demonstrably belongs to some other
 *       game.
 * </ul>
 *
 * <p>Everything here is pure text logic with no Android dependency, so the
 * real failing pairs are pinned by host tests.
 */
public final class TitleMatcher {
    private TitleMatcher() {}

    /** No alias of the requested title reaches this candidate. */
    public static final int TIER_NONE = 0;
    /** Only the requested title with its subtitle removed reaches it. */
    public static final int TIER_SUBTITLE = 1;
    /** Reached after resolving roman numerals and dropping spacing. */
    public static final int TIER_COMPACT = 2;
    /** The full titles agree once dump tags and articles are dropped. */
    public static final int TIER_EXACT = 3;

    private static final String[] KNOWN_EXTENSIONS = new String[]{
            ".png", ".jpg", ".jpeg", ".webp", ".mp4", ".zip", ".7z",
            ".nes", ".unf", ".unif", ".fds", ".sfc", ".smc", ".fig",
            ".n64", ".z64", ".v64", ".gb", ".gbc", ".gba", ".nds",
            ".gg", ".gen", ".md", ".bin", ".cue", ".gdi", ".chd",
            ".iso", ".cso", ".rvz", ".wbfs", ".xci", ".nsp", ".wua",
            ".wux", ".3ds", ".3dsx", ".cia", ".cci", ".vpk", ".pbp"
    };

    /**
     * Cartridges that are not games: cheat hardware, BIOS dumps and service
     * carts. No thumbnail catalog carries box art for them, and their names
     * are short and generic enough that a relaxed alias can drift onto one.
     * "Action Replay Max" is the one the owner reported wearing another
     * game's box; the rest are its neighbours in the same dump sets.
     */
    private static final String[] UTILITY_MARKERS = new String[]{
            "action replay", "actionreplay", "game genie", "gamegenie",
            "game shark", "gameshark", "pro action", "code breaker",
            "codebreaker", "xploder", "game doctor", "sega channel",
            "everdrive", "tmss", "bios", "boot rom", "bootrom",
            "test cartridge", "test program", "service cartridge"
    };

    /** Words describing how a dump was made rather than what game it is. */
    private static final String RELAXABLE =
            "\\b(?:fan translation|english translation|translation|prototype|beta|demo)\\b";

    private static final String[] BUILD_VARIANTS =
            new String[]{"demo", "kiosk", "prototype", "proto", "beta", "sample"};

    // Compiled once: these run over every entry of listings thousands long.
    private static final Pattern[] BUILD_VARIANT_PATTERNS = new Pattern[BUILD_VARIANTS.length];
    static {
        for (int i = 0; i < BUILD_VARIANTS.length; i++)
            BUILD_VARIANT_PATTERNS[i] = Pattern.compile(".*\\b" + BUILD_VARIANTS[i] + "\\b.*");
    }
    private static final Pattern RELAXABLE_WORDS = Pattern.compile(RELAXABLE);
    private static final Pattern DUMP_TAG = Pattern.compile("\\([^()]*\\)|\\[[^\\[\\]]*]");
    private static final Pattern MARKS = Pattern.compile("\\p{M}+");
    private static final Pattern NON_WORD = Pattern.compile("[^a-z0-9]+");
    private static final Pattern SPACES = Pattern.compile("\\s+");
    private static final Pattern ARTICLES = Pattern.compile("\\b(?:the|a|an)\\b");
    private static final Pattern AND = Pattern.compile("\\band\\b");
    private static final Pattern LONE_NUMERAL = Pattern.compile("[ivx]");
    private static final Pattern DIGITS = Pattern.compile("[0-9]+");

    /** A chosen candidate, carrying why it was chosen. */
    public static final class Match {
        public final String name;
        public final int tier;
        public final int regionRank;
        /** Bracketed groups in the file name; the plainest dump wins ties. */
        public final int variantDepth;

        Match(String name, int tier, int regionRank, int variantDepth) {
            this.name = name;
            this.tier = tier;
            this.regionRank = regionRank;
            this.variantDepth = variantDepth;
        }

        /** A short reason string, for the importer's log line. */
        public String reason() {
            if (tier == TIER_EXACT) return "exact-title";
            if (tier == TIER_COMPACT) return "collapsed-numeral";
            if (tier == TIER_SUBTITLE) return "subtitle-dropped";
            return "none";
        }
    }

    /**
     * One catalog listing, with the text every question derives from each
     * entry worked out once.
     *
     * <p>The importer asks a listing about one title at a time, several times
     * per game, and each question used to re-derive every entry: a dozen
     * regular expressions over each of thousands of names. With the screens
     * off, a library media pass on the Thor spent 4-5 s of CPU per game on it,
     * about two cores for the whole pass (2026-10-24). The answers are the
     * ones that per-question derivation gives; the indexes only find them
     * without visiting every entry.
     */
    public static final class Catalog extends AbstractList<String> {
        private static final int INELIGIBLE = -1;
        private static final int UTILITY = 1 << 6;
        private static final int REGION_SHIFT = 8;
        private static final int DEPTH_SHIFT = 12;

        private final String[] names;
        /** Per entry: build-variant bits, utility flag, region rank, depth. */
        private final int[] traits;
        private final Map<String, int[]> byForm = new HashMap<>();
        /** compact(form) + tab + sequelKey(form), for the numeral tier. */
        private final Map<String, int[]> byCompact = new HashMap<>();
        /** Every non-empty normalized stem, sorted for prefix questions. */
        private final String[] stems;
        private volatile Map<String, Integer> byDecodedName;

        public Catalog(Collection<String> candidateNames) {
            names = candidateNames.toArray(new String[0]);
            traits = new int[names.length];
            List<String> sorted = new ArrayList<>(names.length);
            for (int i = 0; i < names.length; i++) {
                String name = names[i];
                if (name == null || name.isEmpty()) {
                    traits[i] = INELIGIBLE;
                    continue;
                }
                String decoded = decode(name);
                int bits = variantBits(decode(decoded).toLowerCase(Locale.US));
                if (isUtilityTitle(decoded)) bits |= UTILITY;
                traits[i] = bits | regionRank(decoded) << REGION_SHIFT |
                        variantDepth(decoded) << DEPTH_SHIFT;
                for (String form : candidateForms(decoded)) {
                    add(byForm, form, i);
                    String compact = compact(form);
                    if (!compact.isEmpty()) add(byCompact, compact + '\t' + sequelKey(form), i);
                }
                String stem = normalize(stem(decoded));
                if (!stem.isEmpty()) sorted.add(stem);
            }
            stems = sorted.toArray(new String[0]);
            Arrays.sort(stems);
        }

        /** This listing's prepared form, or one prepared for a single question. */
        static Catalog of(Collection<String> candidateNames) {
            return candidateNames instanceof Catalog ? (Catalog) candidateNames :
                    new Catalog(candidateNames);
        }

        @Override
        public String get(int index) {
            return names[index];
        }

        @Override
        public int size() {
            return names.length;
        }

        /** The first entry whose decoded file name is exactly this, or null. */
        public String withDecodedName(String decodedName) {
            Map<String, Integer> index = byDecodedName;
            if (index == null) {
                index = new HashMap<>();
                for (int i = names.length - 1; i >= 0; i--)
                    if (names[i] != null) index.put(decode(names[i]), i);
                byDecodedName = index;
            }
            Integer at = index.get(decodedName);
            return at == null ? null : names[at];
        }

        private static void add(Map<String, int[]> index, String key, int entry) {
            int[] entries = index.get(key);
            if (entries == null) {
                index.put(key, new int[]{entry});
                return;
            }
            // Entries arrive in listing order, so only the last can repeat.
            if (entries[entries.length - 1] == entry) return;
            int[] grown = Arrays.copyOf(entries, entries.length + 1);
            grown[entries.length] = entry;
            index.put(key, grown);
        }

        private static void mark(Map<String, int[]> index, String key, BitSet into) {
            int[] entries = index.get(key);
            if (entries != null) for (int entry : entries) into.set(entry);
        }

        /** Whether one entry may answer this request; see isUnwantedVariant. */
        private boolean eligible(int entry, int requestedVariants, boolean utilityRequest) {
            int bits = traits[entry];
            if (bits == INELIGIBLE) return false;
            if ((bits & (UTILITY - 1) & ~requestedVariants) != 0) return false;
            // A cheat cart never stands in for a game, and a game never stands
            // in for a cheat cart.
            return ((bits & UTILITY) != 0) == utilityRequest;
        }

        private Match match(int entry, int tier) {
            int bits = traits[entry];
            return new Match(names[entry], tier, (bits >> REGION_SHIFT) & 0xF,
                    bits >>> DEPTH_SHIFT);
        }

        private boolean hasStem(String stem) {
            return Arrays.binarySearch(stems, stem) >= 0;
        }

        /**
         * Whether some stem starts with this prefix. Every prefix asked ends
         * in a space and stems are trimmed, so a match is always longer.
         */
        private boolean hasStemStartingWith(String prefix) {
            int at = Arrays.binarySearch(stems, prefix);
            if (at < 0) at = -at - 1;
            return at < stems.length && stems[at].startsWith(prefix);
        }
    }

    /**
     * Chooses the catalog entry that belongs to {@code requestedTitle}, or
     * null when none does.
     *
     * @param candidateNames catalog file names or hrefs, in listing order
     * @param claimedTitles  normalized titles of the other games in the same
     *                       collection, from {@link #claimedTitles}
     */
    public static Match select(String requestedTitle, Collection<String> candidateNames,
                               Set<String> claimedTitles) {
        if (requestedTitle == null || candidateNames == null) return null;
        Catalog catalog = Catalog.of(candidateNames);
        Set<String> full = fullTitleForms(requestedTitle);
        boolean utilityRequest = isUtilityTitle(requestedTitle);
        int requestedVariants = variantBits(decode(requestedTitle).toLowerCase(Locale.US));

        // Resolving "II" to "2" is what lets a catalog spell a sequel
        // differently from the ROM. It also resolves a standalone "X" to
        // "10", so the instalment numbers must agree before it is trusted.
        BitSet exact = new BitSet();
        BitSet reached = new BitSet();
        for (String form : full) {
            Catalog.mark(catalog.byForm, form, exact);
            String compact = compact(form);
            if (!compact.isEmpty())
                Catalog.mark(catalog.byCompact, compact + '\t' + sequelKey(form), reached);
        }
        reached.or(exact);
        Match best = null;
        for (int i = reached.nextSetBit(0); i >= 0; i = reached.nextSetBit(i + 1)) {
            if (!catalog.eligible(i, requestedVariants, utilityRequest)) continue;
            best = better(best, catalog.match(i, exact.get(i) ? TIER_EXACT : TIER_COMPACT));
        }
        if (best != null) return best;

        String base = subtitleBase(requestedTitle);
        if (base.isEmpty()) return null;
        // Another game in this collection is literally called that. Its box
        // is that game's box, not this one's.
        if (claimedTitles != null && claimedTitles.contains(base)) return null;
        // The short name is a series root ("Phantasy Star", "Spider-Man"):
        // several distinct catalog entries extend it, so dropping the
        // subtitle names a family and not a game.
        if (isSeriesPrefix(base, catalog)) return null;

        // The short name itself, or its numeral-resolved spelling naming the
        // same instalment.
        BitSet shortened = new BitSet();
        Catalog.mark(catalog.byForm, base, shortened);
        String compactBase = compact(base);
        if (!compactBase.isEmpty())
            Catalog.mark(catalog.byCompact, compactBase + '\t' + sequelKey(base), shortened);
        for (int i = shortened.nextSetBit(0); i >= 0; i = shortened.nextSetBit(i + 1)) {
            if (!catalog.eligible(i, requestedVariants, utilityRequest)) continue;
            best = better(best, catalog.match(i, TIER_SUBTITLE));
        }
        return best;
    }

    /** Convenience wrapper for callers that only want the winning name. */
    public static String selectName(String requestedTitle, Collection<String> candidateNames,
                                    Set<String> claimedTitles) {
        Match match = select(requestedTitle, candidateNames, claimedTitles);
        return match == null ? null : match.name;
    }

    /**
     * Whether any entry in the listing plausibly depicts this title, with
     * every safety guard switched off.
     *
     * <p>This is the question the artwork prune asks, and it is deliberately
     * not {@link #select}: select refuses risky matches, and "the matcher
     * declined to guess" must never be mistaken for "no art exists". Only a
     * title that nothing in any catalog resembles is genuinely artless.
     */
    public static boolean hasAnyCandidate(String requestedTitle,
                                          Collection<String> candidateNames) {
        if (requestedTitle == null || candidateNames == null) return false;
        Set<String> full = fullTitleForms(requestedTitle);
        if (full.isEmpty()) return false;
        Catalog catalog = Catalog.of(candidateNames);
        for (String form : full) {
            if (catalog.byForm.containsKey(form)) return true;
            String compact = compact(form);
            if (!compact.isEmpty() &&
                    catalog.byCompact.containsKey(compact + '\t' + sequelKey(form))) return true;
        }
        // A catalog that files the game under a longer name still has its
        // box: "Phantasy Star IV" is what "Phantasy Star: The End of the
        // Millenium" is called there, and "Romance of the Three Kingdoms
        // III" gains a subtitle. Extra words on the catalog's side are
        // evidence; extra words on the request's side are not, or
        // "Aladdin" would vouch for "Aladdin II" and every ROM hack named
        // "<somebody>'s Super Mario World" would vouch for itself.
        String base = subtitleBase(requestedTitle);
        if (!base.isEmpty() && (catalog.hasStem(base) || catalog.hasStemStartingWith(base + " ")))
            return true;
        for (String form : full)
            if (catalog.hasStemStartingWith(form + " ")) return true;
        return false;
    }

    /** The strength of the strongest alias linking a title to one candidate. */
    public static int tier(String requestedTitle, String candidateName) {
        Match match = select(requestedTitle,
                java.util.Collections.singletonList(candidateName), null);
        return match == null ? TIER_NONE : match.tier;
    }

    private static Match better(Match current, Match challenger) {
        if (current == null) return challenger;
        if (challenger.tier != current.tier)
            return challenger.tier > current.tier ? challenger : current;
        if (challenger.regionRank != current.regionRank)
            return challenger.regionRank < current.regionRank ? challenger : current;
        // Same game, same region: prefer the plainest dump. Every extra
        // bracketed group is a re-release or a hack — "(Final Cut)",
        // "(Virtual Console)", "(Genesis Mini)" — and the retail box is the
        // one the owner expects to see on the shelf.
        if (challenger.variantDepth != current.variantDepth)
            return challenger.variantDepth < current.variantDepth ? challenger : current;
        return current;
    }

    /** How many bracketed groups a catalog file name carries. */
    static int variantDepth(String decodedCandidate) {
        String value = stem(decodedCandidate);
        int depth = 0;
        for (int index = 0; index < value.length(); index++) {
            char character = value.charAt(index);
            if (character == '(' || character == '[') depth++;
        }
        return depth;
    }

    /**
     * True when several distinct catalog entries extend {@code base} with
     * further words, i.e. the short name is a series root rather than a game.
     */
    static boolean isSeriesPrefix(String base, Collection<String> candidateNames) {
        if (base == null || base.isEmpty()) return false;
        return Catalog.of(candidateNames).hasStemStartingWith(base + " ");
    }

    /** Every spelling of the requested title that still names the whole game. */
    public static Set<String> fullTitleForms(String title) {
        Set<String> values = new LinkedHashSet<>();
        String key = normalize(title);
        if (key.isEmpty()) return values;
        addForms(values, key);
        String relaxed = collapse(RELAXABLE_WORDS.matcher(key).replaceAll(" "))
                .replace(" the the ", " the ");
        addForms(values, relaxed);
        if (relaxed.startsWith("the ")) addForms(values, relaxed.substring(4));
        // One catalog files this under its Japanese name entirely.
        if (relaxed.startsWith("castlevania rondo of blood"))
            values.add("akumajou dracula x chi no rondo");
        values.remove("");
        return values;
    }

    private static void addForms(Set<String> values, String key) {
        values.add(key);
        values.add(articleless(key));
        // libretro's thumbnail files replace "&" with "_", which normalizes
        // to nothing, while the ROM's own name expands it to "and". Without
        // this alias every ampersand title misses: "Sonic & Knuckles" never
        // reaches "Sonic _ Knuckles.png", nor "ToeJam & Earl" its own box.
        values.add(andless(key));
        values.add(andless(articleless(key)));
    }

    /**
     * The requested title with its subtitle removed, or empty when it has no
     * usable subtitle. Only a leading segment carrying a space of its own
     * counts, so "B.O.B: ..." cannot collapse to a two-letter stub.
     */
    public static String subtitleBase(String title) {
        if (title == null) return "";
        int colon = title.indexOf(':');
        if (colon <= 3) return "";
        String head = title.substring(0, colon).replaceAll("(?i),\\s*(?:The|A|An)$", "");
        String base = normalize(head);
        return base.contains(" ") ? base : "";
    }

    /** The forms a catalog entry can be recognised by. */
    private static Set<String> candidateForms(String decodedCandidate) {
        Set<String> values = new LinkedHashSet<>();
        String candidate = normalize(stem(decodedCandidate));
        if (candidate.isEmpty()) return values;
        values.add(candidate);
        values.add(articleless(candidate));
        values.add(andless(candidate));
        values.add(andless(articleless(candidate)));
        values.remove("");
        return values;
    }

    /**
     * Filename and URL text reduced to comparable words: directory, extension
     * and every bracketed dump tag removed, accents folded, punctuation
     * flattened.
     */
    public static String normalize(String value) {
        String title = decode(value);
        int slash = Math.max(title.lastIndexOf('/'), title.lastIndexOf(File.separatorChar));
        if (slash >= 0) title = title.substring(slash + 1);
        String lower = title.toLowerCase(Locale.US);
        for (int i = 0; i < KNOWN_EXTENSIONS.length; i++) {
            if (lower.endsWith(KNOWN_EXTENSIONS[i])) {
                title = title.substring(0, title.length() - KNOWN_EXTENSIONS[i].length());
                break;
            }
        }
        String previous;
        do {
            previous = title;
            title = DUMP_TAG.matcher(title).replaceAll(" ");
        } while (!title.equals(previous));
        title = MARKS.matcher(Normalizer.normalize(title, Normalizer.Form.NFKD)).replaceAll("");
        title = title.toLowerCase(Locale.US).replace("&", " and ");
        return collapse(NON_WORD.matcher(title).replaceAll(" "));
    }

    /** Roman numerals resolved and spacing removed, for sequel spelling drift. */
    public static String compact(String normalized) {
        if (normalized == null || normalized.isEmpty()) return "";
        String[] tokens = normalized.split(" ");
        StringBuilder out = new StringBuilder();
        for (int i = 0; i < tokens.length; i++) out.append(arabic(tokens[i], tokens[i]));
        return out.toString();
    }

    /**
     * The instalment a title names, used to guard the collapsed comparison.
     *
     * <p>A lone letter is deliberately never resolved. "Mega Man X" and "Mega
     * Man 10" collapse to the same compact key, and only the raw token tells
     * the 1993 platformer from the WiiWare sequel; returning the letter itself
     * makes it match nothing but the same letter.
     */
    public static String sequelKey(String normalized) {
        if (normalized == null || normalized.isEmpty()) return "";
        String[] tokens = normalized.split(" ");
        String last = tokens[tokens.length - 1];
        if (last.length() == 1 && LONE_NUMERAL.matcher(last).matches()) return "?" + last;
        String resolved = arabic(last, "");
        if (!resolved.isEmpty()) return resolved;
        return DIGITS.matcher(last).matches() ? last : "";
    }

    /**
     * True when a ROM's own file name declares it an unlicensed, pirate or
     * hacked dump.
     *
     * <p>Text similarity alone cannot prove artwork does not exist — a catalog
     * that spells "Caliber .50" where the ROM says "Caliber Fifty" looks
     * identical to a game nobody ever photographed. This is the second,
     * independent signal the artwork prune requires: dump tags are written by
     * the preservation groups, not inferred, and a cart the No-Intro or
     * GoodTools naming calls unlicensed genuinely had no retail box.
     */
    public static boolean isBootlegDump(String romFileName) {
        if (romFileName == null || romFileName.isEmpty()) return false;
        return romFileName.matches(
                "(?i).*[\\[(](?:unl|unlicensed|pirate|bootleg|hack|multicart|aftermarket)" +
                        "[^\\])]*[\\])].*");
    }

    /** True for cheat carts, BIOS dumps and other non-game cartridges. */
    public static boolean isUtilityTitle(String title) {
        if (title == null || title.isEmpty()) return false;
        String key = " " + normalize(title) + " ";
        for (int i = 0; i < UTILITY_MARKERS.length; i++) {
            if (key.contains(" " + UTILITY_MARKERS[i] + " ") ||
                    key.contains(" " + UTILITY_MARKERS[i] + "s ")) return true;
        }
        return false;
    }

    /** Catalog preference between regional dumps of the same game. */
    public static int regionRank(String value) {
        String lower = decode(value).toLowerCase(Locale.US);
        if (lower.contains("(usa") || lower.contains("(us)")) return 0;
        if (lower.contains("(world")) return 1;
        if (lower.contains("(europe")) return 2;
        if (lower.contains("(japan")) return 4;
        return 3;
    }

    /**
     * Parenthetical stripping makes a kiosk or prototype dump normalize to the
     * same key as the retail release. A special build may only answer a
     * request that asked for that same build.
     */
    public static boolean isUnwantedVariant(String candidate, String requestedLower) {
        String candidateLower = decode(candidate).toLowerCase(Locale.US);
        for (int i = 0; i < BUILD_VARIANT_PATTERNS.length; i++) {
            if (BUILD_VARIANT_PATTERNS[i].matcher(candidateLower).matches() &&
                    !BUILD_VARIANT_PATTERNS[i].matcher(requestedLower).matches()) return true;
        }
        return false;
    }

    /** One bit per build variant this lower-cased name declares. */
    private static int variantBits(String lower) {
        int bits = 0;
        for (int i = 0; i < BUILD_VARIANT_PATTERNS.length; i++)
            if (BUILD_VARIANT_PATTERNS[i].matcher(lower).matches()) bits |= 1 << i;
        return bits;
    }

    /** Every normalized title in a collection, for the subtitle guard. */
    public static Set<String> claimedTitles(Collection<String> titles) {
        Set<String> claimed = new LinkedHashSet<>();
        if (titles == null) return claimed;
        for (String title : titles) {
            String key = normalize(title);
            if (key.isEmpty()) continue;
            claimed.add(key);
            claimed.add(articleless(key));
        }
        claimed.remove("");
        return claimed;
    }

    /** File name without directory or extension. */
    public static String stem(String name) {
        if (name == null) return "";
        String value = name;
        int slash = Math.max(value.lastIndexOf('/'), value.lastIndexOf(File.separatorChar));
        if (slash >= 0) value = value.substring(slash + 1);
        int dot = value.lastIndexOf('.');
        return dot > 0 ? value.substring(0, dot) : value;
    }

    private static String articleless(String normalized) {
        return collapse(ARTICLES.matcher(normalized).replaceAll(" "));
    }

    private static String andless(String normalized) {
        return collapse(AND.matcher(normalized).replaceAll(" "));
    }

    private static String collapse(String value) {
        return SPACES.matcher(value).replaceAll(" ").trim();
    }

    private static String arabic(String token, String fallback) {
        if ("ii".equals(token)) return "2";
        if ("iii".equals(token)) return "3";
        if ("iv".equals(token)) return "4";
        if ("v".equals(token)) return "5";
        if ("vi".equals(token)) return "6";
        if ("vii".equals(token)) return "7";
        if ("viii".equals(token)) return "8";
        if ("ix".equals(token)) return "9";
        if ("x".equals(token)) return "10";
        return fallback;
    }

    private static String decode(String value) {
        if (value == null) return "";
        try {
            // Catalog hrefs are URL paths: a '+' is literal, not a space.
            return URLDecoder.decode(value.replace("+", "%2B"), "UTF-8");
        } catch (Exception ignored) {
            return value;
        }
    }
}
