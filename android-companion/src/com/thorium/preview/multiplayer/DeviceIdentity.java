package com.thorium.preview.multiplayer;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/**
 * This device's identity with the multiplayer backend: no accounts, no
 * login, nothing that identifies a real person. The backend itself
 * generates both the device ID (its primary key for presence/roster/
 * schedule rows) and a device secret (a bearer credential proving later
 * requests come from the same device that first registered -- stops a
 * stranger from accepting a match invite or reading a schedule addressed
 * to this device, without needing any password) via one {@code POST
 * /v1/register} call; this class's only job is to make that call exactly
 * once and remember the result.
 *
 * <p>The secret never leaves this class for anywhere but the backend's own
 * Authorization header -- the QML theme's identity endpoint never returns
 * it (see MultiplayerIdentityEndpoint).
 *
 * <p>Known, accepted alpha limitation: clearing app data regenerates the
 * device ID, which orphans any prior roster/schedule rows on the backend
 * for this device -- there is no recovery path for that today.
 *
 * <p><b>{@link #ensureRegistered} performs a blocking HTTP call and must
 * never be invoked from the main thread</b> -- callers already run on a
 * background thread for every other companion-process network operation
 * (see ImportManager), and this is no different.
 */
public final class DeviceIdentity {
    private static final String PREFERENCES = "multiplayer-identity";
    private static final String DEVICE_ID = "deviceId";
    private static final String SECRET = "secret";
    private static final String NICKNAME = "nickname";

    private DeviceIdentity() {}

    public static boolean hasIdentity(Context context) {
        return preferences(context).getString(DEVICE_ID, null) != null;
    }

    public static String deviceId(Context context) {
        return preferences(context).getString(DEVICE_ID, null);
    }

    public static String secret(Context context) {
        return preferences(context).getString(SECRET, null);
    }

    public static String nickname(Context context) {
        String stored = preferences(context).getString(NICKNAME, null);
        return stored != null && !stored.trim().isEmpty() ? stored : "Player";
    }

    public static synchronized void setNickname(Context context, String nickname) {
        String trimmed = nickname == null ? "" : nickname.trim();
        if (trimmed.length() > 40) trimmed = trimmed.substring(0, 40);
        preferences(context).edit().putString(NICKNAME, trimmed).commit();
    }

    /**
     * Registers with the configured backend if this device has never
     * registered before, storing the deviceId/secret/nickname it returns.
     * A no-op (and immediately successful) if identity already exists --
     * registration happens exactly once per install, ever.
     *
     * @throws IOException if the backend is unreachable or rejects the request;
     *         callers should treat this the same as "multiplayer unavailable
     *         right now" rather than a fatal error.
     * @throws IllegalStateException if no backend is configured (see MultiplayerConfig)
     */
    public static synchronized void ensureRegistered(Context context) throws IOException {
        if (hasIdentity(context)) return;
        String baseUrl = MultiplayerConfig.backendBaseUrl(context);
        if (baseUrl.isEmpty())
            throw new IllegalStateException("no multiplayer backend configured");

        JSONObject requestBody = new JSONObject();
        try {
            requestBody.put("nickname", nickname(context));
        } catch (JSONException impossible) {
            throw new IllegalStateException(impossible);
        }

        HttpURLConnection connection = (HttpURLConnection) new URL(baseUrl + "/v1/register").openConnection();
        connection.setRequestMethod("POST");
        connection.setRequestProperty("Content-Type", "application/json");
        connection.setDoOutput(true);
        connection.setConnectTimeout(10_000);
        connection.setReadTimeout(10_000);
        try {
            try (OutputStream out = connection.getOutputStream()) {
                out.write(requestBody.toString().getBytes(StandardCharsets.UTF_8));
            }
            int status = connection.getResponseCode();
            if (status != 200)
                throw new IOException("registration failed with HTTP " + status);
            JSONObject response = new JSONObject(readAll(connection.getInputStream()));
            String deviceId = response.getString("deviceId");
            String secret = response.getString("secret");
            String nickname = response.optString("nickname", nickname(context));
            preferences(context).edit()
                    .putString(DEVICE_ID, deviceId)
                    .putString(SECRET, secret)
                    .putString(NICKNAME, nickname)
                    .commit();
        } catch (JSONException malformedResponse) {
            throw new IOException("malformed registration response", malformedResponse);
        } finally {
            connection.disconnect();
        }
    }

    private static String readAll(InputStream stream) throws IOException {
        ByteArrayOutputStream buffer = new ByteArrayOutputStream();
        byte[] chunk = new byte[4096];
        int read;
        while ((read = stream.read(chunk)) != -1) buffer.write(chunk, 0, read);
        return buffer.toString("UTF-8");
    }

    private static SharedPreferences preferences(Context context) {
        return context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE);
    }
}
