package com.thorium.preview.multiplayer;

import android.content.Context;

import com.thorium.lucent.cheats.CheatDatabase;
import com.thorium.preview.PreviewService;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.util.Map;

/**
 * {@code GET /multiplayer/roster?gameKey=X&system=Y}: this device's cached
 * "who wants to play" roster for one game, as last pushed by the backend's
 * {@code roster.update} message (see {@link
 * MultiplayerManager#onRosterUpdate}). Empty entries -- never an error --
 * when nothing has been cached yet, including the common case where no
 * backend is configured at all.
 *
 * <p>The wire field is called {@code gameKey} for the API contract, but the
 * QML client actually sends a raw game TITLE -- see
 * {@link MultiplayerWantEndpoint}'s doc comment for why this endpoint
 * normalizes (system, title) into the real key via
 * {@link CheatDatabase#key} rather than trusting the client's string
 * directly, the same way that endpoint does. {@code system} is required
 * here for exactly that reason, even though the roster lookup itself only
 * ever needs the resulting key.
 *
 * <p>Response: {@code {"ok":true,"gameKey":"X","entries":[{"deviceId":"...",
 * "nickname":"...","state":"wants"|"wanted","since":"...","minPlayers":N,
 * "maxPlayers":N},...]}}. {@code entries} is passed through verbatim from
 * the cached backend payload -- this endpoint does not reshape it.
 */
public final class MultiplayerRosterEndpoint {
    /** HTTP status line and JSON body for {@code PreviewService.respond}. */
    public static final class Result {
        public final String status;
        public final String body;

        Result(String status, String body) {
            this.status = status;
            this.body = body;
        }
    }

    private MultiplayerRosterEndpoint() {}

    public static Result handle(Context context, String query) {
        Map<String, String> values = MultiplayerQuery.parse(query);
        String title = values.getOrDefault("gameKey", "");
        String system = values.getOrDefault("system", "");
        String gameKey = CheatDatabase.key(system, title);
        MultiplayerManager manager = PreviewService.getMultiplayerManager();
        JSONObject cached = !title.isEmpty() && manager != null ? manager.rosterFor(gameKey) : null;
        JSONArray entries = cached != null ? cached.optJSONArray("entries") : null;
        try {
            JSONObject root = new JSONObject();
            root.put("ok", true);
            root.put("gameKey", gameKey);
            root.put("entries", entries != null ? entries : new JSONArray());
            return new Result("200 OK", root.toString());
        } catch (JSONException impossible) {
            return new Result("200 OK", "{\"ok\":true,\"gameKey\":\"\",\"entries\":[]}");
        }
    }
}
