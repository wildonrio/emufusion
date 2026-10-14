package com.thorium.emufusion.video;

public final class GpuWorkAdaptationPolicyTest {
    public static void main(String[] args) {
        twelveHundredBadPairsNeverRestoreQuality();
        overBudgetShaderTimeAloneNeverDisables();
        oneEmulatorHitchDoesNotDisable();
        startupHitchKeepsFullWork();
        oneDisturbanceCostsOneLevel();
        steadyPressureStepsTheCheapLevels();
        unknownHeadroomRecoversOnShaderEvidence();
        recoveryBacksOffWhenALevelDoesNotHold();
        screenshotSpikeAfterStrayMissesDoesNotDisable();
        suspensionResumesAtMinimumWorkAndCanDisableAgain();
        lastLevelNeedsSteadyMisses();
        steadyPresentBackpressureEarnsTheLastLevelOnly();
        isolatedPhysicalMissesDoNotAccumulate();
        loneDeadlineMissesDoNotRatchetWork();
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
        }
        eq(GpuWorkAdaptationPolicy.DEFAULT_MAX_WORK_LEVEL - 1, value.workLevel(), "shader time alone stops before the last level");
        eq(1200, value.failureCount(), "all bad observations remain counted");
        eq(1200, value.failureCount(GpuWorkAdaptationPolicy.Failure.GPU_OVER_BUDGET),
                "overload reason accounting remains intact");
        eq(0, value.restorationCount(), "1200 bad pairs cannot earn restoration");
        eq(GpuWorkAdaptationPolicy.DEFAULT_MAX_WORK_LEVEL - 1, value.reductionCount(), "the last level needs visible misses");
    }

    private static void overBudgetShaderTimeAloneNeverDisables() {
        // Thor 2026-10-11: GPU timer spans include the emulator's interleaved
        // work; every flagged GameCube frame was still shown in its slot.
        GpuWorkAdaptationPolicy value = new GpuWorkAdaptationPolicy();
        for (int pair = 1; pair <= 5000; ++pair) value.onCompletedPair(pair, 8000L, 7333L, true);
        check(!value.generationDisabled(), "shader time over budget sheds work but never disables");
        eq(0, value.failuresAtMinimum(), "over-budget time is not a minimum-work failure");
        int misses = 0;
        while (!value.generationDisabled() && misses < 1000) {
            value.onFailure(GpuWorkAdaptationPolicy.Failure.PHYSICAL_DEADLINE_MISS);
            ++misses;
        }
        check(value.generationDisabled(), "visible misses sustained at minimum work disable");
        check(misses > (GpuWorkAdaptationPolicy.DEFAULT_PERSISTENCE_BLOCKS - 1) *
                        GpuWorkAdaptationPolicy.DEFAULT_PERSISTENCE_BLOCK_PAIRS,
                "the misses had to persist over several blocks: " + misses);
    }

    private static void screenshotSpikeAfterStrayMissesDoesNotDisable() {
        // Wind Waker HD on Cemu, Thor 2026-10-12, 30 pairs/s: a few misses in
        // the seconds before two screenshots, then 54 misses in their 3 s.
        // Over the burst that was a quarter of all pairs and it disabled
        // generation for the session; the misses were not sustained.
        GpuWorkAdaptationPolicy value = new GpuWorkAdaptationPolicy();
        long pair = reachMinimumWork(value);
        for (int good = 0; good < 60; ++good) value.onCompletedPair(++pair, 500L, 1000L, true);
        for (int i = 0; i < 120; ++i) {
            if (i % 17 == 0) value.onFailure(GpuWorkAdaptationPolicy.Failure.PHYSICAL_DEADLINE_MISS);
            else value.onCompletedPair(++pair, 500L, 1000L, true);
        }
        for (int i = 0; i < 90; ++i) {
            if (i % 5 < 3) value.onFailure(GpuWorkAdaptationPolicy.Failure.PHYSICAL_DEADLINE_MISS);
            else value.onCompletedPair(++pair, 500L, 1000L, true);
        }
        check(value.failuresAtMinimum() >= GpuWorkAdaptationPolicy.DEFAULT_FAILURES_AT_MINIMUM,
                "the fixture reaches the failure count");
        check(!value.generationDisabled(), "a three-second compositor spike is not sustained overload");
        for (int good = 0; good < 300; ++good) value.onCompletedPair(++pair, 500L, 1000L, true);
        check(!value.generationDisabled(), "generation continues after the spike");
        for (int round = 0; round < 150; ++round) {
            value.onFailure(GpuWorkAdaptationPolicy.Failure.PHYSICAL_DEADLINE_MISS);
            value.onCompletedPair(++pair, 500L, 1000L, true);
        }
        check(value.generationDisabled(), "half the frames missing for ten seconds is overload");
    }

    private static void oneEmulatorHitchDoesNotDisable() {
        // GameCube 2026-10-11: one 0.35 s stall missed thirty frames at once.
        GpuWorkAdaptationPolicy value = new GpuWorkAdaptationPolicy();
        long pair = steadyMissesTo(value, GpuWorkAdaptationPolicy.DEFAULT_MAX_WORK_LEVEL - 1, 0L);
        for (int hitch = 0; hitch < 3; ++hitch) {
            for (int miss = 0; miss < 40; ++miss)
                value.onFailure(GpuWorkAdaptationPolicy.Failure.PHYSICAL_DEADLINE_MISS);
            check(!value.generationDisabled(), "a short burst of misses is a hitch, not overload");
            for (int good = 0; good < 300; ++good) value.onCompletedPair(++pair, 500L, 1000L, true);
        }
        check(!value.generationDisabled(), "hitches seconds apart stay below the disable density");
        for (int round = 0; round < 400; ++round) {
            value.onFailure(GpuWorkAdaptationPolicy.Failure.PHYSICAL_DEADLINE_MISS);
            value.onCompletedPair(++pair, 500L, 1000L, true);
        }
        check(value.generationDisabled(), "half the frames missing for seconds is overload");
    }

    /** Steady 1-in-10 visible misses until the policy reaches {@code level}. */
    private static long steadyMissesTo(GpuWorkAdaptationPolicy value, int level, long pair) {
        int rounds = 0;
        while (value.workLevel() < level) {
            value.onFailure(GpuWorkAdaptationPolicy.Failure.PHYSICAL_DEADLINE_MISS);
            for (int good = 0; good < 9; ++good) value.onCompletedPair(++pair, 500L, 1000L, true);
            check(++rounds < 1000, "steady misses reach level " + level);
        }
        return pair;
    }

    /** Dolphin/PS2/PS3/Eden 2026-10-12: two over-budget pairs at startup took level 0 to 2. */
    private static void startupHitchKeepsFullWork() {
        GpuWorkAdaptationPolicy value = new GpuWorkAdaptationPolicy();
        long pair = 0;
        for (int i = 0; i < 3; ++i) value.onCompletedPair(++pair, 9000L, 7333L, false);
        for (int good = 0; good < 600; ++good) value.onCompletedPair(++pair, 3000L, 7333L, false);
        eq(0, value.workLevel(), "a few over-budget pairs keep the per-phase field");
        eq(0, value.reductionCount(), "nothing was shed");
        // A visible hitch sheds at once (Cemu cannot wait), but one burst
        // with nothing completed in between costs one level, not three.
        for (int miss = 0; miss < 30; ++miss) value.onFailure(GpuWorkAdaptationPolicy.Failure.PHYSICAL_DEADLINE_MISS);
        eq(1, value.workLevel(), "a burst of misses sheds one level at once");
        // Misses that keep coming while pairs complete shed the cheap levels.
        for (int round = 0; round < 3 && value.workLevel() < GpuWorkAdaptationPolicy.DEFAULT_MAX_WORK_LEVEL - 1; ++round) {
            for (int good = 0; good < GpuWorkAdaptationPolicy.REDUCTION_SETTLE_PAIRS; ++good)
                value.onCompletedPair(++pair, 3000L, 7333L, false);
            value.onFailure(GpuWorkAdaptationPolicy.Failure.PHYSICAL_DEADLINE_MISS);
        }
        eq(GpuWorkAdaptationPolicy.DEFAULT_MAX_WORK_LEVEL - 1, value.workLevel(), "persisting misses shed the cheap levels");
        // ...and recovery on shader slack with unknown headroom earns it back.
        for (int i = 0; i < 4 * value.recoveryWindowPairs() && value.workLevel() > 0; ++i)
            value.onCompletedPair(++pair, 3000L, 7333L, false);
        eq(0, value.workLevel(), "recovery restores full work after the hitch");
    }

    /** SM3DW soak 2026-10-14: single misses minutes apart ratcheted level 2 to 4 for good. */
    private static void loneDeadlineMissesDoNotRatchetWork() {
        GpuWorkAdaptationPolicy value = new GpuWorkAdaptationPolicy();
        long pair = 0;
        for (int miss = 0; miss < 6; ++miss) {
            for (int good = 0; good < GpuWorkAdaptationPolicy.ISOLATED_MISS_PAIRS; ++good)
                value.onCompletedPair(++pair, 6800L, 7333L, false);
            value.onFailure(GpuWorkAdaptationPolicy.Failure.PHYSICAL_DEADLINE_MISS);
        }
        eq(0, value.workLevel(), "lone misses ten seconds apart shed nothing");
        eq(6, value.failureCount(GpuWorkAdaptationPolicy.Failure.PHYSICAL_DEADLINE_MISS), "each is still counted");
        // A second miss inside the window is pressure.
        for (int good = 0; good < 100; ++good) value.onCompletedPair(++pair, 6800L, 7333L, false);
        value.onFailure(GpuWorkAdaptationPolicy.Failure.PHYSICAL_DEADLINE_MISS);
        eq(1, value.workLevel(), "a repeated miss sheds a level");
    }

    /** 3DS 2026-10-13: three misses in 230 ms (seven pairs) took level 0 to 3 for the session. */
    private static void oneDisturbanceCostsOneLevel() {
        GpuWorkAdaptationPolicy value = new GpuWorkAdaptationPolicy();
        long pair = 0;
        for (int good = 0; good < 300; ++good) value.onCompletedPair(++pair, 3000L, 7333L, false);
        value.onFailure(GpuWorkAdaptationPolicy.Failure.PHYSICAL_DEADLINE_MISS);
        value.onCompletedPair(++pair, 3000L, 7333L, false);
        value.onCompletedPair(++pair, 3000L, 7333L, false);
        value.onFailure(GpuWorkAdaptationPolicy.Failure.PHYSICAL_DEADLINE_MISS);
        for (int good = 0; good < 4; ++good) value.onCompletedPair(++pair, 3000L, 7333L, false);
        value.onFailure(GpuWorkAdaptationPolicy.Failure.PHYSICAL_DEADLINE_MISS);
        eq(1, value.workLevel(), "one disturbance costs one level");
        eq(1, value.reductionCount(), "one reduction");
        eq(3, value.failureCount(GpuWorkAdaptationPolicy.Failure.PHYSICAL_DEADLINE_MISS), "every miss is still counted");
        eq(0, value.consecutiveHealthyPairs(), "and clears recovery");
        // Cemu at startup: about one pair in three missed for seconds.
        int rounds = 0;
        while (value.workLevel() < 3 && rounds < 200) {
            value.onFailure(GpuWorkAdaptationPolicy.Failure.PHYSICAL_DEADLINE_MISS);
            value.onCompletedPair(++pair, 3000L, 7333L, false);
            value.onCompletedPair(++pair, 3000L, 7333L, false);
            ++rounds;
        }
        eq(3, value.workLevel(), "steady misses still reach level 3");
        check(rounds <= 2 * GpuWorkAdaptationPolicy.REDUCTION_SETTLE_PAIRS / 2 + 2,
                "within about two settle windows of pairs: " + rounds);
    }

    private static void steadyPressureStepsTheCheapLevels() {
        GpuWorkAdaptationPolicy value = new GpuWorkAdaptationPolicy();
        long pair = steadyMissesTo(value, 1, 0L);
        check(pair <= 2 * GpuWorkAdaptationPolicy.DEFAULT_PERSISTENCE_BLOCK_PAIRS,
                "steady misses shed the first level within two blocks: " + pair);
        // A quarter of pairs over the shader budget is pressure too.
        GpuWorkAdaptationPolicy busy = new GpuWorkAdaptationPolicy();
        long busyPair = 0;
        for (int i = 0; i < 400 && busy.workLevel() < 1; ++i)
            busy.onCompletedPair(++busyPair, i % 3 == 0 ? 9000L : 5000L, 7333L, false);
        eq(1, busy.workLevel(), "sustained over-budget shader time sheds a level");
    }

    /** Thor: ~97% of pairs have unknown physical headroom, which used to forbid restoring. */
    private static void unknownHeadroomRecoversOnShaderEvidence() {
        GpuWorkAdaptationPolicy value = new GpuWorkAdaptationPolicy();
        long pair = steadyMissesTo(value, 1, 0L);
        int window = value.recoveryWindowPairs();
        int restoredAt = -1;
        for (int i = 0; i < window && restoredAt < 0; ++i) {
            // Marginal timer readings interleave without resetting the streak.
            if (i % 50 == 0) value.onCompletedPair(++pair, 6500L, 7333L, false);
            if (value.onCompletedPair(++pair, 3000L, 7333L, false) ==
                    GpuWorkAdaptationPolicy.Decision.RESTORE_WORK) restoredAt = i;
        }
        check(restoredAt >= window - 20, "unknown headroom with shader slack restores after a full window: " + restoredAt);
        eq(0, value.workLevel(), "full work is back");
        value.onFailure(GpuWorkAdaptationPolicy.Failure.PHYSICAL_DEADLINE_MISS);
        eq(0, value.consecutiveHealthyPairs(), "a visible miss still clears recovery");
    }

    private static void recoveryBacksOffWhenALevelDoesNotHold() {
        GpuWorkAdaptationPolicy value = new GpuWorkAdaptationPolicy();
        long pair = steadyMissesTo(value, 1, 0L);
        int first = value.recoveryWindowPairs();
        for (int i = 0; i < first; ++i) value.onCompletedPair(++pair, 3000L, 7333L, false);
        eq(0, value.workLevel(), "restored");
        pair = steadyMissesTo(value, 1, pair);  // the restored level did not hold
        eq(2 * first, value.recoveryWindowPairs(), "the next restoration waits twice as long");
        for (int round = 0; round < 6; ++round) {
            int window = value.recoveryWindowPairs();
            for (int i = 0; i < window; ++i) value.onCompletedPair(++pair, 3000L, 7333L, false);
            pair = steadyMissesTo(value, 1, pair);
        }
        eq(8 * first, value.recoveryWindowPairs(), "backoff is capped at eight windows");
    }

    /** Steady misses earn the last level; a clean window then clears the burst. */
    private static long reachMinimumWork(GpuWorkAdaptationPolicy value) {
        long pair = 0;
        while (value.workLevel() < GpuWorkAdaptationPolicy.DEFAULT_MAX_WORK_LEVEL) {
            value.onFailure(GpuWorkAdaptationPolicy.Failure.PHYSICAL_DEADLINE_MISS);
            for (int good = 0; good < 9; ++good) value.onCompletedPair(++pair, 500L, 1000L, true);
            check(pair < 10_000, "steady 10% misses reach the last level");
        }
        for (int good = 0; good < 600; ++good) value.onCompletedPair(++pair, 500L, 1000L, false);
        eq(0, value.failuresAtMinimum(), "a clean window clears the burst");
        eq(GpuWorkAdaptationPolicy.DEFAULT_MAX_WORK_LEVEL, value.workLevel(), "and keeps the minimum work level");
        return pair;
    }

    private static void lastLevelNeedsSteadyMisses() {
        GpuWorkAdaptationPolicy value = new GpuWorkAdaptationPolicy();
        long pair = steadyMissesTo(value, GpuWorkAdaptationPolicy.DEFAULT_MAX_WORK_LEVEL - 1, 0L);
        // One 0.35 s hitch: thirty misses at once, then clean pairs.
        for (int miss = 0; miss < 30; ++miss) value.onFailure(GpuWorkAdaptationPolicy.Failure.PHYSICAL_DEADLINE_MISS);
        for (int good = 0; good < 600; ++good) value.onCompletedPair(++pair, 500L, 1000L, true);
        eq(GpuWorkAdaptationPolicy.DEFAULT_MAX_WORK_LEVEL - 1, value.workLevel(), "a hitch never costs the last level");
        // Steady 1-in-10 misses (a saturated GPU) earn it within three blocks.
        int rounds = 0;
        while (value.workLevel() < GpuWorkAdaptationPolicy.DEFAULT_MAX_WORK_LEVEL && rounds < 100) {
            value.onFailure(GpuWorkAdaptationPolicy.Failure.PHYSICAL_DEADLINE_MISS);
            for (int good = 0; good < 9; ++good) value.onCompletedPair(++pair, 500L, 1000L, true);
            ++rounds;
        }
        eq(GpuWorkAdaptationPolicy.DEFAULT_MAX_WORK_LEVEL, value.workLevel(), "steady misses earn the last level");
        check(rounds <= 19, "within three blocks: " + rounds);
    }

    private static void steadyPresentBackpressureEarnsTheLastLevelOnly() {
        GpuWorkAdaptationPolicy value = new GpuWorkAdaptationPolicy();
        long pair = 0;
        check(value.onPresentationBackpressure() == GpuWorkAdaptationPolicy.Decision.UNCHANGED,
                "backpressure alone does not shed the cheap levels");
        pair = steadyMissesTo(value, GpuWorkAdaptationPolicy.DEFAULT_MAX_WORK_LEVEL - 1, pair);
        for (int good = 0; good < 600; ++good) value.onCompletedPair(++pair, 500L, 1000L, true);
        eq(GpuWorkAdaptationPolicy.DEFAULT_MAX_WORK_LEVEL - 1, value.workLevel(), "fixture at the level below the last");
        int rounds = 0;
        while (value.workLevel() < GpuWorkAdaptationPolicy.DEFAULT_MAX_WORK_LEVEL && rounds < 100) {
            value.onPresentationBackpressure();
            for (int good = 0; good < 6; ++good) value.onCompletedPair(++pair, 500L, 1000L, true);
            ++rounds;
        }
        eq(GpuWorkAdaptationPolicy.DEFAULT_MAX_WORK_LEVEL, value.workLevel(), "steady blocked presents earn the last level");
        for (int i = 0; i < 2000; ++i) {
            check(value.onPresentationBackpressure() == GpuWorkAdaptationPolicy.Decision.UNCHANGED,
                    "at the last level backpressure changes nothing");
            value.onCompletedPair(++pair, 500L, 1000L, true);
        }
        check(!value.generationDisabled(), "backpressure never disables generation");
    }

    private static void suspensionResumesAtMinimumWorkAndCanDisableAgain() {
        GpuWorkAdaptationPolicy value = new GpuWorkAdaptationPolicy();
        long pair = 0;
        value.resumeAfterSuspension();
        eq(0, value.resumeCount(), "an enabled policy has nothing to resume");
        while (!value.generationDisabled()) {
            value.onFailure(GpuWorkAdaptationPolicy.Failure.PHYSICAL_DEADLINE_MISS);
            value.onCompletedPair(++pair, 500L, 1000L, true);
        }
        long failures = value.failureCount();
        value.resumeAfterSuspension();
        check(!value.generationDisabled(), "the owner's suspension ended: generation retries");
        eq(1, value.resumeCount(), "the resume is counted");
        eq(GpuWorkAdaptationPolicy.DEFAULT_MAX_WORK_LEVEL, value.workLevel(), "it retries at minimum work");
        eq(0, value.failuresAtMinimum(), "with a fresh burst");
        eq(0, value.overloadedBlocks(), "and no overloaded blocks carried over");
        eq(failures, value.failureCount(), "failure accounting is kept");
        for (int good = 0; good < 600; ++good) value.onCompletedPair(++pair, 500L, 1000L, true);
        check(!value.generationDisabled(), "a lighter scene keeps generating");
        while (!value.generationDisabled() && pair < 100_000) {
            value.onFailure(GpuWorkAdaptationPolicy.Failure.PHYSICAL_DEADLINE_MISS);
            value.onCompletedPair(++pair, 500L, 1000L, true);
        }
        check(value.generationDisabled(), "overload that returns disables it again");
        eq(2, value.disableTransitionCount(), "both disables are counted");
    }

    private static void isolatedPhysicalMissesDoNotAccumulate() {
        GpuWorkAdaptationPolicy value = new GpuWorkAdaptationPolicy(0, 1200, 3, 10);
        long pair = 0;
        for (int round = 0; round < 100; ++round) {
            value.onFailure(GpuWorkAdaptationPolicy.Failure.PHYSICAL_DEADLINE_MISS);
            for (int good = 0; good < 10; ++good) value.onCompletedPair(++pair, 500L, 1000L, true);
        }
        check(!value.generationDisabled(), "rare misses spread over a long session never disable");
        eq(0, value.failuresAtMinimum(), "a failure-free window clears the burst count");
        value.onFailure(GpuWorkAdaptationPolicy.Failure.PHYSICAL_DEADLINE_MISS);
        value.onCompletedPair(++pair, 500L, 1000L, true);
        value.onFailure(GpuWorkAdaptationPolicy.Failure.PHYSICAL_DEADLINE_MISS);
        value.onFailure(GpuWorkAdaptationPolicy.Failure.PHYSICAL_DEADLINE_MISS);
        check(value.generationDisabled(), "misses within one window still disable");
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
            eq(reason == GpuWorkAdaptationPolicy.Failure.GPU_OVER_BUDGET ? 0 : 1,
                    value.failuresAtMinimum(),
                    "visible minimum failures are retained; shader time is not one");
            value.onCompletedPair(4L, 500L, 1000L, true);
            eq(0, value.restorationCount(), "one later good sample cannot spend stale credit");
        }
    }

    private static void restorationRequiresConsecutiveEvidenceAndHeadroom() {
        GpuWorkAdaptationPolicy value = new GpuWorkAdaptationPolicy(1, 1200, 30);
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
            value.onFailure(GpuWorkAdaptationPolicy.Failure.PHYSICAL_DEADLINE_MISS);
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
        for (int[] bounds : new int[][] {{-1, 4, 3, 1}, {2, 0, 3, 1}, {2, 4, 0, 1}, {2, 4, 3, 0}}) {
            boolean rejected = false;
            try { new GpuWorkAdaptationPolicy(bounds[0], bounds[1], bounds[2], bounds[3]); }
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
