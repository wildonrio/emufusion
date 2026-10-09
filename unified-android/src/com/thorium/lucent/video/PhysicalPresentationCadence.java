package com.thorium.lucent.video;

/**
 * Rolling, allocation-free interpretation of physical display-present times.
 *
 * <p>Inputs must come from {@code EGL_DISPLAY_PRESENT_TIME_ANDROID}; swap,
 * callback and submission times are deliberately not accepted here.  The
 * displayed actual rate becomes available after a short observation window,
 * while qualification requires two clean seconds at one exact panel-scan
 * divisor.  A missed compositor presentation therefore lowers the measured
 * rate and invalidates cadence instead of being counted as delivered.</p>
 */
public final class PhysicalPresentationCadence {
    private static final int CAPACITY = 256;
    private static final long ACTUAL_MIN_SPAN_NS = 500_000_000L;
    private static final long QUALIFIED_MIN_SPAN_NS = 2_000_000_000L;
    private static final int ACTUAL_MIN_INTERVALS = 16;
    // 3 percent (250 us on a 120-Hz scan): the Thor's DISPLAY_PRESENT_TIME
    // jitters ~0.17 ms on single scans (wiiu-b45: 8.50-ms intervals), which
    // no viewer can see, while a genuinely missed scan is +100 percent.
    private static final double MAX_INTERVAL_ERROR_FRACTION = 0.03;
    private static final long MIN_INTERVAL_TOLERANCE_NS = 150_000L;
    private static final double MAX_RATE_ERROR_FRACTION = 0.01;

    private final long[] timestamps = new long[CAPACITY];
    // (2026-09-01) Frames whose compositor history expired before the
    // timestamp query are UNVERIFIABLE, not dropped: the driver keeps only
    // eight frames of history and the in-process Cemu/Eden adapters delayed
    // the poll past it on ~57 frames per second (wiiu-b40: 12239 expiries,
    // zero compositor drops, physical rate 120.01), so the cadence never
    // held two seconds and generation never reported qualified.  Each
    // expiry is remembered against the next verified present; interval
    // checks bridge that many expected intervals and a bounded fraction of
    // the window may be unverifiable.  Compositor DROPS stay fail-closed.
    private final int[] unverifiedBefore = new int[CAPACITY];
    private int pendingUnverified;
    private static final double MAX_UNVERIFIED_FRACTION = 0.25;
    private int head;
    private int count;
    private int scansPerOutput = -1;
    private long panelPeriodNs;
    private boolean recoveringFromDrop;
    private long firstPresentAfterDropNs;
    private long successfulPresents;
    private long droppedPresents;
    private long unavailablePresents;

    /** Records one buffer that began physical scanout. */
    public boolean recordPresented(long presentNs, int scans,
                                   long measuredPanelPeriodNs) {
        if (presentNs <= 0L || scans < 0 || measuredPanelPeriodNs <= 0L)
            return false;
        adoptTarget(scans, measuredPanelPeriodNs);
        if (count > 0 && presentNs <= newestTimestamp()) return false;
        if (count == CAPACITY) {
            head = (head + 1) % CAPACITY;
            --count;
        }
        timestamps[(head + count) % CAPACITY] = presentNs;
        unverifiedBefore[(head + count) % CAPACITY] = pendingUnverified;
        pendingUnverified = 0;
        ++count;
        ++successfulPresents;
        if (recoveringFromDrop) {
            if (firstPresentAfterDropNs == 0L)
                firstPresentAfterDropNs = presentNs;
            else if (presentNs - firstPresentAfterDropNs >=
                    QUALIFIED_MIN_SPAN_NS) {
                recoveringFromDrop = false;
                firstPresentAfterDropNs = 0L;
            }
        }
        return true;
    }

    /** Records an enqueued buffer that the compositor reports was not shown. */
    public void recordDropped(int scans, long measuredPanelPeriodNs) {
        if (scans < 0 || measuredPanelPeriodNs <= 0L) {
            reset();
            return;
        }
        adoptTarget(scans, measuredPanelPeriodNs);
        recoveringFromDrop = true;
        firstPresentAfterDropNs = 0L;
        ++droppedPresents;
    }

    /** Records a frame whose finite compositor history expired before query. */
    public void recordUnavailable(int scans, long measuredPanelPeriodNs) {
        if (scans < 0 || measuredPanelPeriodNs <= 0L) {
            reset();
            return;
        }
        adoptTarget(scans, measuredPanelPeriodNs);
        if (pendingUnverified < Integer.MAX_VALUE) ++pendingUnverified;
        ++unavailablePresents;
    }

    public void reset() {
        head = 0;
        count = 0;
        pendingUnverified = 0;
        scansPerOutput = -1;
        panelPeriodNs = 0L;
        recoveringFromDrop = false;
        firstPresentAfterDropNs = 0L;
    }

    /** A rolling physically presented rate, never a requested or swap rate. */
    public double actualHz(int expectedScans, long expectedPanelPeriodNs) {
        if (!targetMatches(expectedScans, expectedPanelPeriodNs) ||
                count <= ACTUAL_MIN_INTERVALS)
            return 0.0;
        long span = newestTimestamp() - oldestTimestamp();
        if (span < ACTUAL_MIN_SPAN_NS) return 0.0;
        // Unverifiable frames occupied their scans (the compositor reported
        // no drop); leaving them out read 96-115 on a 120-Hz output that
        // presented every scan (wiiu-b41).
        long unverified = 0L;
        for (int index = 1; index < count; ++index)
            unverified += unverifiedBefore[(head + index) % CAPACITY];
        return (count - 1 + unverified) * 1_000_000_000.0 / span;
    }

    private String lastRejection = "none";

    /** Why the newest complete window did not qualify (diagnostic only). */
    public String lastRejection() { return lastRejection; }

    public boolean qualified(int expectedScans, long expectedPanelPeriodNs) {
        if (expectedScans <= 0 || recoveringFromDrop ||
                !targetMatches(expectedScans, expectedPanelPeriodNs) || count < 2)
            return false;
        long expectedInterval = saturatingMultiply(expectedPanelPeriodNs,
                expectedScans);
        long span = newestTimestamp() - oldestTimestamp();
        if (expectedInterval <= 0L || span < QUALIFIED_MIN_SPAN_NS) return false;
        long tolerance = Math.max(MIN_INTERVAL_TOLERANCE_NS,
                Math.round(expectedInterval * MAX_INTERVAL_ERROR_FRACTION));
        long previous = timestamps[head];
        long unverified = 0L;
        for (int index = 1; index < count; ++index) {
            int slot = (head + index) % CAPACITY;
            long current = timestamps[slot];
            long delta = current - previous;
            // An unverifiable frame between two verified presents still
            // occupied its scans: the verified interval must be exactly
            // that many expected intervals.
            long bridged = saturatingMultiply(expectedInterval,
                    1 + unverifiedBefore[slot]);
            long bridgedTolerance = Math.max(tolerance, Math.round(
                    bridged * MAX_INTERVAL_ERROR_FRACTION));
            if (delta <= 0L || absoluteDifference(delta, bridged) >
                    bridgedTolerance) {
                lastRejection = "interval index=" + index + "/" + count +
                        " deltaNs=" + delta + " expectedNs=" + bridged +
                        " unverifiedBefore=" + unverifiedBefore[slot];
                return false;
            }
            unverified += unverifiedBefore[slot];
            previous = current;
        }
        if (unverified * 1.0 > (count + unverified) * MAX_UNVERIFIED_FRACTION) {
            lastRejection = "unverified=" + unverified + "/" +
                    (count + unverified);
            return false;
        }
        double actual = (count - 1 + unverified) * 1_000_000_000.0 / span;
        double target = 1_000_000_000.0 / expectedInterval;
        boolean ok = Math.abs(actual - target) <= target * MAX_RATE_ERROR_FRACTION;
        lastRejection = ok ? "none" : "rate actual=" + actual + " target=" + target;
        return ok;
    }

    public int sampleCount() { return count; }
    public long successfulPresents() { return successfulPresents; }
    public long droppedPresents() { return droppedPresents; }
    public long unavailablePresents() { return unavailablePresents; }
    public boolean waitingAfterDrop() { return recoveringFromDrop; }

    private void adoptTarget(int scans, long measuredPanelPeriodNs) {
        if (scansPerOutput == scans && panelPeriodNs == measuredPanelPeriodNs) return;
        head = 0;
        count = 0;
        recoveringFromDrop = false;
        firstPresentAfterDropNs = 0L;
        scansPerOutput = scans;
        panelPeriodNs = measuredPanelPeriodNs;
    }

    private boolean targetMatches(int scans, long measuredPanelPeriodNs) {
        return scansPerOutput == scans && panelPeriodNs == measuredPanelPeriodNs;
    }

    private long oldestTimestamp() { return timestamps[head]; }

    private long newestTimestamp() {
        return timestamps[(head + count - 1) % CAPACITY];
    }

    private static long saturatingMultiply(long value, int multiplier) {
        if (value <= 0L || multiplier <= 0) return 0L;
        if (value > Long.MAX_VALUE / multiplier) return Long.MAX_VALUE;
        return value * multiplier;
    }

    private static long absoluteDifference(long left, long right) {
        return left >= right ? left - right : right - left;
    }
}
