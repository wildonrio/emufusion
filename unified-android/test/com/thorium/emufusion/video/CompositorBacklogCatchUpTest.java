package com.thorium.emufusion.video;

public final class CompositorBacklogCatchUpTest {
    private static final long P = 8_333_333L;

    public static void main(String[] args) {
        aBacklogAsksForOneSkip();
        isolatedLateFramesAreNotABacklog();
        aSkipThatDoesNotClearBacksOff();
        backlogsThatKeepReturningBackOff();
        System.out.println("CompositorBacklogCatchUpTest passed");
    }

    /** Double Dash, 3.2.108 trial: one late render, then every frame a scan behind. */
    private static void aBacklogAsksForOneSkip() {
        CompositorBacklogCatchUp c = new CompositorBacklogCatchUp();
        long t = 1_000_000_000L;
        for (int i = 0; i < CompositorBacklogCatchUp.BACKLOG_FRAMES - 1; ++i, t += P)
            check(!c.observe(t, t + P, P, t), "not yet");
        check(c.observe(t, t + P, P, t), "a backlog");
        check(c.takeSkip(t), "skip once");
        check(!c.takeSkip(t), "only once");
        t += P;
        // Frames queued before the skip are still late; then on time.
        for (int i = 0; i < 3; ++i, t += P) c.observe(t, t + P, P, t);
        for (int i = 0; i < 60; ++i, t += P) check(!c.observe(t, t, P, t), "caught up");
        check(c.ineffective() == 0L && c.holdoffNs() == CompositorBacklogCatchUp.MIN_HOLDOFF_NS, "it held");
        eq(1L, c.skips(), "one skip");
    }

    private static void isolatedLateFramesAreNotABacklog() {
        CompositorBacklogCatchUp c = new CompositorBacklogCatchUp();
        long t = 1_000_000_000L;
        for (int i = 0; i < 600; ++i, t += P)
            check(!c.observe(t, i % 10 == 0 ? t + P : t, P, t), "isolated misses");
        // Frames shown early, or two scans late, are not this backlog.
        for (int i = 0; i < 100; ++i, t += P) check(!c.observe(t, t - P, P, t), "early");
        for (int i = 0; i < 100; ++i, t += P) check(!c.observe(t, t + 2 * P, P, t), "two scans");
    }

    /** The compositor holding frames to the later scan itself: back off, doubling. */
    private static void aSkipThatDoesNotClearBacksOff() {
        CompositorBacklogCatchUp c = new CompositorBacklogCatchUp();
        long t = 1_000_000_000L;
        while (!c.observe(t, t + P, P, t)) t += P;
        check(c.takeSkip(t), "first skip");
        t += P;
        long skippedAt = t;
        for (int i = 0; i < 200; ++i, t += P) c.observe(t, t + P, P, t);
        eq(1L, c.ineffective(), "did not clear");
        eq(2L * CompositorBacklogCatchUp.MIN_HOLDOFF_NS, c.holdoffNs(), "hold-off doubled");
        check(!c.takeSkip(t), "nothing during the hold-off");
        while (!c.observe(t, t + P, P, t)) t += P;
        check(t - skippedAt + P >= 2L * CompositorBacklogCatchUp.MIN_HOLDOFF_NS, "after the hold-off");
        check(c.takeSkip(t), "one more try");
    }

    /** Double Dash on the final 3.2.108 candidate: each skip cleared it, but it returned within 2 s. */
    private static void backlogsThatKeepReturningBackOff() {
        CompositorBacklogCatchUp c = new CompositorBacklogCatchUp();
        long t = 1_000_000_000L;
        long last = -1L;
        int skips = 0;
        for (int round = 0; round < 6; ++round) {
            // A late render, then a backlog until the skip; the skip clears it.
            while (!c.observe(t, t + P, P, t)) t += P;
            check(c.takeSkip(t), "skip");
            if (last >= 0L) check(t - last >= c.holdoffNs() / 2L, "spaced by the hold-off");
            last = t;
            ++skips;
            t += P;
            for (int i = 0; i < 200; ++i, t += P) c.observe(t, t, P, t);   // 1.7 s on time
        }
        check(c.reformed() >= 4L, "returning backlogs counted: " + c.reformed());
        check(c.holdoffNs() >= 16L * CompositorBacklogCatchUp.MIN_HOLDOFF_NS, "hold-off grew: " + c.holdoffNs());
        // A long calm starts again from the minimum.
        for (int i = 0; i < 120 * 300; ++i, t += P) c.observe(t, t, P, t);   // 5 min on time
        while (!c.observe(t, t + P, P, t)) t += P;
        check(c.takeSkip(t), "skip after the calm");
        eq(CompositorBacklogCatchUp.MIN_HOLDOFF_NS, c.holdoffNs(), "hold-off reset");
    }

    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }

    private static void eq(long expected, long actual, String message) {
        if (expected != actual) throw new AssertionError(message + ": expected " + expected + " got " + actual);
    }
}
