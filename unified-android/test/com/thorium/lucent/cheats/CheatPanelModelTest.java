package com.thorium.lucent.cheats;

import com.thorium.lucent.TestSupport;

import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashSet;
import java.util.List;

/**
 * Host tests for the panel the pad drives — the half of the cheats feature that
 * can be exercised without a device or a second display.
 */
public final class CheatPanelModelTest {

    public static void main(String[] args) {
        selectionWrapsInBothDirections();
        selectionSurvivesAnEnabledRefresh();
        outOfRangeSelectionIsIgnored();
        snapshotReportsWhatEachRowReads();
        snapshotIsFrozenAgainstLaterChanges();
        aGameWithNoCheatsSaysSoAndSwallowsMovement();
        detailFallsBackWhenACheatHasNoDescription();
        staleEnabledIdsAreDropped();
        hugeCataloguesArePagedWithoutLosingGlobalSelection();
        System.out.println("CheatPanelModelTest passed");
    }

    private static Cheat cheat(String id, String description) {
        return new Cheat(id, id + " name", description, "CODE-" + id);
    }

    private static List<Cheat> three() {
        return Arrays.asList(cheat("lives", "Lives never decrease."),
                cheat("magic", ""), cheat("rupees", "Sets the counter."));
    }

    private static CheatPanelModel loaded() {
        CheatPanelModel model = new CheatPanelModel();
        model.load("Zelda", three(), new LinkedHashSet<>(Arrays.asList("magic")));
        return model;
    }

    /** Up from the first row must reach the last, or a long list has a dead end. */
    private static void selectionWrapsInBothDirections() {
        CheatPanelModel model = loaded();
        TestSupport.equal(0, model.selectedIndex(), "opens on the first row");
        model.moveSelection(-1);
        TestSupport.equal(2, model.selectedIndex(), "up from the top wraps to the last row");
        model.moveSelection(1);
        TestSupport.equal(0, model.selectedIndex(), "down from the last row wraps to the top");
        model.moveSelection(2);
        TestSupport.equal(2, model.selectedIndex(), "a two-step move still lands in range");
    }

    /**
     * The engine is re-read after every toggle. If that reset the cursor, each
     * toggle would throw the user back to the first row.
     */
    private static void selectionSurvivesAnEnabledRefresh() {
        CheatPanelModel model = loaded();
        model.moveSelection(2);
        model.setEnabledIds(new LinkedHashSet<>(Arrays.asList("lives", "rupees")));
        TestSupport.equal(2, model.selectedIndex(), "the cursor stays on the toggled row");
        TestSupport.truth(model.isEnabled("rupees"), "the refreshed state is visible");
        TestSupport.truth(!model.isEnabled("magic"), "a cheat the engine dropped goes off");
    }

    private static void outOfRangeSelectionIsIgnored() {
        CheatPanelModel model = loaded();
        model.select(1);
        model.select(9);
        TestSupport.equal(1, model.selectedIndex(), "an index past the end is refused");
        model.select(-1);
        TestSupport.equal(1, model.selectedIndex(), "a negative index is refused");
    }

    private static void snapshotReportsWhatEachRowReads() {
        CheatPanelSnapshot snapshot = loaded().snapshot();
        TestSupport.equal(3, snapshot.rows.size(), "one row per cheat");
        TestSupport.equal("Zelda", snapshot.title, "the panel is titled with the game");
        TestSupport.equal("lives name   •   OFF", snapshot.rows.get(0).label(),
                "an off cheat reads OFF");
        TestSupport.equal("magic name   •   ON", snapshot.rows.get(1).label(),
                "an on cheat reads ON");
        TestSupport.truth(snapshot.message.isEmpty(),
                "a game with cheats carries no empty-state message");
    }

    /**
     * The lower display draws from a snapshot handed across from the game host.
     * A snapshot that tracked the live model could redraw one screen against a
     * selection the other has already moved past.
     */
    private static void snapshotIsFrozenAgainstLaterChanges() {
        CheatPanelModel model = loaded();
        CheatPanelSnapshot before = model.snapshot();
        model.moveSelection(1);
        model.setEnabledIds(new LinkedHashSet<>(Arrays.asList("lives")));
        TestSupport.equal(0, before.selected, "the old snapshot keeps its selection");
        TestSupport.truth(!before.rows.get(0).enabled, "the old snapshot keeps its states");
        TestSupport.equal(1, model.snapshot().selected, "a new snapshot has the new one");
    }

    private static void aGameWithNoCheatsSaysSoAndSwallowsMovement() {
        CheatPanelModel model = new CheatPanelModel();
        model.load("Unknown Game", Collections.<Cheat>emptyList(), null);
        TestSupport.truth(model.isEmpty(), "an empty catalogue entry is empty");
        TestSupport.truth(model.selectedCheat() == null, "there is nothing to select");
        model.moveSelection(1);
        TestSupport.equal(0, model.selectedIndex(), "movement cannot leave row zero");
        CheatPanelSnapshot snapshot = model.snapshot();
        TestSupport.truth(snapshot.isEmpty(), "the snapshot is empty too");
        TestSupport.truth(!snapshot.message.isEmpty(),
                "the panel must be able to explain itself rather than draw nothing");
        TestSupport.equal(snapshot.message, snapshot.detail(),
                "the detail line carries the explanation");
    }

    private static void detailFallsBackWhenACheatHasNoDescription() {
        CheatPanelModel model = loaded();
        TestSupport.equal("Lives never decrease.", model.snapshot().detail(),
                "an authored description is shown as written");
        model.moveSelection(1);
        TestSupport.truth(model.snapshot().detail().contains("Applies while the game runs"),
                "an undescribed cheat still gets a line");
    }

    /** A selection saved before a database update must not claim a cheat is on. */
    private static void staleEnabledIdsAreDropped() {
        CheatPanelModel model = new CheatPanelModel();
        model.load("Zelda", three(),
                new LinkedHashSet<>(Arrays.asList("lives", "cheat-that-was-removed")));
        TestSupport.equal(new LinkedHashSet<>(Arrays.asList("lives")), model.enabledIds(),
                "only ids this game still offers survive");
    }

    private static void hugeCataloguesArePagedWithoutLosingGlobalSelection() {
        java.util.ArrayList<Cheat> values = new java.util.ArrayList<>();
        for (int index = 0; index < 30_911; index++)
            values.add(cheat("large-" + index, "Large set"));
        CheatPanelModel model = new CheatPanelModel();
        model.load("Turok", values, null);
        model.select(30_910);
        CheatPanelSnapshot snapshot = model.snapshot();
        TestSupport.truth(snapshot.rows.size() <= CheatPanelModel.PAGE_SIZE,
                "a giant database must not allocate thirty thousand Android rows");
        TestSupport.equal(30_911, snapshot.totalCount, "paging lost catalogue rows");
        TestSupport.equal(30_910, snapshot.firstIndex + snapshot.selected,
                "page-local selection no longer identifies the global cheat");
        TestSupport.truth(snapshot.detail().contains("30911 of 30911"),
                "a paged list must tell the user where they are");
    }
}
