package com.thorium.preview.game;

import android.content.Intent;

/**
 * The exact frontend selection to reveal after emulation finishes.
 *
 * The frontend remains alive below EmuFusionGameActivity in the normal path, so
 * this state is primarily a recovery contract for process/task recreation.
 */
public final class SessionReturnState {
    public static final String EXTRA_PREFIX = "lucent.return.";
    public static final SessionReturnState EMPTY = new SessionReturnState(
            "", "", "", "", "", -1, -1, "");

    public final String view;
    public final String systemId;
    public final String section;
    public final String sort;
    public final String gameId;
    public final int systemIndex;
    public final int gameIndex;
    public final String navigationToken;

    public SessionReturnState(String view, String systemId, String section,
                              String sort, String gameId, int systemIndex,
                              int gameIndex, String navigationToken) {
        this.view = clean(view);
        this.systemId = clean(systemId);
        this.section = clean(section);
        this.sort = clean(sort);
        this.gameId = clean(gameId);
        this.systemIndex = systemIndex;
        this.gameIndex = gameIndex;
        this.navigationToken = clean(navigationToken);
    }

    public boolean isEmpty() {
        return view.isEmpty() && systemId.isEmpty() && gameId.isEmpty()
                && navigationToken.isEmpty();
    }

    public void putInto(Intent intent) {
        intent.putExtra(EXTRA_PREFIX + "view", view)
                .putExtra(EXTRA_PREFIX + "system", systemId)
                .putExtra(EXTRA_PREFIX + "section", section)
                .putExtra(EXTRA_PREFIX + "sort", sort)
                .putExtra(EXTRA_PREFIX + "game", gameId)
                .putExtra(EXTRA_PREFIX + "system_index", systemIndex)
                .putExtra(EXTRA_PREFIX + "game_index", gameIndex)
                .putExtra(EXTRA_PREFIX + "token", navigationToken);
    }

    public static SessionReturnState from(Intent intent) {
        if (intent == null) return EMPTY;
        return new SessionReturnState(
                intent.getStringExtra(EXTRA_PREFIX + "view"),
                intent.getStringExtra(EXTRA_PREFIX + "system"),
                intent.getStringExtra(EXTRA_PREFIX + "section"),
                intent.getStringExtra(EXTRA_PREFIX + "sort"),
                intent.getStringExtra(EXTRA_PREFIX + "game"),
                intent.getIntExtra(EXTRA_PREFIX + "system_index", -1),
                intent.getIntExtra(EXTRA_PREFIX + "game_index", -1),
                intent.getStringExtra(EXTRA_PREFIX + "token"));
    }

    private static String clean(String value) {
        return value == null ? "" : value.trim();
    }
}
