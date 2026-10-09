package com.thorium.lucent.cheats;

import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

/**
 * Which row a cheat panel is pointing at, and what each row currently reads.
 *
 * <p>Selection lives here rather than in either panel because the same list is
 * drawn in two places — over the game on a single-screen device, and on the
 * Thor's lower display while the game keeps running — and a D-pad press from
 * the game host has to move both. Keeping the index next to the list is also
 * what makes the wrap-around and the out-of-range cases testable on the host,
 * where the panels themselves cannot be constructed at all.
 *
 * <p>The enabled set is refreshed from the running engine after every toggle
 * rather than being flipped locally: a core that refuses a cheat must not leave
 * a row showing a switch position the game is not in.
 */
public final class CheatPanelModel {

    /** Keeps both Android panels bounded even for 30,000-code N64 sets. */
    public static final int PAGE_SIZE = 96;

    private static final String NOTHING_TO_SHOW =
            "This game has no cheats in EmuFusion's database.";

    private final List<Cheat> cheats = new ArrayList<>();
    private final Set<String> enabled = new LinkedHashSet<>();
    private String title = "";
    private int selected;

    /** Replaces the list and starts at the top, as reopening the panel does. */
    public void load(String gameTitle, List<Cheat> available, Set<String> enabledIds) {
        title = gameTitle == null ? "" : gameTitle;
        cheats.clear();
        if (available != null) cheats.addAll(available);
        selected = 0;
        setEnabledIds(enabledIds);
    }

    /**
     * Re-reads which cheats are on, keeping the selection where it is.
     *
     * <p>Ids the list no longer offers are dropped: a stale id would count
     * towards nothing on screen while still making the panel claim a cheat was
     * on.
     */
    public void setEnabledIds(Set<String> enabledIds) {
        enabled.clear();
        if (enabledIds == null) return;
        for (Cheat cheat : cheats)
            if (enabledIds.contains(cheat.id)) enabled.add(cheat.id);
    }

    public boolean isEmpty() { return cheats.isEmpty(); }

    public int size() { return cheats.size(); }

    public String title() { return title; }

    public int selectedIndex() { return selected; }

    /** Null only when the game has no cheats at all. */
    public Cheat selectedCheat() {
        return cheats.isEmpty() ? null : cheats.get(selected);
    }

    public Cheat cheatAt(int index) {
        return index < 0 || index >= cheats.size() ? null : cheats.get(index);
    }

    public boolean isEnabled(String cheatId) { return enabled.contains(cheatId); }

    /** Wraps, so a pad can reach the last row by pressing up once. */
    public void moveSelection(int direction) {
        if (cheats.isEmpty()) return;
        selected = ((selected + direction) % cheats.size() + cheats.size()) % cheats.size();
    }

    /** Ignores an index off the end rather than throwing: a touch on the lower
     * display can arrive one frame after the list shrank. */
    public void select(int index) {
        if (index < 0 || index >= cheats.size()) return;
        selected = index;
    }

    public CheatPanelSnapshot snapshot() {
        int first = cheats.isEmpty() ? 0 : (selected / PAGE_SIZE) * PAGE_SIZE;
        int end = Math.min(cheats.size(), first + PAGE_SIZE);
        List<CheatPanelSnapshot.Row> rows = new ArrayList<>(end - first);
        for (int index = first; index < end; index++) {
            Cheat cheat = cheats.get(index);
            rows.add(new CheatPanelSnapshot.Row(
                    cheat.name, cheat.description, enabled.contains(cheat.id)));
        }
        return new CheatPanelSnapshot(title, rows, selected - first,
                cheats.isEmpty() ? NOTHING_TO_SHOW : "", first, cheats.size());
    }

    public Set<String> enabledIds() {
        return Collections.unmodifiableSet(new LinkedHashSet<>(enabled));
    }
}
