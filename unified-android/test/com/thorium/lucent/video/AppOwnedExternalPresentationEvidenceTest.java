package com.thorium.lucent.video;

public final class AppOwnedExternalPresentationEvidenceTest {
    private static final long PANEL_NS = 8_448_000L;
    private static final long LEAD_NS = 2_000_000L;

    public static void main(String[] args) {
        cleanAppOwnedRowsQualify();
        physicalSlotMissFailsClosed();
        submissionAndGpuOverrunsFailClosed();
        thorOnTimeFrameIsRejectedOnlyByGpuDuration();
        thorOnTimeRealFrameExceedsSwapBudget();
        epochAndTargetChangesResetEvidence();
        unavailableHistoryRestartsOnlyTheEvidenceWindow();
        System.out.println("AppOwnedExternalPresentationEvidenceTest PASS");
    }

    private static void cleanAppOwnedRowsQualify() {
        AppOwnedExternalPresentationEvidence evidence =
                new AppOwnedExternalPresentationEvidence();
        long desiredNs = 1_000_000_000L;
        for (int index = 0; index < 132; ++index) {
            boolean generated = (index & 1) != 0;
            FrameGenerationPresentationRequest request = request(
                    index + 1L, 7L, desiredNs, generated,
                    generated ? 0.5 : 1.0);
            evidence.record(request, index + 1L, desiredNs,
                    2, PANEL_NS, 100_000L, 500_000L,
                    request.hardCompletionDeadlineNs() - 1L,
                    generated ? 6_000_000L : 0L);
            desiredNs += 2L * PANEL_NS;
        }
        check(evidence.timingQualified(), "clean app-owned rows qualify");
        check(evidence.physicalPresents() == 132L,
                "all physical rows counted");
        check(evidence.physicalGenerated() == 66L,
                "generated rows counted");
        check(evidence.physicalEndpoints() == 66L,
                "endpoint rows counted");
        check(evidence.criticalP95Ns() == 600_000L,
                "critical p95 is exact");
        check(evidence.maxGpuWorkNs() == 6_000_000L,
                "GPU maximum is exact");
        check(evidence.identityMatches(2, PANEL_NS, 7L),
                "app-owned identity matches");
        check(evidence.firstActualPresentNs() == 1_000_000_000L &&
                        evidence.lastActualPresentNs() ==
                                1_000_000_000L + 131L * 2L * PANEL_NS,
                "physical timing endpoints bind the complete evidence epoch");
    }

    private static void physicalSlotMissFailsClosed() {
        AppOwnedExternalPresentationEvidence evidence =
                new AppOwnedExternalPresentationEvidence();
        FrameGenerationPresentationRequest request = request(
                1L, 8L, 2_000_000_000L, true, 0.5);
        evidence.record(request, 1L,
                request.desiredPhysicalPresentTimeNs() + PANEL_NS,
                2, PANEL_NS, 100_000L, 500_000L,
                request.hardCompletionDeadlineNs() - 1L, 6_000_000L);
        check(evidence.desiredSlotMisses() == 1L,
                "one-scan physical miss is rejected");
        check(evidence.lateDesiredSlotMisses() == 1L,
                "late miss direction retained");
        check(!evidence.timingQualified(),
                "physical miss cannot qualify");
    }

    private static void submissionAndGpuOverrunsFailClosed() {
        AppOwnedExternalPresentationEvidence evidence =
                new AppOwnedExternalPresentationEvidence();
        FrameGenerationPresentationRequest request = request(
                1L, 9L, 3_000_000_000L, true, 0.5);
        evidence.record(request, 1L,
                request.desiredPhysicalPresentTimeNs(),
                2, PANEL_NS, 9_000_000L, 9_000_000L,
                request.hardCompletionDeadlineNs() + 1L,
                40_000_000L);
        check(evidence.submissionDeadlineMisses() == 1L,
                "late/over-budget app submission rejected");
        check(evidence.gpuBudgetMisses() == 1L,
                "GPU work beyond its endpoint interval rejected");
    }

    private static void epochAndTargetChangesResetEvidence() {
        AppOwnedExternalPresentationEvidence evidence =
                new AppOwnedExternalPresentationEvidence();
        FrameGenerationPresentationRequest first = request(
                1L, 10L, 4_000_000_000L, true, 0.5);
        evidence.record(first, 1L, first.desiredPhysicalPresentTimeNs(),
                2, PANEL_NS, 100_000L, 500_000L,
                first.hardCompletionDeadlineNs() - 1L, 6_000_000L);
        evidence.beginEpoch(1, PANEL_NS, 11L);
        check(evidence.presentationEpoch() == 11L,
                "new epoch retained");
        check(evidence.targetScansPerOutput() == 1,
                "new divisor retained");
        check(evidence.physicalPresents() == 0L,
                "old timing rows cannot cross an epoch/target boundary");
        check(evidence.firstActualPresentNs() == 0L &&
                        evidence.lastActualPresentNs() == 0L,
                "new epoch clears both physical timing endpoints");
    }

    private static void unavailableHistoryRestartsOnlyTheEvidenceWindow() {
        AppOwnedExternalPresentationEvidence evidence =
                new AppOwnedExternalPresentationEvidence();
        FrameGenerationPresentationRequest old = request(
                1L, 12L, 5_000_000_000L, true, 0.5);
        evidence.record(old, 1L, old.desiredPhysicalPresentTimeNs(),
                1, PANEL_NS, 100_000L, 500_000L,
                old.hardCompletionDeadlineNs() - 1L, 6_000_000L);
        evidence.restartWindow(1, PANEL_NS, 12L);
        check(evidence.identityMatches(1, PANEL_NS, 12L),
                "window restart preserves scheduler identity");
        check(evidence.physicalPresents() == 0L &&
                        evidence.physicalGenerated() == 0L &&
                        evidence.submissionDeadlineMisses() == 0L &&
                        evidence.desiredSlotMisses() == 0L,
                "unavailable history discards every prior timing sample");

        long desiredNs = 6_000_000_000L;
        for (int index = 0; index < 242; ++index) {
            boolean generated = (index & 1) != 0;
            FrameGenerationPresentationRequest request = request(
                    index + 2L, 12L, desiredNs, generated,
                    generated ? 0.5 : 1.0);
            evidence.record(request, index + 2L, desiredNs,
                    1, PANEL_NS, 100_000L, 500_000L,
                    request.hardCompletionDeadlineNs() - 1L,
                    generated ? 6_000_000L : 0L);
            desiredNs += PANEL_NS;
        }
        check(evidence.timingQualified(),
                "a fresh clean window can qualify after history loss");
        check(evidence.physicalPresents() == 242L,
                "only post-restart timing rows are counted");
    }

    private static void thorOnTimeFrameIsRejectedOnlyByGpuDuration() {
        // September 16 acquire-live-jZ4R12, physical frame 131. Source span
        // reconstructed from its 60-Hz producer; other timings are captured.
        long sourceNs = 73858571540739L;
        long desiredNs = 73858716500383L;
        FrameGenerationPresentationRequest request = FrameGenerationPresentationRequest.between(
                1L, 1L, 198L, sourceNs - 8_333_334L,
                199L, sourceNs + 8_333_334L, sourceNs,
                desiredNs, desiredNs - LEAD_NS, desiredNs - LEAD_NS,
                0, 256, 240, FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM);
        AppOwnedExternalPresentationEvidence evidence = new AppOwnedExternalPresentationEvidence();
        evidence.record(request, 131L, 73858716489947L,
                1, 8_333_333L, 13_385L, 1_342_448L,
                73858689018541L, 17_288_906L);
        check(evidence.physicalGenerated() == 1L, "generated image physically presented");
        check(evidence.submissionDeadlineMisses() == 0L, "submission met deadline");
        check(evidence.desiredSlotMisses() == 0L, "physical scan met target");
        check(evidence.gpuBudgetMisses() == 1L, "GPU duration alone rejected this row");
    }

    private static void thorOnTimeRealFrameExceedsSwapBudget() {
        // Captured ready-live-3EPHe3 frame2255. Source endpoints are fixture
        // values; physical/swap timestamps and duration are the device values.
        long desiredNs = 81983212148793L;
        FrameGenerationPresentationRequest request = request(1L, 28L,
                desiredNs, false, 1.0);
        AppOwnedExternalPresentationEvidence evidence = new AppOwnedExternalPresentationEvidence();
        evidence.record(request, 2255L, 81983212152473L,
                1, 8_335_000L, 1L, 8_682_500L, 81983188886952L, 0L);
        check(evidence.submissionDeadlineMisses() == 0L,
                "early swap completion is not a missed deadline");
        check(evidence.submissionDurationOverruns() == 1L,
                "long swap retained as capacity telemetry");
        check(evidence.desiredSlotMisses() == 0L, "actual presentation met its slot");
        check(evidence.gpuBudgetMisses() == 0L, "real frame has no inference budget");
    }

    private static FrameGenerationPresentationRequest request(
            long sequence, long epoch, long desiredNs,
            boolean generated, double phase) {
        long leftNs = 10_000_000_000L + sequence * 40_000_000L;
        long rightNs = leftNs + 33_792_000L;
        long sourceNs = phase == 1.0 ? rightNs :
                leftNs + Math.round((rightNs - leftNs) * phase);
        return FrameGenerationPresentationRequest.between(
                1L, epoch, sequence, leftNs, sequence + 1L, rightNs,
                sourceNs, desiredNs, desiredNs - LEAD_NS,
                desiredNs - LEAD_NS, 0, 128, 72,
                FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM);
    }

    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
}
