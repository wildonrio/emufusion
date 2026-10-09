package com.thorium.lucent.video;

public final class GpuPhysicalHeadroomLedgerTest {
    private static final long TARGET = 1_000_000_000L;
    private static final long PERIOD = 8_333_333L;
    private static final long DEADLINE = TARGET - 2_000_000L;

    public static void main(String[] args) {
        exactOwnerAndCompleteShaderJoin();
        optionalTimestampsNeverFabricateHeadroom();
        submissionOrderBlocksSkippedEvidence();
        missedAndMarginalDeadlinesAreDistinct();
        epochsAndCapacityFailClosed();
        qualifiedRecoveryUsesFreshPairedEvidence();
        rejectedBindingPreservesDiagnosticOwner();
        System.out.println("GpuPhysicalHeadroomLedgerTest passed");
    }

    private static void exactOwnerAndCompleteShaderJoin() {
        GpuPhysicalHeadroomLedger value = create(4);
        check(bind(value, 11, 1, 5), "exact swap identity bound");
        check(value.ownsFrame(11) && !value.ownsFrame(12), "only exact EGL owner exists");
        check(physical(value, 11, 15, TARGET - 4_000_000L, TARGET - 2_000_000L),
                "physical event may precede shader result");
        check(value.takeCompleted() == null, "physical result cannot guess missing shader cost");
        check(value.recordShader(1, 1, 500, 1000), "full actual pair timing accepted");
        GpuPhysicalHeadroomLedger.Result result = value.takeCompleted();
        check(result != null && result.outcome == GpuPhysicalHeadroomLedger.Outcome.VERIFIED_HEADROOM,
                "complete owned rendering and compositor margins qualify");
        eq(11, result.frameId, "exact physical frame retained");
        eq(5, result.warpSequence, "exact warp retained");
        eq(7, result.presentationEpoch, "scheduler epoch is not relabeled");
        long offset = 10L * 2L * PERIOD; // frame 11 in this fixture's timeline
        eq(TARGET + offset, result.desiredNs, "diagnostic retains exact desired timestamp");
        eq(TARGET + offset, result.actualNs, "diagnostic retains actual physical timestamp");
        eq(DEADLINE + offset, result.deadlineNs, "diagnostic retains application deadline");
        eq(TARGET - 4_000_000L + offset, result.renderCompleteNs, "diagnostic retains driver completion");
        eq(PERIOD, result.panelPeriodNs, "diagnostic retains panel period");
        eq(TARGET - 3_000_000L + offset, result.latchNs, "exact compositor latch retained");
        eq(TARGET - 3_000_000L + offset, result.startNs, "exact composition start retained");
        eq(TARGET - 2_000_000L + offset, result.gpuFinishedNs, "exact compositor completion retained");
        eq(15, result.supportedMask, "unsupported timestamps remain distinguishable");
        eq(2_000_000L, result.appMarginNs, "margin uses actual driver completion time");
        eq(2_000_000L, result.compositorMarginNs, "compositor cost is part of critical path");
        check(!value.recordShader(1, 1, 500, 1000), "shader replay rejected");
        check(!physical(value, 11, 15, TARGET - 4_000_000L, TARGET - 2_000_000L),
                "physical replay rejected");
        check(value.takeCompleted() == null, "one result cannot recover twice");
    }

    private static void optionalTimestampsNeverFabricateHeadroom() {
        for (int mask = 0; mask < 15; ++mask) {
            GpuPhysicalHeadroomLedger value = create(2);
            bind(value, 1, 1, 1);
            value.recordShader(1, 1, 500, 1000);
            physical(value, 1, mask, TARGET - 4_000_000L, 0);
            check(value.takeCompleted().outcome == GpuPhysicalHeadroomLedger.Outcome.UNKNOWN,
                    "unsupported optional fields never qualify even with positive values");
        }
        for (int malformedMask : new int[] {-1, 31}) {
            GpuPhysicalHeadroomLedger value = create(2);
            bind(value, 1, 1, 1);
            value.recordShader(1, 1, 500, 1000);
            physical(value, 1, malformedMask, TARGET - 4_000_000L, 0);
            check(value.takeCompleted().outcome == GpuPhysicalHeadroomLedger.Outcome.UNKNOWN,
                    "malformed capability bits cannot authorize readiness");
        }
        for (long unknown : new long[] {-2L, -1L, 0L}) {
            GpuPhysicalHeadroomLedger value = create(2);
            bind(value, 1, 1, 1);
            value.recordShader(1, 1, 500, 1000);
            physical(value, 1, 15, unknown, TARGET - 2_000_000L);
            check(value.takeCompleted().outcome == GpuPhysicalHeadroomLedger.Outcome.UNKNOWN,
                    "pending/invalid/zero app-ready timestamp is never measured readiness");
        }
        GpuPhysicalHeadroomLedger display = create(2);
        bind(display, 1, 1, 1);
        display.recordShader(1, 1, 500, 1000);
        physical(display, 1, 15, TARGET - 4_000_000L, 0);
        check(display.takeCompleted().outcome == GpuPhysicalHeadroomLedger.Outcome.VERIFIED_HEADROOM,
                "supported zero compositor GPU finish explicitly means display composition");
    }

    private static void submissionOrderBlocksSkippedEvidence() {
        GpuPhysicalHeadroomLedger value = create(4);
        check(bind(value, 1, 0, 0), "endpoint continuity row is retained");
        check(bind(value, 2, 1, 1), "following generated row is retained");
        value.recordShader(1, 1, 500, 1000);
        physical(value, 2, 15, TARGET - 4_000_000L, TARGET - 2_000_000L);
        check(value.takeCompleted() == null, "a later clean midpoint cannot skip an unresolved endpoint");
        check(value.recordPhysical(1, 1, GpuPhysicalHeadroomLedger.DROPPED, 0, 2, PERIOD,
                0, -1, -1, -1, -1), "earlier endpoint drop retained");
        GpuPhysicalHeadroomLedger.Result dropped = value.takeCompleted();
        check(!dropped.generated() && dropped.outcome == GpuPhysicalHeadroomLedger.Outcome.DEADLINE_MISS,
                "endpoint failure invalidates recovery before later midpoint can be credited");
        check(value.takeCompleted().generated(), "following midpoint becomes consumable only afterward");
    }

    private static void missedAndMarginalDeadlinesAreDistinct() {
        GpuPhysicalHeadroomLedger late = create(2);
        bind(late, 1, 1, 1);
        late.recordShader(1, 1, 500, 1000);
        late.recordPhysical(1, 1, 1, TARGET + PERIOD, 2, PERIOD, 0, -1, -1, -1, -1);
        check(late.takeCompleted().outcome == GpuPhysicalHeadroomLedger.Outcome.DEADLINE_MISS,
                "known physical slot miss cannot be hidden by missing optional metrics");
        GpuPhysicalHeadroomLedger marginal = create(2);
        bind(marginal, 1, 1, 1);
        marginal.recordShader(1, 1, 500, 1000);
        physical(marginal, 1, 15, DEADLINE - 999_999L, TARGET - 1_000_000L);
        check(marginal.takeCompleted().outcome == GpuPhysicalHeadroomLedger.Outcome.MARGINAL_HEADROOM,
                "on-time rendering with insufficient slack cannot restore more expensive work");
        GpuPhysicalHeadroomLedger missed = create(2);
        bind(missed, 1, 1, 1);
        missed.recordShader(1, 1, 500, 1000);
        physical(missed, 1, 15, DEADLINE + 1L, TARGET - 1_000_000L);
        check(missed.takeCompleted().outcome == GpuPhysicalHeadroomLedger.Outcome.DEADLINE_MISS,
                "actual render completion beyond deadline is a measured miss");
        GpuPhysicalHeadroomLedger partlyKnown = create(2);
        bind(partlyKnown, 1, 1, 1);
        partlyKnown.recordShader(1, 1, 500, 1000);
        physical(partlyKnown, 1, 1, DEADLINE + 1L, -1L);
        check(partlyKnown.takeCompleted().outcome == GpuPhysicalHeadroomLedger.Outcome.DEADLINE_MISS,
                "missing compositor data cannot hide a supported app-render deadline miss");
    }

    private static void epochsAndCapacityFailClosed() {
        GpuPhysicalHeadroomLedger value = create(1);
        bind(value, 1, 1, 1);
        check(!bind(value, 2, 2, 2), "bounded queue never erases missing physical evidence");
        check(value.recordShader(1, 1, 500, 1000), "pending owner accepted");
        check(!value.recordShader(1, 2, 500, 1000), "shader ring cannot overwrite unconsumed evidence");
        value.beginEvidenceEpoch(2);
        check(!value.recordShader(1, 1, 500, 1000), "old evidence epoch rejected");
        check(!value.recordPhysical(1, 1, 1, TARGET, 2, PERIOD, 15, 1, 1, 1, 1),
                "old physical owner cannot enter new epoch");
        eq(0, value.pendingCount(), "epoch change clears only pending ownership");
    }

    private static void qualifiedRecoveryUsesFreshPairedEvidence() {
        GpuPhysicalHeadroomLedger value = create(4);
        GpuWorkAdaptationPolicy policy = new GpuWorkAdaptationPolicy(1, 4, 30);
        policy.onFailure(GpuWorkAdaptationPolicy.Failure.GPU_OVER_BUDGET);
        for (int pair = 1; pair <= 4; ++pair) {
            bind(value, pair, pair, pair);
            value.recordShader(1, pair, 500, 1000);
            physical(value, pair, 15, TARGET - 4_000_000L, TARGET - 2_000_000L);
            GpuPhysicalHeadroomLedger.Result result = value.takeCompleted();
            policy.onCompletedPair(pair, result.shaderCostUs, result.shaderBudgetUs,
                    result.outcome == GpuPhysicalHeadroomLedger.Outcome.VERIFIED_HEADROOM);
            for (int poll = 0; poll < 1200; ++poll)
                check(value.takeCompleted() == null, "poll time supplies no fabricated completion");
            eq(pair == 4 ? 1 : 0, policy.restorationCount(), "only fresh consecutive pairs restore");
        }
    }

    private static GpuPhysicalHeadroomLedger create(int capacity) {
        GpuPhysicalHeadroomLedger value = new GpuPhysicalHeadroomLedger(capacity);
        value.beginEvidenceEpoch(1);
        return value;
    }
    private static void rejectedBindingPreservesDiagnosticOwner() {
        GpuPhysicalHeadroomLedger value = create(2);
        check(bind(value, 11, 3, 5), "initial owner");
        String before = value.bindingState();
        check(before.contains("lastFrameId=11 lastPair=3 lastWarp=5"),
                "diagnostic identifies exact previous owner");
        check(before.contains("pending=1 capacity=2"), "diagnostic exposes saturation");
        check(!bind(value, 12, 3, 6), "duplicate pair rejected");
        check(before.equals(value.bindingState()), "failed bind cannot mutate ownership");
        check(bind(value, 12, 4, 6), "diagnostic does not change admission");
        value.beginEvidenceEpoch(2);
        check(value.bindingState().contains("epoch=2 lastFrameId=0 lastPair=0 lastWarp=0"),
                "diagnostic resets with actual evidence");
    }
    private static boolean bind(GpuPhysicalHeadroomLedger value, long frame, long pair, long warp) {
        long offset = (frame - 1L) * 2L * PERIOD;
        return value.bindSwap(1, 7, frame, pair, warp, TARGET + offset, DEADLINE + offset, 2, PERIOD);
    }
    private static boolean physical(GpuPhysicalHeadroomLedger value, long frame, int mask,
                                    long ready, long compositorReady) {
        long offset = (frame - 1L) * 2L * PERIOD;
        return value.recordPhysical(1, frame, 1, TARGET + offset, 2, PERIOD, mask,
                ready > 0L ? ready + offset : ready,
                TARGET - 3_000_000L + offset, TARGET - 3_000_000L + offset,
                compositorReady > 0L ? compositorReady + offset : compositorReady);
    }
    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
    private static void eq(long expected, long actual, String message) {
        if (expected != actual) throw new AssertionError(message + ": " + actual);
    }
}
