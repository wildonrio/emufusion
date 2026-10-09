package com.thorium.lucent.metadata;

import java.io.File;
import java.net.URLDecoder;
import java.text.Normalizer;
import java.util.Collection;
import java.util.LinkedHashSet;
import java.util.Locale;
import java.util.Set;

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
        Set<String> full = fullTitleForms(requestedTitle);
        boolean utilityRequest = isUtilityTitle(requestedTitle);
        String requestedLower = decode(requestedTitle).toLowerCase(Locale.US);

        Match best = null;
        for (String name : candidateNames) {
            String decoded = eligible(name, requestedLower, utilityRequest);
            if (decoded == null) continue;
            int tier = fullTier(full, candidateForms(decoded));
            if (tier == TIER_NONE) continue;
            best = better(best, new Match(name, tier, regionRank(decoded),
                    variantDepth(decoded)));
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
        if (isSeriesPrefix(base, candidateNames)) return null;

        String compactBase = compact(base);
        String baseSequel = sequelKey(base);
        for (String name : candidateNames) {
            String decoded = eligible(name, requestedLower, utilityRequest);
            if (decoded == null) continue;
            for (String form : candidateForms(decoded)) {
                boolean reached = base.equals(form) ||
                        (!compactBase.isEmpty() && compactBase.equals(compact(form)));
                if (!reached || !baseSequel.equals(sequelKey(form))) continue;
                best = better(best, new Match(name, TIER_SUBTITLE, regionRank(decoded),
                        variantDepth(decoded)));
                break;
            }
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
        String base = subtitleBase(requestedTitle);
        for (String name : candidateNames) {
            if (name == null || name.isEmpty()) continue;
            String candidate = normalize(stem(decode(name)));
            if (candidate.isEmpty()) continue;
            if (fullTier(full, candidateForms(decode(name))) != TIER_NONE) return true;
            // A catalog that files the game under a longer name still has its
            // box: "Phantasy Star IV" is what "Phantasy Star: The End of the
            // Millenium" is called there, and "Romance of the Three Kingdoms
            // III" gains a subtitle. Extra words on the catalog's side are
            // evidence; extra words on the request's side are not, or
            // "Aladdin" would vouch for "Aladdin II" and every ROM hack named
            // "<somebody>'s Super Mario World" would vouch for itself.
            if (!base.isEmpty() && (base.equals(candidate) ||
                    candidate.startsWith(base + " "))) return true;
            for (String form : full)
                if (candidate.startsWith(form + " ")) return true;
        }
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

    /** Returns the decoded candidate when it may answer this request. */
    private static String eligible(String name, String requestedLower, boolean utilityRequest) {
        if (name == null || name.isEmpty()) return null;
        String decoded = decode(name);
        if (isUnwantedVariant(decoded, requestedLower)) return null;
        // A cheat cart never stands in for a game, and a game never stands in
        // for a cheat cart.
        if (isUtilityTitle(decoded) != utilityRequest) return null;
        return decoded;
    }

    private static int fullTier(Set<String> full, Set<String> candidate) {
        for (String form : full)
            if (candidate.contains(form)) return TIER_EXACT;
        // Resolving "II" to "2" is what lets a catalog spell a sequel
        // differently from the ROM. It also resolves a standalone "X" to
        // "10", so the instalment numbers must agree before it is trusted.
        for (String form : full) {
            String compact = compact(form);
            if (compact.isEmpty()) continue;
            for (String other : candidate) {
                if (!compact.equals(compact(other))) continue;
                if (sequelKey(form).equals(sequelKey(other))) return TIER_COMPACT;
            }
        }
        return TIER_NONE;
    }

    /**
     * True when several distinct catalog entries extend {@code base} with
     * further words, i.e. the short name is a series root rather than a game.
     */
    static boolean isSeriesPrefix(String base, Collection<String> candidateNames) {
        if (base == null || base.isEmpty()) return false;
        String prefix = base + " ";
        Set<String> extensions = new LinkedHashSet<>();
        for (String name : candidateNames) {
            if (name == null || name.isEmpty()) continue;
            String candidate = normalize(stem(decode(name)));
            if (candidate.startsWith(prefix) && candidate.length() > prefix.length())
                extensions.add(candidate);
        }
        return !extensions.isEmpty();
    }

    /** Every spelling of the requested title that still names the whole game. */
    public static Set<String> fullTitleForms(String title) {
        Set<String> values = new LinkedHashSet<>();
        String key = normalize(title);
        if (key.isEmpty()) return values;
        addForms(values, key);
        String relaxed = collapse(key.replaceAll(RELAXABLE, " ")).replace(" the the ", " the ");
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
            title = title.replaceAll("\\([^()]*\\)|\\[[^\\[\\]]*]", " ");
        } while (!title.equals(previous));
        title = Normalizer.normalize(title, Normalizer.Form.NFKD).replaceAll("\\p{M}+", "");
        title = title.toLowerCase(Locale.US).replace("&", " and ");
        return collapse(title.replaceAll("[^a-z0-9]+", " "));
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
        if (last.length() == 1 && last.matches("[ivx]")) return "?" + last;
        String resolved = arabic(last, "");
        if (!resolved.isEmpty()) return resolved;
        return last.matches("[0-9]+") ? last : "";
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
        for (int i = 0; i < BUILD_VARIANTS.length; i++) {
            if (candidateLower.matches(".*\\b" + BUILD_VARIANTS[i] + "\\b.*") &&
                    !requestedLower.matches(".*\\b" + BUILD_VARIANTS[i] + "\\b.*")) return true;
        }
        return false;
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
        return collapse(normalized.replaceAll("\\b(?:the|a|an)\\b", " "));
    }

    private static String andless(String normalized) {
        return collapse(normalized.replaceAll("\\band\\b", " "));
    }

    private static String collapse(String value) {
        return value.replaceAll("\\s+", " ").trim();
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
            return URLDecoder.decode(value, "UTF-8");
        } catch (Exception ignored) {
            return value;
        }
    }
}
