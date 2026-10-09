package com.thorium.preview.multiplayer;

import android.content.Context;

import com.thorium.lucent.cheats.CheatDatabase;
import com.thorium.preview.PreviewService;

import org.json.JSONArray;
import org.json.JSONException;

import java.util.Map;

/**
 * {@code GET /multiplayer/schedule/submit} and {@code GET
 * /multiplayer/schedule/cancel}: grouped in one class because both just
 * forward straight to {@link MultiplayerManager}'s own schedule methods and
 * share nothing else with the other endpoints.
 */
public final class MultiplayerScheduleEndpoint {
    /** HTTP status line and JSON body for {@code PreviewService.respond}. */
    public static final class Result {
        public final String status;
        public final String body;

        Result(String status, String body) {
            this.status = status;
            this.body = body;
        }
    }

    private MultiplayerScheduleEndpoint() {}

    /**
     * {@code ?gameKey=X&system=Y&minPlayers=N&maxPlayers=N&windows=<url-encoded
     * JSON array of {"start":"RFC3339","end":"RFC3339"}>}.
     *
     * <p>Response: {@code {"ok":true}}, or {@code {"ok":false,"error":"..."}}
     * if {@code windows} does not parse as a JSON array.
     */
    public static Result submit(Context context, String query) {
        Map<String, String> values = MultiplayerQuery.parse(query);
        // "gameKey" carries a raw title over the wire, normalized here the
        // same way as MultiplayerWantEndpoint/MultiplayerRosterEndpoint --
        // see MultiplayerWantEndpoint's doc comment for why.
        String title = values.getOrDefault("gameKey", "");
        String system = values.getOrDefault("system", "");
        String canonicalKey = CheatDatabase.key(system, title);
        int minPlayers = MultiplayerQuery.parseInt(values, "minPlayers", 2);
        int maxPlayers = MultiplayerQuery.parseInt(values, "maxPlayers", 2);
        String windowsRaw = values.getOrDefault("windows", "");
        JSONArray windows;
        try {
            windows = new JSONArray(windowsRaw.trim().isEmpty() ? "[]" : windowsRaw);
        } catch (JSONException malformed) {
            return new Result("200 OK",
                    "{\"ok\":false,\"error\":\"windows must be a JSON array\"}");
        }
        MultiplayerManager manager = PreviewService.getMultiplayerManager();
        if (manager != null) manager.submitSchedule(canonicalKey, system, windows, minPlayers, maxPlayers);
        return new Result("200 OK", "{\"ok\":true}");
    }

    /** {@code ?scheduleId=X}. Response: {@code {"ok":true}}. */
    public static Result cancel(Context context, String query) {
        Map<String, String> values = MultiplayerQuery.parse(query);
        String scheduleId = values.getOrDefault("scheduleId", "");
        MultiplayerManager manager = PreviewService.getMultiplayerManager();
        if (manager != null) manager.cancelSchedule(scheduleId);
        return new Result("200 OK", "{\"ok\":true}");
    }
}
