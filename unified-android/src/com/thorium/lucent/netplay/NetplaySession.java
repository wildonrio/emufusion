package com.thorium.lucent.netplay;

import android.content.Context;
import android.util.Log;

import org.json.JSONException;
import org.json.JSONObject;
import org.webrtc.DataChannel;
import org.webrtc.IceCandidate;
import org.webrtc.MediaConstraints;
import org.webrtc.PeerConnection;
import org.webrtc.PeerConnectionFactory;
import org.webrtc.SdpObserver;
import org.webrtc.SessionDescription;

import java.nio.ByteBuffer;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;

/**
 * One netplay match's WebRTC transport: a star topology (see the design
 * plan) where the host holds one {@link PeerConnection} per joined
 * participant, and every non-host participant holds exactly one
 * {@link PeerConnection} to the host. This class only moves bytes over a
 * DataChannel per peer -- it knows nothing about libretro ports, input
 * framing, or lockstep timing; that belongs to whatever later phase wires
 * a {@link DataListener} into the engine sessions.
 *
 * <p>All WebRTC calls for a given {@link PeerConnection} happen on the
 * signaling thread WebRTC's own factory creates internally, driven by
 * this class's callbacks -- never spawned onto a separate thread/executor
 * by this class itself, since PeerConnection is not thread-safe for
 * concurrent access from multiple threads at once.
 */
public final class NetplaySession {
    private static final String TAG = "LucentNetplaySession";
    private static final String DATA_CHANNEL_LABEL = "netplay";

    /** Free public STUN only for the alpha -- see backend/README.md's NAT traversal section. */
    private static final String[] DEFAULT_STUN_URLS = {
            "stun:stun.l.google.com:19302",
            "stun:stun1.l.google.com:19302",
    };

    /**
     * All three callbacks fire on WebRTC's own internal signaling thread,
     * never the caller's thread and never the main/UI thread -- this is
     * deliberate, not an oversight: a lockstep-with-input-delay
     * consumer (see the design plan) wants the shortest possible path
     * from "peer input arrived" to "merge it into the next frame," and a
     * hop through the main thread would add latency for no benefit here.
     * Implementations must not do main-thread-only work (touching Views,
     * etc.) directly in these callbacks.
     */
    public interface DataListener {
        void onPeerData(String fromDeviceId, byte[] data);
        void onPeerConnected(String peerDeviceId);
        void onPeerDisconnected(String peerDeviceId);

        /**
         * Fired once, in addition to {@link #onPeerDisconnected} for that
         * same peer, exactly when the peer confirmed lost is this match's
         * host (see {@link #setHostDeviceId}). Per the design plan's
         * reconnect section: "a dropped host ends the session for
         * everyone" -- host migration is out of scope for this alpha, so
         * there is no path back from this once it fires.
         */
        void onHostLost();
    }

    /**
     * How long a transient ICE DISCONNECTED state is tolerated before this
     * device treats a peer as genuinely gone. ICE reports DISCONNECTED for
     * plenty of recoverable blips (a brief Wi-Fi hiccup, a NAT rebind) that
     * self-heal back to CONNECTED within a second or two; firing
     * onPeerDisconnected/onHostLost immediately on every one of those would
     * mean a flaky network releases held input or kills the whole match far
     * more often than the underlying connection actually warrants. FAILED
     * and CLOSED are treated as immediately final -- WebRTC only reaches
     * those after it has already given up, so no grace period adds anything
     * there.
     */
    private static final long RECONNECT_GRACE_MS = 6_000L;

    private static volatile PeerConnectionFactory factory;

    /** Must be called once (Application.onCreate is a reasonable place) before any session is created. */
    public static void globalInit(Context appContext) {
        if (factory != null) return;
        synchronized (NetplaySession.class) {
            if (factory != null) return;
            PeerConnectionFactory.initialize(
                    PeerConnectionFactory.InitializationOptions.builder(appContext)
                            .createInitializationOptions());
            factory = PeerConnectionFactory.builder().createPeerConnectionFactory();
        }
    }

    private final NetplaySignalingClient signaling;
    private final String matchId;
    private final Map<String, Peer> peers = new ConcurrentHashMap<>();
    private final Map<String, ScheduledFuture<?>> pendingGraceChecks = new ConcurrentHashMap<>();
    private final ScheduledExecutorService graceTimers =
            Executors.newSingleThreadScheduledExecutor(runnable -> {
                Thread thread = new Thread(runnable, "lucent-netplay-reconnect-grace");
                thread.setDaemon(true);
                return thread;
            });
    // Not final and not a constructor parameter: which device is host isn't
    // known until the backend's match.role_assigned reaches this device
    // (async, after construction), and the listener is ordinarily a
    // NetplayInputRelay that itself needs a reference to this
    // already-constructed session -- see MultiplayerManager.activateMatch,
    // the only real caller, for the exact order this actually happens in.
    private volatile DataListener listener;
    // Same reason: unknown at construction, set once role_assigned arrives.
    private volatile String hostDeviceId;

    public NetplaySession(NetplaySignalingClient signaling, String matchId) {
        if (factory == null)
            throw new IllegalStateException("NetplaySession.globalInit was never called");
        this.signaling = signaling;
        this.matchId = matchId;
    }

    public void setDataListener(DataListener listener) {
        this.listener = listener;
    }

    /** Called once {@code match.role_assigned} tells this device who the host is (both the host's own device and every client's). */
    public void setHostDeviceId(String hostDeviceId) {
        this.hostDeviceId = hostDeviceId;
    }

    /**
     * Host-only: begins connecting to a newly-joined participant by
     * sending it an offer. Enforced by the caller, not this class: only
     * MultiplayerManager.onRoleAssigned calls this, and only once the
     * backend has confirmed this device is the host for this match --
     * see this class's own doc comment on why host status can't be a
     * constructor-time flag here.
     */
    public void addPeer(String peerDeviceId) {
        Peer peer = peerFor(peerDeviceId, true);
        DataChannel.Init init = new DataChannel.Init();
        init.ordered = true; // control/state traffic needs order; a later phase may add a
        // second, unordered channel specifically for per-frame input once that's built.
        peer.dataChannel = peer.connection.createDataChannel(DATA_CHANNEL_LABEL, init);
        wireDataChannel(peer);
        peer.connection.createOffer(new SimpleSdpObserver() {
            @Override public void onCreateSuccess(SessionDescription description) {
                peer.connection.setLocalDescription(new SimpleSdpObserver(), description);
                sendSignal(peerDeviceId, sdpPayload(description));
            }
        }, new MediaConstraints());
    }

    /**
     * Routes one {@code signal} message this device received, addressed
     * to this match. The owner of the {@link NetplaySignalingClient}
     * (e.g. a MultiplayerManager) is responsible for calling this from
     * its {@code Listener.onSignal} whenever the payload's matchId
     * matches this session's.
     */
    public void handleSignal(JSONObject envelopePayload) {
        String fromDeviceId = envelopePayload.optString("fromDeviceId");
        JSONObject inner = envelopePayload.optJSONObject("payload");
        if (fromDeviceId.isEmpty() || inner == null) {
            Log.w(TAG, "malformed signal payload, ignoring");
            return;
        }
        String kind = inner.optString("kind");
        Peer peer = peerFor(fromDeviceId, false);
        if ("sdp".equals(kind)) {
            handleSdp(peer, fromDeviceId, inner);
        } else if ("ice".equals(kind)) {
            handleIce(peer, inner);
        } else {
            Log.w(TAG, "unknown signal kind: " + kind);
        }
    }

    private void handleSdp(Peer peer, String fromDeviceId, JSONObject inner) {
        String sdpType = inner.optString("sdpType");
        String sdp = inner.optString("sdp");
        SessionDescription.Type type = "offer".equals(sdpType)
                ? SessionDescription.Type.OFFER : SessionDescription.Type.ANSWER;
        SessionDescription description = new SessionDescription(type, sdp);
        peer.connection.setRemoteDescription(new SimpleSdpObserver() {
            @Override public void onSetSuccess() {
                if (type == SessionDescription.Type.OFFER) {
                    peer.connection.createAnswer(new SimpleSdpObserver() {
                        @Override public void onCreateSuccess(SessionDescription answer) {
                            peer.connection.setLocalDescription(new SimpleSdpObserver(), answer);
                            sendSignal(fromDeviceId, sdpPayload(answer));
                        }
                    }, new MediaConstraints());
                }
            }
        }, description);
    }

    private void handleIce(Peer peer, JSONObject inner) {
        String candidate = inner.optString("candidate");
        String sdpMid = inner.optString("sdpMid");
        int sdpMLineIndex = inner.optInt("sdpMLineIndex");
        if (candidate.isEmpty()) return;
        peer.connection.addIceCandidate(new IceCandidate(sdpMid, sdpMLineIndex, candidate));
    }

    public void sendTo(String peerDeviceId, byte[] data) {
        Peer peer = peers.get(peerDeviceId);
        if (peer == null || peer.dataChannel == null ||
                peer.dataChannel.state() != DataChannel.State.OPEN) return;
        peer.dataChannel.send(new DataChannel.Buffer(ByteBuffer.wrap(data), true));
    }

    public void sendToAll(byte[] data) {
        for (String peerDeviceId : peers.keySet()) sendTo(peerDeviceId, data);
    }

    public void close() {
        for (ScheduledFuture<?> pending : pendingGraceChecks.values()) pending.cancel(false);
        pendingGraceChecks.clear();
        graceTimers.shutdownNow();
        for (Peer peer : peers.values()) {
            if (peer.dataChannel != null) peer.dataChannel.dispose();
            peer.connection.close();
        }
        peers.clear();
    }

    /** Starts (or leaves running, if already pending) a grace-period check for a peer that just went DISCONNECTED. */
    private void scheduleGraceCheck(String peerDeviceId) {
        pendingGraceChecks.computeIfAbsent(peerDeviceId, id -> graceTimers.schedule(() -> {
            pendingGraceChecks.remove(id);
            Peer peer = peers.get(id);
            if (peer == null || peer.connection == null) return;
            PeerConnection.IceConnectionState current = peer.connection.iceConnectionState();
            if (current == PeerConnection.IceConnectionState.CONNECTED ||
                    current == PeerConnection.IceConnectionState.COMPLETED) {
                return; // recovered on its own within the grace window
            }
            firePeerLost(id);
        }, RECONNECT_GRACE_MS, TimeUnit.MILLISECONDS));
    }

    private void cancelPendingGraceCheck(String peerDeviceId) {
        ScheduledFuture<?> pending = pendingGraceChecks.remove(peerDeviceId);
        if (pending != null) pending.cancel(false);
    }

    /** The one real, confirmed (post-grace-period or immediate FAILED/CLOSED) loss of a peer. */
    private void firePeerLost(String peerDeviceId) {
        DataListener currentListener = listener;
        if (currentListener == null) return;
        currentListener.onPeerDisconnected(peerDeviceId);
        if (peerDeviceId.equals(hostDeviceId)) currentListener.onHostLost();
    }

    private Peer peerFor(String peerDeviceId, boolean mustBeNew) {
        Peer existing = peers.get(peerDeviceId);
        if (existing != null) {
            if (mustBeNew) throw new IllegalStateException("peer already exists: " + peerDeviceId);
            return existing;
        }
        Peer peer = new Peer();
        List<PeerConnection.IceServer> iceServers = new ArrayList<>();
        for (String url : DEFAULT_STUN_URLS)
            iceServers.add(PeerConnection.IceServer.builder(url).createIceServer());
        PeerConnection.RTCConfiguration config = new PeerConnection.RTCConfiguration(iceServers);
        peer.connection = factory.createPeerConnection(config, new PeerConnection.Observer() {
            @Override public void onIceCandidate(IceCandidate candidate) {
                JSONObject payload = new JSONObject();
                try {
                    payload.put("kind", "ice");
                    payload.put("candidate", candidate.sdp);
                    payload.put("sdpMid", candidate.sdpMid);
                    payload.put("sdpMLineIndex", candidate.sdpMLineIndex);
                } catch (JSONException impossible) {
                    throw new IllegalStateException(impossible);
                }
                sendSignal(peerDeviceId, payload);
            }

            @Override public void onDataChannel(DataChannel channel) {
                peer.dataChannel = channel;
                wireDataChannel(peer);
            }

            @Override public void onIceConnectionChange(PeerConnection.IceConnectionState state) {
                Log.i(TAG, "peer=" + peerDeviceId + " ICE state=" + state);
                if (state == PeerConnection.IceConnectionState.CONNECTED ||
                        state == PeerConnection.IceConnectionState.COMPLETED) {
                    cancelPendingGraceCheck(peerDeviceId);
                } else if (state == PeerConnection.IceConnectionState.FAILED ||
                        state == PeerConnection.IceConnectionState.CLOSED) {
                    cancelPendingGraceCheck(peerDeviceId);
                    firePeerLost(peerDeviceId);
                } else if (state == PeerConnection.IceConnectionState.DISCONNECTED) {
                    scheduleGraceCheck(peerDeviceId);
                }
            }

            @Override public void onIceConnectionReceivingChange(boolean receiving) {}
            @Override public void onIceGatheringChange(PeerConnection.IceGatheringState state) {}
            @Override public void onSignalingChange(PeerConnection.SignalingState state) {}
            @Override public void onIceCandidatesRemoved(IceCandidate[] candidates) {}
            @Override public void onAddStream(org.webrtc.MediaStream stream) {}
            @Override public void onRemoveStream(org.webrtc.MediaStream stream) {}
            @Override public void onRenegotiationNeeded() {}
        });
        peers.put(peerDeviceId, peer);
        return peer;
    }

    private void wireDataChannel(Peer peer) {
        if (peer.dataChannel == null) return;
        String peerDeviceId = findKey(peer);
        peer.dataChannel.registerObserver(new DataChannel.Observer() {
            @Override public void onBufferedAmountChange(long previousAmount) {}

            @Override public void onStateChange() {
                if (peer.dataChannel.state() == DataChannel.State.OPEN && listener != null) {
                    listener.onPeerConnected(peerDeviceId);
                }
            }

            @Override public void onMessage(DataChannel.Buffer buffer) {
                if (listener == null) return;
                byte[] data = new byte[buffer.data.remaining()];
                buffer.data.get(data);
                listener.onPeerData(peerDeviceId, data);
            }
        });
    }

    private String findKey(Peer target) {
        for (Map.Entry<String, Peer> entry : peers.entrySet())
            if (entry.getValue() == target) return entry.getKey();
        return "";
    }

    private void sendSignal(String toDeviceId, JSONObject signalPayload) {
        signaling.send(NetplayMessage.signal(matchId, toDeviceId, signalPayload));
    }

    private static JSONObject sdpPayload(SessionDescription description) {
        JSONObject payload = new JSONObject();
        try {
            payload.put("kind", "sdp");
            payload.put("sdpType", description.type == SessionDescription.Type.OFFER ? "offer" : "answer");
            payload.put("sdp", description.description);
        } catch (JSONException impossible) {
            throw new IllegalStateException(impossible);
        }
        return payload;
    }

    private static final class Peer {
        PeerConnection connection;
        volatile DataChannel dataChannel;
    }

    /** Convenience base so call sites only override the one callback they need. */
    private static class SimpleSdpObserver implements SdpObserver {
        @Override public void onCreateSuccess(SessionDescription description) {}
        @Override public void onSetSuccess() {}
        @Override public void onCreateFailure(String error) {
            Log.w(TAG, "SDP create failed: " + error);
        }
        @Override public void onSetFailure(String error) {
            Log.w(TAG, "SDP set failed: " + error);
        }
    }
}
