package com.thorium.lucent.cheats;

import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * The per-game cheat catalogue.
 *
 * <p>Deliberately free of any parser or Android type: this is the model, and
 * loading it from JSON lives in the Android layer. That keeps title matching --
 * the part with real logic and real failure modes -- testable on the host with
 * no SDK.
 *
 * <p>Games are matched on (system, normalised title) rather than a content
 * hash. A hash would be exact, but these libraries are full of regional and
 * revision variants of one title whose hashes all differ while their cheat
 * codes are identical, so hashing would leave most games with nothing.
 */
public final class CheatDatabase {

    private final Map<String, List<Cheat>> byKey;

    private CheatDatabase(Map<String, List<Cheat>> byKey) {
        this.byKey = byKey;
    }

    public static CheatDatabase empty() {
        return new CheatDatabase(new HashMap<String, List<Cheat>>());
    }

    /** Builds from (system, title) -> cheats; entries with no cheats are dropped. */
    public static CheatDatabase of(Map<GameId, List<Cheat>> games) {
        Map<String, List<Cheat>> byKey = new HashMap<>();
        if (games != null) {
            for (Map.Entry<GameId, List<Cheat>> entry : games.entrySet()) {
                GameId id = entry.getKey();
                List<Cheat> cheats = entry.getValue();
                if (id == null || cheats == null || cheats.isEmpty()) continue;
                byKey.put(key(id.system, id.title),
                        Collections.unmodifiableList(new ArrayList<>(cheats)));
            }
        }
        return new CheatDatabase(byKey);
    }

    /** A game the catalogue is keyed by. */
    public static final class GameId {
        public final String system;
        public final String title;
        public GameId(String system, String title) {
            if (system == null || title == null)
                throw new IllegalArgumentException("system and title required");
            this.system = system;
            this.title = title;
        }
        @Override public boolean equals(Object other) {
            if (!(other instanceof GameId)) return false;
            GameId that = (GameId) other;
            return system.equals(that.system) && title.equals(that.title);
        }
        @Override public int hashCode() { return system.hashCode() * 31 + title.hashCode(); }
    }

    /** Cheats for this game in authored order; never null. */
    public List<Cheat> forGame(String system, String title) {
        if (system == null || title == null) return Collections.emptyList();
        List<Cheat> found = byKey.get(key(system, title));
        return found == null ? Collections.<Cheat>emptyList() : found;
    }

    public boolean hasCheats(String system, String title) {
        return !forGame(system, title).isEmpty();
    }

    public int gameCount() { return byKey.size(); }

    /** The stable per-game key, also used to record the user's selection. */
    public static String key(String system, String title) {
        return normalise(system) + " " + normalise(title);
    }

    /**
     * Lowercases, drops a file extension, removes bracketed scraper tags such
     * as "(USA)", "[!]" or "(Rev 1)", then strips everything that is not a
     * letter or digit. Two names differing only by those compare equal.
     */
    public static String normalise(String value) {
        if (value == null) return "";
        String text = value.toLowerCase(Locale.US).trim();
        int slash = Math.max(text.lastIndexOf('/'), text.lastIndexOf('\\'));
        if (slash >= 0) text = text.substring(slash + 1);
        int dot = text.lastIndexOf('.');
        if (dot > 0 && text.length() - dot <= 5) text = text.substring(0, dot);
        text = text.replaceAll("\\([^)]*\\)", " ").replaceAll("\\[[^\\]]*\\]", " ");
        StringBuilder out = new StringBuilder(text.length());
        for (int i = 0; i < text.length(); i++) {
            char ch = text.charAt(i);
            if (Character.isLetterOrDigit(ch)) out.append(ch);
        }
        return out.toString();
    }
}
