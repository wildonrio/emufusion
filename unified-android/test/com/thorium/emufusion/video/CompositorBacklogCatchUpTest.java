package com.thorium.emufusion.video;

public final class CompositorBacklogCatchUpTest {
    private static final long P = 8_333_333L;

    public static void main(String[] args) {
        aBacklogAsksForOneSkip();
        isolatedLateFramesAreNotABacklog();
        aSkipThatDoesNotClearBacksOff();
        backlogsThatKeepReturningBackOff();
        aQuietBacklogSkipsWithoutTheHoldoff();
        aDueSkipWaitsForAQuietMoment();
        busyPicturesNeverSkipEarly();
        quietSkipsKeepTheirOwnHoldoff();
        quietTimingCanBeTurnedOff();
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
        long calm = 5L * CompositorBacklogCatchUp.MAX_HOLDOFF_NS;
        for (long until = t + calm; t < until; t += P) c.observe(t, t, P, t);
        while (!c.observe(t, t + P, P, t)) t += P;
        check(c.takeSkip(t), "skip after the calm");
        eq(CompositorBacklogCatchUp.MIN_HOLDOFF_NS, c.holdoffNs(), "hold-off reset");
    }

    /** Two quiet pairs and a short backlog: skipped at once, the budget untouched. */
    private static void aQuietBacklogSkipsWithoutTheHoldoff() {
        CompositorBacklogCatchUp c = new CompositorBacklogCatchUp();
        long t = 1_000_000_000L;
        c.observeChange(0.001, t);
        c.observeChange(0.002, t);
        for (int i = 0; i < CompositorBacklogCatchUp.QUIET_BACKLOG_FRAMES - 1; ++i, t += P) {
            c.observe(t, t + P, P, t);
            check(!c.takeSkip(t), "not a backlog yet");
        }
        c.observe(t, t + P, P, t);
        c.observeChange(0.0, t);
        check(c.takeSkip(t), "quiet skip");
        eq(0L, c.skips(), "budgeted skips");
        eq(1L, c.quietSkips(), "quiet skips");
        check(!c.takeSkip(t), "only once");
    }

    /** A due skip waits while the picture moves, then takes the quiet moment. */
    private static void aDueSkipWaitsForAQuietMoment() {
        CompositorBacklogCatchUp c = new CompositorBacklogCatchUp();
        long t = 1_000_000_000L;
        while (!c.observe(t, t + P, P, t)) { c.observeChange(0.2, t); t += P; }
        c.observeChange(0.2, t);
        check(!c.takeSkip(t), "waits while busy");
        t += P;
        c.observe(t, t + P, P, t);
        c.observeChange(0.001, t);
        check(!c.takeSkip(t), "one quiet pair is not enough");
        c.observeChange(0.001, t);
        check(c.takeSkip(t), "quiet moment");
        eq(1L, c.skips(), "the budgeted skip");
    }

    /** Busy throughout: the due skip still comes, after the wait. */
    private static void busyPicturesNeverSkipEarly() {
        CompositorBacklogCatchUp c = new CompositorBacklogCatchUp();
        long t = 1_000_000_000L;
        int taken = 0;
        long dueAt = -1L;
        for (int i = 0; i < 2000; ++i, t += P) {
            boolean due = c.observe(t, t + P, P, t);
            if (due && dueAt < 0L) dueAt = t;
            c.observeChange(0.05, t);
            if (c.takeSkip(t)) {
                ++taken;
                check(t - dueAt >= CompositorBacklogCatchUp.QUIET_WAIT_NS, "waited for quiet");
                break;
            }
        }
        eq(1L, taken, "skipped after the wait");
        eq(0L, c.quietSkips(), "never quiet");
    }

    /** Quiet skips that do not clear the backlog back off on their own. */
    private static void quietSkipsKeepTheirOwnHoldoff() {
        CompositorBacklogCatchUp c = new CompositorBacklogCatchUp();
        long t = 1_000_000_000L;
        long last = -1L;
        for (int i = 0; i < 3000; ++i, t += P) {
            c.observe(t, t + P, P, t);          // the compositor keeps every frame late
            c.observeChange(0.0, t);
            long before = c.quietSkips();
            if (c.takeSkip(t) && c.quietSkips() > before) {
                if (last >= 0L) check(t - last >= CompositorBacklogCatchUp.QUIET_HOLDOFF_NS, "spaced");
                last = t;
            }
        }
        check(c.quietIneffective() >= 2L, "ineffective quiet skips counted");
        check(c.quietSkips() <= 6L, "backed off: " + c.quietSkips());
    }

    private static void quietTimingCanBeTurnedOff() {
        CompositorBacklogCatchUp c = new CompositorBacklogCatchUp();
        c.setQuietEnabled(false);
        long t = 1_000_000_000L;
        for (int i = 0; i < CompositorBacklogCatchUp.BACKLOG_FRAMES - 1; ++i, t += P) {
            c.observe(t, t + P, P, t);
            c.observeChange(0.0, t);
            check(!c.takeSkip(t), "no quiet skips");
        }
        c.observeChange(0.5, t);
        check(c.observe(t, t + P, P, t), "a backlog");
        check(c.takeSkip(t), "skips at once, as before");
    }

    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }

    private static void eq(long expected, long actual, String message) {
        if (expected != actual) throw new AssertionError(message + ": expected " + expected + " got " + actual);
    }
}
