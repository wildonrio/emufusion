package com.thorium.emufusion.video;

public final class SourcePhaseAdvisorTest {
    private static final long PERIOD = 8_333_333L;

    public static void main(String[] args) {
        aSteadyLateArrivalIsMovedOnce();
        aDriftingClockIsLeftAlone();
        aShortWaitNeedsNoShift();
        stallsRestartTheWindow();
        movesThatDoNotHoldEndTheAdvice();
        System.out.println("SourcePhaseAdvisorTest passed");
    }

    private static void window(SourcePhaseAdvisor a, long baseNs, long jitterNs) {
        for (int i = 0; i < SourcePhaseAdvisor.WINDOW; ++i)
            a.observe(baseNs + (i % 7) * jitterNs / 6, PERIOD);
    }

    /** Ocarina, Thor 3.2.103: every image waited 4.0-4.5 ms for its callback. */
    private static void aSteadyLateArrivalIsMovedOnce() {
        SourcePhaseAdvisor a = new SourcePhaseAdvisor();
        eq(0L, a.take(), "nothing before a window");
        window(a, 4_000_000L, 500_000L);
        eq(4_000_000L - SourcePhaseAdvisor.TARGET_WAIT_NS - 500_000L, a.take(),
                "the shortest wait less the margin and the jitter");
        eq(0L, a.take(), "offered once");
        eq(1L, a.shifts(), "one shift");
        // After the move the waits are short: no further shift.
        for (int w = 0; w <= SourcePhaseAdvisor.HOLDOFF_WINDOWS + 2; ++w) {
            window(a, 1_500_000L, 500_000L);
            eq(0L, a.take(), "settled");
        }
        // A move never exceeds half a scan.
        SourcePhaseAdvisor b = new SourcePhaseAdvisor();
        window(b, 8_000_000L, 0L);
        eq(PERIOD / 2L, b.take(), "capped");
    }

    /** Mega Drive before its clock lock: waits swept 1.5 -> 7.2 ms. */
    private static void aDriftingClockIsLeftAlone() {
        SourcePhaseAdvisor a = new SourcePhaseAdvisor();
        for (int w = 0; w < 4; ++w) {
            for (int i = 0; i < SourcePhaseAdvisor.WINDOW; ++i)
                a.observe(1_500_000L + i * 95_000L, PERIOD);
            eq(0L, a.take(), "a sweep is not a phase");
        }
    }

    private static void aShortWaitNeedsNoShift() {
        SourcePhaseAdvisor a = new SourcePhaseAdvisor();
        window(a, 1_500_000L, 300_000L);
        eq(0L, a.take(), "under the minimum gain");
    }

    private static void stallsRestartTheWindow() {
        SourcePhaseAdvisor a = new SourcePhaseAdvisor();
        for (int i = 0; i < SourcePhaseAdvisor.WINDOW - 1; ++i) a.observe(5_000_000L, PERIOD);
        a.observe(40_000_000L, PERIOD);  // an image held through a stall
        eq(0L, a.take(), "the stall restarted the window");
        a.observe(5_000_000L, 0L);
        window(a, 5_000_000L, 0L);
        eq(4_000_000L, a.take(), "a full window after the stall");
    }

    /** Ocarina on the hardware-core loop: each 3 ms move was back to 4.1 ms within seconds. */
    private static void movesThatDoNotHoldEndTheAdvice() {
        SourcePhaseAdvisor a = new SourcePhaseAdvisor();
        window(a, 4_100_000L, 300_000L);
        eq(2_800_000L, a.take(), "first move");
        // The source came back; nothing more during the hold-off.
        for (int w = 0; w < SourcePhaseAdvisor.HOLDOFF_WINDOWS; ++w) {
            window(a, 4_100_000L, 300_000L);
            eq(0L, a.take(), "held off");
        }
        window(a, 4_100_000L, 300_000L);
        eq(2_800_000L, a.take(), "one more try");
        window(a, 4_100_000L, 300_000L);   // and back again
        eq(0L, a.take(), "left alone");
        check(a.abandoned(), "abandoned");
        for (int w = 0; w < 20; ++w) window(a, 4_100_000L, 300_000L);
        eq(0L, a.take(), "for good");
        // A move that holds is not counted against the source.
        SourcePhaseAdvisor b = new SourcePhaseAdvisor();
        window(b, 4_000_000L, 300_000L);
        eq(2_700_000L, b.take(), "move");
        for (int w = 0; w < SourcePhaseAdvisor.HOLDOFF_WINDOWS; ++w) window(b, 1_300_000L, 300_000L);
        window(b, 2_300_000L, 300_000L);   // slow residual drift
        eq(1_000_000L, b.take(), "a later small correction");
        check(!b.abandoned(), "still advising");
    }

    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }

    private static void eq(long expected, long actual, String message) {
        if (expected != actual) throw new AssertionError(message + ": expected " + expected + " got " + actual);
    }
}
