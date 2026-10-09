package com.thorium.preview.multiplayer;

import android.content.Context;

import org.json.JSONException;
import org.json.JSONObject;

import java.util.Map;

/**
 * {@code GET /multiplayer/identity[?nickname=X]}: this device's multiplayer
 * identity, and the one place a caller can set the nickname later sent to
 * the backend at registration (see {@link DeviceIdentity}).
 *
 * <p>Response: {@code {"ok":true,"deviceId":"...","nickname":"...",
 * "configured":true|false}}. {@code configured} mirrors {@link
 * MultiplayerConfig#isConfigured}; {@code deviceId} is empty until this
 * device has actually registered with a backend (see {@link
 * DeviceIdentity#ensureRegistered}, which only ever runs once a backend is
 * configured). {@code nickname} is always readable/settable -- it is a
 * plain local preference with a built-in default and never requires a
 * network round trip -- so a caller can pre-fill it before a backend is
 * ever configured.
 */
public final class MultiplayerIdentityEndpoint {
    /** HTTP status line and JSON body for {@code PreviewService.respond}. */
    public static final class Result {
        public final String status;
        public final String body;

        Result(String status, String body) {
            this.status = status;
            this.body = body;
        }
    }

    private MultiplayerIdentityEndpoint() {}

    public static Result handle(Context context, String query) {
        Map<String, String> values = MultiplayerQuery.parse(query);
        if (values.containsKey("nickname")) {
            DeviceIdentity.setNickname(context, values.get("nickname"));
        }
        boolean configured = MultiplayerConfig.isConfigured(context);
        String deviceId = configured ? nullToEmpty(DeviceIdentity.deviceId(context)) : "";
        String nickname = DeviceIdentity.nickname(context);
        try {
            JSONObject root = new JSONObject();
            root.put("ok", true);
            root.put("deviceId", deviceId);
            root.put("nickname", nickname);
            root.put("configured", configured);
            return new Result("200 OK", root.toString());
        } catch (JSONException impossible) {
            return new Result("200 OK",
                    "{\"ok\":false,\"error\":\"cannot serialise multiplayer identity\"}");
        }
    }

    private static String nullToEmpty(String value) {
        return value != null ? value : "";
    }
}
