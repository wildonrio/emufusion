package com.thorium.lucent.netplay;

import android.util.Log;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.zip.CRC32;

/**
 * Keeps one engine session's local port-0 joypad state broadcast to every
 * connected peer, and applies whatever the same peers report back onto
 * their assigned remote ports. This is the netplay integration point for
 * an active {@link NetplaySession}: the engine session calls
 * {@link #onLocalJoypadButton} from the exact same place it already
 * drives port 0 (see LibretroEngineSession/PpssppGlesEngineSession's
 * joypadSink), and this class's {@link NetplaySession.DataListener}
 * methods feed the result into a {@link RemoteJoypadSink} -- ordinarily
 * the same session's {@code applyRemoteJoypadButton}.
 *
 * <p>See {@link NetplayInputMessage} for why this deliberately applies
 * remote state on arrival rather than buffering it against a matching
 * local frame number.
 *
 * <p>Also owns the optional periodic desync check ({@link DesyncCheckMessage});
 * see that class's doc comment for the full design and its honest precision
 * caveat. Never live-verified against two real network peers as of this
 * writing (see the multiplayer alpha's own progress notes) -- this is
 * structurally complete and follows every existing pattern in this package,
 * but a real two-device desync-mismatch scenario has not been observed.
 */
public final class NetplayInputRelay implements NetplaySession.DataListener {
    private static final String TAG = "LucentNetplayInputRelay";

    /** How often this device ticks its own desync-check heartbeat. See DesyncCheckMessage's doc comment. */
    private static final long DESYNC_CHECK_INTERVAL_MS = 5_000L;
    /** Bound on how many not-yet-matched checksums (ours or a peer's) are kept before the oldest is dropped. */
    private static final int MAX_PENDING_DESYNC_CHECKS = 16;

    private final NetplaySession session;
    private final RemoteJoypadSink localTarget;
    private final Map<String, Integer> peerPorts; // deviceId -> assigned port (1..7)
    private final Runnable onHostLost;
    private final java.util.function.Supplier<byte[]> localStateSupplier;
    private final Runnable onDesyncDetected;
    private volatile int localButtonMask;
    private final Map<String, Integer> lastAppliedMaskByPeer = new ConcurrentHashMap<>();

    private final ScheduledExecutorService desyncTimer;
    private final Map<Integer, Integer> localChecksumsByIndex = new ConcurrentHashMap<>();
    private final Map<Integer, Integer> pendingRemoteChecksumsByIndex = new ConcurrentHashMap<>();
    private final AtomicInteger nextCheckIndex = new AtomicInteger();
    private final AtomicBoolean desyncAlreadyReported = new AtomicBoolean(false);

    /**
     * @param peerPorts the port each connected peer's input should land on,
     *                  as announced by the host over the control channel
     *                  during match setup (see the design plan section 4).
     * @param onHostLost called once, at most, if this device's host is
     *                    confirmed lost (see NetplaySession.DataListener#onHostLost's
     *                    doc comment) -- ordinarily MultiplayerManager's
     *                    match teardown. May be null (e.g. the host's own
     *                    relay never loses itself as host).
     */
    public NetplayInputRelay(NetplaySession session, RemoteJoypadSink localTarget,
                              Map<String, Integer> peerPorts, Runnable onHostLost) {
        this(session, localTarget, peerPorts, onHostLost, null, null);
    }

    /**
     * @param localStateSupplier ordinarily {@code NetplayCapableSession#currentSerializedStateForDesync},
     *                            polled on this class's own timer thread (never the render-owner
     *                            thread) -- see that method's doc comment on why calling it off-thread
     *                            is safe. Pass null to disable the desync check entirely (e.g. a core
     *                            with no working serialize() at all -- see that method's own contract
     *                            for how a temporarily-unavailable snapshot is distinguished from that).
     * @param onDesyncDetected called at most once if a peer's reported checksum for a check index this
     *                          device also computed does not match -- ordinarily ends the match with a
     *                          clear message to the player, mirroring onHostLost's shape. Ignored
     *                          (never called) when localStateSupplier is null.
     */
    public NetplayInputRelay(NetplaySession session, RemoteJoypadSink localTarget,
                              Map<String, Integer> peerPorts, Runnable onHostLost,
                              java.util.function.Supplier<byte[]> localStateSupplier,
                              Runnable onDesyncDetected) {
        this.session = session;
        this.localTarget = localTarget;
        this.peerPorts = peerPorts;
        this.onHostLost = onHostLost;
        this.localStateSupplier = localStateSupplier;
        this.onDesyncDetected = onDesyncDetected;
        if (localStateSupplier != null) {
            desyncTimer = Executors.newSingleThreadScheduledExecutor(runnable -> {
                Thread thread = new Thread(runnable, "lucent-netplay-desync-check");
                thread.setDaemon(true);
                return thread;
            });
            desyncTimer.scheduleWithFixedDelay(this::tickDesyncCheck,
                    DESYNC_CHECK_INTERVAL_MS, DESYNC_CHECK_INTERVAL_MS, TimeUnit.MILLISECONDS);
        } else {
            desyncTimer = null;
        }
    }

    /** Call once this relay is being torn down (mirrors NetplaySession.close()'s own timer shutdown). */
    public void stop() {
        if (desyncTimer != null) desyncTimer.shutdownNow();
    }

    /** Call this from the same place port 0's local button state is already applied. */
    public void onLocalJoypadButton(int retroId, boolean pressed) {
        if (retroId < 0 || retroId > 15) return; // outside this message format's 16-bit mask
        int bit = 1 << retroId;
        localButtonMask = pressed ? (localButtonMask | bit) : (localButtonMask & ~bit);
        session.sendToAll(NetplayInputMessage.encodeButtonState(localButtonMask));
    }

    private void tickDesyncCheck() {
        byte[] state = localStateSupplier.get();
        if (state == null) return; // this cycle's snapshot wasn't available; try again next tick
        CRC32 crc = new CRC32();
        crc.update(state);
        int checksum = (int) crc.getValue();
        int index = nextCheckIndex.getAndIncrement();
        localChecksumsByIndex.put(index, checksum);
        trim(localChecksumsByIndex);
        Integer remoteAlreadyArrived = pendingRemoteChecksumsByIndex.remove(index);
        if (remoteAlreadyArrived != null) compareAndMaybeReport(index, checksum, remoteAlreadyArrived);
        session.sendToAll(DesyncCheckMessage.encode(index, checksum));
    }

    private void compareAndMaybeReport(int checkIndex, int mine, int remote) {
        if (mine == remote) return;
        if (!desyncAlreadyReported.compareAndSet(false, true)) return; // already reported once
        Log.w(TAG, "DESYNC DETECTED at checkIndex=" + checkIndex +
                ": local checksum=" + mine + " remote checksum=" + remote +
                " -- ending match (no rollback/resync for this alpha)");
        if (onDesyncDetected != null) onDesyncDetected.run();
    }

    private static void trim(Map<Integer, Integer> map) {
        while (map.size() > MAX_PENDING_DESYNC_CHECKS) {
            Integer oldest = map.keySet().stream().min(Integer::compareTo).orElse(null);
            if (oldest == null) break;
            map.remove(oldest);
        }
    }

    @Override public void onPeerData(String fromDeviceId, byte[] data) {
        DesyncCheckMessage.Decoded desync = DesyncCheckMessage.decode(data);
        if (desync != null) {
            if (localStateSupplier == null) return; // desync checking is off on this device; ignore peer's
            Integer mine = localChecksumsByIndex.get(desync.checkIndex);
            if (mine != null) {
                compareAndMaybeReport(desync.checkIndex, mine, desync.checksum);
            } else {
                pendingRemoteChecksumsByIndex.put(desync.checkIndex, desync.checksum);
                trim(pendingRemoteChecksumsByIndex);
            }
            return;
        }
        Integer port = peerPorts.get(fromDeviceId);
        if (port == null) {
            Log.w(TAG, "input from unassigned peer " + fromDeviceId + ", ignoring");
            return;
        }
        int bitmask = NetplayInputMessage.decodeButtonState(data);
        if (bitmask < 0) return; // not a recognized message kind
        int previous = lastAppliedMaskByPeer.getOrDefault(fromDeviceId, 0);
        int changed = previous ^ bitmask;
        if (changed == 0) return;
        for (int retroId = 0; retroId < 16; retroId++) {
            int bit = 1 << retroId;
            if ((changed & bit) == 0) continue;
            localTarget.applyRemoteJoypadButton(port, retroId, (bitmask & bit) != 0);
        }
        lastAppliedMaskByPeer.put(fromDeviceId, bitmask);
    }

    @Override public void onPeerConnected(String peerDeviceId) {
        Log.i(TAG, "peer connected: " + peerDeviceId);
    }

    @Override public void onHostLost() {
        Log.w(TAG, "host lost -- ending match, per design (host migration is out of scope for this alpha)");
        if (onHostLost != null) onHostLost.run();
    }

    @Override public void onPeerDisconnected(String peerDeviceId) {
        Log.w(TAG, "peer disconnected: " + peerDeviceId);
        Integer port = peerPorts.get(peerDeviceId);
        Integer lastMask = lastAppliedMaskByPeer.remove(peerDeviceId);
        // Release every button a now-gone peer was holding, rather than
        // leaving their character walking into a wall forever.
        if (port != null && lastMask != null) {
            for (int retroId = 0; retroId < 16; retroId++) {
                if ((lastMask & (1 << retroId)) != 0)
                    localTarget.applyRemoteJoypadButton(port, retroId, false);
            }
        }
    }
}
