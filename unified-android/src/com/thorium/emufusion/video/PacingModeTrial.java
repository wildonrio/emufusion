package com.thorium.emufusion.video;

/**
 * Chooses, per session, between arrival pacing and the content-time
 * timeline from what reached the screen.
 *
 * <p>Arrival pacing (3.2.88) shows each new image as soon as it is taken up,
 * which is the lowest latency, but a source whose images arrive unevenly
 * holds a real image an extra scan each time its successor is late. The
 * content-time timeline waits for the successor and spaces the outputs on
 * the images' own timestamps instead. Thor, 2026-10-27: Super Mario 3D World
 * (Cemu, GPU-bound) had 122-128 frames per 1000 held longer than usual with
 * arrival pacing and 21 with the content-time timeline at the same latency;
 * Metroid Dread (Eden, 30 fps) got worse with it (61 -> 138). So neither is
 * right for every source, and the engine alone does not say which.</p>
 *
 * <p>Each window of {@link #WINDOW_INTERVALS} shown intervals counts the
 * frames shown longer than the window's usual interval (stalls excluded):</p>
 * <ul>
 * <li>Arrival pacing above {@link #TRIGGER_PER_1000} in
 * {@link #TRIGGER_WINDOWS} windows in a row (a game's start alone does not
 * count), with every output a single scan, makes the next window a trial of
 * the content-time timeline. Outputs that span several scans (a 20 or 30 fps
 * source) are left alone: there the timeline waits a whole source frame
 * for the successor (Thor, 2026-10-27: Ocarina's real images 37 -> 75 ms,
 * Wind Waker HD 50 -> 79 ms, no smoother). A trial is kept only if it holds
 * at most {@link #KEEP_RATIO} of arrival pacing's rate. A failed trial returns to arrival pacing and the
 * next waits {@link #FAIL_HOLDOFF_WINDOWS} windows, doubling.</li>
 * <li>A kept content-time timeline is re-checked with one window of arrival
 * pacing after {@link #KEEP_WINDOWS} windows: if arrival pacing is now under
 * the trigger it stays, otherwise the content-time timeline returns at once
 * and the next re-check waits twice as long (at most
 * {@link #MAX_KEEP_WINDOWS}).</li>
 * </ul>
 * <p>The first {@link #SETTLE_INTERVALS} intervals after a switch are not
 * counted: the timeline re-primes there.</p>
 */
public final class PacingModeTrial {
    public static final int WINDOW_INTERVALS = 720;      // ~6 s at 120 Hz
    public static final int SETTLE_INTERVALS = 60;
    public static final double TRIGGER_PER_1000 = 20.0;
    public static final int TRIGGER_WINDOWS = 2;
    /**
     * Thor, 2026-10-27, SM3DW alternated: the content-time timeline held
     * 0.50-0.57 of arrival pacing's frames at equal or lower latency, so a
     * quarter fewer is enough to keep it on single-scan outputs.
     */
    public static final double KEEP_RATIO = 0.75;
    public static final int FAIL_HOLDOFF_WINDOWS = 4;
    public static final int MAX_FAIL_HOLDOFF_WINDOWS = 32;
    public static final int KEEP_WINDOWS = 8;
    public static final int MAX_KEEP_WINDOWS = 64;
    public static final int MAX_SCANS = 12;
    private static final int BUCKETS = 6;

    private enum State { ARRIVAL, TRIAL, CONTENT, RECHECK }

    private State state = State.ARRIVAL;
    private double arrivalRate = -1.0, contentRate = -1.0;
    private int holdoff, failHoldoff = FAIL_HOLDOFF_WINDOWS;
    private int keepLeft, keepWindows = KEEP_WINDOWS;
    private int settle;
    private int aboveWindows;
    private final int[] shown = new int[BUCKETS];
    private int intervals;
    private long lastActualNs;
    private boolean lastKeepAlive;
    private int trials, kept, rechecks;

    /** Whether the session should use the content-time timeline now. */
    public synchronized boolean contentTime() {
        return state == State.TRIAL || state == State.CONTENT;
    }

    /** One presented frame: its actual display time, the scan length, and whether it was a keep-alive. */
    public synchronized void record(long actualNs, long periodNs, boolean keepAlive) {
        if (actualNs <= 0L || periodNs <= 0L) return;
        long previous = lastActualNs;
        boolean stall = keepAlive || lastKeepAlive;
        lastActualNs = actualNs;
        lastKeepAlive = keepAlive;
        if (previous <= 0L || actualNs <= previous || stall) return;
        long scans = (actualNs - previous + periodNs / 2L) / periodNs;
        if (scans < 1L || scans > MAX_SCANS) return;
        if (settle > 0) {
            --settle;
            return;
        }
        ++shown[(int) Math.min(BUCKETS - 1, scans - 1)];
        if (++intervals < WINDOW_INTERVALS) return;
        decide(holdsPer1000(), usualScans() == 1);
        java.util.Arrays.fill(shown, 0);
        intervals = 0;
    }

    private int usualScans() {
        int usual = 0;
        for (int i = 1; i < BUCKETS - 1; ++i) if (shown[i] > shown[usual]) usual = i;
        return usual + 1;
    }

    /** A new stream: its first frame has no interval. */
    public synchronized void restart() {
        lastActualNs = 0L;
        lastKeepAlive = false;
    }

    private double holdsPer1000() {
        int holds = 0;
        for (int i = usualScans(); i < BUCKETS; ++i) holds += shown[i];
        return 1000.0 * holds / Math.max(1, intervals);
    }

    private void decide(double rate, boolean singleScan) {
        switch (state) {
            case ARRIVAL:
                arrivalRate = rate;
                aboveWindows = singleScan && rate > TRIGGER_PER_1000 ? aboveWindows + 1 : 0;
                if (holdoff > 0) {
                    --holdoff;
                } else if (aboveWindows >= TRIGGER_WINDOWS) {
                    aboveWindows = 0;
                    ++trials;
                    enter(State.TRIAL);
                }
                break;
            case TRIAL:
                contentRate = rate;
                if (rate <= arrivalRate * KEEP_RATIO) {
                    ++kept;
                    failHoldoff = FAIL_HOLDOFF_WINDOWS;
                    keepLeft = keepWindows;
                    enter(State.CONTENT);
                } else {
                    holdoff = failHoldoff;
                    failHoldoff = Math.min(MAX_FAIL_HOLDOFF_WINDOWS, failHoldoff * 2);
                    enter(State.ARRIVAL);
                }
                break;
            case CONTENT:
                contentRate = rate;
                if (--keepLeft <= 0) {
                    ++rechecks;
                    enter(State.RECHECK);
                }
                break;
            case RECHECK:
                arrivalRate = rate;
                if (rate <= TRIGGER_PER_1000) {
                    keepWindows = KEEP_WINDOWS;
                    enter(State.ARRIVAL);
                } else {
                    keepWindows = Math.min(MAX_KEEP_WINDOWS, keepWindows * 2);
                    keepLeft = keepWindows;
                    enter(State.CONTENT);
                }
                break;
        }
    }

    private void enter(State next) {
        boolean wasContent = contentTime();
        state = next;
        if (contentTime() != wasContent) settle = SETTLE_INTERVALS;
    }

    public synchronized int trials() { return trials; }
    public synchronized int kept() { return kept; }
    public synchronized int rechecks() { return rechecks; }
    public synchronized double arrivalRate() { return arrivalRate; }
    public synchronized double contentRate() { return contentRate; }
}
