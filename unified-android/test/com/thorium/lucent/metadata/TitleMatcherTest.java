package com.thorium.lucent.metadata;

import com.thorium.lucent.TestSupport;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

/**
 * Box-art matching, pinned against the owner's real Sega Genesis library.
 *
 * <p>Every candidate list below is a verbatim slice of
 * {@code thumbnails.libretro.com/Sega - Mega Drive - Genesis/Named_Boxarts/},
 * and every requested title is the exact {@code game:} line from the device's
 * {@code 22-genesis.metadata.pegasus.txt}. The reported symptom was artwork
 * attached to games it did not belong to, and these are the pairings that
 * produced it.
 */
public final class TitleMatcherTest {

    /** The Genesis titles that surround the reported failures, as shipped. */
    private static final List<String> GENESIS_LIBRARY = Arrays.asList(
            "Action 52", "Action Replay Max", "Aladdin", "Aladdin II",
            "Disney's Aladdin", "Bass Masters Classic", "Bass Masters Classic: Pro Edition",
            "Jurassic Park", "Jurassic Park: Rampage Edition",
            "Mighty Morphin Power Rangers", "Mighty Morphin Power Rangers: The Movie",
            "Uncharted Waters", "Uncharted Waters: New Horizons",
            "Phantasy Star: The End of the Millenium", "Spider-Man: The Animated Series",
            "Judge Dredd: The Movie", "Genesis TMSS BIOS", "Sega Channel",
            "The Addams Family", "ClayFighter", "Gauntlet 4");

    public static void main(String[] args) {
        aladdinNeverWearsAladdinII();
        cheatCartridgesAreNotGames();
        subtitleNeverStealsTheBaseGamesBox();
        subtitleStillWorksWhenNothingElseOwnsTheName();
        seriesRootsAreNeverGuessedAt();
        regionAndArticleSpellingsStillMatch();
        collapsedNumeralsRespectTheInstalment();
        specialBuildsStayOutOfRetailSlots();
        artlessProbeIgnoresEveryGuard();
        System.out.println("TitleMatcherTest passed");
    }

    /**
     * The pirate sequel and the Disney original are different cartridges. The
     * owner saw one wearing the other's box; neither may reach the other now.
     */
    private static void aladdinNeverWearsAladdinII() {
        List<String> catalog = Arrays.asList(
                "Aladdin (Europe).png", "Aladdin (Japan).png",
                "Aladdin (USA) (Final Cut).png", "Aladdin (USA).png",
                "Aladdin (World) (Disney Classic Games).png");
        Set<String> claimed = claimed();
        TestSupport.equal("Aladdin (USA).png",
                TitleMatcher.selectName("Aladdin", catalog, claimed),
                "plain Aladdin takes the USA dump of its own box");
        TestSupport.equal(null, TitleMatcher.selectName("Aladdin II", catalog, claimed),
                "Aladdin II has no box in this catalog and must not borrow Aladdin's");
        TestSupport.equal(null, TitleMatcher.selectName("Aladdin 2", catalog, claimed),
                "the arabic spelling of the sequel is refused for the same reason");
        TestSupport.truth(!TitleMatcher.hasAnyCandidate("Aladdin II", catalog),
                "and nothing in the catalog resembles it at any tier");

        // Where the sequel really is published, it must find itself and only
        // itself. This is the NES set, where the pirate sequels are catalogued.
        List<String> nes = Arrays.asList("Aladdin (Unl).png", "Aladdin 2 (Unl).png",
                "Aladdin 3 (Unl).png", "Aladdin 4 (Unl).png");
        TestSupport.equal("Aladdin 2 (Unl).png",
                TitleMatcher.selectName("Aladdin 2", nes, null),
                "the sequel matches its own entry");
        TestSupport.equal("Aladdin (Unl).png", TitleMatcher.selectName("Aladdin", nes, null),
                "and the original is not dragged onto a numbered sequel");
    }

    /**
     * "Action Replay Max" is a cheat cartridge. No catalog carries a box for
     * it, and it must never be handed one belonging to a game — nor may its
     * short generic name reach a game's artwork.
     */
    private static void cheatCartridgesAreNotGames() {
        List<String> catalog = Arrays.asList("Action 52 (USA) (Unl).png",
                "Action Fighter (USA, Europe).png", "Action Chess (USA).png");
        Set<String> claimed = claimed();
        TestSupport.truth(TitleMatcher.isUtilityTitle("Action Replay Max"),
                "a cheat cartridge is recognised as a non-game");
        TestSupport.truth(TitleMatcher.isUtilityTitle("Genesis TMSS BIOS"),
                "so is a BIOS dump");
        TestSupport.truth(TitleMatcher.isUtilityTitle("Sega Channel"),
                "and so is the download service cartridge");
        TestSupport.truth(!TitleMatcher.isUtilityTitle("Action 52"),
                "an unlicensed compilation is still a game");
        TestSupport.truth(!TitleMatcher.isUtilityTitle("Last Action Hero"),
                "and so is a game that merely contains the word action");
        TestSupport.equal(null,
                TitleMatcher.selectName("Action Replay Max", catalog, claimed),
                "the cheat cartridge takes none of the Action* boxes");
        TestSupport.equal("Action 52 (USA) (Unl).png",
                TitleMatcher.selectName("Action 52", catalog, claimed),
                "and Action 52 keeps its own");
        // Symmetric: a game may not be given a cheat cartridge's artwork.
        TestSupport.equal(null, TitleMatcher.selectName("Action Fighter",
                Collections.singletonList("Action Replay (USA) (Unl).png"), claimed),
                "a game is never given a cheat cartridge's box");
    }

    /**
     * The exact failure the owner reported: an edition with a subtitle wearing
     * the base game's box while its own box sat in the same listing.
     */
    private static void subtitleNeverStealsTheBaseGamesBox() {
        List<String> bass = Arrays.asList("Bass Masters Classic (USA).png",
                "Bass Masters Classic - Pro Edition (USA).png");
        TestSupport.equal("Bass Masters Classic - Pro Edition (USA).png",
                TitleMatcher.selectName("Bass Masters Classic: Pro Edition", bass, claimed()),
                "the Pro Edition takes its own box, not the base game's");
        TestSupport.equal("Bass Masters Classic (USA).png",
                TitleMatcher.selectName("Bass Masters Classic", bass, claimed()),
                "and the base game is unaffected");

        List<String> jurassic = Arrays.asList(
                "Jurassic Park (USA) (1993-05-26) (Sega Channel).png",
                "Jurassic Park (USA).png",
                "Jurassic Park - Rampage Edition (USA, Europe).png",
                "Jurassic Park - Rampage Edition (Europe).png");
        TestSupport.equal("Jurassic Park - Rampage Edition (USA, Europe).png",
                TitleMatcher.selectName("Jurassic Park: Rampage Edition", jurassic, claimed()),
                "Rampage Edition takes its own box even though the base sorts first");

        List<String> rangers = Arrays.asList("Mighty Morphin Power Rangers (USA).png",
                "Mighty Morphin Power Rangers - The Movie (USA).png");
        TestSupport.equal("Mighty Morphin Power Rangers - The Movie (USA).png",
                TitleMatcher.selectName("Mighty Morphin Power Rangers: The Movie",
                        rangers, claimed()),
                "the movie tie-in takes its own box");

        // Nothing in the catalog is the sequel, and the library already owns
        // the shorter name, so guessing would put game one's box on game two.
        TestSupport.equal(null, TitleMatcher.selectName("Uncharted Waters: New Horizons",
                Collections.singletonList("Uncharted Waters (USA).png"), claimed()),
                "the sequel does not borrow the first game's box");
        TestSupport.equal("Uncharted Waters (USA).png",
                TitleMatcher.selectName("Uncharted Waters",
                        Collections.singletonList("Uncharted Waters (USA).png"), claimed()),
                "while the first game still gets it");
    }

    /**
     * Dropping a subtitle is often right: many catalogs simply file a game
     * under a shorter name, and nothing else claims it.
     */
    private static void subtitleStillWorksWhenNothingElseOwnsTheName() {
        List<String> catalog = Arrays.asList("Judge Dredd (USA).png",
                "Judge Dredd (World).png", "Judge Dredd (Japan).png");
        TestSupport.equal("Judge Dredd (USA).png",
                TitleMatcher.selectName("Judge Dredd: The Movie", catalog, claimed()),
                "the only Judge Dredd on the platform is this game's box");
        TestSupport.equal("Doom Troopers (USA).png",
                TitleMatcher.selectName("Doom Troopers: Mutant Chronicles",
                        Collections.singletonList("Doom Troopers (USA).png"), claimed()),
                "and a catalog that omits the subtitle still resolves");
    }

    /**
     * A shorter name that several distinct entries extend is a series, not a
     * game. Phantasy Star IV must not be handed Phantasy Star's box.
     */
    private static void seriesRootsAreNeverGuessedAt() {
        List<String> catalog = Arrays.asList("Phantasy Star (Japan).png",
                "Phantasy Star II (USA, Europe).png",
                "Phantasy Star III - Generations of Doom (USA, Europe, Korea).png",
                "Phantasy Star IV (USA).png");
        TestSupport.equal(null,
                TitleMatcher.selectName("Phantasy Star: The End of the Millenium",
                        catalog, claimed()),
                "a numbered series root is never used as a subtitle fallback");
        TestSupport.equal("Phantasy Star II (USA, Europe).png",
                TitleMatcher.selectName("Phantasy Star II", catalog, claimed()),
                "while the numbered entries still match exactly");

        List<String> spider = Arrays.asList("Spider-Man (USA) (Sega).png",
                "Spider-Man (USA, Europe) (Acclaim).png",
                "Spider-Man . Venom - Maximum Carnage (World).png",
                "Spider-Man X-Men - Arcade's Revenge (USA, Europe).png");
        TestSupport.equal(null,
                TitleMatcher.selectName("Spider-Man: The Animated Series", spider, claimed()),
                "four different Spider-Man games means the short name names none of them");
    }

    /** Dump tags, leading articles and accents must not break a real match. */
    private static void regionAndArticleSpellingsStillMatch() {
        TestSupport.equal("Addams Family, The (USA, Europe).png",
                TitleMatcher.selectName("The Addams Family",
                        Arrays.asList("Addams Family, The (USA, Europe).png",
                                "Addams Family, The (Europe).png"), claimed()),
                "a trailing article in the catalog still matches a leading one");
        TestSupport.equal("Asterix and the Great Rescue (USA).png",
                TitleMatcher.selectName("Astérix and the Great Rescue",
                        Arrays.asList("Asterix and the Great Rescue (Europe).png",
                                "Asterix and the Great Rescue (USA).png"), null),
                "accents fold and USA still wins the region order");
        TestSupport.equal("ClayFighter (USA).png",
                TitleMatcher.selectName("ClayFighter",
                        Arrays.asList("Clay Fighter (USA).png", "ClayFighter (USA).png"), null),
                "the identical spelling beats the respaced one even though it sorts later");
    }

    /** "II" and "2" are the same instalment; "X" and "10" are not. */
    private static void collapsedNumeralsRespectTheInstalment() {
        TestSupport.equal("Gauntlet IV (USA, Europe) (En,Ja).png",
                TitleMatcher.selectName("Gauntlet 4",
                        Collections.singletonList("Gauntlet IV (USA, Europe) (En,Ja).png"), null),
                "an arabic ROM name still finds the roman catalog entry");
        TestSupport.equal("Golden Axe II (USA, Europe).png",
                TitleMatcher.selectName("Golden Axe 2",
                        Collections.singletonList("Golden Axe II (USA, Europe).png"), null),
                "and the same holds for a sequel");
        TestSupport.equal(null,
                TitleMatcher.selectName("Mega Man X",
                        Collections.singletonList("Mega Man 10 (USA).png"), null),
                "a lone X is a name, not the numeral ten");
        TestSupport.equal(null,
                TitleMatcher.selectName("Mega Man 10",
                        Collections.singletonList("Mega Man X (USA).png"), null),
                "and the reverse pairing is refused too");
        TestSupport.equal("2", TitleMatcher.sequelKey("golden axe ii"),
                "a roman instalment resolves");
        TestSupport.equal("?x", TitleMatcher.sequelKey("mega man x"),
                "a lone letter matches only the same letter");
    }

    /** A kiosk or prototype dump may not stand in for the retail release. */
    private static void specialBuildsStayOutOfRetailSlots() {
        TestSupport.equal(null,
                TitleMatcher.selectName("Sonic the Hedgehog 3",
                        Collections.singletonList("Sonic the Hedgehog 3 (USA) (Prototype).png"),
                        null),
                "a prototype dump is not the retail box");
        TestSupport.equal("Sonic the Hedgehog 3 (USA) (Prototype).png",
                TitleMatcher.selectName("Sonic the Hedgehog 3 (Prototype)",
                        Collections.singletonList("Sonic the Hedgehog 3 (USA) (Prototype).png"),
                        null),
                "unless the ROM itself asked for that build");
    }

    /**
     * The prune's probe asks a different question from the matcher: not "may
     * this artwork be attached" but "does artwork exist at all". A match the
     * matcher refuses out of caution must still count as artwork existing, or
     * the caution would turn into a deletion.
     */
    private static void artlessProbeIgnoresEveryGuard() {
        Set<String> claimed = claimed();
        List<String> catalog = Collections.singletonList("Uncharted Waters (USA).png");
        TestSupport.equal(null,
                TitleMatcher.selectName("Uncharted Waters: New Horizons", catalog, claimed),
                "the matcher declines to attach the first game's box");
        TestSupport.truth(TitleMatcher.hasAnyCandidate("Uncharted Waters: New Horizons", catalog),
                "but the probe still reports artwork, so nothing is deleted");
        TestSupport.truth(TitleMatcher.hasAnyCandidate("Phantasy Star: The End of the Millenium",
                        Collections.singletonList("Phantasy Star IV (USA).png")),
                "a series entry the matcher skipped is not evidence of absence");
        TestSupport.truth(!TitleMatcher.hasAnyCandidate("Action Replay Max",
                        Arrays.asList("Action 52 (USA) (Unl).png", "Aladdin (USA).png")),
                "a cheat cartridge really has nothing anywhere");
        TestSupport.truth(!TitleMatcher.hasAnyCandidate("Aladdin II",
                        Arrays.asList("Aladdin (USA).png", "Aladdin (Europe).png")),
                "and neither does the pirate sequel");
    }

    private static Set<String> claimed() {
        Set<String> titles = new LinkedHashSet<>(new ArrayList<>(GENESIS_LIBRARY));
        return TitleMatcher.claimedTitles(titles);
    }
}
