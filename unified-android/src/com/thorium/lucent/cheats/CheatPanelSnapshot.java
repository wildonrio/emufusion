package com.thorium.lucent.cheats;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * Everything a cheat panel needs to draw itself, frozen at one instant.
 *
 * <p>This exists because the panel is drawn on the Thor's lower display by a
 * different Activity than the one that owns the running game. Handing that
 * Activity the live model would let it read a selection that the game host is
 * halfway through changing; handing it an immutable copy means the two screens
 * can never disagree about what the pad is pointing at.
 *
 * <p>{@link #message} carries the empty case rather than leaving the caller to
 * invent wording: a game with no cheats still has to say so on screen, and the
 * two panels that render this must say the same thing.
 */
public final class CheatPanelSnapshot {

    /** One toggle row, already reduced to what is drawn. */
    public static final class Row {
        public final String name;
        public final String description;
        public final boolean enabled;

        public Row(String name, String description, boolean enabled) {
            this.name = name == null ? "" : name;
            this.description = description == null ? "" : description;
            this.enabled = enabled;
        }

        /** The row's own text, so both panels label a toggle identically. */
        public String label() {
            return name + "   •   " + (enabled ? "ON" : "OFF");
        }
    }

    public final String title;
    public final List<Row> rows;
    /** Index into {@link #rows}; 0 when there are none. */
    public final int selected;
    /** Global catalogue index represented by {@code rows.get(0)}. */
    public final int firstIndex;
    /** Full deduplicated catalogue size, including rows outside this page. */
    public final int totalCount;
    /** Non-empty only when there is nothing to show. */
    public final String message;

    public CheatPanelSnapshot(String title, List<Row> rows, int selected, String message) {
        this(title, rows, selected, message, 0, rows == null ? 0 : rows.size());
    }

    public CheatPanelSnapshot(String title, List<Row> rows, int selected, String message,
                              int firstIndex, int totalCount) {
        this.title = title == null ? "" : title;
        this.rows = rows == null ? Collections.<Row>emptyList()
                : Collections.unmodifiableList(new ArrayList<>(rows));
        this.selected = this.rows.isEmpty() ? 0
                : Math.max(0, Math.min(selected, this.rows.size() - 1));
        this.firstIndex = this.rows.isEmpty() ? 0 : Math.max(0, firstIndex);
        this.totalCount = Math.max(this.rows.size(), totalCount);
        this.message = message == null ? "" : message;
    }

    public boolean isEmpty() { return rows.isEmpty(); }

    /**
     * The description line for the selected row.
     *
     * <p>Falls back to a general sentence rather than a blank line, because an
     * entry with no authored description would otherwise make the panel look
     * like it had failed to load half of itself.
     */
    public String detail() {
        if (rows.isEmpty()) return message;
        String description = rows.get(selected).description;
        String detail = description.isEmpty()
                ? "Applies while the game runs; turning it off restores the game."
                : description;
        return totalCount > rows.size()
                ? ("Code " + (firstIndex + selected + 1) + " of " + totalCount + " • " + detail)
                : detail;
    }
}
