package com.thorium.preview.multiplayer;

import android.content.Context;
import android.util.Log;

import com.thorium.lucent.netplay.ActiveEngineSessionRegistry;
import com.thorium.lucent.netplay.NetplayCapableSession;
import com.thorium.lucent.netplay.NetplayInputRelay;
import com.thorium.lucent.netplay.NetplayMessage;
import com.thorium.lucent.netplay.NetplayPortAssignment;
import com.thorium.lucent.netplay.NetplaySession;
import com.thorium.lucent.netplay.NetplaySignalingClient;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Owns this device's whole multiplayer lifecycle: registering identity,
 * connecting to the configured backend, tracking roster/schedule/invite
 * state, and -- once a match is accepted by every participant -- creating
 * the {@link NetplaySession} and attaching it to whatever engine session
 * {@link ActiveEngineSessionRegistry} currently publishes.
 *
 * <p>A no-op end to end (never connects, every call below returns
 * harmlessly) when {@link MultiplayerConfig#isConfigured} is false --
 * this backend is self-hosted per deployment, not a Lucent-operated
 * service, so an unconfigured device is the default, expected state, not
 * an error.
 *
 * <p><b>Known gap, not yet built</b>: if the accepted match's game isn't
 * the one currently running (or nothing is running at all),
 * {@link ActiveEngineSessionRegistry#current} returns null or the wrong
 * session and this class currently just logs and gives up on attaching --
 * tearing down whatever is running and launching the right game instead
 * is real, separate work the design plan flags as its own investigation
 * (see PLAY_NOW_LAUNCH_NOT_IMPLEMENTED below).
 */
public final class MultiplayerManager implements NetplaySignalingClient.Listener {
    private static final String TAG = "LucentMultiplayer";

    private final Context context;
    private volatile NetplaySignalingClient signaling;
    private volatile boolean registering;

    private final Map<String, JSONObject> rosterByGameKey = new ConcurrentHashMap<>();
    private final Map<String, JSONObject> invitesByMatchId = new ConcurrentHashMap<>();
    private final Map<String, JSONObject> scheduledByMatchId = new ConcurrentHashMap<>();
    private volatile ActiveMatch activeMatch;

    private static final class ActiveMatch {
        final String matchId;
        final List<String> participants;
        final NetplaySession session;
        String hostDeviceId;
        // Only set for the libretro/PPSSPP family (see activateMatch) -- the
        // native-adapter family has no desync check to stop (neither Eden
        // nor Cemu reports quick-resume support, and aps3e has no real
        // second controller to desync against in the first place).
        NetplayInputRelay libretroRelay;

        ActiveMatch(String matchId, List<String> participants, NetplaySession session) {
            this.matchId = matchId;
            this.participants = participants;
            this.session = session;
        }
    }

    public MultiplayerManager(Context context) {
        this.context = context.getApplicationContext();
    }

    /** Safe to call unconditionally from PreviewService.onCreate(); a no-op if unconfigured. */
    public void start() {
        if (!MultiplayerConfig.isConfigured(context)) {
            Log.i(TAG, "no multiplayer backend configured; feature inactive");
            return;
        }
        if (registering) return;
        registering = true;
        // ensureRegistered() and the initial WebSocket connect both block;
        // never run this on the caller's thread (PreviewService.onCreate()
        // has its own tight foreground-service deadline -- see its own
        // comment on why launchMigration below runs on its own thread too).
        new Thread(() -> {
            try {
                DeviceIdentity.ensureRegistered(context);
            } catch (IOException | IllegalStateException failure) {
                Log.w(TAG, "multiplayer registration failed; will not connect this run", failure);
                registering = false;
                return;
            }
            connect();
        }, "lucent-multiplayer-register").start();
    }

    private void connect() {
        String wsUrl = MultiplayerConfig.backendWebSocketUrl(context);
        String nickname = DeviceIdentity.nickname(context);
        NetplaySignalingClient client = new NetplaySignalingClient(
                wsUrl + "?nickname=" + safeQueryValue(nickname),
                DeviceIdentity.deviceId(context), DeviceIdentity.secret(context), this);
        signaling = client;
        client.connect();
    }

    // ---- Called by (future) companion HTTP endpoints ----

    public void setWant(String gameKey, String system, boolean want, int minPlayers, int maxPlayers) {
        NetplaySignalingClient client = signaling;
        if (client == null) return;
        client.send(NetplayMessage.wantSet(gameKey, system, want, minPlayers, maxPlayers));
    }

    public void submitSchedule(String gameKey, String system, JSONArray windows,
                                int minPlayers, int maxPlayers) {
        NetplaySignalingClient client = signaling;
        if (client == null) return;
        client.send(NetplayMessage.scheduleSubmit(gameKey, system, windows, minPlayers, maxPlayers));
    }

    public void cancelSchedule(String scheduleId) {
        NetplaySignalingClient client = signaling;
        if (client == null) return;
        client.send(NetplayMessage.scheduleCancel(scheduleId));
    }

    public void respondToInvite(String matchId, boolean accept) {
        NetplaySignalingClient client = signaling;
        if (client == null) return;
        client.send(NetplayMessage.inviteRespond(matchId, accept));
        if (!accept) invitesByMatchId.remove(matchId);
    }

    public JSONObject rosterFor(String gameKey) { return rosterByGameKey.get(gameKey); }

    public JSONObject invite(String matchId) { return invitesByMatchId.get(matchId); }

    /** True once the WebSocket to the backend is up (see {@link #onConnectionLost}). */
    public boolean isConnected() { return signaling != null; }

    /** The matchId of the currently active (accepted and attached) match, or null. */
    public String currentActiveMatchId() {
        ActiveMatch match = activeMatch;
        return match != null ? match.matchId : null;
    }

    /**
     * Assembles the one aggregate poll payload for {@code GET
     * /multiplayer/status}: configuration/connection state plus every
     * pending invite and scheduled match this device currently knows
     * about, and the active match id if a netplay session is live. Safe to
     * call at any time -- including before {@link #start} has connected
     * anything -- since it only ever reads the existing caches.
     */
    public JSONObject statusSnapshot() {
        JSONObject root = new JSONObject();
        try {
            root.put("ok", true);
            root.put("configured", MultiplayerConfig.isConfigured(context));
            root.put("connected", isConnected());
            JSONArray invites = new JSONArray();
            for (JSONObject invite : invitesByMatchId.values()) invites.put(invite);
            root.put("invites", invites);
            JSONArray scheduled = new JSONArray();
            for (JSONObject match : scheduledByMatchId.values()) scheduled.put(match);
            root.put("scheduled", scheduled);
            String activeMatchId = currentActiveMatchId();
            root.put("activeMatchId", activeMatchId != null ? activeMatchId : JSONObject.NULL);
        } catch (JSONException impossible) {
            throw new IllegalStateException(impossible);
        }
        return root;
    }

    // ---- NetplaySignalingClient.Listener ----

    @Override public void onIdentityAck(String deviceId, String nickname) {
        Log.i(TAG, "connected to multiplayer backend as " + deviceId + " (" + nickname + ")");
    }

    @Override public void onRosterUpdate(JSONObject payload) {
        String gameKey = payload.optString("gameKey");
        if (!gameKey.isEmpty()) rosterByGameKey.put(gameKey, payload);
    }

    @Override public void onMatchScheduled(JSONObject payload) {
        String matchId = payload.optString("matchId");
        if (!matchId.isEmpty()) scheduledByMatchId.put(matchId, payload);
    }

    @Override public void onInviteAvailable(JSONObject payload) {
        String matchId = payload.optString("matchId");
        if (matchId.isEmpty()) return;
        invitesByMatchId.put(matchId, payload);
        // Phase 3 (not built yet): this is where the in-game/library "so-and-so
        // wants to play" overlay notification fires. Today this only makes the
        // invite queryable via invite()/rosterFor() for whatever polls it.
    }

    @Override public void onRoleAssigned(JSONObject payload) {
        String matchId = payload.optString("matchId");
        String hostDeviceId = payload.optString("hostDeviceId");
        ActiveMatch match = activeMatch;
        if (match == null || !match.matchId.equals(matchId)) return;
        match.hostDeviceId = hostDeviceId;
        match.session.setHostDeviceId(hostDeviceId);
        String myDeviceId = DeviceIdentity.deviceId(context);
        if (hostDeviceId.equals(myDeviceId)) {
            for (String peerId : match.participants) {
                if (!peerId.equals(myDeviceId)) match.session.addPeer(peerId);
            }
        }
        // Non-host devices do nothing here: they wait for the host's SDP
        // offer to arrive via onSignal, exactly like NetplaySession.handleSignal
        // already expects (see its own doc comment).
    }

    @Override public void onSignal(JSONObject payload) {
        ActiveMatch match = activeMatch;
        if (match == null) return;
        match.session.handleSignal(payload);
    }

    @Override public void onMatchEnded(String type, JSONObject payload) {
        String matchId = payload.optString("matchId");
        invitesByMatchId.remove(matchId);
        scheduledByMatchId.remove(matchId);
        ActiveMatch match = activeMatch;
        if (match != null && match.matchId.equals(matchId)) {
            teardownActiveMatch(match);
        }
    }

    @Override public void onConnectionLost(Throwable cause) {
        Log.w(TAG, "multiplayer backend connection lost", cause);
        // Alpha scope: no automatic reconnect/backoff yet -- see the design
        // plan's Phase 5 (alpha polish). A future call to start() (e.g. the
        // app returning to foreground) will open a fresh connection.
        signaling = null;
    }

    // ---- Match activation once accepted ----

    /**
     * Called once every participant has accepted an invite (this device's
     * own acceptance is respondToInvite(matchId, true) above; the backend
     * doesn't currently push a distinct "everyone accepted, go" message,
     * so for now this must be invoked by whatever UI code observes all
     * responses -- see PLAY_NOW_LAUNCH_NOT_IMPLEMENTED-style caller-side
     * gap noted on the class itself). Creates the WebRTC session and
     * claims host if this device was first to try.
     */
    public void activateMatch(String matchId, List<String> participants) {
        String myDeviceId = DeviceIdentity.deviceId(context);
        Object target = ActiveEngineSessionRegistry.current();
        if (!(target instanceof NetplayCapableSession) &&
                !(target instanceof com.thorium.lucent.netplay.NativeAdapterCapableSession)) {
            Log.w(TAG, "activateMatch(" + matchId + "): no running engine session to attach to " +
                    "(launching the right game automatically is not implemented yet)");
            return;
        }
        NetplaySignalingClient client = signaling;
        if (client == null) {
            Log.w(TAG, "activateMatch(" + matchId + "): not connected to the backend");
            return;
        }
        NetplaySession session = new NetplaySession(client, matchId);
        ActiveMatch match = new ActiveMatch(matchId, new ArrayList<>(participants), session);
        activeMatch = match;

        // Same alphabetical-sort-and-index scheme either way -- "port" for
        // the libretro family and "controller_index" for the native-adapter
        // family are the same concept (which player slot a peer drives).
        Map<String, Integer> indices = new ConcurrentHashMap<>();
        for (String peerId : participants) {
            if (peerId.equals(myDeviceId)) continue;
            indices.put(peerId, NetplayPortAssignment.portFor(myDeviceId, peerId, participants));
        }
        // Guards against a delayed (post-reconnect-grace-period) onHostLost
        // firing after this match has already ended and a newer one has
        // started -- mirrors onMatchEnded's own matchId check.
        Runnable onHostLost = () -> {
            ActiveMatch current = activeMatch;
            if (current == match) teardownActiveMatch(current);
        };

        // The relay needs the already-constructed session (to call
        // sendToAll), so it can't be a constructor argument to NetplaySession
        // -- see NetplaySession.setDataListener's own doc comment.
        if (target instanceof NetplayCapableSession) {
            NetplayCapableSession libretroTarget = (NetplayCapableSession) target;
            Runnable onDesyncDetected = () -> {
                ActiveMatch current = activeMatch;
                if (current == match) teardownActiveMatch(current);
            };
            NetplayInputRelay relay = new NetplayInputRelay(
                    session, libretroTarget::applyRemoteJoypadButton, indices, onHostLost,
                    libretroTarget::currentSerializedStateForDesync, onDesyncDetected);
            match.libretroRelay = relay;
            session.setDataListener(relay);
            libretroTarget.attachNetplayRelay(relay);
        } else {
            com.thorium.lucent.netplay.NativeAdapterCapableSession nativeTarget =
                    (com.thorium.lucent.netplay.NativeAdapterCapableSession) target;
            com.thorium.lucent.netplay.NativeAdapterInputRelay relay =
                    new com.thorium.lucent.netplay.NativeAdapterInputRelay(
                            session, nativeTarget::applyRemoteControl, indices, onHostLost);
            session.setDataListener(relay);
            nativeTarget.attachNetplayRelay(relay);
        }

        client.send(NetplayMessage.claimHost(matchId));
    }

    private void teardownActiveMatch(ActiveMatch match) {
        activeMatch = null;
        Object target = ActiveEngineSessionRegistry.current();
        if (target instanceof NetplayCapableSession) {
            ((NetplayCapableSession) target).detachNetplayRelay();
        } else if (target instanceof com.thorium.lucent.netplay.NativeAdapterCapableSession) {
            ((com.thorium.lucent.netplay.NativeAdapterCapableSession) target).detachNetplayRelay();
        }
        if (match.libretroRelay != null) match.libretroRelay.stop();
        match.session.close();
    }

    private static String safeQueryValue(String value) {
        try {
            return java.net.URLEncoder.encode(value, "UTF-8");
        } catch (java.io.UnsupportedEncodingException impossible) {
            throw new IllegalStateException(impossible);
        }
    }
}
