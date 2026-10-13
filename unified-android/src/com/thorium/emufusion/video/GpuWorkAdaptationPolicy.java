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
    /**
     * Work levels: 1 trims the coarsest solve and refinement, 2 drops the
     * reciprocal refinement and the phase field, 3 halves the finer solve
     * levels (a GPU an engine already saturates: Cemu blocked our swaps 12.5 ms
     * p95 at level 2, 2026-10-12). Level 3 needs three consecutive blocks at
     * level 2 each with at least 5% of pairs missed, so a startup hitch alone
     * never costs motion reach.
     *
     * <p>Levels 1 and 2 used to follow the first failures: two over-budget
     * pairs a few seconds into a game (shader compiles; GPU timers also span
     * the emulator's own work) took Dolphin, PS2, PS3 and Eden sessions from
     * level 0 to 2 within 50 ms, and since physical headroom is unknown for
     * ~97% of Thor pairs nothing ever restored them, so the high-end systems
     * ran without the per-phase motion field for the whole session
     * (2026-10-12). In the product policy shader time over budget now sheds
     * those levels only after two consecutive blocks with a quarter of pairs
     * over budget; a visible miss still sheds at once, and recovery may
     * proceed on shader-time evidence while headroom is merely unknown, so a
     * startup hitch costs the per-phase field for one recovery window, not
     * the session.</p>
     */
    public static final int DEFAULT_MAX_WORK_LEVEL = 3;
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
    // Consecutive blocks each with at least 5% of pairs missed: steady misses,
    // which a single hitch (its misses inside one or two blocks) cannot give.
    private int steadyMissBlocks;
    private static final int LAST_STEP_BLOCKS = 3;
    // Lower steps on shader time alone (product policy): consecutive blocks
    // with a quarter of pairs over the shader budget.
    private static final int STEP_BLOCKS = 2;
    private int blockOverBudget;
    private int pressureBlocks;
    // Recovery window, doubled (to 8x) when work had to be shed again within
    // one window of a restoration, so a level that does not fit stops cycling.
    private int recoveryWindowPairs;
    private int pairsSinceRestoration = Integer.MAX_VALUE;
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
    private long resumes;
    private long backpressureEvents;
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
        this.recoveryWindowPairs = recoveryGoodPairs;
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
        if (pairsSinceRestoration < Integer.MAX_VALUE) ++pairsSinceRestoration;
        if (workLevel >= blockObservedLevel()) observeAtMinimum(false);
        else if (stepsNeedBlocks()) observeStep(false, false);
        // A window of failure-free pairs ends a burst; isolated misses spread
        // across a long session never add up to a disable.
        if (++pairsSinceFailure >= failureWindowPairs) clearBurst();
        if (!physicalHeadroomVerified) {
            ++physicalHeadroomUnknownPairs;
            // Unknown is not a miss: in the product policy shader-time slack
            // may still earn recovery (any failure resets it).
            if (!stepsNeedBlocks()) {
                consecutiveHealthyPairs = 0;
                return Decision.UNCHANGED;
            }
        }
        // floor(4 * budget / 5), without overflowing a long multiplication.
        long recoveryBudgetUs = shaderBudgetUs - shaderBudgetUs / 5L -
                (shaderBudgetUs % 5L == 0L ? 0L : 1L);
        if (totalGpuUs > recoveryBudgetUs) {
            ++marginalShaderPairs;
            // Timer noise: a marginal pair neither banks nor (in the product
            // policy) spends recovery evidence.
            if (!stepsNeedBlocks()) consecutiveHealthyPairs = 0;
            return Decision.UNCHANGED;
        }
        if (physicalHeadroomVerified) ++verifiedHealthyPairs;
        if (workLevel == 0) {
            consecutiveHealthyPairs = 0;
            return Decision.UNCHANGED;
        }
        if (++consecutiveHealthyPairs < recoveryWindowPairs) return Decision.UNCHANGED;
        --workLevel;
        ++restorations;
        consecutiveHealthyPairs = 0;
        pairsSinceRestoration = 0;
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
        if (workLevel < maxWorkLevel && workLevel == maxWorkLevel - 1 && lastStepNeedsBlock()) {
            // The last level costs motion reach; take it only for misses that
            // keep coming, not for a startup hitch or for shader time alone.
            boolean visible = reason != Failure.GPU_OVER_BUDGET;
            if (visible) pairsSinceFailure = 0;
            observeAtMinimum(visible);
            if (steadyMissBlocks < LAST_STEP_BLOCKS) return Decision.UNCHANGED;
        }
        if (workLevel < maxWorkLevel - 1 && stepsNeedBlocks() &&
                reason == Failure.GPU_OVER_BUDGET) {
            // Shader time alone (timers also span the emulator's work) sheds
            // a lower level only when it persists. A visible miss still sheds
            // at once: gating those too left Cemu at full work for 8 s of
            // ~25 late callbacks a second at every start (2026-10-12).
            observeStep(false, true);
            if (pressureBlocks < STEP_BLOCKS) return Decision.UNCHANGED;
        }
        if (workLevel < maxWorkLevel) return reduce();
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

    /**
     * A present that blocked for longer than a scan: the GPU is saturated and
     * an output slot was lost even though the frame itself was on time (Cemu
     * SM3DW blocked 12.5 ms p95 with few deadline misses, 2026-10-12). It
     * counts toward the last work level like a steady miss, never toward a
     * disable.
     */
    public Decision onPresentationBackpressure() {
        // A saturated GPU is never evidence of headroom to restore work.
        consecutiveHealthyPairs = 0;
        if (disabled || !lastStepNeedsBlock() || workLevel != maxWorkLevel - 1)
            return Decision.UNCHANGED;
        ++backpressureEvents;
        // Pressure keeps the burst open: after a failure-free window every
        // completed pair used to clear the blocks, so steady blocked presents
        // could never earn the last level.
        pairsSinceFailure = 0;
        observeAtMinimum(true);
        if (steadyMissBlocks < LAST_STEP_BLOCKS) return Decision.UNCHANGED;
        return reduce();
    }

    private Decision reduce() {
        ++workLevel;
        ++reductions;
        clearBurst();
        pairsSinceFailure = 0;
        if (pairsSinceRestoration < recoveryWindowPairs)
            recoveryWindowPairs = Math.min(recoveryGoodPairs * 8, recoveryWindowPairs * 2);
        pairsSinceRestoration = Integer.MAX_VALUE;
        return Decision.REDUCE_WORK;
    }

    /** Product policy: every work step needs pressure sustained over blocks. */
    private boolean stepsNeedBlocks() { return lastStepNeedsBlock(); }

    /** One observation below the last levels; a block closes as pressured or not. */
    private void observeStep(boolean visibleMiss, boolean overBudget) {
        if (visibleMiss) ++blockMisses;
        if (overBudget) ++blockOverBudget;
        if (++blockObservations < persistenceBlockPairs) return;
        boolean pressured = (long) blockMisses * 20L >= blockObservations ||
                (long) blockOverBudget * 4L >= blockObservations;
        pressureBlocks = pressured ? pressureBlocks + 1 : 0;
        blockObservations = 0;
        blockMisses = 0;
        blockOverBudget = 0;
    }

    /** The product policy's last work level must be earned by a sustained block. */
    private boolean lastStepNeedsBlock() {
        return persistenceBlocks > 0 && maxWorkLevel >= 3;
    }

    /** Lowest level at which observations fill overload blocks. */
    private int blockObservedLevel() {
        return lastStepNeedsBlock() ? maxWorkLevel - 1 : maxWorkLevel;
    }

    /** One minimum-work observation; a block closes as overloaded or not. */
    private void observeAtMinimum(boolean miss) {
        if (miss) ++blockMisses;
        if (++blockObservations < persistenceBlockPairs) return;
        overloadedBlocks = (long) blockMisses * 4L >= blockObservations ? overloadedBlocks + 1 : 0;
        steadyMissBlocks = (long) blockMisses * 20L >= blockObservations ? steadyMissBlocks + 1 : 0;
        blockObservations = 0;
        blockMisses = 0;
    }

    private void clearBurst() {
        failuresAtMinimum = 0;
        burstObservations = 0;
        blockObservations = 0;
        blockMisses = 0;
        blockOverBudget = 0;
        overloadedBlocks = 0;
        steadyMissBlocks = 0;
        pressureBlocks = 0;
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

    /**
     * Ends a disable after the owner's timed suspension: generation retries
     * at minimum work with a fresh burst. Overload that persists disables it
     * again, and the owner lengthens the next suspension. Failure accounting
     * and the work level are kept. Nothing else rearms a disabled policy.
     */
    public void resumeAfterSuspension() {
        if (!disabled) return;
        disabled = false;
        clearBurst();
        pairsSinceFailure = 0;
        consecutiveHealthyPairs = 0;
        ++resumes;
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
    public long resumeCount() { return resumes; }
    public long backpressureEventCount() { return backpressureEvents; }
    public long evidenceEpochCount() { return evidenceEpochs; }
    /** Healthy pairs the next restoration needs (doubles when a level would not hold). */
    public int recoveryWindowPairs() { return recoveryWindowPairs; }
}
