package com.thorium.preview.multiplayer;

import android.content.Context;

import com.thorium.preview.PreviewService;

import java.util.Map;

/**
 * {@code GET /multiplayer/invite/respond?matchId=X&accept=1|0}: accepts or
 * declines a pending match invite, forwarded to the backend as {@code
 * invite.respond} (see {@link MultiplayerManager#respondToInvite}).
 * Response: {@code {"ok":true}}.
 */
public final class MultiplayerInviteEndpoint {
    /** HTTP status line and JSON body for {@code PreviewService.respond}. */
    public static final class Result {
        public final String status;
        public final String body;

        Result(String status, String body) {
            this.status = status;
            this.body = body;
        }
    }

    private MultiplayerInviteEndpoint() {}

    public static Result handle(Context context, String query) {
        Map<String, String> values = MultiplayerQuery.parse(query);
        String matchId = values.getOrDefault("matchId", "");
        boolean accept = MultiplayerQuery.parseBool(values, "accept", false);
        MultiplayerManager manager = PreviewService.getMultiplayerManager();
        if (manager != null) manager.respondToInvite(matchId, accept);
        return new Result("200 OK", "{\"ok\":true}");
    }
}
