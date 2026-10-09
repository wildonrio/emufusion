package com.thorium.lucent.video;

public final class GpuPairTimingLedgerTest {
    public static void main(String[] args) {
        GpuPairTimingLedger ledger = new GpuPairTimingLedger(4);
        stages(ledger, 1L, 10L);
        eq(0L, ledger.takeCompletedPair(), "estimator alone is never complete GPU evidence");
        check(ledger.expectWarp(17L, 1L), "warp binds to immutable pair owner");
        stages(ledger, 2L, 20L);
        check(ledger.expectWarp(18L, 2L), "different warp binds to different pair");
        check(ledger.recordWarp(18L, 7L), "later warp may finish first");
        eq(2L, ledger.takeCompletedPair(), "only the later pair has its own warp");
        eq(107L, ledger.completedTotalUs(2L), "join uses actual later warp cost");
        eq(0L, ledger.takeCompletedPair(), "each complete pair is admitted once");
        check(ledger.recordWarp(17L, 3L), "earlier warp may finish later");
        eq(1L, ledger.takeCompletedPair(), "earlier pair retains its independent owner");
        eq(53L, ledger.completedTotalUs(1L), "no p95 or unrelated warp substitutes for owner");
        check(!ledger.recordWarp(17L, 3L), "replayed warp cannot earn another completion");
        check(!ledger.recordEstimatorStage(1L, 1, 10L), "replayed estimator cannot earn recovery");
        check(!ledger.expectWarp(19L, 1L), "second midpoint cannot reuse the pair");

        GpuPairTimingLedger missing = new GpuPairTimingLedger(2);
        check(missing.expectWarp(1L, 1L), "warp can be registered before stage results");
        stages(missing, 1L, 2L);
        check(!missing.recordEstimatorStage(3L, 1, 2L), "ring cannot erase a missing warp");
        missing.beginEvidenceEpoch();
        check(!missing.recordWarp(1L, 2L), "old epoch warp loses ownership");
        stages(missing, 1L, 2L);
        check(missing.recordEstimatorStage(3L, 1, 2L), "unrequested warp is unpaired, not missing");
        eq(1L, missing.unpairedEstimateCount(), "retired unpaired estimate remains visible");

        GpuPairTimingLedger overflow = new GpuPairTimingLedger(2);
        check(overflow.recordEstimatorStage(1L, 1, Long.MAX_VALUE), "first finite stage retained");
        check(!overflow.recordEstimatorStage(1L, 2, 1L), "stage sum cannot overflow healthy");
        check(!overflow.recordEstimatorStage(0L, 1, 1L), "zero identity rejected");
        check(!overflow.recordEstimatorStage(2L, 0, 1L), "unknown stage rejected");
        check(!overflow.recordWarp(99L, 1L), "unannounced warp cannot be paired");
        overflow.beginEvidenceEpoch();
        check(overflow.expectWarp(1L, 1L), "warp can arrive before estimator");
        check(overflow.recordWarp(1L, Long.MAX_VALUE), "large positive warp retained");
        check(!overflow.recordEstimatorStage(1L, 1, 1L), "late estimator cannot overflow warp sum");
        joinedFailuresAreIndependentAndBounded();
        System.out.println("GpuPairTimingLedgerTest passed");
    }

    private static void joinedFailuresAreIndependentAndBounded() {
        GpuPairTimingLedger ledger = new GpuPairTimingLedger(4);
        GpuWorkAdaptationPolicy policy = new GpuWorkAdaptationPolicy();
        for (int pair = 1; pair <= 32; ++pair) {
            stages(ledger, pair, 100L);
            check(ledger.expectWarp(pair, pair), "fresh warp owns its pair");
            eq(0L, ledger.takeCompletedPair(), "five cheap stages cannot hide missing warp");
            check(ledger.recordWarp(pair, 600L), "actual warp added to its owner");
            long completed = ledger.takeCompletedPair();
            eq(pair, completed, "complete pair consumed once");
            policy.onCompletedPair(completed, ledger.completedTotalUs(completed), 1000L, false);
            for (int repeatedPoll = 0; repeatedPoll < 1200; ++repeatedPoll)
                eq(0L, ledger.takeCompletedPair(), "an old spike cannot become a fresh failure");
            eq(pair, policy.failureCount(), "one combined shader overload per independent pair");
            eq(0L, policy.restorationCount(), "no overload earns recovery");
            check(policy.generationDisabled() == (pair == 32),
                    "Direct is bounded by 32 real failed pairs, not 32 polls");
        }
        ledger.beginEvidenceEpoch();
        policy.beginEvidenceEpoch();
        check(policy.generationDisabled(), "resetting timing ownership cannot undo Direct latch");
        eq(32L, policy.failureCount(), "epoch reset preserves failure accounting");
    }

    private static void stages(GpuPairTimingLedger ledger, long pair, long cost) {
        for (int stage = 1; stage <= 5; ++stage)
            check(ledger.recordEstimatorStage(pair, stage, cost), "fresh estimator stage accepted");
    }
    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
    private static void eq(long expected, long actual, String message) {
        if (expected != actual) throw new AssertionError(message + ": " + actual);
    }
}
