package com.thorium.preview.multiplayer;

import android.content.Context;

import com.thorium.lucent.cheats.CheatDatabase;
import com.thorium.preview.PreviewService;

import java.util.Map;

/**
 * {@code GET /multiplayer/want?gameKey=X&system=Y&want=1|0&minPlayers=N&
 * maxPlayers=N}: declares (or withdraws) this device's interest in playing
 * one game online, forwarded to the backend as {@code want.set} (see
 * {@link MultiplayerManager#setWant}). A no-op, not an error, while no
 * backend is connected -- the response is unconditionally {@code
 * {"ok":true}}.
 *
 * <p>The wire field is called {@code gameKey} for the API contract, but the
 * QML client actually sends a raw game TITLE (there is no cross-device
 * identity reachable from QML today) -- this endpoint is the single place
 * that normalizes (system, title) into the real key via
 * {@link CheatDatabase#key}, the exact same function
 * {@code MultiplayerOverlay} (the in-game side, unified-android) already
 * uses from the launch request's own (systemId, gameTitle). Both sides
 * landing on the same Java function is what makes "is the invited game
 * currently running" actually work; computing it independently on both
 * sides (a file path here, a normalized title there) was a real bug this
 * session found and fixed.
 */
public final class MultiplayerWantEndpoint {
    /** HTTP status line and JSON body for {@code PreviewService.respond}. */
    public static final class Result {
        public final String status;
        public final String body;

        Result(String status, String body) {
            this.status = status;
            this.body = body;
        }
    }

    private MultiplayerWantEndpoint() {}

    public static Result handle(Context context, String query) {
        Map<String, String> values = MultiplayerQuery.parse(query);
        String title = values.getOrDefault("gameKey", "");
        String system = values.getOrDefault("system", "");
        String canonicalKey = CheatDatabase.key(system, title);
        boolean want = MultiplayerQuery.parseBool(values, "want", false);
        int minPlayers = MultiplayerQuery.parseInt(values, "minPlayers", 2);
        int maxPlayers = MultiplayerQuery.parseInt(values, "maxPlayers", 2);
        MultiplayerManager manager = PreviewService.getMultiplayerManager();
        if (manager != null) manager.setWant(canonicalKey, system, want, minPlayers, maxPlayers);
        return new Result("200 OK", "{\"ok\":true}");
    }
}
