package com.thorium.preview.multiplayer;

import android.content.Context;
import android.content.SharedPreferences;

/**
 * Where this device's copy of Lucent looks for the self-hosted multiplayer
 * backend (see backend/README.md). Unlike every other Lucent setting, this
 * one has no sensible built-in default: the backend is self-hosted per
 * user/group, not a Lucent-operated service, so there is no URL to ship in
 * the app. Multiplayer features stay off (see {@link #isConfigured}) until
 * whoever deployed a backend enters its address once.
 */
public final class MultiplayerConfig {
    private static final String PREFERENCES = "multiplayer-identity";
    private static final String BACKEND_BASE_URL = "backendBaseUrl";

    private MultiplayerConfig() {}

    public static String backendBaseUrl(Context context) {
        return preferences(context).getString(BACKEND_BASE_URL, "");
    }

    public static boolean isConfigured(Context context) {
        return !backendBaseUrl(context).trim().isEmpty();
    }

    public static synchronized void setBackendBaseUrl(Context context, String url) {
        String trimmed = url == null ? "" : url.trim();
        // Strip a trailing slash so callers can do baseUrl + "/v1/register"
        // without ever producing a doubled "//v1/register".
        while (trimmed.endsWith("/")) trimmed = trimmed.substring(0, trimmed.length() - 1);
        preferences(context).edit().putString(BACKEND_BASE_URL, trimmed).commit();
    }

    /** The WebSocket URL for /v1/connect, derived from the same configured host. */
    public static String backendWebSocketUrl(Context context) {
        String base = backendBaseUrl(context);
        if (base.isEmpty()) return "";
        if (base.startsWith("https://")) return "wss://" + base.substring("https://".length()) + "/v1/connect";
        if (base.startsWith("http://")) return "ws://" + base.substring("http://".length()) + "/v1/connect";
        return "";
    }

    private static SharedPreferences preferences(Context context) {
        return context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE);
    }
}
