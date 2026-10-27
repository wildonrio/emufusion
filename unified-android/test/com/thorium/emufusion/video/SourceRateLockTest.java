package com.thorium.emufusion.video;

public final class SourceRateLockTest {
    private static final long P = 8_341_083L;        // Thor 119.89 Hz

    public static void main(String[] args) {
        holdsFromAnyStartPhaseDriftAndJitter();
        anEngineThatDoesNotFollowIsLeftAlone();
        System.out.println("SourceRateLockTest passed");
    }

    /**
     * An engine whose emulated vsync runs at two scans scaled by the trim
     * (and off by {@code ppm}), its images {@code renderNs} after each vsync
     * plus jitter; the rate lock updated once a second. Returns the mean wait
     * over the last {@code tail} frames in ms.
     */
    private static double run(SourceRateLock rate, double ppm, long startNs, long renderNs, long jitterNs,
                              int frames, int tail, boolean follows) {
        SourcePhaseLock phase = new SourcePhaseLock();
        double scale = 1.0;
        double vsync = startNs;
        double sum = 0;
        int n = 0;
        for (int f = 0; f < frames; ++f) {
            double period = 2.0 * P * (1.0 + ppm * 1e-6) / (follows ? scale : 1.0);
            vsync += period;
            double arrival = vsync + renderNs + ((f * 7919) % 13 - 6) * jitterNs / 6.0;
            long callback = (long) Math.ceil(arrival / P) * P;
            long wait = callback - (long) arrival;
            phase.observe(wait, P);
            if (f % 60 == 59) scale = rate.update(phase.smoothedErrorNs());
            if (f >= frames - tail) { sum += wait; ++n; }
        }
        return sum / n / 1e6;
    }

    private static void holdsFromAnyStartPhaseDriftAndJitter() {
        for (double ppm : new double[] {-600, -250, 0, 250, 600})
            for (long start = 0; start < 2 * P; start += 800_000L)
                for (long jitter : new long[] {0L, 300_000L, 1_500_000L}) {
                    SourceRateLock rate = new SourceRateLock();
                    // Three minutes: a rate trim moves the phase slowly.
                    double mean = run(rate, ppm, 1_000_000_000L + start, 4_000_000L, jitter, 10800, 1800, true);
                    double limit = SourcePhaseLock.TARGET_WAIT_NS / 1e6 + 2.5 * jitter / 1e6 + 1.2;
                    check(!rate.abandoned() && mean < limit, "ppm " + ppm + " start " + start / 1000 +
                            " us jitter " + jitter / 1000 + " us: mean wait " + mean + " ms trim " +
                            rate.trim() + (rate.abandoned() ? " (abandoned)" : ""));
                }
    }

    private static void anEngineThatDoesNotFollowIsLeftAlone() {
        SourceRateLock rate = new SourceRateLock();
        run(rate, 0, 1_000_000_000L + 5_000_000L, 4_000_000L, 0L, 10800, 60, false);
        check(rate.abandoned() && rate.trim() == 0.0, "left alone, untrimmed");
    }

    private static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }
}
