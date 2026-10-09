package com.thorium.preview.game;

import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.Surface;

import com.thorium.lucent.cheats.Cheat;
import com.thorium.lucent.input.CanonicalControl;
import com.thorium.preview.cheats.delivery.CheatSessionRegistry;

import java.util.Collections;
import java.util.List;
import java.util.Set;

/** Runtime boundary shared by future libretro and native engine adapters. */
public interface EngineSession {
    enum PauseReason { LUCENT_MENU, ANDROID_BACKGROUND }
    enum StopReason { EXIT_TO_LUCENT, ACTIVITY_DESTROYED }

    interface Listener {
        void onSessionReady();
        void onSessionError(String message, Throwable cause);
        void onSessionStopRejected(String message, Throwable cause);
        void onRestoreAvailabilityChanged(boolean available);
    }

    interface Completion {
        void complete();
    }

    void prepare(GameLaunchRequest request, Listener listener);
    void attachSurface(Surface surface, int width, int height);
    void resizeSurface(int width, int height);
    void detachSurface();
    void resume();
    void pause(PauseReason reason);

    /**
     * One-shot notification that the session has successfully published its
     * first gameplay frame. Direct SurfaceView launches use this to remove the
     * black launch curtain without a guessed timer.
     */
    default void setFirstFrameCallback(Runnable callback) {}

    /**
     * Near-native display-clock correction (policy 2026-09-04). Positive
     * requests must stay within 0.75 percent of the original declared core
     * clock; zero restores the normal synchronized clock. Unsafe requests
     * leave the clock unchanged. Never downclock the guest to hide load or
     * confuse a game's unique-image FPS with its simulation clock. Engines
     * without clock control return false.
     */
    default boolean setPacedVideoHz(double hz) { return false; }

    /** Explicit clock correction set by {@link #setPacedVideoHz}, or zero. */
    default double pacedVideoHz() { return 0.0; }

    /** The core's own declared video clock in Hz, or zero when unknown. */
    default double declaredVideoHz() { return 0.0; }

    /**
     * Core frames actually run per second over the trailing second, or zero
     * when unknown.  Distinguishes a core that is failing its clock from one
     * that runs at full speed while the game itself updates less often.
     */
    default double achievedCoreHz() { return 0.0; }

    /**
     * Clock the engine could sustain from its worst per-second frame work
     * time over the trailing fifteen seconds, or zero when not yet known.
     * A paced core uses this to prove headroom before its pacing is lifted,
     * so the lift itself never produces a wobbling burst.
     */
    default double sustainedFrameWorkCapacityHz() { return 0.0; }

    /**
     * Drains any in-flight frame and prevents another frame from being
     * scheduled before EmuFusion reveals its warm library UI. Hardware sessions
     * must complete this boundary while their Android Surface is still valid.
     */
    void quiesceForExit();

    /**
     * Pause and detach the primary producer before a failed generator is retired.
     * True acknowledges completed owner-thread work, never a queued request or
     * elapsed wait. No reset, save reload, or guest-clock change is permitted.
     */
    default boolean quiesceForPresentationRecovery() { return false; }

    /** Worker-only acknowledgement before releasing a published FG input,
     * including when native startup is still using that input. */
    default boolean quiesceForSurfaceRetirement() {
        return quiesceForPresentationRecovery();
    }

    /** Returns true when the engine displayed its Lucent-owned remapping UI. */
    boolean openControls();

    /** Returns true when the engine displayed a Lucent-owned checkpoint timeline. */
    boolean openRestoreHistory();

    /**
     * Restarts the running game from power-on, as the held Select+Start combo
     * requests.
     *
     * Fails closed: an adapter that cannot prove it reached a real reset must
     * return false so the host reports nothing happened rather than leaving the
     * player unsure whether their progress was discarded.
     */
    default boolean reset() { return false; }

    /**
     * Cheats this session can switch on and off while the game runs, in the
     * catalogue's authored order.
     *
     * <p>Empty for an engine with no cheat support and for a game the
     * catalogue does not carry, which is the same answer the pause menu needs:
     * offer nothing rather than an empty list.
     */
    default List<Cheat> availableCheats() {
        // Engines without a live bridge of their own still list the boot-
        // delivered rows CheatLaunchHooks registered for this session; with
        // nothing registered the answer stays the empty list (2026-09-06).
        List<Cheat> registered = CheatSessionRegistry.availableCheats(this);
        return registered == null ? Collections.<Cheat>emptyList() : registered;
    }

    /** Ids currently switched on, a subset of {@link #availableCheats()}. */
    default Set<String> enabledCheatIds() {
        Set<String> registered = CheatSessionRegistry.enabledCheatIds(this);
        return registered == null ? Collections.<String>emptySet() : registered;
    }

    /**
     * Switches one cheat on the running game and records the choice.
     *
     * <p>Fails closed: an engine that cannot prove the change reached the game
     * returns false so the menu can say so instead of showing a toggle that
     * moved but did nothing. A registered boot-delivered row records the
     * choice and rewrites the engine's boot file; nothing registered is false.
     */
    default boolean setCheatEnabled(String cheatId, boolean enabled) {
        return CheatSessionRegistry.setCheatEnabled(this, cheatId, enabled);
    }

    /** Receives gameplay keys after EmuFusion's pause/Stop-button handling. */
    boolean dispatchKeyEvent(KeyEvent event);

    /** Receives joystick axes after EmuFusion's shell-level gestures. */
    boolean dispatchGenericMotionEvent(MotionEvent event);

    /** Unclaimed touches on the primary gameplay view, in logical view pixels. */
    default void onPrimaryTouch(MotionEvent event, int width, int height) {}

    /** Local display selection for a dual-screen core running on one panel. */
    default boolean canSwitchPrimaryScreen() { return false; }
    default boolean isGamepadOnPrimary() { return false; }
    default boolean switchPrimaryScreen() { return false; }

    /** True only on phones/tablets without a complete physical controller. */
    boolean shouldShowOnScreenControls();

    /** Input from EmuFusion's own optional touch overlay. */
    boolean dispatchVirtualControl(CanonicalControl control, boolean pressed);

    /** Analog sticks exposed by the phone overlay; physical routing is unchanged. */
    default int virtualAnalogStickCount() { return 0; }
    default boolean dispatchVirtualAnalog(int stick, float x, float y) { return false; }

    /** Implementations save Quick Resume before invoking completion. */
    void stop(StopReason reason, Completion completion);

    void release();
}
