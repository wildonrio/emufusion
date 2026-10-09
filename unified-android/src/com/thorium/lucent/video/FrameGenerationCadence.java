package com.thorium.lucent.video;

/**
 * Presentation-only cadence estimator for EmuFusion frame generation.
 *
 * <p>The emulator remains the sole owner of simulation and audio time. This
 * class observes when real frames arrive and answers how far presentation has
 * advanced between the previous and current real images. It never asks a core
 * to run an extra frame and it never changes a core's clock.
 */
public final class FrameGenerationCadence {
    private static final long MIN_SOURCE_PERIOD_NS = 2_000_000L;
    private static final long MAX_SOURCE_PERIOD_NS = 250_000_000L;
    private static final double FILTER_NEW_SAMPLE = 0.20;
    private static final double GENERATION_MARGIN = 1.10;

    private long displayPeriodNs;
    private long estimatedSourcePeriodNs;
    private long lastSourceFrameNs;
    private int sourceFrames;

    public FrameGenerationCadence(double displayRefreshHz) {
        setDisplayRefreshHz(displayRefreshHz);
    }

    public void setDisplayRefreshHz(double refreshHz) {
        if (!Double.isFinite(refreshHz) || refreshHz < 20.0 || refreshHz > 1000.0)
            refreshHz = 60.0;
        displayPeriodNs = Math.max(1L, Math.round(1_000_000_000.0 / refreshHz));
    }

    /** Records one genuinely new producer frame. Duplicate display presents do not call this. */
    public void onSourceFrame(long frameTimeNs) {
        if (lastSourceFrameNs > 0L) {
            long sample = frameTimeNs - lastSourceFrameNs;
            if (sample >= MIN_SOURCE_PERIOD_NS && sample <= MAX_SOURCE_PERIOD_NS) {
                if (estimatedSourcePeriodNs == 0L) estimatedSourcePeriodNs = sample;
                else estimatedSourcePeriodNs = Math.round(
                        estimatedSourcePeriodNs * (1.0 - FILTER_NEW_SAMPLE) +
                                sample * FILTER_NEW_SAMPLE);
            }
        }
        lastSourceFrameNs = frameTimeNs;
        if (sourceFrames < Integer.MAX_VALUE) ++sourceFrames;
    }

    /** True only when at least one intermediate panel refresh fits between source frames. */
    public boolean generatesIntermediateFrames() {
        return sourceFrames >= 2 && estimatedSourcePeriodNs > 0L &&
                estimatedSourcePeriodNs > displayPeriodNs * GENERATION_MARGIN;
    }

    /**
     * Blend of previous to current at a display-vsync timestamp.
     *
     * <p>Interpolation deliberately carries one source-frame of presentation
     * history. At the instant a new real frame arrives, the previous image is
     * still the continuous endpoint; subsequent display refreshes progress to
     * the new image. When source and display cadence are effectively equal,
     * current is returned directly and no artificial latency is added.
     */
    public float interpolation(long displayFrameTimeNs) {
        if (!generatesIntermediateFrames()) return 1f;
        long elapsed = Math.max(0L, displayFrameTimeNs - lastSourceFrameNs);
        if (elapsed >= estimatedSourcePeriodNs) return 1f;
        return (float) elapsed / (float) estimatedSourcePeriodNs;
    }

    public double displayRefreshHz() {
        return 1_000_000_000.0 / displayPeriodNs;
    }

    public double estimatedSourceHz() {
        return estimatedSourcePeriodNs <= 0L ? 0.0 :
                1_000_000_000.0 / estimatedSourcePeriodNs;
    }

    public long estimatedSourcePeriodNs() { return estimatedSourcePeriodNs; }

    /**
     * Presentation timestamp for a buffer rendered from one Choreographer tick.
     *
     * <p>The callback describes the scan that started the render. The resulting
     * buffer cannot be latched until a later scan, so its first legal target is
     * one display period later. If a long frame finishes after that target,
     * advance directly to the first future scan instead of submitting a stale
     * timestamp or trying to catch up with two buffers on one scan.</p>
     */
    public static long nextPresentationTimeNs(
            long callbackFrameNs, long displayPeriodNs, long nowNs) {
        if (callbackFrameNs <= 0L || displayPeriodNs <= 0L || nowNs < 0L)
            return 0L;
        long target = callbackFrameNs > Long.MAX_VALUE - displayPeriodNs ?
                Long.MAX_VALUE : callbackFrameNs + displayPeriodNs;
        if (target > nowNs) return target;
        long behind = nowNs - target;
        long periods = behind / displayPeriodNs + 1L;
        if (periods > (Long.MAX_VALUE - target) / displayPeriodNs)
            return Long.MAX_VALUE;
        return target + periods * displayPeriodNs;
    }

    /** Outliers become a renderer failure only after consecutive bad windows. */
    public static int advanceCadenceFailureWindows(
            int previous, boolean eligible, boolean underTarget) {
        if (!eligible || !underTarget) return 0;
        return previous == Integer.MAX_VALUE ? previous : previous + 1;
    }

    /**
     * A generator is never allowed to make presentation slower than showing
     * the measured source directly. This floor is deliberately independent of
     * the aspirational x2 target: missing that target can be a transient, but
     * falling below 96% of the real source over a complete window means the
     * generation path is actively suppressing emulator frames and must fail
     * closed to direct endpoints.
     */
    public static boolean generationFallsBelowSourceFloor(
            long elapsedMs, long presents, int sourceFps, int outputFps) {
        if (elapsedMs < 800L || presents <= 0L || sourceFps <= 0 ||
                outputFps <= sourceFps) return false;
        return presents * 1000.0 / elapsedMs < sourceFps * 0.96;
    }

    /**
     * A claimed generated mode is atomic: it either sustains its target or is
     * disabled. Intermediate outcomes such as 30/45 or 50/41 are neither a
     * stable direct cadence nor the advertised x2 cadence and are visibly
     * worse than an honest direct fallback.
     */
    public static boolean generationMissesTargetCadence(
            long elapsedMs, long presents, int sourceFps, int outputFps) {
        if (elapsedMs < 800L || presents <= 0L || sourceFps <= 0 ||
                outputFps <= sourceFps) return false;
        return presents * 1000.0 / elapsedMs < outputFps * 0.96;
    }
}
