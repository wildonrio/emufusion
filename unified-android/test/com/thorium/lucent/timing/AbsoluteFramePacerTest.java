package com.thorium.lucent.timing;

import com.thorium.lucent.TestSupport;

public final class AbsoluteFramePacerTest {
    public static void main(String[] ignored) {
        carriesSleepOvershootIntoTheNextDeadline();
        doesNotHideAFrameForSubPeriodLateness();
        marksOnlyWholePeriodCatchUpForVisualCoalescing();
        resetsAfterLargeExternalStalls();
        rejectsInvalidPeriods();
        exposesTheDueTimeOfTheFrameAboutToRun();
        fourCoalescedFramesExplainFivePeriodVideoGap();
        smallTrimPreservesScheduledTimestamp();
        System.out.println("AbsoluteFramePacerTest passed");
    }

    private static void smallTrimPreservesScheduledTimestamp() {
        AbsoluteFramePacer pacer = new AbsoluteFramePacer(16_678_000L);
        pacer.reset(1_000_000_000L);
        pacer.delayAfterFrame(1_001_000_000L);
        long scheduled = pacer.deadlineNanos();
        pacer = pacer.withPeriodPreservingDeadline(16_675_000L);
        TestSupport.equal(scheduled, pacer.deadlineNanos(),
                "trim cannot inject thread-wake jitter into the current PTS");
        pacer.delayAfterFrame(scheduled + 1_000_000L);
        TestSupport.equal(scheduled + 16_675_000L, pacer.deadlineNanos(),
                "new period applies to subsequent frame spacing");
        boolean rejected = false;
        try { pacer.withPeriodPreservingDeadline(0L); }
        catch (IllegalArgumentException expected) { rejected = true; }
        TestSupport.truth(rejected, "invalid trim rejected");
    }

    private static void fourCoalescedFramesExplainFivePeriodVideoGap() {
        // Device span 83,385,885 ns and telemetry sourceCoalesced=4.
        // This establishes a compatible mechanism, not the stall's cause.
        long period = 16_677_177L;
        AbsoluteFramePacer pacer = new AbsoluteFramePacer(period);
        pacer.reset(0L);
        pacer.delayAfterFrame(0L);
        long resumedTimestamp = 0L;
        int hidden = 0;
        for (int frame = 1; frame <= 5; ++frame) {
            long timestamp = pacer.deadlineNanos();
            pacer.delayAfterFrame(5L * period);
            if (pacer.coalescingCatchUpPresentation()) ++hidden;
            else resumedTimestamp = timestamp;
        }
        TestSupport.equal(4, hidden, "four catch-up visuals coalesced");
        TestSupport.equal(83_385_885L, resumedTimestamp,
                "retained endpoints span five source periods");
    }

    private static void exposesTheDueTimeOfTheFrameAboutToRun() {
        AbsoluteFramePacer pacer = new AbsoluteFramePacer(10L);
        pacer.reset(100L);
        TestSupport.equal(100L, pacer.deadlineNanos(),
                "the first frame after a reset is due at the reset instant");
        pacer.delayAfterFrame(103L);
        TestSupport.equal(110L, pacer.deadlineNanos(),
                "the next frame is due one period after the previous deadline");
        pacer.delayAfterFrame(112L);
        TestSupport.equal(120L, pacer.deadlineNanos(),
                "sub-period lateness does not move the lattice");
        pacer.delayAfterFrame(200L);
        TestSupport.equal(210L, pacer.deadlineNanos(),
                "a large stall re-bases the lattice on the stall instant");
    }

    private static void doesNotHideAFrameForSubPeriodLateness() {
        AbsoluteFramePacer pacer = new AbsoluteFramePacer(10L);
        pacer.reset(0L);
        TestSupport.equal(0L, pacer.delayAfterFrame(11L),
                "minor lateness can legitimately have no remaining sleep");
        TestSupport.truth(!pacer.coalescingCatchUpPresentation(),
                "zero delay alone must not suppress a visible frame");
    }

    private static void marksOnlyWholePeriodCatchUpForVisualCoalescing() {
        AbsoluteFramePacer pacer = new AbsoluteFramePacer(10L);
        pacer.reset(0L);
        TestSupport.equal(0L, pacer.delayAfterFrame(27L), "stalled step catches up");
        TestSupport.truth(pacer.coalescingCatchUpPresentation(),
                "a whole-period-late endpoint is coalesced");
        TestSupport.equal(0L, pacer.delayAfterFrame(27L), "second step is still catching up");
        TestSupport.truth(pacer.coalescingCatchUpPresentation(),
                "zero-delay tail stays coalesced after a whole-period stall");
        TestSupport.equal(3L, pacer.delayAfterFrame(27L), "next step rejoins timeline");
        TestSupport.truth(!pacer.coalescingCatchUpPresentation(),
                "the newest endpoint is published once caught up");
        TestSupport.equal(10L, pacer.delayAfterFrame(100L), "large stall resets");
        TestSupport.truth(!pacer.coalescingCatchUpPresentation(),
                "a reset publishes one newest endpoint rather than entering catch-up");
    }

    private static void carriesSleepOvershootIntoTheNextDeadline() {
        AbsoluteFramePacer pacer = new AbsoluteFramePacer(10L);
        pacer.reset(0L);
        TestSupport.equal(7L, pacer.delayAfterFrame(3L), "first absolute delay");
        // The scheduler woke two nanoseconds late and work took three. A
        // frame-relative sleep would incorrectly return 7 again; the absolute
        // deadline carries that overshoot and returns only 5.
        TestSupport.equal(5L, pacer.delayAfterFrame(15L),
                "sleep overshoot must not accumulate into a lower frame rate");
        TestSupport.equal(7L, pacer.delayAfterFrame(23L),
                "timeline remains anchored after the scheduler catches up");
        TestSupport.equal(9L, pacer.delayAfterFrame(31L),
                "minor lateness is carried into the next absolute deadline");
    }

    private static void resetsAfterLargeExternalStalls() {
        AbsoluteFramePacer pacer = new AbsoluteFramePacer(10L);
        pacer.reset(0L);
        TestSupport.equal(7L, pacer.delayAfterFrame(3L), "initial delay");
        TestSupport.equal(10L, pacer.delayAfterFrame(100L),
                "large screenshot/background stall starts a fresh deadline");
    }

    private static void rejectsInvalidPeriods() {
        boolean rejected = false;
        try { new AbsoluteFramePacer(0L); }
        catch (IllegalArgumentException expected) { rejected = true; }
        TestSupport.truth(rejected, "zero frame period rejected");
    }
}
