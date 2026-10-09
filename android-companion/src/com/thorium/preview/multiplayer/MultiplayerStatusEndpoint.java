package com.thorium.preview.multiplayer;

import android.content.Context;

import com.thorium.preview.PreviewService;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/**
 * {@code GET /multiplayer/status}: the one aggregate poll endpoint --
 * backend configuration/connection state plus every pending invite and
 * scheduled match this device currently knows about, and the active match
 * id if a netplay session is live. See {@link
 * MultiplayerManager#statusSnapshot}.
 *
 * <p>Response: {@code {"ok":true,"configured":true|false,"connected":
 * true|false,"invites":[...raw invite.available payloads...],"scheduled":
 * [...raw match.scheduled payloads...],"activeMatchId":"..."|null}}.
 */
public final class MultiplayerStatusEndpoint {
    /** HTTP status line and JSON body for {@code PreviewService.respond}. */
    public static final class Result {
        public final String status;
        public final String body;

        Result(String status, String body) {
            this.status = status;
            this.body = body;
        }
    }

    private MultiplayerStatusEndpoint() {}

    public static Result handle(Context context, String query) {
        MultiplayerManager manager = PreviewService.getMultiplayerManager();
        try {
            JSONObject root;
            if (manager != null) {
                root = manager.statusSnapshot();
            } else {
                // The manager is only ever null in the brief window before
                // PreviewService.onCreate() has run; still answer safely
                // rather than surfacing that startup race to a caller.
                root = new JSONObject();
                root.put("ok", true);
                root.put("configured", MultiplayerConfig.isConfigured(context));
                root.put("connected", false);
                root.put("invites", new JSONArray());
                root.put("scheduled", new JSONArray());
                root.put("activeMatchId", JSONObject.NULL);
            }
            return new Result("200 OK", root.toString());
        } catch (JSONException impossible) {
            return new Result("200 OK",
                    "{\"ok\":false,\"error\":\"cannot serialise multiplayer status\"}");
        }
    }
}
