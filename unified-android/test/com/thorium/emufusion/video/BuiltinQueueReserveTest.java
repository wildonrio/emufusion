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

    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }

    private static void eq(long expected, long actual, String message) {
        if (expected != actual) throw new AssertionError(message + ": expected " + expected + " got " + actual);
    }
}
