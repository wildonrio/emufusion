package com.thorium.emufusion.video;

public final class SourcePhaseLockTest {
    private static final long P = 8_341_083L;        // Thor 119.89 Hz

    public static void main(String[] args) {
        aDriftingCoreIsHeldAtTheTarget();
        anImageJustAfterACallbackMovesEarlier();
        aSourceThatDoesNotFollowIsLeftAlone();
        holdsFromAnyStartPhaseDriftAndJitter();
        System.out.println("SourcePhaseLockTest passed");
    }

    /**
     * Every start phase over two scans, clock errors of -600 to +600 ppm and
     * no, light or heavy jitter: never abandoned, the wait ends near its
     * target. The first device build failed a third of these: the error was
     * smoothed across the wrap, and the lock's own steps counted as jitter.
     */
    private static void holdsFromAnyStartPhaseDriftAndJitter() {
        for (double ppm : new double[] {-600, -250, 0, 250, 600})
            for (long start = 0; start < 2 * P; start += 400_000L)
                for (long jitter : new long[] {0L, 300_000L, 1_500_000L}) {
                    SourcePhaseLock lock = new SourcePhaseLock();
                    double mean = run(lock, ppm, 1_000_000_000L + start, 1_000_000L, jitter, 3600, 1200, true);
                    double limit = SourcePhaseLock.TARGET_WAIT_NS / 1e6 + 2.0 * jitter / 1e6 + 1.0;
                    check(!lock.abandoned() && mean < limit, "ppm " + ppm + " start " + start / 1000 +
                            " us jitter " + jitter / 1000 + " us: mean wait " + mean + " ms" +
                            (lock.abandoned() ? " (abandoned)" : ""));
                }
    }

    /**
     * A core paced at two scans with a clock error of {@code ppm}, its images
     * {@code workNs} after each deadline plus deterministic jitter; returns
     * the mean wait over the last {@code tail} frames.
     */
    private static double run(SourcePhaseLock lock, double ppm, long startNs, long workNs, long jitterNs,
                              int frames, int tail, boolean follows) {
        double period = 2.0 * P * (1.0 + ppm * 1e-6);
        double deadline = startNs;
        double sum = 0;
        int n = 0;
        for (int f = 0; f < frames; ++f) {
            double arrival = deadline + workNs + ((f * 7919) % 13 - 6) * jitterNs / 6.0;
            long callback = (long) Math.ceil(arrival / P) * P;
            long wait = callback - (long) arrival;
            lock.observe(wait, P);
            long nudge = lock.take();
            deadline += period + (follows ? nudge : 0);
            if (f >= frames - tail) { sum += wait; ++n; }
        }
        return sum / n / 1e6;
    }

    /** NES, 2026-10-27: ~250 ppm off, waits drifting 0.25 ms a second. */
    private static void aDriftingCoreIsHeldAtTheTarget() {
        SourcePhaseLock lock = new SourcePhaseLock();
        double mean = run(lock, 250, 1_000_000_000L + 5_000_000L, 1_000_000L, 300_000L, 3600, 1200, true);
        check(!lock.abandoned(), "keeps locking");
        check(mean > 0.8 && mean < 2.4, "mean wait near the target: " + mean + " ms");
        check(lock.nudges() > 100, "nudges every so often: " + lock.nudges());
        SourcePhaseLock other = new SourcePhaseLock();
        double negative = run(other, -250, 1_000_000_000L + 2_000_000L, 1_000_000L, 300_000L, 3600, 1200, true);
        check(!other.abandoned() && negative > 0.8 && negative < 2.4,
                "held against the other drift: " + negative + " ms");
    }

    /** Arriving 0.3 ms after a callback: moved earlier by ~1.5 ms, not a scan later. */
    private static void anImageJustAfterACallbackMovesEarlier() {
        SourcePhaseLock lock = new SourcePhaseLock();
        // Deadline so that images land 0.3 ms after a callback.
        long start = 100L * P + 300_000L - 1_000_000L;
        double mean = run(lock, 0, start, 1_000_000L, 0L, 600, 200, true);
        check(mean > 1.2 && mean < 2.2, "ends just before the callback: " + mean + " ms");
        check(lock.nudgedTotalNs() < 0L, "moved earlier: " + lock.nudgedTotalNs() / 1000 + " us");
        check(lock.nudgedTotalNs() > -3_000_000L, "by about the lateness, not a scan");
    }

    /** Ocarina on the hardware-core loop: its arrivals keep their own phase. */
    private static void aSourceThatDoesNotFollowIsLeftAlone() {
        SourcePhaseLock lock = new SourcePhaseLock();
        run(lock, 0, 1_000_000_000L + 5_000_000L, 1_000_000L, 0L, 3600, 100, false);
        check(lock.abandoned(), "left alone after nudges that never hold");
    }

    private static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }
}
