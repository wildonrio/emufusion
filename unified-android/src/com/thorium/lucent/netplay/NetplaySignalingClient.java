package com.thorium.lucent.netplay;

import android.os.Handler;
import android.os.Looper;
import android.util.Log;

import com.neovisionaries.ws.client.WebSocket;
import com.neovisionaries.ws.client.WebSocketAdapter;
import com.neovisionaries.ws.client.WebSocketException;
import com.neovisionaries.ws.client.WebSocketFactory;

import org.json.JSONException;
import org.json.JSONObject;

import java.util.List;
import java.util.Map;

/**
 * The one persistent WebSocket connection to the multiplayer backend
 * (presence, roster, matchmaking, and WebRTC signaling only -- see
 * backend/README.md for the full contract). This class owns the
 * connection lifecycle and message dispatch; it does not know anything
 * about WebRTC itself, so {@link NetplaySession} depends on this class
 * and not the other way around.
 */
public final class NetplaySignalingClient {
    private static final String TAG = "LucentNetplaySignal";
    private static final long HEARTBEAT_INTERVAL_MS = 20_000L;

    /** Mirrors the server -> client message types in backend/README.md. */
    public interface Listener {
        void onIdentityAck(String deviceId, String nickname);
        void onRosterUpdate(JSONObject payload);
        void onMatchScheduled(JSONObject payload);
        void onInviteAvailable(JSONObject payload);
        void onRoleAssigned(JSONObject payload);
        void onSignal(JSONObject payload);
        void onMatchEnded(String type, JSONObject payload);
        /** A connection-level failure; the caller decides whether/when to retry. */
        void onConnectionLost(Throwable cause);
    }

    private final String wsUrl;
    private final String deviceId;
    private final String secret;
    private final Listener listener;
    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private final Runnable heartbeatTask = this::sendHeartbeat;

    private volatile WebSocket socket;

    public NetplaySignalingClient(String wsUrl, String deviceId, String secret, Listener listener) {
        if (wsUrl == null || deviceId == null || secret == null || listener == null)
            throw new IllegalArgumentException("wsUrl, deviceId, secret, and listener are all required");
        this.wsUrl = wsUrl;
        this.deviceId = deviceId;
        this.secret = secret;
        this.listener = listener;
    }

    /** Connects on a background thread; delivers {@link Listener} callbacks on the main thread. */
    public void connect() {
        try {
            WebSocketFactory factory = new WebSocketFactory().setConnectionTimeout(10_000);
            WebSocket ws = factory.createSocket(wsUrl)
                    .addHeader("X-Device-Id", deviceId)
                    .addHeader("Authorization", "Bearer " + secret)
                    .addListener(new WebSocketAdapter() {
                        @Override public void onConnected(WebSocket websocket,
                                Map<String, List<String>> headers) {
                            mainHandler.postDelayed(heartbeatTask, HEARTBEAT_INTERVAL_MS);
                        }

                        @Override public void onTextMessage(WebSocket websocket, String text) {
                            handleWire(text);
                        }

                        @Override public void onDisconnected(WebSocket websocket,
                                com.neovisionaries.ws.client.WebSocketFrame serverCloseFrame,
                                com.neovisionaries.ws.client.WebSocketFrame clientCloseFrame,
                                boolean closedByServer) {
                            mainHandler.removeCallbacks(heartbeatTask);
                            mainHandler.post(() -> listener.onConnectionLost(
                                    new java.io.IOException("WebSocket disconnected (byServer=" +
                                            closedByServer + ")")));
                        }

                        @Override public void onConnectError(WebSocket websocket, WebSocketException cause) {
                            mainHandler.post(() -> listener.onConnectionLost(cause));
                        }

                        @Override public void onError(WebSocket websocket, WebSocketException cause) {
                            Log.w(TAG, "signaling socket error", cause);
                        }
                    });
            socket = ws;
            ws.connectAsynchronously();
        } catch (java.io.IOException failure) {
            mainHandler.post(() -> listener.onConnectionLost(failure));
        }
    }

    public void close() {
        mainHandler.removeCallbacks(heartbeatTask);
        WebSocket ws = socket;
        if (ws != null) ws.disconnect();
        socket = null;
    }

    public void send(NetplayMessage message) {
        WebSocket ws = socket;
        if (ws == null) {
            Log.w(TAG, "dropped " + message.type + ": not connected");
            return;
        }
        ws.sendText(message.toWire());
    }

    private void sendHeartbeat() {
        send(NetplayMessage.heartbeat());
        mainHandler.postDelayed(heartbeatTask, HEARTBEAT_INTERVAL_MS);
    }

    private void handleWire(String raw) {
        final NetplayMessage message;
        try {
            message = NetplayMessage.fromWire(raw);
        } catch (JSONException malformed) {
            Log.w(TAG, "malformed message from backend, ignoring", malformed);
            return;
        }
        mainHandler.post(() -> dispatch(message));
    }

    private void dispatch(NetplayMessage message) {
        switch (message.type) {
            case "identity.ack":
                listener.onIdentityAck(
                        message.payload.optString("deviceId"),
                        message.payload.optString("nickname"));
                break;
            case "roster.update":
                listener.onRosterUpdate(message.payload);
                break;
            case "match.scheduled":
                listener.onMatchScheduled(message.payload);
                break;
            case "invite.available":
                listener.onInviteAvailable(message.payload);
                break;
            case "match.role_assigned":
                listener.onRoleAssigned(message.payload);
                break;
            case "signal":
                listener.onSignal(message.payload);
                break;
            case "match.cancelled":
            case "match.expired":
                listener.onMatchEnded(message.type, message.payload);
                break;
            default:
                Log.w(TAG, "unknown message type from backend: " + message.type);
        }
    }
}
