package com.thorium.lucent.netplay;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/**
 * The JSON envelope exchanged over one persistent WebSocket connection to
 * the multiplayer backend, matching backend/internal/protocol/messages.go
 * exactly: {@code {"type": "...", "payload": {...}}}. This class only
 * carries the envelope itself; callers build/read the type-specific
 * payload object directly, the same way the Go side treats it as
 * {@code json.RawMessage} until dispatch.
 *
 * <p>Uses {@code org.json} (already on the Android platform, and already
 * the convention used by the companion process's own settings endpoints,
 * e.g. WidescreenHackEndpoint) rather than adding a JSON library
 * dependency for this.
 */
public final class NetplayMessage {
    public final String type;
    public final JSONObject payload;

    public NetplayMessage(String type, JSONObject payload) {
        if (type == null || type.isEmpty())
            throw new IllegalArgumentException("message type is required");
        this.type = type;
        this.payload = payload != null ? payload : new JSONObject();
    }

    public String toWire() {
        try {
            JSONObject envelope = new JSONObject();
            envelope.put("type", type);
            envelope.put("payload", payload);
            return envelope.toString();
        } catch (JSONException impossible) {
            throw new IllegalStateException(impossible);
        }
    }

    public static NetplayMessage fromWire(String raw) throws JSONException {
        JSONObject envelope = new JSONObject(raw);
        String type = envelope.getString("type");
        JSONObject payload = envelope.optJSONObject("payload");
        return new NetplayMessage(type, payload);
    }

    // ---- Client -> server payload builders ----

    public static NetplayMessage heartbeat() {
        return new NetplayMessage("heartbeat", new JSONObject());
    }

    public static NetplayMessage wantSet(String gameKey, String system, boolean want,
                                          int minPlayers, int maxPlayers) {
        try {
            JSONObject payload = new JSONObject();
            payload.put("gameKey", gameKey);
            payload.put("system", system);
            payload.put("want", want);
            payload.put("minPlayers", minPlayers);
            payload.put("maxPlayers", maxPlayers);
            return new NetplayMessage("want.set", payload);
        } catch (JSONException impossible) {
            throw new IllegalStateException(impossible);
        }
    }

    public static NetplayMessage scheduleSubmit(String gameKey, String system,
                                                 JSONArray windows, int minPlayers, int maxPlayers) {
        try {
            JSONObject payload = new JSONObject();
            payload.put("gameKey", gameKey);
            payload.put("system", system);
            payload.put("windows", windows);
            payload.put("minPlayers", minPlayers);
            payload.put("maxPlayers", maxPlayers);
            return new NetplayMessage("schedule.submit", payload);
        } catch (JSONException impossible) {
            throw new IllegalStateException(impossible);
        }
    }

    public static NetplayMessage scheduleCancel(String scheduleId) {
        try {
            JSONObject payload = new JSONObject();
            payload.put("scheduleId", scheduleId);
            return new NetplayMessage("schedule.cancel", payload);
        } catch (JSONException impossible) {
            throw new IllegalStateException(impossible);
        }
    }

    public static NetplayMessage inviteRespond(String matchId, boolean accept) {
        try {
            JSONObject payload = new JSONObject();
            payload.put("matchId", matchId);
            payload.put("accept", accept);
            return new NetplayMessage("invite.respond", payload);
        } catch (JSONException impossible) {
            throw new IllegalStateException(impossible);
        }
    }

    public static NetplayMessage claimHost(String matchId) {
        try {
            JSONObject payload = new JSONObject();
            payload.put("matchId", matchId);
            payload.put("role", "host");
            return new NetplayMessage("match.role_claim", payload);
        } catch (JSONException impossible) {
            throw new IllegalStateException(impossible);
        }
    }

    public static NetplayMessage signal(String matchId, String toDeviceId, JSONObject signalPayload) {
        try {
            JSONObject payload = new JSONObject();
            payload.put("matchId", matchId);
            payload.put("toDeviceId", toDeviceId);
            payload.put("payload", signalPayload);
            return new NetplayMessage("signal", payload);
        } catch (JSONException impossible) {
            throw new IllegalStateException(impossible);
        }
    }
}
