package com.thorium.lucent.netplay;

/**
 * Implemented by every engine session family that can host a netplay
 * match today (LibretroEngineSession, PpssppGlesEngineSession -- see
 * NetplayInputMessage's doc comment for why NativeAdapterEngineSession
 * is not one of these yet). Lets {@link ActiveEngineSessionRegistry} and
 * {@code MultiplayerManager} attach/detach a relay and route decoded
 * remote input without an instanceof check per session family.
 *
 * <p>Extends {@link RemoteJoypadSink} rather than duplicating its method:
 * every implementor already has one (see LibretroEngineSession's
 * applyRemoteJoypadButton and its Ppsspp mirror), and MultiplayerManager
 * needs to pass a session reference where a sink is expected (building a
 * NetplayInputRelay), so the two need to be the same type.
 */
public interface NetplayCapableSession extends RemoteJoypadSink {
    void attachNetplayRelay(NetplayInputRelay relay);
    void detachNetplayRelay();

    /**
     * The core's current full-state snapshot, for {@link NetplayInputRelay}'s
     * periodic desync check (see its own doc comment) -- exactly the same
     * bytes Quick Resume already persists via this session's own
     * {@code serialize()} path, reused here rather than duplicated. Returns
     * null (never a fake/empty result) whenever a real snapshot isn't
     * available right now: no active core, or the underlying
     * {@code serialize()} call itself failed or returned nothing -- a core
     * that can't produce state should be silently skipped for this cycle's
     * desync check, never reported as a false mismatch.
     */
    byte[] currentSerializedStateForDesync();
}
