package com.thorium.emufusion.video;

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
 * session reaches through rare, isolated misses. In the product policy the
 * misses must also persist: a burst has to span a few seconds of pairs with
 * at least a quarter of them missed. One emulator hitch (a shader compile, a
 * 0.35 s stall) misses thirty frames in a fifth of a second and used to end
 * generation for the whole session (GameCube, 2026-10-11).</p>
 *
 * <p>The product policy also needs the overload to be sustained, not just dense
 * on average since the burst began: several consecutive blocks of minimum-work
 * pairs must each miss at least a quarter of their frames. A screenshot taken
 * while a GPU-heavy engine runs makes the compositor late for two or three
 * seconds; with a couple of stray misses earlier in the burst that was enough
 * to end generation for the session (Wind Waker HD on Cemu, 2026-10-12: no
 * more than 9 misses in 10 s of 30->60, then 54 in the 3 s of two screenshots).</p>
 */
public final class GpuWorkAdaptationPolicy {
    public static final int DEFAULT_MAX_WORK_LEVEL = 2;
    public static final int DEFAULT_RECOVERY_GOOD_PAIRS = 1200;
    public static final int DEFAULT_FAILURES_AT_MINIMUM = 30;
    /** Completed pairs without a failure that clear the minimum-work count (~10 s at 60). */
    public static final int DEFAULT_FAILURE_WINDOW_PAIRS = 600;
    /** Observations a minimum-work burst must span before it can disable (~3 s at 60). */
    public static final int DEFAULT_MIN_DISABLE_SPAN_PAIRS = 180;
    /** Minimum-work observations per overload-persistence block (1 s at 60 pairs/s). */
    public static final int DEFAULT_PERSISTENCE_BLOCK_PAIRS = 60;
    /** Consecutive blocks with a quarter of their pairs missed before a disable. */
    public static final int DEFAULT_PERSISTENCE_BLOCKS = 4;

    public enum Decision { UNCHANGED, REDUCE_WORK, RESTORE_WORK, DISABLE_GENERATION }
    public enum Failure {
        GPU_OVER_BUDGET, TIMER_MISSING, TIMER_DISJOINT, TIMER_INVALID,
        PHYSICAL_DEADLINE_MISS, PIPELINE_FAILURE
    }

    private final int maxWorkLevel;
    private final int recoveryGoodPairs;
    private final int failuresAtMinimumLimit;
    private final int failureWindowPairs;
    private final int minDisableSpanPairs;
    private final int persistenceBlockPairs;
    private final int persistenceBlocks;
    private int blockObservations;
    private int blockMisses;
    private int overloadedBlocks;
    private int pairsSinceFailure;
    // Observations (completed or failed) since the current burst's first failure.
    private int burstObservations;
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
                DEFAULT_FAILURES_AT_MINIMUM, DEFAULT_FAILURE_WINDOW_PAIRS,
                DEFAULT_MIN_DISABLE_SPAN_PAIRS, DEFAULT_PERSISTENCE_BLOCK_PAIRS,
                DEFAULT_PERSISTENCE_BLOCKS);
    }

    public GpuWorkAdaptationPolicy(int maxWorkLevel, int recoveryGoodPairs,
                                   int failuresAtMinimumLimit) {
        this(maxWorkLevel, recoveryGoodPairs, failuresAtMinimumLimit,
                DEFAULT_FAILURE_WINDOW_PAIRS);
    }

    public GpuWorkAdaptationPolicy(int maxWorkLevel, int recoveryGoodPairs,
                                   int failuresAtMinimumLimit, int failureWindowPairs) {
        this(maxWorkLevel, recoveryGoodPairs, failuresAtMinimumLimit, failureWindowPairs, 1);
    }

    public GpuWorkAdaptationPolicy(int maxWorkLevel, int recoveryGoodPairs,
                                   int failuresAtMinimumLimit, int failureWindowPairs,
                                   int minDisableSpanPairs) {
        this(maxWorkLevel, recoveryGoodPairs, failuresAtMinimumLimit, failureWindowPairs,
                minDisableSpanPairs, 1, 0);
    }

    /** persistenceBlocks 0 leaves out the sustained-overload requirement. */
    public GpuWorkAdaptationPolicy(int maxWorkLevel, int recoveryGoodPairs,
                                   int failuresAtMinimumLimit, int failureWindowPairs,
                                   int minDisableSpanPairs, int persistenceBlockPairs,
                                   int persistenceBlocks) {
        if (maxWorkLevel < 0 || recoveryGoodPairs < 1 || failuresAtMinimumLimit < 1 ||
                failureWindowPairs < 1 || minDisableSpanPairs < 1 ||
                persistenceBlockPairs < 1 || persistenceBlocks < 0)
            throw new IllegalArgumentException("invalid GPU adaptation bounds");
        this.maxWorkLevel = maxWorkLevel;
        this.recoveryGoodPairs = recoveryGoodPairs;
        this.failuresAtMinimumLimit = failuresAtMinimumLimit;
        this.failureWindowPairs = failureWindowPairs;
        this.minDisableSpanPairs = minDisableSpanPairs;
        this.persistenceBlockPairs = persistenceBlockPairs;
        this.persistenceBlocks = persistenceBlocks;
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
        if (failuresAtMinimum > 0) ++burstObservations;
        if (workLevel == maxWorkLevel) observeAtMinimum(false);
        // A window of failure-free pairs ends a burst; isolated misses spread
        // across a long session never add up to a disable.
        if (++pairsSinceFailure >= failureWindowPairs) clearBurst();
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
        clearBurst();
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
            clearBurst();
            pairsSinceFailure = 0;
            return Decision.REDUCE_WORK;
        }
        // Nothing left to shed, and over-budget shader time is not a visible
        // failure: keep generating and let physical misses decide.
        if (reason == Failure.GPU_OVER_BUDGET) {
            if (failuresAtMinimum > 0) ++burstObservations;
            observeAtMinimum(false);
            return Decision.UNCHANGED;
        }
        pairsSinceFailure = 0;
        ++failuresAtMinimum;
        ++burstObservations;
        observeAtMinimum(true);
        if (failuresAtMinimum < failuresAtMinimumLimit ||
                burstObservations < minDisableSpanPairs ||
                (long) failuresAtMinimum * 4L < burstObservations ||
                overloadedBlocks < persistenceBlocks)
            return Decision.UNCHANGED;
        disabled = true;
        ++disableTransitions;
        return Decision.DISABLE_GENERATION;
    }

    /** One minimum-work observation; a block closes as overloaded or not. */
    private void observeAtMinimum(boolean miss) {
        if (miss) ++blockMisses;
        if (++blockObservations < persistenceBlockPairs) return;
        overloadedBlocks = (long) blockMisses * 4L >= blockObservations ? overloadedBlocks + 1 : 0;
        blockObservations = 0;
        blockMisses = 0;
    }

    private void clearBurst() {
        failuresAtMinimum = 0;
        burstObservations = 0;
        blockObservations = 0;
        blockMisses = 0;
        overloadedBlocks = 0;
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
    /** Consecutive closed minimum-work blocks that missed a quarter of their pairs. */
    public int overloadedBlocks() { return overloadedBlocks; }
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
