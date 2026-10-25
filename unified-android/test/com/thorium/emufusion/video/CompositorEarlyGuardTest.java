package com.thorium.emufusion.video;

public final class CompositorEarlyGuardTest {
    private static final long PERIOD = 8_333_333L;

    public static void main(String[] args) {
        offUntilFramesAreSeenEarly();
        framesShownEarlyTurnItOn();
        aRunOfEarlyFramesLeavesItOff();
        lateFramesTurnItOffForGood();
        unknownResultsAreIgnored();
        System.out.println("CompositorEarlyGuardTest passed");
    }

    /** Feeds one window; every {@code earlyEvery}-th frame early, every {@code lateEvery}-th late. */
    private static boolean window(CompositorEarlyGuard g, long[] clock, int earlyEvery, int lateEvery) {
        boolean changed = false;
        for (int i = 1; i <= CompositorEarlyGuard.WINDOW; ++i) {
            clock[0] += 2L * PERIOD;
            long desired = clock[0];
            long actual = earlyEvery > 0 && i % earlyEvery == 0 ? desired - PERIOD :
                    lateEvery > 0 && i % lateEvery == 0 ? desired + PERIOD : desired + 80_000L;
            changed |= g.observe(desired, actual, PERIOD);
        }
        return changed;
    }

    private static void offUntilFramesAreSeenEarly() {
        CompositorEarlyGuard g = new CompositorEarlyGuard();
        long[] clock = {1_000_000_000L};
        for (int w = 0; w < 10; ++w)
            check(!window(g, clock, 0, 4), "late frames alone never turn it on");
        check(!g.active(), "off");
        // Off, the plan's own lead-time request goes to the driver.
        eq(5_000L - 2_000L, g.driverDesiredNs(5_000L, 3_000L, PERIOD), "planned request");
        // A few early frames (under a tenth) are not enough.
        check(!window(g, clock, 15, 0), "one in fifteen early");
        check(!g.active(), "still off");
    }

    private static void framesShownEarlyTurnItOn() {
        // Wind Waker HD, 2026-10-25: 44.5% of frames shown a scan early.
        CompositorEarlyGuard g = new CompositorEarlyGuard();
        long[] clock = {2_000_000_000L};
        check(window(g, clock, 2, 0), "half early turns it on");
        check(g.active(), "on");
        eq(1L, g.activations(), "one activation");
        long target = 10_000_000_000L;
        eq(target + PERIOD / 2L, g.driverDesiredNs(target, target - 2_000_000L, PERIOD),
                "half a scan after the slot");
        // On time afterwards: it stays on.
        for (int w = 0; w < 10; ++w) check(!window(g, clock, 0, 0), "on time keeps it");
        check(g.active(), "still on");
        // Occasional late frames (rendering, not the request) keep it.
        check(!window(g, clock, 0, 5), "a fifth late keeps it");
        check(g.active(), "still on");
    }

    /** SNES on the Thor: 1-2 s of every frame a scan early, then every frame
     *  in its slot. Even, and sooner while early: not the guard's case. */
    private static void aRunOfEarlyFramesLeavesItOff() {
        CompositorEarlyGuard g = new CompositorEarlyGuard();
        long[] clock = {4_000_000_000L};
        for (int w = 0; w < 6; ++w) {
            for (int i = 0; i < CompositorEarlyGuard.WINDOW; ++i) {
                clock[0] += PERIOD;
                long desired = clock[0];
                // Half a window early, then half in their slot.
                boolean early = i < CompositorEarlyGuard.WINDOW / 2;
                check(!g.observe(desired, early ? desired - PERIOD : desired + 80_000L, PERIOD),
                        "runs of early frames");
            }
        }
        check(!g.active(), "off");
    }

    private static void lateFramesTurnItOffForGood() {
        // A compositor that holds frames to their desired time shows every
        // frame a scan late once the request moves after the slot.
        CompositorEarlyGuard g = new CompositorEarlyGuard();
        long[] clock = {3_000_000_000L};
        window(g, clock, 2, 0);
        check(g.active(), "on");
        check(window(g, clock, 0, 1), "every frame late turns it off");
        check(!g.active() && g.disabled(), "off for good");
        for (int w = 0; w < 5; ++w) check(!window(g, clock, 1, 0), "early frames no longer matter");
        check(!g.active(), "stays off");
        eq(1L, g.activations(), "no second activation");
    }

    private static void unknownResultsAreIgnored() {
        CompositorEarlyGuard g = new CompositorEarlyGuard();
        for (int i = 0; i < 10 * CompositorEarlyGuard.WINDOW; ++i) {
            check(!g.observe(1_000_000L * (i + 1), 0L, PERIOD), "no actual time");
            check(!g.observe(1_000_000L * (i + 1), 1L, 0L), "no period");
        }
        check(!g.active(), "off");
        eq(77L, g.driverDesiredNs(0L, 77L, PERIOD), "no target, planned request");
    }

    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }

    private static void eq(long expected, long actual, String message) {
        if (expected != actual) throw new AssertionError(message + ": expected " + expected + " got " + actual);
    }
}
