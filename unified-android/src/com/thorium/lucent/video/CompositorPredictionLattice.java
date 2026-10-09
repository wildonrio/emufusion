package com.thorium.lucent.video;

/**
 * Integer scan identity in successive Android prediction windows. This is a
 * planning clock, never evidence that any image was displayed.
 *
 * <p>Android revises its predictions continuously. Carry the integer ordinal
 * across nearby windows, then use the current window's phase and spacing,
 * instead of extrapolating a stale prediction with a noisy fence frequency.
 * Immutable requests and the physical ledger still determine scanout success.</p>
 */
public final class CompositorPredictionLattice {
    public static final long MAX_WINDOW_GAP_NS = 250_000_000L;
    private long frameTimeNs;
    private long headNs;
    private long periodNs;
    private long headOrdinal;

    /** Invalid/discontinuous windows leave all state unchanged. */
    public boolean observe(long callbackNs, long[] expectedNs, int count) {
        if (callbackNs <= 0L || expectedNs == null || count < 2 ||
                count > expectedNs.length || expectedNs[0] <= callbackNs)
            return false;
        long nextPeriod = expectedNs[1] - expectedNs[0];
        if (nextPeriod <= 0L) return false;
        for (int i = 1; i < count; ++i) {
            long interval = expectedNs[i] - expectedNs[i - 1];
            if (interval <= 0L || difference(interval, nextPeriod) > 1L)
                return false;
        }
        long nextOrdinal = 0L;
        if (headNs != 0L) {
            // Long gaps or mode/phase jumps require a scheduler discontinuity,
            // not a guess about which old divisor phase the new grid belongs to.
            if (callbackNs < frameTimeNs ||
                    callbackNs - frameTimeNs > MAX_WINDOW_GAP_NS ||
                    difference(nextPeriod, periodNs) >
                            CompositorFrameTimeline.MAX_TARGET_ERROR_NS)
                return false;
            long delta = expectedNs[0] - headNs;
            if (delta < 0L || delta > Long.MAX_VALUE - nextPeriod / 2L)
                return false;
            long scans = (delta + nextPeriod / 2L) / nextPeriod;
            if (scans > Long.MAX_VALUE / nextPeriod ||
                    difference(delta, scans * nextPeriod) >
                            CompositorFrameTimeline.MAX_TARGET_ERROR_NS ||
                    headOrdinal > Long.MAX_VALUE - scans ||
                    (callbackNs == frameTimeNs && delta != 0L))
                return false;
            nextOrdinal = headOrdinal + scans;
        }
        frameTimeNs = callbackNs;
        headNs = expectedNs[0];
        periodNs = nextPeriod;
        headOrdinal = nextOrdinal;
        return true;
    }

    /** Nearby origin retaining the original integer divisor phase. */
    public long anchorNs(int scansPerOutput) {
        if (headNs <= 0L || scansPerOutput < 1) return 0L;
        long residual = headOrdinal % scansPerOutput;
        if (residual > Long.MAX_VALUE / periodNs) return 0L;
        long offset = residual * periodNs;
        return offset < headNs ? headNs - offset : 0L;
    }

    public long periodNs() { return periodNs; }
    public long headOrdinal() { return headOrdinal; }
    public boolean available() { return headNs > 0L; }
    public void reset() {
        frameTimeNs = 0L;
        headNs = 0L;
        periodNs = 0L;
        headOrdinal = 0L;
    }
    private static long difference(long left, long right) {
        return left >= right ? left - right : right - left;
    }
}
