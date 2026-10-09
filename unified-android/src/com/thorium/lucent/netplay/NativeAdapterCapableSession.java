package com.thorium.lucent.netplay;

/**
 * Implemented by {@code NativeAdapterEngineSession} once it can host a
 * netplay match (Eden/Cemu/aPS3e, Phase 4 of the multiplayer alpha plan --
 * see {@link NetplayCapableSession} for why the libretro/PPSSPP family has
 * its own, separate version of this interface rather than sharing one).
 * Lets {@code ActiveEngineSessionRegistry} and {@code MultiplayerManager}
 * attach/detach a relay without an instanceof check per session family.
 */
public interface NativeAdapterCapableSession extends NativeControlSink {
    void attachNetplayRelay(NativeAdapterInputRelay relay);
    void detachNetplayRelay();
}
