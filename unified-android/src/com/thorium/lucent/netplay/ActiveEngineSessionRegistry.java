package com.thorium.lucent.netplay;

/**
 * The one currently-running netplay-capable engine session, if any --
 * updated by InWindowGameHost as sessions become ready and are torn
 * down. This is how MultiplayerManager (android-companion, a different
 * source tree entirely, though compiled into the same APK) finds
 * somewhere to attach a relay once a match goes active, without either
 * side depending on the other's concrete engine session classes.
 *
 * <p>Deliberately a single slot, not a stack or map: only one game can be
 * running in the foreground at a time in this app's architecture (see
 * InWindowGameHost's own doc comment on owning gameplay inside the
 * existing Qt window rather than a separate Activity per session).
 *
 * <p>Typed as {@code Object} rather than one specific capable-session
 * interface because two genuinely different session families can occupy
 * this slot -- {@link NetplayCapableSession} (libretro/PPSSPP,
 * {@link NetplayInputRelay}) and {@link NativeAdapterCapableSession}
 * (Eden/Cemu/aPS3e, {@link NativeAdapterInputRelay}) -- and the caller
 * (MultiplayerManager) already has to pick which relay type to build, so
 * it is the natural place to {@code instanceof}-check which family the
 * current session belongs to.
 */
public final class ActiveEngineSessionRegistry {
    private static volatile Object current;

    private ActiveEngineSessionRegistry() {}

    public static void set(Object session) {
        current = session;
    }

    /** Call when a session is torn down; a no-op if it wasn't the current one (avoids a stale clear racing a newer session's set). */
    public static void clearIfCurrent(Object session) {
        if (current == session) current = null;
    }

    public static Object current() {
        return current;
    }
}
