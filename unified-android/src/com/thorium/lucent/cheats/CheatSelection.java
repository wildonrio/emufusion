package com.thorium.lucent.cheats;

import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

/**
 * Which cheats are switched on for one game, and the ordered code list the core
 * is given.
 *
 * <p>Selection is stored as cheat ids, not as codes or slot numbers. Ids survive
 * a database update that reorders, renames or re-codes an entry; slots do not,
 * and a stored slot would silently start pointing at a different cheat.
 */
public final class CheatSelection {

    private final List<Cheat> available;
    private final Set<String> enabled = new LinkedHashSet<>();

    public CheatSelection(List<Cheat> available) {
        this.available = available == null
                ? Collections.<Cheat>emptyList() : new ArrayList<>(available);
    }

    public List<Cheat> available() { return Collections.unmodifiableList(available); }

    public boolean isEnabled(String cheatId) { return enabled.contains(cheatId); }

    /** Ignores ids the database no longer offers, so stale saves cannot resurrect them. */
    public void setEnabled(String cheatId, boolean on) {
        if (cheatId == null) return;
        boolean known = false;
        for (Cheat cheat : available) if (cheat.id.equals(cheatId)) { known = true; break; }
        if (!known) return;
        if (on) enabled.add(cheatId); else enabled.remove(cheatId);
    }

    public void restore(Set<String> enabledIds) {
        enabled.clear();
        if (enabledIds == null) return;
        for (String id : enabledIds) setEnabled(id, true);
    }

    public Set<String> enabledIds() {
        return Collections.unmodifiableSet(new LinkedHashSet<>(enabled));
    }

    /**
     * Codes for the enabled cheats, in the database's own order rather than the
     * order the user toggled them. Cheats that patch overlapping addresses can
     * depend on which is applied last, so the order has to be the authored one
     * to stay reproducible between sessions.
     */
    public List<String> enabledCodes() {
        List<String> codes = new ArrayList<>();
        for (Cheat cheat : available) if (enabled.contains(cheat.id)) codes.add(cheat.code);
        return codes;
    }

    public int enabledCount() { return enabled.size(); }
}
