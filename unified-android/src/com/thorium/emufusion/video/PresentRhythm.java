package com.thorium.emufusion.video;

/**
 * The rhythm the viewer saw: how many refreshes each presented frame stayed
 * on screen, from the display's own present times, over a fixed window.
 *
 * <p>The QA physical trace measures this on the Thor only with a marker file
 * and a host-side parser. This keeps the same two numbers in normal play on
 * any phone that reports present times, for one log line per window:
 * <ul>
 * <li>a <em>hitch</em> is a frame shown longer than the window's usual
 * interval (doubling a 60 fps game on 120 Hz: a frame shown two refreshes
 * instead of one), whatever its cause -- the judder the owner sees;</li>
 * <li>on intended: the shown interval equals the interval the scheduler asked
 * for, so a hitch it did not ask for is the compositor's, not ours.</li>
 * </ul>
 * Gaps longer than {@link #MAX_INTERVAL_SCANS} refreshes are pauses, loads or
 * source stalls and are counted apart.</p>
 */
public final class PresentRhythm {
    public static final long WINDOW_NS = 30_000_000_000L;
    public static final int MIN_INTERVALS = 100;
    public static final int MAX_INTERVAL_SCANS = 12;
    private static final int BUCKETS = 5;

    private long lastDesiredNs, lastActualNs;
    private long windowStartNs;
    private final int[] shown = new int[BUCKETS];
    private int intervals, onIntended, gaps;
    private int summaryIntervals, summaryOnIntended, summaryGaps, summaryHitches;
    private int summaryUsualScans;
    private final int[] summaryShown = new int[BUCKETS];
    private long windows;

    /**
     * One presented frame. Returns true when it completed a window; the
     * window's numbers are then readable until the next completed window.
     */
    public boolean record(long desiredNs, long actualNs, long periodNs) {
        if (desiredNs <= 0L || actualNs <= 0L || periodNs <= 0L) return false;
        long previousDesired = lastDesiredNs, previousActual = lastActualNs;
        lastDesiredNs = desiredNs;
        lastActualNs = actualNs;
        if (windowStartNs == 0L) windowStartNs = actualNs;
        if (previousActual <= 0L || actualNs <= previousActual) return false;
        long shownNs = actualNs - previousActual;
        long requestedNs = desiredNs - previousDesired;
        long scans = (shownNs + periodNs / 2) / periodNs;
        if (scans < 1L || scans > MAX_INTERVAL_SCANS) {
            ++gaps;
        } else {
            ++intervals;
            ++shown[(int) Math.min(BUCKETS - 1, scans - 1)];
            if (Math.abs(shownNs - requestedNs) < periodNs / 2) ++onIntended;
        }
        if (actualNs - windowStartNs < WINDOW_NS) return false;
        boolean complete = intervals >= MIN_INTERVALS;
        if (complete) publish();
        clearWindow(actualNs);
        return complete;
    }

    /** A new stream (resize, ownership change): its first frame has no interval. */
    public void restart() {
        lastDesiredNs = 0L;
        lastActualNs = 0L;
    }

    private void publish() {
        int usual = 0;
        for (int i = 1; i < BUCKETS - 1; ++i) if (shown[i] > shown[usual]) usual = i;
        int hitches = 0;
        for (int i = usual + 1; i < BUCKETS; ++i) hitches += shown[i];
        System.arraycopy(shown, 0, summaryShown, 0, BUCKETS);
        summaryIntervals = intervals;
        summaryOnIntended = onIntended;
        summaryGaps = gaps;
        summaryHitches = hitches;
        summaryUsualScans = usual + 1;
        ++windows;
    }

    private void clearWindow(long nowNs) {
        java.util.Arrays.fill(shown, 0);
        intervals = 0;
        onIntended = 0;
        gaps = 0;
        windowStartNs = nowNs;
    }

    public long windows() { return windows; }
    public int intervals() { return summaryIntervals; }
    public int usualScans() { return summaryUsualScans; }
    /** Frames shown longer than the usual interval in the last window. */
    public int hitches() { return summaryHitches; }
    public int gaps() { return summaryGaps; }
    /** Frames shown for 1, 2, 3, 4 and 5 or more refreshes. */
    public int shownForScans(int scans) {
        return scans < 1 ? 0 : summaryShown[Math.min(BUCKETS, scans) - 1];
    }
    public double onIntendedPercent() {
        return summaryIntervals == 0 ? 0.0 : 100.0 * summaryOnIntended / summaryIntervals;
    }
}
