package com.thorium.preview.game;

import android.view.Surface;
import com.thorium.lucent.video.NativeSourceImageProvider;
import com.thorium.lucent.video.RuntimePresentationFailure;

/**
 * Engine-facing contract for one EmuFusion-owned frame-generation renderer.
 *
 * <p>The emulator receives only {@link #inputSurface()}. Implementations own
 * the corresponding display Surface and must keep endpoint identity, source
 * authority, cadence selection, and successful-presentation accounting under
 * EmuFusion control. A backend is therefore a renderer implementation, never
 * a second capture loop or scheduler.</p>
 */
public interface FrameGenerationRenderer extends AutoCloseable {
    interface StatsListener {
        void onFrameRate(double sustainedSourceFps, double selectedOutputFps,
                         double actualPresentedFps, boolean cadenceQualified);
    }

    /** The only Surface an emulator receives. */
    Surface inputSurface();

    /** Current honest routing label for the owner overlay. */
    default String activeBackendLabel() { return "Built-in"; }

    /**
     * Observed source tier (20/30/40/60), or zero while unacquired or when
     * the clock is authoritative. Telemetry only: an observed throughput tier
     * never authorizes changing the guest clock or slowing gameplay.
     */
    default int measuredSourceTier() { return 0; }

    /**
     * True when the unique source clock is an irregular fraction of the
     * core's submission clock (held/dropped frames); false for exact
     * every-Nth-frame schedules. This does not prove a guest clock rate and
     * must not be used to underclock the game.
     */
    default boolean sourceStreamIrregular() { return false; }

    /**
     * True when the source submits on its full lattice but holds 2-8 percent
     * of frames (60 submits, 55-59 unique): light enough that the bridged
     * held-frame proof may still qualify the presentation lattice. This is
     * image-stream telemetry, not authority to alter guest speed.
     */
    default boolean sourceStreamLightlyHeld() { return false; }

    /** Measured unique-image rate of the source in Hz (0 when unknown). */
    default double sourceUniqueHz() { return 0.0; }

    /** Physical/declared panel clock ratio for core pacing (1.0 = unknown). */
    default double panelClockRatio() { return 1.0; }

    /** Fresh sustained physical scan frequency, or zero when not qualified. */
    default double physicalPanelHz() { return 0.0; }

    /** Source-vs-scan drift in microseconds per second (0 = unknown/none). */
    default double endpointDriftUsPerSecond() { return 0.0; }

    /** Latest endpoint-to-slot residue in nanoseconds at a REAL snap. */
    default long endpointOffsetNs() { return 0L; }

    /**
     * The host has locked the core clock to the measured panel clock.  The
     * presentation timeline re-primes once so its prime anchor is taken with
     * the source and scan lattices already commensurate: from then on every
     * endpoint lands on its slot and every interior phase is an exact k/N.
     * Before the lock the anchor drifted ~65 us/s (F-Zero run n64-60first
     * sat at phase 0.357 instead of 0.5).
     */
    default void onCoreClockLocked() {}

    /**
     * The physical panel changed mode (60 <-> 120 Hz) after this renderer was
     * created.  The Thor applies the window's 120-Hz request a moment after
     * the Surface exists, so a generator attached at 60.000004 Hz otherwise
     * plans a 60-Hz protocol against a panel that scans at 120 (N64 run
     * n64-tier1 and GameCube run gc2, 2026-09-01: every due slot missed,
     * cadence rejected, session fell to direct).
     */
    default void setPanelRefreshHz(float hz) {}

    /** True while the timing authority is still gathering evidence for a
     *  canonical source clock (a higher lattice may fund shortly). */
    default boolean clockAcquisitionInProgress() { return false; }

    /** Native adapters stamp presents on real-time lattice slots; a dropped
     *  guest frame is a doubled span with one submission. */
    default void setSlotLatticeProducer(boolean value) {}

    void setStatsListener(StatsListener value);

    /** Once-only runtime failure; owners must marshal to UI and validate Surface identity.
     * Never close/rebind the renderer from this callback's render-owner thread. */
    default void setRuntimeErrorListener(RuntimePresentationFailure.Listener value) {}

    /** Uses the fixed cadence declared by a deterministic legacy core. */
    void setAuthoritativeSourceHz(double sourceHz);

    /** Hardware-core PTS clock; transport provenance, never source authority. */
    void setProducerTimelineHz(double timelineHz);

    /** Optional exact-host image observer, never timing/generation authority.
     * The renderer owns provider-generation and retained-image invalidation. */
    default void setNativeSourceImageProvider(NativeSourceImageProvider provider) {}

    /** Runs once after the producer's first complete buffer is consumed. */
    void setFirstSubmittedFrameListener(Runnable value);

    /**
     * Optional zero-copy-friendly software-frame submission path.
     *
     * <p>The implementation must take an immutable snapshot before returning
     * true because the emulation thread immediately reuses {@code colors}.</p>
     */
    boolean submitSoftwareFrame(int[] colors, int frameWidth, int frameHeight,
                                int left, int top, int right, int bottom,
                                float contentAspect);

    /**
     * Software-frame submission carrying the producer's scheduled timestamp
     * (System.nanoTime domain, zero when unknown).  A paced libretro core is
     * stamped on the exact lattice it is paced at, which is what the timing
     * authority's clock proof needs; the upload thread's arrival time is not.
     */
    default boolean submitSoftwareFrame(int[] colors, int frameWidth, int frameHeight,
                                        int left, int top, int right, int bottom,
                                        float contentAspect, long producerTimestampNs) {
        return submitSoftwareFrame(colors, frameWidth, frameHeight, left, top,
                right, bottom, contentAspect);
    }

    /** Resizes without replacing the producer Surface or restarting a core. */
    void resize(int newInputWidth, int newInputHeight,
                int newOutputWidth, int newOutputHeight, float newRefreshHz);

    @Override void close();
}
