package com.thorium.lucent.video;

public final class GpuWorkAdaptationPolicyTest {
    public static void main(String[] args) {
        twelveHundredBadPairsNeverRestoreQuality();
        everyFailureInvalidatesRecoveryAtMinimumWork();
        restorationRequiresConsecutiveEvidenceAndHeadroom();
        freshPairsAndFullTimingAreRequired();
        intermittentFailureCannotEvadeTheMinimumWorkLimit();
        epochsPreserveFailureAccountingAndDisable();
        shaderBudgetAloneCannotProvePhysicalHeadroom();
        duplicateFailureClearsRecoveryWithoutRecounting();
        invalidConfigurationRejected();
        System.out.println("GpuWorkAdaptationPolicyTest passed");
    }

    private static void twelveHundredBadPairsNeverRestoreQuality() {
        GpuWorkAdaptationPolicy value = new GpuWorkAdaptationPolicy();
        for (int pair = 1; pair <= 1200; ++pair) {
            GpuWorkAdaptationPolicy.Decision decision =
                    value.onCompletedPair(pair, 8000L, 7333L, true);
            check(decision != GpuWorkAdaptationPolicy.Decision.RESTORE_WORK,
                    "an over-budget pair never restores quality");
            eq(0, value.consecutiveHealthyPairs(), "bad sample always clears recovery");
            if (pair >= 32) check(value.generationDisabled(), "chronic overload disables by 32");
        }
        eq(2, value.workLevel(), "minimum work level reached");
        eq(1200, value.failureCount(), "all bad observations remain counted");
        eq(1200, value.failureCount(GpuWorkAdaptationPolicy.Failure.GPU_OVER_BUDGET),
                "overload reason accounting remains intact");
        eq(0, value.restorationCount(), "1200 bad pairs cannot earn restoration");
        eq(1, value.disableTransitionCount(), "disable latches exactly once");
        eq(2, value.reductionCount(), "only two work reductions exist");
    }

    private static void everyFailureInvalidatesRecoveryAtMinimumWork() {
        for (GpuWorkAdaptationPolicy.Failure reason : GpuWorkAdaptationPolicy.Failure.values()) {
            GpuWorkAdaptationPolicy value = new GpuWorkAdaptationPolicy(2, 4, 30);
            value.onFailure(GpuWorkAdaptationPolicy.Failure.GPU_OVER_BUDGET);
            value.onFailure(GpuWorkAdaptationPolicy.Failure.GPU_OVER_BUDGET);
            for (int pair = 1; pair <= 3; ++pair) value.onCompletedPair(pair, 500L, 1000L, true);
            eq(3, value.consecutiveHealthyPairs(), "recovery fixture nearly complete");
            value.onFailure(reason);
            eq(0, value.consecutiveHealthyPairs(), reason + " invalidates recovery at minimum");
            eq(2, value.workLevel(), "failure cannot upgrade minimum work");
            eq(1, value.failuresAtMinimum(), "minimum failure is retained");
            value.onCompletedPair(4L, 500L, 1000L, true);
            eq(0, value.restorationCount(), "one later good sample cannot spend stale credit");
        }
    }

    private static void restorationRequiresConsecutiveEvidenceAndHeadroom() {
        GpuWorkAdaptationPolicy value = new GpuWorkAdaptationPolicy();
        value.onFailure(GpuWorkAdaptationPolicy.Failure.GPU_OVER_BUDGET);
        for (int pair = 1; pair < 1200; ++pair)
            check(value.onCompletedPair(pair, 500L, 1000L, true) ==
                    GpuWorkAdaptationPolicy.Decision.UNCHANGED, "recovery is deliberately slow");
        eq(1, value.workLevel(), "1199 good pairs do not restore quality");
        check(value.onCompletedPair(1200L, 500L, 1000L, true) ==
                GpuWorkAdaptationPolicy.Decision.RESTORE_WORK, "1200th consecutive good pair restores");
        eq(0, value.workLevel(), "one quality level restored");
        eq(0, value.consecutiveHealthyPairs(), "restoration spends all recovery evidence");
        eq(1, value.failureCount(), "restoration does not erase failures");
        value.onFailure(GpuWorkAdaptationPolicy.Failure.TIMER_MISSING);
        for (int pair = 1201; pair <= 2400; ++pair) value.onCompletedPair(pair, 801L, 1000L, true);
        eq(1, value.workLevel(), "marginal shader slack cannot restore more costly work");
        eq(0, value.consecutiveHealthyPairs(), "marginal pairs cannot bank recovery");
        eq(1200, value.marginalShaderPairs(), "marginal observations stay visible");
    }

    private static void freshPairsAndFullTimingAreRequired() {
        GpuWorkAdaptationPolicy value = new GpuWorkAdaptationPolicy(2, 4, 30);
        value.onFailure(GpuWorkAdaptationPolicy.Failure.GPU_OVER_BUDGET);
        value.onCompletedPair(1L, 500L, 1000L, true);
        value.onCompletedPair(2L, 500L, 1000L, true);
        value.onCompletedPair(2L, 500L, 1000L, true);
        eq(0, value.consecutiveHealthyPairs(), "a duplicate result invalidates the streak");
        value.onCompletedPair(1L, 500L, 1000L, true);
        value.onCompletedPair(3L, 0L, 1000L, true);
        value.onCompletedPair(4L, 500L, 0L, true);
        eq(3, value.failureCount(GpuWorkAdaptationPolicy.Failure.TIMER_INVALID),
                "duplicate, regressed, and invalid budget are invalid evidence");
        eq(1, value.failureCount(GpuWorkAdaptationPolicy.Failure.TIMER_MISSING),
                "a missing complete cost is not zero-cost work");
        eq(0, value.restorationCount(), "incomplete evidence never restores quality");
        value.onCompletedPair(5L, Long.MAX_VALUE, 1000L, true);
        eq(2, value.failureCount(GpuWorkAdaptationPolicy.Failure.GPU_OVER_BUDGET),
                "huge elapsed cost cannot overflow into healthy credit");
    }

    private static void intermittentFailureCannotEvadeTheMinimumWorkLimit() {
        GpuWorkAdaptationPolicy value = new GpuWorkAdaptationPolicy(0, 1200, 3);
        for (int pair = 1; pair <= 3; ++pair) {
            value.onFailure(GpuWorkAdaptationPolicy.Failure.GPU_OVER_BUDGET);
            value.onCompletedPair(pair, 500L, 1000L, true);
        }
        check(value.generationDisabled(), "isolated good samples cannot hide chronic failure");
        eq(3, value.failuresAtMinimum(), "failure budget survives isolated good samples");
        eq(0, value.restorationCount(), "there was never consecutive recovery evidence");
    }

    private static void epochsPreserveFailureAccountingAndDisable() {
        GpuWorkAdaptationPolicy value = new GpuWorkAdaptationPolicy(1, 4, 2);
        value.onFailure(GpuWorkAdaptationPolicy.Failure.TIMER_DISJOINT);
        value.onFailure(GpuWorkAdaptationPolicy.Failure.TIMER_DISJOINT);
        value.onCompletedPair(8L, 500L, 1000L, true);
        value.beginEvidenceEpoch();
        eq(1, value.workLevel(), "timer recreation cannot restore quality");
        eq(1, value.failuresAtMinimum(), "timer recreation cannot erase load failures");
        eq(0, value.consecutiveHealthyPairs(), "ownership change invalidates consecutive proof");
        value.onCompletedPair(1L, 500L, 1000L, true);
        eq(2, value.failureCount(), "fresh epoch may restart pair identity");
        value.onFailure(GpuWorkAdaptationPolicy.Failure.TIMER_DISJOINT);
        check(value.generationDisabled(), "failure limit survives epoch reset");
        value.beginEvidenceEpoch();
        for (int pair = 1; pair <= 1200; ++pair)
            check(value.onCompletedPair(pair, 500L, 1000L, true) ==
                    GpuWorkAdaptationPolicy.Decision.DISABLE_GENERATION,
                    "a disabled session cannot silently rearm");
        eq(1, value.disableTransitionCount(), "epoch changes preserve disable accounting");
        eq(0, value.restorationCount(), "disabled sessions cannot earn recovery");
    }

    private static void shaderBudgetAloneCannotProvePhysicalHeadroom() {
        GpuWorkAdaptationPolicy value = new GpuWorkAdaptationPolicy(1, 4, 30);
        value.onFailure(GpuWorkAdaptationPolicy.Failure.GPU_OVER_BUDGET);
        for (int pair = 1; pair <= 3; ++pair) value.onCompletedPair(pair, 100L, 1000L, true);
        value.onCompletedPair(4L, 100L, 1000L, false);
        eq(0, value.consecutiveHealthyPairs(), "unknown physical budget breaks consecutive proof");
        for (int pair = 5; pair <= 1204; ++pair) value.onCompletedPair(pair, 100L, 1000L, false);
        eq(1, value.workLevel(), "fast shader timings alone cannot restore quality");
        eq(1201, value.physicalHeadroomUnknownPairs(), "missing total headroom remains visible");
        eq(1, value.failureCount(), "unknown headroom is not falsely called shader overload");
        value.onFailure(GpuWorkAdaptationPolicy.Failure.PHYSICAL_DEADLINE_MISS);
        eq(1, value.failureCount(GpuWorkAdaptationPolicy.Failure.PHYSICAL_DEADLINE_MISS),
                "physical overload remains a distinct measured failure");
    }

    private static void invalidConfigurationRejected() {
        for (int[] bounds : new int[][] {{-1, 4, 3}, {2, 0, 3}, {2, 4, 0}}) {
            boolean rejected = false;
            try { new GpuWorkAdaptationPolicy(bounds[0], bounds[1], bounds[2]); }
            catch (IllegalArgumentException expected) { rejected = true; }
            check(rejected, "invalid bounds cannot silently disable safety gates");
        }
    }

    private static void duplicateFailureClearsRecoveryWithoutRecounting() {
        GpuWorkAdaptationPolicy value = new GpuWorkAdaptationPolicy(1, 4, 30);
        value.onFailure(GpuWorkAdaptationPolicy.Failure.GPU_OVER_BUDGET);
        for (int pair = 1; pair <= 3; ++pair) value.onCompletedPair(pair, 100L, 1000L, true);
        eq(3, value.consecutiveHealthyPairs(), "fixture has recovery credit");
        for (int repeatedPoll = 0; repeatedPoll < 1200; ++repeatedPoll)
            value.invalidateRecoveryEvidence();
        eq(0, value.consecutiveHealthyPairs(), "duplicate evidence invalidates recovery");
        eq(1, value.failureCount(), "repeated evidence is not independent load failure");
        check(!value.generationDisabled(), "one old spike cannot become chronic overload");
    }

    private static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }

    private static void eq(long expected, long actual, String message) {
        if (expected != actual)
            throw new AssertionError(message + ": expected=" + expected + " actual=" + actual);
    }
}
