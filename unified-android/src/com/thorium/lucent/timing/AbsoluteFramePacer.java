package com.thorium.lucent.timing;

/** Monotonic absolute-deadline pacer that does not accumulate sleep overshoot. */
public final class AbsoluteFramePacer {
    private static final long DEFAULT_MAX_LATE_PERIODS = 4L;

    private final long periodNanos;
    private final long maxLatenessNanos;
    private long deadlineNanos;
    private boolean started;
    private boolean coalescingCatchUpPresentation;

    public AbsoluteFramePacer(long periodNanos) {
        if (periodNanos < 1L) throw new IllegalArgumentException("period must be positive");
        this.periodNanos = periodNanos;
        this.maxLatenessNanos = saturatingMultiply(
                periodNanos, DEFAULT_MAX_LATE_PERIODS);
    }

    /** Starts/restarts the timeline at resume or after a deliberate pause. */
    public void reset(long nowNanos) {
        deadlineNanos = nowNanos;
        started = true;
        coalescingCatchUpPresentation = false;
    }

    /** Returns time remaining until the next absolute frame deadline. */
    public long delayAfterFrame(long nowNanos) {
        if (!started) reset(nowNanos);
        long candidate = saturatingAdd(deadlineNanos, periodNanos);
        long lateness = nowNanos > candidate ? nowNanos - candidate : 0L;
        boolean resetTimeline = lateness > maxLatenessNanos;
        /* A short scheduler/GC stall may require the emulation and audio clock
         * to execute more than one core step immediately. Those catch-up steps
         * must not each become a visible Surface post: that converts one hitch
         * into a rapid burst followed by another hold. The owner can coalesce
         * whole-period catch-up steps and publish only the newest endpoint when
         * the absolute timeline is back within one period. Ordinary sub-period
         * overshoot remains visible, and a very large stall resets outright. */
        if (resetTimeline) {
            coalescingCatchUpPresentation = false;
            candidate = saturatingAdd(nowNanos, periodNanos);
        } else if (lateness >= periodNanos) {
            coalescingCatchUpPresentation = true;
        } else if (candidate > nowNanos) {
            // Once catch-up began, keep all zero-delay iterations coalesced.
            // Publish exactly once only when the timeline has a positive wait.
            coalescingCatchUpPresentation = false;
        }
        deadlineNanos = candidate;
        return candidate > nowNanos ? candidate - nowNanos : 0L;
    }

    public long periodNanos() { return periodNanos; }

    /** Changes future spacing without moving the frame already scheduled. */
    public AbsoluteFramePacer withPeriodPreservingDeadline(long newPeriodNanos) {
        AbsoluteFramePacer next = new AbsoluteFramePacer(newPeriodNanos);
        next.deadlineNanos = deadlineNanos;
        next.started = started;
        next.coalescingCatchUpPresentation = coalescingCatchUpPresentation;
        return next;
    }

    /**
     * Absolute due time of the frame the owner is about to run (the deadline
     * {@link #delayAfterFrame} last scheduled, or the reset instant).  Frames
     * stamped with it sit on the pacer's exact lattice, so a paced software
     * core is stamped on the clock it is paced at rather than on the jitter
     * of the thread that later uploads the picture.
     */
    public long deadlineNanos() { return deadlineNanos; }

    public boolean coalescingCatchUpPresentation() {
        return coalescingCatchUpPresentation;
    }

    private static long saturatingAdd(long first, long second) {
        if (second > 0L && first > Long.MAX_VALUE - second) return Long.MAX_VALUE;
        return first + second;
    }

    private static long saturatingMultiply(long value, long multiplier) {
        if (value > Long.MAX_VALUE / multiplier) return Long.MAX_VALUE;
        return value * multiplier;
    }
}
