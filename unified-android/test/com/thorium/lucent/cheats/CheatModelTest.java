package com.thorium.lucent.cheats;

import com.thorium.lucent.TestSupport;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;

/** Host tests for the cheat model: title matching, selection, and code order. */
public final class CheatModelTest {

    public static void main(String[] args) {
        titleMatchingIgnoresScraperTags();
        titleMatchingIgnoresPathAndExtension();
        differentGamesDoNotCollide();
        selectionKeepsAuthoredOrderNotToggleOrder();
        selectionRejectsUnknownIds();
        restoreDropsIdsTheDatabaseNoLongerHas();
        System.out.println("CheatModelTest passed");
    }

    private static Cheat cheat(String id, String code) {
        return new Cheat(id, id, "", code);
    }

    private static CheatDatabase database() {
        Map<CheatDatabase.GameId, List<Cheat>> games = new HashMap<>();
        games.put(new CheatDatabase.GameId("snes", "Super Mario World"),
                Arrays.asList(cheat("lives", "7E0DBE:63"), cheat("coins", "7E0DBF:63")));
        games.put(new CheatDatabase.GameId("nes", "Contra"),
                Arrays.asList(cheat("lives", "SXIOPO")));
        return CheatDatabase.of(games);
    }

    /** Region and revision tags differ across dumps while the codes do not. */
    private static void titleMatchingIgnoresScraperTags() {
        CheatDatabase db = database();
        for (String variant : new String[]{
                "Super Mario World", "super mario world", "Super Mario World (USA)",
                "Super Mario World (USA) [!]", "Super Mario World (Europe) (Rev 1)",
                "  Super  Mario  World  "}) {
            TestSupport.equal(2, db.forGame("snes", variant).size(),
                    "variant should resolve: " + variant);
        }
    }

    private static void titleMatchingIgnoresPathAndExtension() {
        CheatDatabase db = database();
        TestSupport.equal(2, db.forGame("snes", "/roms/snes/Super Mario World.sfc").size(),
                "a full path with an extension should still match");
        TestSupport.equal(2, db.forGame("SNES", "Super-Mario-World.smc").size(),
                "system case and punctuation should not matter");
    }

    /** Normalisation must not be so aggressive that distinct games merge. */
    private static void differentGamesDoNotCollide() {
        CheatDatabase db = database();
        TestSupport.truth(db.forGame("snes", "Super Mario Kart").isEmpty(),
                "a different title must not match");
        TestSupport.truth(db.forGame("nes", "Super Mario World").isEmpty(),
                "the same title on another system must not match");
        TestSupport.equal(1, db.forGame("nes", "Contra").size(), "nes Contra resolves");
    }

    /**
     * Cheats that patch overlapping addresses depend on which is applied last,
     * so the order must be the database's, not the order the user tapped them.
     */
    private static void selectionKeepsAuthoredOrderNotToggleOrder() {
        CheatSelection selection = new CheatSelection(
                database().forGame("snes", "Super Mario World"));
        selection.setEnabled("coins", true);
        selection.setEnabled("lives", true);
        TestSupport.equal(Arrays.asList("7E0DBE:63", "7E0DBF:63"), selection.enabledCodes(),
                "codes follow authored order");
        selection.setEnabled("lives", false);
        TestSupport.equal(Arrays.asList("7E0DBF:63"), selection.enabledCodes(),
                "disabling drops just that code");
        TestSupport.equal(1, selection.enabledCount(), "one cheat left enabled");
    }

    private static void selectionRejectsUnknownIds() {
        CheatSelection selection = new CheatSelection(
                database().forGame("snes", "Super Mario World"));
        selection.setEnabled("not-in-this-game", true);
        TestSupport.truth(!selection.isEnabled("not-in-this-game"), "unknown id is ignored");
        TestSupport.truth(selection.enabledCodes().isEmpty(), "no codes from unknown ids");
    }

    /** A stale saved selection must not resurrect cheats that were removed. */
    private static void restoreDropsIdsTheDatabaseNoLongerHas() {
        CheatSelection selection = new CheatSelection(
                database().forGame("nes", "Contra"));
        selection.restore(new LinkedHashSet<>(Arrays.asList("lives", "removed-cheat")));
        TestSupport.truth(selection.isEnabled("lives"), "known id restores");
        TestSupport.truth(!selection.isEnabled("removed-cheat"), "unknown id is dropped");
        TestSupport.equal(new LinkedHashSet<>(new ArrayList<>(Arrays.asList("lives"))),
                selection.enabledIds(), "only known ids persist");
    }
}
