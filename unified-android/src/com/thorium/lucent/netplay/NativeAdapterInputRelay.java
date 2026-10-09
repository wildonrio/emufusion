package com.thorium.lucent.netplay;

import android.util.Log;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * The Phase 3 native-adapter (Eden/Cemu/aPS3e) analogue of
 * {@link NetplayInputRelay} -- see that class's doc comment for the shared
 * design; this differs only in carrying float control values against a
 * controller_index instead of a boolean joypad bitmask against a port, per
 * {@link NativeControlSink}'s doc comment on why the two families don't
 * share one message shape.
 */
public final class NativeAdapterInputRelay implements NetplaySession.DataListener {
    private static final String TAG = "LucentNetplayNativeRelay";
    private static final int CONTROL_COUNT = 32; // lucent_native_control has 22 today; room to grow

    private final NetplaySession session;
    private final NativeControlSink localTarget;
    private final Map<String, Integer> peerControllerIndices; // deviceId -> assigned controller_index (1..N-1)
    private final Runnable onHostLost;
    private final Map<String, float[]> lastAppliedValuesByPeer = new ConcurrentHashMap<>();

    /**
     * @param peerControllerIndices the controller_index each connected peer's
     *                              input should land on, as announced by the
     *                              host over the control channel during match
     *                              setup (mirrors NetplayInputRelay's peerPorts).
     * @param onHostLost called once, at most, if this device's host is
     *                    confirmed lost (see NetplaySession.DataListener#onHostLost's
     *                    doc comment) -- ordinarily MultiplayerManager's
     *                    match teardown. May be null (e.g. the host's own
     *                    relay never loses itself as host).
     */
    public NativeAdapterInputRelay(NetplaySession session, NativeControlSink localTarget,
                                    Map<String, Integer> peerControllerIndices, Runnable onHostLost) {
        this.session = session;
        this.localTarget = localTarget;
        this.peerControllerIndices = peerControllerIndices;
        this.onHostLost = onHostLost;
    }

    /** Call this from the same place this device's own controller_index 0
     * local input is already applied. */
    public void onLocalControl(int control, float value) {
        if (control < 0 || control >= CONTROL_COUNT) return; // outside this message format's ordinal range
        session.sendToAll(NativeControlMessage.encode(control, value));
    }

    @Override public void onPeerData(String fromDeviceId, byte[] data) {
        Integer controllerIndex = peerControllerIndices.get(fromDeviceId);
        if (controllerIndex == null) {
            Log.w(TAG, "input from unassigned peer " + fromDeviceId + ", ignoring");
            return;
        }
        NativeControlMessage.Decoded decoded = NativeControlMessage.decode(data);
        if (decoded == null) return; // not a recognized message kind
        float[] lastValues = lastAppliedValuesByPeer.computeIfAbsent(
                fromDeviceId, ignored -> new float[CONTROL_COUNT]);
        lastValues[decoded.control] = decoded.value;
        localTarget.applyRemoteControl(controllerIndex, decoded.control, decoded.value);
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
        Integer controllerIndex = peerControllerIndices.get(peerDeviceId);
        float[] lastValues = lastAppliedValuesByPeer.remove(peerDeviceId);
        // Release every control a now-gone peer had set (buttons back to
        // 0f, sticks back to center), rather than leaving their controller
        // stuck holding whatever it last sent.
        if (controllerIndex != null && lastValues != null) {
            for (int control = 0; control < CONTROL_COUNT; control++) {
                if (lastValues[control] != 0f)
                    localTarget.applyRemoteControl(controllerIndex, control, 0f);
            }
        }
    }
}
