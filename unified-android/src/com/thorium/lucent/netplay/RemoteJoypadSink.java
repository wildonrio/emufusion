package com.thorium.lucent.netplay;

/**
 * Where a remote player's joypad input goes once it's known -- implemented
 * by {@code LibretroEngineSession.applyRemoteJoypadButton} and
 * {@code PpssppGlesEngineSession.applyRemoteJoypadButton} (both in
 * com.thorium.preview.game, referenced here only via method reference so
 * this package stays independent of the engine-session classes). Shared
 * by both {@link NetplaySyntheticInputTester} (synthetic, no networking)
 * and {@link NetplayInputRelay} (real DataChannel bytes) so the two are
 * interchangeable at the call site in InWindowGameHost.
 */
public interface RemoteJoypadSink {
    void applyRemoteJoypadButton(int port, int retroId, boolean pressed);
}
