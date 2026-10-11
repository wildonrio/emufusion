package com.thorium.lucent.video;

/**
 * Session-owned GPU work degradation and recovery bookkeeping.
 *
 * <p>Shader timing is only one part of GPU load. A completed shader sample
 * cannot prove that the emulator, generation, and compositor together meet
 * their physical deadlines. Recovery also requires independent, current
 * physical headroom evidence from the caller. This class neither declares a
 * generated frame safe nor authorizes a presentation.</p>
 *
 * <p>The owner reports each completed pair once, after its full required timer
 * set and warp cost are known. A merely pending zero-duration timer poll is
 * not an observation. Missing/expired/invalid results must be reported as
 * failures and cannot be skipped while crediting later recovery samples.</p>
 *
 * <p>Only failures the viewer can see may disable generation. Shader time over
 * budget sheds work while work can still be shed, but at minimum work it is
 * not a reason to stop: GPU timer spans include the emulator's interleaved
 * rendering, and the frames they flagged on the Thor were all presented in
 * their slot (2026-10-11). Disabling also needs the failures to be recent --
 * a full limit within one failure window -- not a lifetime total that a long
 * session reaches through rare, isolated misses.</p>
 */
public final class GpuWorkAdaptationPolicy {
    public static final int DEFAULT_MAX_WORK_LEVEL = 2;
    public static final int DEFAULT_RECOVERY_GOOD_PAIRS = 1200;
    public static final int DEFAULT_FAILURES_AT_MINIMUM = 30;
    /** Completed pairs without a failure that clear the minimum-work count (~10 s at 60). */
    public static final int DEFAULT_FAILURE_WINDOW_PAIRS = 600;

    public enum Decision { UNCHANGED, REDUCE_WORK, RESTORE_WORK, DISABLE_GENERATION }
    public enum Failure {
        GPU_OVER_BUDGET, TIMER_MISSING, TIMER_DISJOINT, TIMER_INVALID,
        PHYSICAL_DEADLINE_MISS, PIPELINE_FAILURE
    }

    private final int maxWorkLevel;
    private final int recoveryGoodPairs;
    private final int failuresAtMinimumLimit;
    private final int failureWindowPairs;
    private int pairsSinceFailure;
    private final long[] failuresByReason = new long[Failure.values().length];
    private int workLevel;
    private int consecutiveHealthyPairs;
    private int failuresAtMinimum;
    private long lastPairSequence;
    private boolean disabled;
    private long completedPairObservations;
    private long verifiedHealthyPairs;
    private long physicalHeadroomUnknownPairs;
    private long marginalShaderPairs;
    private long failures;
    private long reductions;
    private long restorations;
    private long disableTransitions;
    private long evidenceEpochs;

    public GpuWorkAdaptationPolicy() {
        this(DEFAULT_MAX_WORK_LEVEL, DEFAULT_RECOVERY_GOOD_PAIRS,
                DEFAULT_FAILURES_AT_MINIMUM, DEFAULT_FAILURE_WINDOW_PAIRS);
    }

    public GpuWorkAdaptationPolicy(int maxWorkLevel, int recoveryGoodPairs,
                                   int failuresAtMinimumLimit) {
        this(maxWorkLevel, recoveryGoodPairs, failuresAtMinimumLimit,
                DEFAULT_FAILURE_WINDOW_PAIRS);
    }

    public GpuWorkAdaptationPolicy(int maxWorkLevel, int recoveryGoodPairs,
                                   int failuresAtMinimumLimit, int failureWindowPairs) {
        if (maxWorkLevel < 0 || recoveryGoodPairs < 1 || failuresAtMinimumLimit < 1 ||
                failureWindowPairs < 1)
            throw new IllegalArgumentException("invalid GPU adaptation bounds");
        this.maxWorkLevel = maxWorkLevel;
        this.recoveryGoodPairs = recoveryGoodPairs;
        this.failuresAtMinimumLimit = failuresAtMinimumLimit;
        this.failureWindowPairs = failureWindowPairs;
    }

    /**
     * Records a fresh, fully measured pair and its accounted visible warp cost.
     * Sequence numbers must increase within an evidence epoch. The combined
     * cost must be computed with overflow-safe arithmetic by the caller.
     *
     * <p>Recovery needs both current physical headroom proof and at least 20%
     * spare shader budget for the whole uninterrupted recovery window. A pair
     * merely inside the hard budget can keep running but cannot restore more
     * expensive work. Unknown physical headroom clears recovery without being
     * mislabeled as a measured shader overload.</p>
     */
    public Decision onCompletedPair(long pairSequence, long totalGpuUs,
                                     long shaderBudgetUs,
                                     boolean physicalHeadroomVerified) {
        ++completedPairObservations;
        if (pairSequence <= 0L || pairSequence <= lastPairSequence)
            return onFailure(Failure.TIMER_INVALID);
        lastPairSequence = pairSequence;
        if (shaderBudgetUs <= 0L) return onFailure(Failure.TIMER_INVALID);
        if (totalGpuUs <= 0L) return onFailure(Failure.TIMER_MISSING);
        if (totalGpuUs > shaderBudgetUs) return onFailure(Failure.GPU_OVER_BUDGET);
        if (disabled) return Decision.DISABLE_GENERATION;
        // A window of failure-free pairs ends a burst; isolated misses spread
        // across a long session never add up to a disable.
        if (++pairsSinceFailure >= failureWindowPairs) failuresAtMinimum = 0;
        if (!physicalHeadroomVerified) {
            ++physicalHeadroomUnknownPairs;
            consecutiveHealthyPairs = 0;
            return Decision.UNCHANGED;
        }
        // floor(4 * budget / 5), without overflowing a long multiplication.
        long recoveryBudgetUs = shaderBudgetUs - shaderBudgetUs / 5L -
                (shaderBudgetUs % 5L == 0L ? 0L : 1L);
        if (totalGpuUs > recoveryBudgetUs) {
            ++marginalShaderPairs;
            consecutiveHealthyPairs = 0;
            return Decision.UNCHANGED;
        }
        ++verifiedHealthyPairs;
        if (workLevel == 0) {
            consecutiveHealthyPairs = 0;
            return Decision.UNCHANGED;
        }
        if (++consecutiveHealthyPairs < recoveryGoodPairs) return Decision.UNCHANGED;
        --workLevel;
        ++restorations;
        consecutiveHealthyPairs = 0;
        failuresAtMinimum = 0;
        return Decision.RESTORE_WORK;
    }

    /**
     * Invalidates recovery for every failed observation, even at minimum work.
     * Failures at minimum accumulate until a complete healthy recovery window
     * earns a quality restoration. Interleaving one good or unknown sample
     * therefore cannot keep a chronically overloaded session generating.
     */
    public Decision onFailure(Failure reason) {
        if (reason == null) reason = Failure.TIMER_INVALID;
        ++failures;
        ++failuresByReason[reason.ordinal()];
        consecutiveHealthyPairs = 0;
        if (disabled) return Decision.DISABLE_GENERATION;
        if (workLevel < maxWorkLevel) {
            ++workLevel;
            ++reductions;
            failuresAtMinimum = 0;
            pairsSinceFailure = 0;
            return Decision.REDUCE_WORK;
        }
        // Nothing left to shed, and over-budget shader time is not a visible
        // failure: keep generating and let physical misses decide.
        if (reason == Failure.GPU_OVER_BUDGET) return Decision.UNCHANGED;
        pairsSinceFailure = 0;
        if (++failuresAtMinimum < failuresAtMinimumLimit) return Decision.UNCHANGED;
        disabled = true;
        ++disableTransitions;
        return Decision.DISABLE_GENERATION;
    }

    /**
     * New stream/timer ownership invalidates consecutive evidence, not session
     * failure accounting. Recreating a timer must not erase overload or undo a
     * disable decision. Only a genuinely new session creates a fresh policy.
     */
    public void beginEvidenceEpoch() {
        ++evidenceEpochs;
        lastPairSequence = 0L;
        consecutiveHealthyPairs = 0;
    }

    /** Invalid evidence cannot retain recovery credit even when its failure was already counted. */
    public void invalidateRecoveryEvidence() { consecutiveHealthyPairs = 0; }

    public int workLevel() { return workLevel; }
    public int consecutiveHealthyPairs() { return consecutiveHealthyPairs; }
    public int failuresAtMinimum() { return failuresAtMinimum; }
    public boolean generationDisabled() { return disabled; }
    public long completedPairObservations() { return completedPairObservations; }
    public long verifiedHealthyPairs() { return verifiedHealthyPairs; }
    public long physicalHeadroomUnknownPairs() { return physicalHeadroomUnknownPairs; }
    public long marginalShaderPairs() { return marginalShaderPairs; }
    public long failureCount() { return failures; }
    public long failureCount(Failure reason) {
        return failuresByReason[(reason == null ? Failure.TIMER_INVALID : reason).ordinal()];
    }
    public long reductionCount() { return reductions; }
    public long restorationCount() { return restorations; }
    public long disableTransitionCount() { return disableTransitions; }
    public long evidenceEpochCount() { return evidenceEpochs; }
}
