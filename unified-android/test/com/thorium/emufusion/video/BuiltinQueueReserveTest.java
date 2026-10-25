package com.thorium.emufusion.video;

public final class BuiltinQueueReserveTest {
    private static final long PERIOD = 8_333_333L;
    private static final long LATENCY = 10_333_333L;

    public static void main(String[] args) {
        depthIsCountedFromTheCallback();
        isolatedMissesStayAtTheEarliestScan();
        aBurstDeepensOnce();
        compositorMissesDoNotCount();
        recorderBurstGivesTheScanBackOnceFramesFitEarlier();
        recoveryNeedsUnbrokenEvidence();
        failedRecoveryRestoresAtOnceAndBacksOff();
        recoveryThatHoldsResetsTheBackoff();
        sustainedLoadReachesTwoScansAndStepsBackOneAtATime();
        withoutTimestampsRecoveryIsSlow();
        framesShownEarlyGiveTheScanBack();
        occasionalEarlyFramesKeepTheDepth();
        earlyRecoveriesHoldOffDeepening();
        aDeepeningThatAddsNothingIsGivenBack();
        aDeepeningThatHelpsIsKept();
        aCappedQueueNeverDeepens();
        System.out.println("BuiltinQueueReserveTest passed");
    }

    /** A frame shown in its slot; GPU finished {@code renderBeforeLatch} ahead of its own latch. */
    private static BuiltinQueueReserve.Change onTime(BuiltinQueueReserve r, long[] clock,
                                                      long renderBeforeLatchNs) {
        clock[0] += PERIOD;
        long desired = clock[0], latch = desired - LATENCY;
        return r.observe(false, desired, desired, latch - renderBeforeLatchNs, latch, PERIOD);
    }

    /** A frame shown a scan late whose rendering ended after its latch. */
    private static BuiltinQueueReserve.Change late(BuiltinQueueReserve r, long[] clock) {
        clock[0] += PERIOD;
        long desired = clock[0];
        return r.observe(true, desired, desired + PERIOD, desired - 4_000_000L,
                desired + PERIOD - LATENCY, PERIOD);
    }

    private static void advance(long[] clock, long ns) { clock[0] += ns; }

    /** Deepen with a burst of three late frames. */
    private static void burst(BuiltinQueueReserve r, long[] clock) {
        late(r, clock);
        late(r, clock);
        check(late(r, clock) == BuiltinQueueReserve.Change.DEEPENED, "three late frames deepen");
    }

    /** QA queue_deepen=0: late frames stay late rather than buy a scan of latency. */
    private static void aCappedQueueNeverDeepens() {
        BuiltinQueueReserve r = new BuiltinQueueReserve();
        long[] clock = {1_000_000_000L};
        burst(r, clock);
        eq(1L, r.extraScans(), "deepened");
        r.setMaxExtraScans(0);
        eq(0L, r.extraScans(), "given back at once");
        advance(clock, 3_000_000_000L);
        for (int i = 0; i < 30; ++i)
            check(late(r, clock) == BuiltinQueueReserve.Change.NONE, "never deepens");
        eq(BuiltinQueueReserve.MIN_NS, r.reserveNs(clock[0], clock[0] + 500_000L, PERIOD), "earliest scan");
        r.setMaxExtraScans(BuiltinQueueReserve.MAX_EXTRA_SCANS);
        advance(clock, 3_000_000_000L);
        burst(r, clock);
    }

    private static void depthIsCountedFromTheCallback() {
        BuiltinQueueReserve r = new BuiltinQueueReserve();
        long callback = 1_000_000_000L;
        eq(BuiltinQueueReserve.MIN_NS, r.reserveNs(callback, callback + 500_000L, PERIOD), "earliest scan");
        eq(BuiltinQueueReserve.MIN_NS, r.reserveNs(callback, callback + 3_000_000L, PERIOD), "same, planned late");
        long[] clock = {callback};
        burst(r, clock);
        // One extra scan: the first deadline at least MIN + one interval after
        // the callback, wherever planning ran within the callback.
        eq(BuiltinQueueReserve.MIN_NS + PERIOD - 500_000L, r.reserveNs(callback, callback + 500_000L, PERIOD),
                "one scan from the callback");
        eq(BuiltinQueueReserve.MIN_NS + PERIOD - 3_000_000L, r.reserveNs(callback, callback + 3_000_000L, PERIOD),
                "the same deadline when planned later");
        eq(BuiltinQueueReserve.MIN_NS, r.reserveNs(callback, callback + 2L * PERIOD, PERIOD),
                "a callback processed a whole scan late takes the first deadline it can make");
        eq(BuiltinQueueReserve.MIN_NS + PERIOD, r.reserveNs(0L, callback, PERIOD), "no callback time");
        PhysicalPresentationDeadline earliest = PhysicalPresentationDeadline.nextEgl(
                callback + 4_270_000L, PERIOD, LATENCY, callback + 500_000L, 0L,
                new BuiltinQueueReserve().reserveNs(callback, callback + 500_000L, PERIOD));
        PhysicalPresentationDeadline deeper = PhysicalPresentationDeadline.nextEgl(
                callback + 4_270_000L, PERIOD, LATENCY, callback + 3_000_000L, 0L,
                r.reserveNs(callback, callback + 3_000_000L, PERIOD));
        PhysicalPresentationDeadline deeperEarly = PhysicalPresentationDeadline.nextEgl(
                callback + 4_270_000L, PERIOD, LATENCY, callback + 200_000L, 0L,
                r.reserveNs(callback, callback + 200_000L, PERIOD));
        eq(0L, earliest.skippedPanelScans(), "depth 0 takes the first deadline");
        eq(1L, deeper.skippedPanelScans(), "depth 1 takes the next one");
        eq(1L, deeperEarly.skippedPanelScans(), "whenever planning ran");
    }

    private static void isolatedMissesStayAtTheEarliestScan() {
        // Thor 2026-10-23, NSMBU Deluxe: misses six seconds apart.
        BuiltinQueueReserve r = new BuiltinQueueReserve();
        long[] clock = {2_000_000_000L};
        for (int i = 0; i < 20; ++i) {
            check(late(r, clock) == BuiltinQueueReserve.Change.NONE, "an isolated miss");
            advance(clock, 1_000_000_000L);
        }
        eq(0L, r.extraScans(), "still the earliest scan");
        advance(clock, 3_000_000_000L);
        late(r, clock);
        advance(clock, 900_000_000L);
        late(r, clock);
        advance(clock, 1_200_000_000L);
        check(late(r, clock) == BuiltinQueueReserve.Change.NONE, "three misses over 2.1 s are not a burst");
        eq(0L, r.extraScans(), "still the earliest scan");
    }

    private static void aBurstDeepensOnce() {
        // Thor 2026-10-23, Ocarina of Time: the recorder's start, four late
        // frames within half a second, with frames already queued behind them.
        BuiltinQueueReserve r = new BuiltinQueueReserve();
        long[] clock = {3_000_000_000L};
        burst(r, clock);
        eq(1L, r.extraScans(), "one scan deeper");
        for (int i = 0; i < 6; ++i)
            check(late(r, clock) == BuiltinQueueReserve.Change.NONE, "frames queued before the change");
        eq(1L, r.extraScans(), "not two");
        eq(1L, r.deepenings(), "one deepening");
    }

    private static void compositorMissesDoNotCount() {
        BuiltinQueueReserve r = new BuiltinQueueReserve();
        long desired = 4_000_000_000L;
        for (int i = 0; i < 10; ++i) {
            desired += PERIOD;
            // Rendered three scans before its slot and still late: not ours.
            check(r.observe(true, desired, desired + PERIOD, desired - 3L * PERIOD,
                    desired + PERIOD - LATENCY, PERIOD) == BuiltinQueueReserve.Change.NONE, "compositor miss");
            // No render time at all: unknown, not ours.
            check(r.observe(true, desired, desired + PERIOD, 0L, 0L, PERIOD) ==
                    BuiltinQueueReserve.Change.NONE, "unknown render time");
        }
        eq(0L, r.extraScans(), "no deepening");
        check(new BuiltinQueueReserve().observe(true, 1L, 1L, 1L, 1L, 0L) == BuiltinQueueReserve.Change.NONE,
                "no panel period, no change");
    }

    private static void recorderBurstGivesTheScanBackOnceFramesFitEarlier() {
        BuiltinQueueReserve r = new BuiltinQueueReserve();
        long[] clock = {5_000_000_000L};
        burst(r, clock);
        // Frames rendered ~2 ms ahead of the latch one scan earlier.
        BuiltinQueueReserve.Change last = BuiltinQueueReserve.Change.NONE;
        int frames = 0;
        while (last != BuiltinQueueReserve.Change.RECOVERED && frames < 1000) {
            last = onTime(r, clock, PERIOD + 2_000_000L);
            ++frames;
        }
        int settle = (int) (BuiltinQueueReserve.SETTLE_NS / PERIOD);
        check(frames >= BuiltinQueueReserve.RECOVERY_FRAMES + settle - 1 &&
                frames <= BuiltinQueueReserve.RECOVERY_FRAMES + settle + 1, "about two seconds of evidence: " + frames);
        eq(0L, r.extraScans(), "the scan is given back");
        eq(1L, r.recoveries(), "one recovery");
        for (int i = 0; i < 2000; ++i)
            check(onTime(r, clock, 3_000_000L) == BuiltinQueueReserve.Change.NONE, "nothing below the earliest scan");
    }

    private static void recoveryNeedsUnbrokenEvidence() {
        BuiltinQueueReserve r = new BuiltinQueueReserve();
        long[] clock = {6_000_000_000L};
        burst(r, clock);
        for (int round = 0; round < 20; ++round) {
            for (int i = 0; i < BuiltinQueueReserve.RECOVERY_FRAMES - 1; ++i)
                check(onTime(r, clock, PERIOD + 2_000_000L) != BuiltinQueueReserve.Change.RECOVERED,
                        "not before the full streak");
            // One frame that would have missed the earlier latch breaks the streak.
            onTime(r, clock, PERIOD - 500_000L);
        }
        eq(0L, r.recoveries(), "no recovery without an unbroken streak");
        eq(1L, r.extraScans(), "depth kept");
    }

    private static void failedRecoveryRestoresAtOnceAndBacksOff() {
        BuiltinQueueReserve r = new BuiltinQueueReserve();
        long[] clock = {7_000_000_000L};
        burst(r, clock);
        int window = BuiltinQueueReserve.RECOVERY_FRAMES;
        for (int round = 0; round < 6; ++round) {
            BuiltinQueueReserve.Change change = BuiltinQueueReserve.Change.NONE;
            while (change != BuiltinQueueReserve.Change.RECOVERED)
                change = onTime(r, clock, PERIOD + 2_000_000L);
            eq(0L, r.extraScans(), "recovered");
            // The load is still there: the first frame at the earlier scan is late.
            check(late(r, clock) == BuiltinQueueReserve.Change.RESTORED,
                    "one late frame right after a recovery restores the depth");
            eq(1L, r.extraScans(), "restored");
            window = Math.min(BuiltinQueueReserve.MAX_RECOVERY_FRAMES, 2 * window);
            eq(window, r.recoveryFrames(), "next recovery needs twice the evidence");
        }
        eq(6L, r.failedRecoveries(), "every failed recovery counted");
        eq(1L, r.deepenings(), "restores are not new deepenings");
    }

    private static void recoveryThatHoldsResetsTheBackoff() {
        BuiltinQueueReserve r = new BuiltinQueueReserve();
        long[] clock = {8_000_000_000L};
        burst(r, clock);
        BuiltinQueueReserve.Change change = BuiltinQueueReserve.Change.NONE;
        while (change != BuiltinQueueReserve.Change.RECOVERED) change = onTime(r, clock, PERIOD + 2_000_000L);
        late(r, clock);
        eq(2 * BuiltinQueueReserve.RECOVERY_FRAMES, r.recoveryFrames(), "backed off once");
        change = BuiltinQueueReserve.Change.NONE;
        while (change != BuiltinQueueReserve.Change.RECOVERED) change = onTime(r, clock, PERIOD + 2_000_000L);
        // On time at the earliest scan for longer than the hold window.
        long frames = BuiltinQueueReserve.RECOVERY_HOLD_NS / PERIOD + 1L;
        for (long i = 0; i < frames; ++i) onTime(r, clock, 3_000_000L - PERIOD);
        eq(BuiltinQueueReserve.RECOVERY_FRAMES, r.recoveryFrames(), "a recovery that held resets the backoff");
        // A late frame long after the recovery is an ordinary miss.
        check(late(r, clock) == BuiltinQueueReserve.Change.NONE, "an isolated miss again");
        eq(0L, r.extraScans(), "earliest scan");
    }

    private static void sustainedLoadReachesTwoScansAndStepsBackOneAtATime() {
        BuiltinQueueReserve r = new BuiltinQueueReserve();
        long[] clock = {9_000_000_000L};
        burst(r, clock);
        advance(clock, BuiltinQueueReserve.SETTLE_NS);
        burst(r, clock);
        eq(2L, r.extraScans(), "two scans under sustained load");
        advance(clock, BuiltinQueueReserve.SETTLE_NS);
        for (int i = 0; i < 10; ++i) late(r, clock);
        eq(2L, r.extraScans(), "capped at two");
        BuiltinQueueReserve.Change change = BuiltinQueueReserve.Change.NONE;
        while (change != BuiltinQueueReserve.Change.RECOVERED) change = onTime(r, clock, PERIOD + 2_000_000L);
        eq(1L, r.extraScans(), "one scan back");
        long recovered = clock[0];
        change = BuiltinQueueReserve.Change.NONE;
        while (change != BuiltinQueueReserve.Change.RECOVERED) change = onTime(r, clock, PERIOD + 2_000_000L);
        eq(0L, r.extraScans(), "and the next");
        check(clock[0] - recovered >= BuiltinQueueReserve.SETTLE_NS +
                (BuiltinQueueReserve.RECOVERY_FRAMES - 1) * PERIOD, "frames queued at depth 2 were not counted");
    }

    private static void withoutTimestampsRecoveryIsSlow() {
        BuiltinQueueReserve r = new BuiltinQueueReserve();
        long desired = 10_000_000_000L;
        for (int i = 0; i < 3; ++i) {
            desired += PERIOD;
            r.observe(true, desired, desired + PERIOD, desired - 4_000_000L, 0L, PERIOD);
        }
        eq(1L, r.extraScans(), "late rendering without a latch time still deepens");
        int frames = 0;
        BuiltinQueueReserve.Change change = BuiltinQueueReserve.Change.NONE;
        while (change != BuiltinQueueReserve.Change.RECOVERED && frames < 10_000) {
            desired += PERIOD;
            change = r.observe(false, desired, desired, 0L, 0L, PERIOD);
            ++frames;
        }
        check(frames >= BuiltinQueueReserve.BLIND_RECOVERY_FRAMES, "blind recovery waits ~20 s: " + frames);
        eq(0L, r.extraScans(), "recovered");
    }

    /** A frame the compositor showed a whole scan before its requested slot
     *  (reported as a wrong-slot miss), rendered 12 ms before that slot. */
    private static BuiltinQueueReserve.Change early(BuiltinQueueReserve r, long[] clock) {
        clock[0] += PERIOD;
        long desired = clock[0], actual = desired - PERIOD;
        return r.observe(true, desired, actual, desired - 12_000_000L, actual - LATENCY, PERIOD);
    }

    /** Wind Waker HD, 2026-10-24: after a startup burst, 74% of frames landed a
     *  scan early and the rest in their slot -- a 1/3-scan judder. */
    private static void framesShownEarlyGiveTheScanBack() {
        BuiltinQueueReserve r = new BuiltinQueueReserve();
        long[] clock = {30_000_000_000L};
        burst(r, clock);
        eq(1L, r.extraScans(), "a startup burst deepens");
        advance(clock, BuiltinQueueReserve.SETTLE_NS);
        int frames = 0;
        BuiltinQueueReserve.Change change = BuiltinQueueReserve.Change.NONE;
        while (change != BuiltinQueueReserve.Change.RECOVERED && frames < 1_000) {
            // Three of every four shown early; the fourth in its slot, rendered
            // too late to prove the earlier latch.
            change = frames % 4 == 3 ? onTime(r, clock, 1_000_000L) : early(r, clock);
            ++frames;
        }
        check(change == BuiltinQueueReserve.Change.RECOVERED,
                "frames shown early give the scan back");
        check(frames <= BuiltinQueueReserve.EARLY_WINDOW, "within one window: " + frames);
        eq(0L, r.extraScans(), "back at the earliest scan");
        eq(1L, r.earlyRecoveries(), "counted as an early recovery");
        // Not a trial recovery: one late frame does not restore the depth.
        advance(clock, BuiltinQueueReserve.SETTLE_NS);
        check(late(r, clock) == BuiltinQueueReserve.Change.NONE, "one late frame changes nothing");
        eq(0L, r.extraScans(), "still at the earliest scan");
        // A burst within the hold-off does not deepen: the depth adds no lead here.
        check(late(r, clock) == BuiltinQueueReserve.Change.NONE, "two late frames are not a burst");
        check(late(r, clock) == BuiltinQueueReserve.Change.NONE, "a burst during the hold-off");
        eq(1L, r.heldDeepenings(), "the held burst is counted");
        eq(0L, r.extraScans(), "still at the earliest scan");
        // The early guard turns on: the next burst deepens (a new trial).
        r.allowDeepening();
        advance(clock, BuiltinQueueReserve.MISS_WINDOW_NS + 1L);
        burst(r, clock);
        eq(1L, r.extraScans(), "deepened after the hold-off was lifted");
    }

    /** Wind Waker HD, 2026-10-25 (per-present trace, no recorder): every
     *  deepening landed half its frames a scan early, and a burst deepened it
     *  again every few seconds. Each early recovery doubles the hold-off. */
    private static void earlyRecoveriesHoldOffDeepening() {
        BuiltinQueueReserve r = new BuiltinQueueReserve();
        long[] clock = {50_000_000_000L};
        long holdoff = BuiltinQueueReserve.DEEPEN_HOLDOFF_NS;
        for (int round = 0; round < 6; ++round) {
            burst(r, clock);
            advance(clock, BuiltinQueueReserve.SETTLE_NS);
            BuiltinQueueReserve.Change change = BuiltinQueueReserve.Change.NONE;
            int frames = 0;
            // Half early, half in their slot: "EE..".
            while (change != BuiltinQueueReserve.Change.RECOVERED && frames < 1_000) {
                change = frames % 4 < 2 ? early(r, clock) : onTime(r, clock, 1_000_000L);
                ++frames;
            }
            check(change == BuiltinQueueReserve.Change.RECOVERED, "half early gives the scan back");
            check(frames <= BuiltinQueueReserve.EARLY_WINDOW, "within one window: " + frames);
            long recovered = clock[0];
            // Bursts until just before the hold-off ends do not deepen.
            while (clock[0] - recovered < holdoff - BuiltinQueueReserve.MISS_WINDOW_NS) {
                advance(clock, BuiltinQueueReserve.MISS_WINDOW_NS / 4);
                check(late(r, clock) != BuiltinQueueReserve.Change.DEEPENED, "held off");
            }
            eq(0L, r.extraScans(), "earliest scan through the hold-off");
            advance(clock, BuiltinQueueReserve.MISS_WINDOW_NS + 1L);
            holdoff = Math.min(BuiltinQueueReserve.MAX_DEEPEN_HOLDOFF_NS, 2L * holdoff);
        }
        eq(6L, r.earlyRecoveries(), "six early recoveries");
        check(r.heldDeepenings() > 0L, "bursts were held");
        eq(6L, r.deepenings(), "one deepening after each hold-off");
    }

    private static void occasionalEarlyFramesKeepTheDepth() {
        BuiltinQueueReserve r = new BuiltinQueueReserve();
        long[] clock = {40_000_000_000L};
        burst(r, clock);
        advance(clock, BuiltinQueueReserve.SETTLE_NS);
        for (int i = 0; i < 4 * BuiltinQueueReserve.EARLY_WINDOW; ++i) {
            BuiltinQueueReserve.Change change = i % 3 == 0 ? early(r, clock) : onTime(r, clock, 0L);
            check(change == BuiltinQueueReserve.Change.NONE, "a third shown early is not enough");
        }
        eq(1L, r.extraScans(), "depth kept");
    }

    /** Shown a scan late although rendered three scans ahead: the compositor's
     *  miss, which no depth fixes and which never counts toward a burst. */
    private static BuiltinQueueReserve.Change compositorLate(BuiltinQueueReserve r, long[] clock) {
        clock[0] += PERIOD;
        long desired = clock[0];
        return r.observe(true, desired, desired + PERIOD, desired - 3L * PERIOD,
                desired + PERIOD - LATENCY, PERIOD);
    }

    /** One in six frames late at depth 0, and still one in six one scan deeper:
     *  the trial fails, the scan is given back and deepening waits. */
    private static void aDeepeningThatAddsNothingIsGivenBack() {
        BuiltinQueueReserve r = new BuiltinQueueReserve();
        long[] clock = {60_000_000_000L};
        for (int i = 0; i < BuiltinQueueReserve.TRIAL_FRAMES; ++i)
            if (i % 6 == 5) compositorLate(r, clock); else onTime(r, clock, 0L);
        burst(r, clock);
        advance(clock, BuiltinQueueReserve.SETTLE_NS);
        BuiltinQueueReserve.Change change = BuiltinQueueReserve.Change.NONE;
        int frames = 0;
        while (change == BuiltinQueueReserve.Change.NONE && frames < 1_000) {
            change = frames % 6 == 5 ? compositorLate(r, clock) : onTime(r, clock, 0L);
            ++frames;
        }
        check(change == BuiltinQueueReserve.Change.RECOVERED, "the trial gives the scan back: " + change);
        eq(BuiltinQueueReserve.TRIAL_FRAMES, frames, "after one trial's frames");
        eq(1L, r.rejectedTrials(), "one rejected trial");
        eq(0L, r.extraScans(), "earliest scan");
        advance(clock, BuiltinQueueReserve.SETTLE_NS);
        late(r, clock);
        late(r, clock);
        check(late(r, clock) == BuiltinQueueReserve.Change.NONE, "a burst during the hold-off");
        eq(1L, r.heldDeepenings(), "held");
    }

    /** A quarter late at depth 0, all in their slot one scan deeper: kept. */
    private static void aDeepeningThatHelpsIsKept() {
        BuiltinQueueReserve r = new BuiltinQueueReserve();
        long[] clock = {70_000_000_000L};
        for (int i = 0; i < BuiltinQueueReserve.TRIAL_FRAMES; ++i)
            if (i % 4 == 3) compositorLate(r, clock); else onTime(r, clock, 0L);
        burst(r, clock);
        advance(clock, BuiltinQueueReserve.SETTLE_NS);
        for (int i = 0; i < 1_000; ++i)
            check(onTime(r, clock, 0L) == BuiltinQueueReserve.Change.NONE, "kept");
        eq(1L, r.extraScans(), "one scan deeper");
        eq(0L, r.rejectedTrials(), "the trial passed");
    }

    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }

    private static void eq(long expected, long actual, String message) {
        if (expected != actual) throw new AssertionError(message + ": expected " + expected + " got " + actual);
    }
}
