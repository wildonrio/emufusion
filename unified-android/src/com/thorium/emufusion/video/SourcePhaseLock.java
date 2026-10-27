package com.thorium.emufusion.video;

/**
 * Holds a paced source's images a fixed short wait before the panel callback
 * that takes them up: a phase-locked loop on the arrival-to-callback wait.
 *
 * <p>A core locked to the panel runs at twice the measured scan period, but
 * that measurement is off by a few hundred ppm, so its phase drifts.
 * {@link SourcePhaseAdvisor}'s one-off moves then let the wait creep back up
 * between moves (Thor, 2026-10-27: NES moved 6 times in 60 s, 1.1-3.8 ms
 * each, about 0.25 ms of drift a second; its first generated image 10-15 ms
 * after arrival from run to run). This instead nudges the source's next frame
 * every frame by a fraction of the smoothed wait error, at most
 * {@link #MAX_NUDGE_NS}, earlier or later.</p>
 *
 * <p>The error is circular: an image that arrives just after a callback
 * waits nearly a whole scan for the next one, which is a small lateness, not
 * a long wait, so the source is moved earlier, never a scan later. The target
 * wait is {@link #TARGET_WAIT_NS} plus {@link #JITTER_MARGIN} times the arrival jitter (its mean
 * absolute deviation), so jittery images still arrive in time. A source whose
 * arrivals do not follow the nudges (its pace is set elsewhere: Ocarina on
 * the hardware-core loop returned to its own phase after every move) is
 * left alone after {@link #MAX_INEFFECTIVE_NS} of nudging without the error
 * shrinking.</p>
 *
 * <p>Observed on the renderer thread, taken on the source's thread.</p>
 */
public final class SourcePhaseLock {
    /**
     * Thor, 2026-10-27, NES alternated: a 1-ms target (plus twice the
     * jitter) cut the first generated image 11.0-11.7 -> 8.6-9.3 ms but held
     * 4-7 frames per 1000 against 3, images that jitter past their
     * callback; smoothness comes first, so the margin is wider.
     */
    public static final long TARGET_WAIT_NS = 1_500_000L;
    public static final double JITTER_MARGIN = 3.0;
    public static final long MAX_NUDGE_NS = 100_000L;
    public static final long DEADBAND_NS = 150_000L;
    /** Error smoothing: short, so the nudges follow the moves they make. */
    public static final double ALPHA = 1.0 / 4.0;
    /** Jitter smoothing: long, so one late image does not widen the margin. */
    public static final double JITTER_ALPHA = 1.0 / 32.0;
    public static final double GAIN = 1.0 / 8.0;
    /**
     * After this much nudging the error must be under {@link #LARGE_ERROR_NS}
     * or at most half what it was: more than half a scan, the longest a
     * working move can need. Holding a steady drift keeps the error near the
     * deadband with small nudges, which is the loop working.
     */
    public static final long MAX_INEFFECTIVE_NS = 10_000_000L;
    public static final long LARGE_ERROR_NS = 1_000_000L;
    /** Observations before the first nudge: the smoothing settles. */
    public static final int WARMUP = 30;
    /** Frames without a nudge before arrival jitter is measured. */
    public static final int STEADY_FRAMES = 8;

    private double errorEma, jitterEma, waitEma;
    private int observed;
    private int framesSinceNudge = STEADY_FRAMES;
    private long pendingNs;
    private boolean abandoned;
    // Ineffective-move detection: nudges since the error was last checked.
    private long nudgedSinceCheckNs;
    private double errorAtCheck = Double.NaN;
    private long nudges, nudgedTotalNs;

    /** One newly taken-up image: arrival to the callback that took it up. */
    public synchronized void observe(long waitNs, long panelPeriodNs) {
        if (abandoned || panelPeriodNs <= 0L || waitNs < 0L || waitNs > panelPeriodNs) {
            if (!abandoned) reset();
            return;
        }
        double period = panelPeriodNs;
        if (observed == 0) {
            waitEma = waitNs;
            jitterEma = 0.0;
        } else {
            // Unwrapped next to its mean, like the error below: an image that
            // crosses into the previous callback is not 8 ms of jitter.
            double wait = waitNs;
            while (wait - waitEma > period / 2.0) wait -= period;
            while (wait - waitEma < -period / 2.0) wait += period;
            if (framesSinceNudge >= STEADY_FRAMES) {
                jitterEma += JITTER_ALPHA * (Math.abs(wait - waitEma) - jitterEma);
                waitEma += JITTER_ALPHA * (wait - waitEma);
            } else {
                // While the lock moves the source its own steps are no jitter.
                waitEma = wait;
            }
        }
        double target = TARGET_WAIT_NS + JITTER_MARGIN * jitterEma;
        double error = waitNs - target;
        if (observed == 0) {
            // Just after a callback: late by the rest of the scan, not early.
            if (error > period / 2.0) error -= period;
            errorEma = error;
        } else {
            // The error is a phase: unwrap it next to the smoothed one, or the
            // smoothing averages +4 and -4 ms to nothing as an image crosses
            // a callback while the source is being moved.
            while (error - errorEma > period / 2.0) error -= period;
            while (error - errorEma < -period / 2.0) error += period;
            errorEma += ALPHA * (error - errorEma);
        }
        if (++observed < WARMUP) return;
        if (Math.abs(errorEma) < DEADBAND_NS) {
            pendingNs = 0L;
            nudgedSinceCheckNs = 0L;
            errorAtCheck = Double.NaN;
            return;
        }
        // Positive: the image waits too long (arrives early), so delay the source.
        pendingNs = (long) Math.max(-MAX_NUDGE_NS, Math.min(MAX_NUDGE_NS, errorEma * GAIN));
    }

    /** The signed shift for the source's next frame (positive = later), or zero. */
    public synchronized long take() {
        long nudge = pendingNs;
        pendingNs = 0L;
        if (nudge == 0L || abandoned) {
            if (framesSinceNudge < Integer.MAX_VALUE) ++framesSinceNudge;
            return 0L;
        }
        framesSinceNudge = 0;
        if (Double.isNaN(errorAtCheck)) errorAtCheck = Math.abs(errorEma);
        nudgedSinceCheckNs += Math.abs(nudge);
        if (nudgedSinceCheckNs >= MAX_INEFFECTIVE_NS) {
            if (Math.abs(errorEma) > LARGE_ERROR_NS && Math.abs(errorEma) > errorAtCheck / 2.0) {
                abandoned = true;
                return 0L;
            }
            nudgedSinceCheckNs = 0L;
            errorAtCheck = Math.abs(errorEma);
        }
        ++nudges;
        nudgedTotalNs += nudge;
        return nudge;
    }

    /** A stall, a held image or a restart: the next waits are not this phase. */
    public synchronized void reset() {
        observed = 0;
        pendingNs = 0L;
        nudgedSinceCheckNs = 0L;
        errorAtCheck = Double.NaN;
    }

    public synchronized boolean abandoned() { return abandoned; }

    /**
     * The smoothed, unwrapped wait error (positive = images arrive early and
     * wait too long), or NaN before the first {@link #WARMUP} observations:
     * the input of a source clocked by rate instead of nudged
     * (SourceRateLock).
     */
    public synchronized double smoothedErrorNs() {
        return observed < WARMUP ? Double.NaN : errorEma;
    }
    public synchronized long nudges() { return nudges; }
    public synchronized long nudgedTotalNs() { return nudgedTotalNs; }
    public synchronized double meanWaitNs() { return waitEma; }
}
