package com.thorium.lucent.video;

public final class ExternalPresentationEvidenceTest {
    private static final long PANEL_NS = 8_448_000L;
    private static final long LEAD_NS = 2_000_000L;

    public static void main(String[] args) {
        cleanPhysicalRowsQualifyAfterGeneratedHistory();
        combinedDeadlineMissRejects();
        wrongDesiredPhysicalSlotRejects();
        earliestAndEarlyPresentViolationsReject();
        presentMarginDistributionAndLateCorrelationAreExact();
        generatedPhaseAndEndpointSpanRemainExact();
        explicitOneScanPresentationPipelineQualifiesExactPhysicalContent();
        targetChangeStartsFreshTimingEvidence();
        presentationEpochChangeStartsFreshTimingEvidence();
        System.out.println("ExternalPresentationEvidenceTest passed");
    }

    private static void cleanPhysicalRowsQualifyAfterGeneratedHistory() {
        ExternalPresentationLedger ledger = new ExternalPresentationLedger();
        ExternalPresentationEvidence evidence = new ExternalPresentationEvidence();
        long scanNs = 1_000_000_000L;
        long sourceNs = 10_000_000_000L;
        for (int index = 0; index < 132; ++index) {
            long left = index + 1L;
            long leftNs = sourceNs + index * 33_792_000L;
            long rightNs = leftNs + 33_792_000L;
            long contentNs = index % 2 == 0 ? leftNs + 16_896_000L : rightNs;
            FrameGenerationPresentationRequest request =
                    FrameGenerationPresentationRequest.between(
                            1L, 11L, left, leftNs, left + 1L, rightNs,
                            contentNs, scanNs, scanNs - LEAD_NS,
                            scanNs - LEAD_NS, 0, 128, 72,
                            FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM);
            ledger.submit(request, 2);
            evidence.record(ledger.physicallyPresented(
                    request, index + 1L, scanNs - LEAD_NS, scanNs,
                    scanNs, 100_000L, PANEL_NS,
                    1_500_000L, 5_500_000L), LEAD_NS);
            scanNs += 2L * PANEL_NS;
        }
        check(evidence.timingQualified(), "clean generated history qualifies");
        check(evidence.physicalPresents() == 132L, "all physical rows counted");
        check(evidence.physicalGenerated() == 66L, "generated physical rows counted");
        check(evidence.physicalEndpoints() == 66L, "endpoint physical rows counted");
        check(evidence.deadlineMisses() == 0L, "clean deadline history");
        check(evidence.desiredSlotMisses() == 0L, "clean desired slots");
        check(evidence.combinedP95Ns() == 7_000_000L, "exact combined p95");
        check(evidence.firstActualPresentNs() == 1_000_000_000L &&
                        evidence.lastActualPresentNs() ==
                                1_000_000_000L + 131L * 2L * PANEL_NS,
                "physical timing endpoints bind the complete evidence epoch");
    }

    private static void combinedDeadlineMissRejects() {
        ExternalPresentationEvidence evidence = new ExternalPresentationEvidence();
        evidence.record(commit(1, 1_000_000_000L, 2,
                8_000_000L, 7_000_000L, 0L), LEAD_NS);
        check(evidence.deadlineMisses() == 1L,
                "record plus GPU work beyond early cutoff is a miss");
        check(!evidence.timingQualified(), "deadline miss never qualifies");
    }

    private static void wrongDesiredPhysicalSlotRejects() {
        ExternalPresentationEvidence evidence = new ExternalPresentationEvidence();
        evidence.record(commit(1, 1_000_000_000L, 2,
                1_000_000L, 5_000_000L, 1_000_000L), LEAD_NS);
        check(evidence.desiredSlotMisses() == 1L,
                "scanout one millisecond off its exact slot rejects");
        check(evidence.maxDesiredSlotErrorNs() == 1_000_000L,
                "slot error retained exactly");
        check(evidence.lateDesiredSlotMisses() == 1L &&
                        evidence.earlyDesiredSlotMisses() == 0L,
                "late desired-slot miss is classified exactly");
        check(evidence.minLateSlotPresentMarginNs() == 100_000L &&
                        evidence.maxLateSlotPresentMarginNs() == 100_000L,
                "late desired-slot miss retains its processing margin");
        check(evidence.minSignedDesiredSlotErrorNs() == 1_000_000L &&
                        evidence.maxSignedDesiredSlotErrorNs() == 1_000_000L &&
                        evidence.lastSignedDesiredSlotErrorNs() == 1_000_000L,
                "late physical slot error retains its sign");
        ExternalPresentationEvidence early = new ExternalPresentationEvidence();
        early.record(commit(1, 1_000_000_000L, 2,
                1_000_000L, 5_000_000L, -1_000_000L), LEAD_NS);
        check(early.minSignedDesiredSlotErrorNs() == -1_000_000L &&
                        early.maxSignedDesiredSlotErrorNs() == -1_000_000L &&
                        early.lastSignedDesiredSlotErrorNs() == -1_000_000L,
                "early physical slot error retains its sign");
        check(early.earlyDesiredSlotMisses() == 1L &&
                        early.lateDesiredSlotMisses() == 0L,
                "early desired-slot miss is classified exactly");
        check(early.minLateSlotPresentMarginNs() == 0L &&
                        early.maxLateSlotPresentMarginNs() == 0L,
                "no late miss reports no correlated margin");
    }

    private static void presentMarginDistributionAndLateCorrelationAreExact() {
        ExternalPresentationLedger ledger = new ExternalPresentationLedger();
        ExternalPresentationEvidence evidence = new ExternalPresentationEvidence();
        long[] margins = {100L, 500L, 300L, 200L, 400L};
        long actualNs = 2_500_000_000L;
        for (int index = 0; index < margins.length; ++index) {
            long left = index + 1L;
            long leftNs = 30_000_000_000L + index * 33_792_000L;
            long targetNs = actualNs + index * 2L * PANEL_NS;
            long driverNs = targetNs - LEAD_NS;
            FrameGenerationPresentationRequest request =
                    FrameGenerationPresentationRequest.between(
                            1L, 31L, left, leftNs, left + 1L,
                            leftNs + 33_792_000L, leftNs + 16_896_000L,
                            targetNs, driverNs, driverNs, 0, 128, 72,
                            FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM);
            ledger.submit(request, 2);
            evidence.record(ledger.physicallyPresented(
                    request, index + 1L, driverNs, targetNs, targetNs,
                    margins[index], PANEL_NS, 1_000_000L, 5_000_000L),
                    LEAD_NS);
        }
        check(evidence.minPresentMarginNs() == 100L,
                "minimum present margin retained");
        check(evidence.presentMarginP05Ns() == 100L,
                "rolling present-margin p05 is exact");
        check(evidence.presentMarginP50Ns() == 300L,
                "rolling present-margin median is exact");
        check(evidence.presentMarginP95Ns() == 500L,
                "rolling present-margin p95 is exact");
        check(evidence.maxPresentMarginNs() == 500L,
                "maximum present margin retained");
        check(evidence.lastPresentMarginNs() == 400L,
                "last present margin retained");
    }

    private static void generatedPhaseAndEndpointSpanRemainExact() {
        ExternalPresentationEvidence evidence = new ExternalPresentationEvidence();
        evidence.record(commit(7, 2_000_000_000L, 2,
                1_000_000L, 5_000_000L, 0L), LEAD_NS);
        near(0.5, evidence.minGeneratedPhase(), 0.000001,
                "minimum generated phase");
        near(0.5, evidence.maxGeneratedPhase(), 0.000001,
                "maximum generated phase");
        check(evidence.maxEndpointSpanNs() == 33_792_000L,
                "endpoint span retained");
    }

    private static void explicitOneScanPresentationPipelineQualifiesExactPhysicalContent() {
        long contentNs = 2_250_000_000L;
        long driverNs = contentNs - PANEL_NS - LEAD_NS;
        long leftNs = 20_000_000_000L;
        FrameGenerationPresentationRequest request =
                FrameGenerationPresentationRequest.between(
                        1L, 11L, 1L, leftNs, 2L,
                        leftNs + 33_792_000L, leftNs + 16_896_000L,
                        contentNs, driverNs, driverNs,
                        1, 128, 72,
                        FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM);
        ExternalPresentationLedger ledger = new ExternalPresentationLedger();
        ledger.submit(request, 2);
        ExternalPresentationEvidence evidence = new ExternalPresentationEvidence();
        evidence.record(ledger.physicallyPresented(
                request, 1L, driverNs, contentNs, contentNs,
                100_000L, PANEL_NS, 1_000_000L, 5_000_000L), LEAD_NS);
        check(evidence.desiredSlotMisses() == 0L,
                "one-scan pipeline still binds exact physical content");
        check(evidence.earlyPresentViolations() == 0L,
                "one-scan pipeline preserves its earlier driver slot");

        // VkPastPresentationTimingGOOGLE reports the display's measured
        // refresh duration, which can differ by a few microseconds from the
        // calibrated period used when the immutable request was planned.
        // That physical measurement jitter must not invalidate an otherwise
        // exact one-scan request identity.
        FrameGenerationPresentationRequest jittered =
                FrameGenerationPresentationRequest.between(
                        1L, 12L, 3L, leftNs + 67_584_000L, 4L,
                        leftNs + 101_376_000L, leftNs + 84_480_000L,
                        contentNs + 2L * PANEL_NS,
                        driverNs + 2L * PANEL_NS,
                        driverNs + 2L * PANEL_NS,
                        1, 128, 72,
                        FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM);
        ExternalPresentationLedger jitteredLedger =
                new ExternalPresentationLedger();
        jitteredLedger.submit(jittered, 2);
        ExternalPresentationEvidence jitteredEvidence =
                new ExternalPresentationEvidence();
        jitteredEvidence.record(jitteredLedger.physicallyPresented(
                jittered, 1L, jittered.driverDesiredPresentTimeNs(),
                jittered.desiredPhysicalPresentTimeNs(),
                jittered.desiredPhysicalPresentTimeNs(),
                100_000L, PANEL_NS + 2_500L,
                1_000_000L, 5_000_000L), LEAD_NS);
        check(jitteredEvidence.desiredSlotMisses() == 0L,
                "measured refresh jitter preserves the planned pipeline");

        long wrongDriverNs = contentNs - LEAD_NS;
        FrameGenerationPresentationRequest wrong =
                FrameGenerationPresentationRequest.between(
                        1L, 12L, 3L, leftNs + 67_584_000L, 4L,
                        leftNs + 101_376_000L, leftNs + 84_480_000L,
                        contentNs + 2L * PANEL_NS,
                        wrongDriverNs + 2L * PANEL_NS,
                        wrongDriverNs + 2L * PANEL_NS,
                        1, 128, 72,
                        FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM);
        ExternalPresentationLedger wrongLedger = new ExternalPresentationLedger();
        wrongLedger.submit(wrong, 2);
        ExternalPresentationLedger.Commit wrongRow =
                wrongLedger.physicallyPresented(
                        wrong, 1L, wrong.driverDesiredPresentTimeNs(),
                        wrong.desiredPhysicalPresentTimeNs(),
                        wrong.desiredPhysicalPresentTimeNs(),
                        100_000L, PANEL_NS, 1_000_000L, 5_000_000L);
        try {
            new ExternalPresentationEvidence().record(wrongRow, LEAD_NS);
            throw new AssertionError(
                    "pipeline request without its panel-scan lead was accepted");
        } catch (IllegalStateException expected) {
            // Exact contract mismatch is fail-closed.
        }
    }

    private static void earliestAndEarlyPresentViolationsReject() {
        ExternalPresentationEvidence wrongEarliest =
                new ExternalPresentationEvidence();
        ExternalPresentationLedger.Commit row = commit(
                1, 1_500_000_000L, 2,
                1_000_000L, 5_000_000L, 0L);
        FrameGenerationPresentationRequest request = row.request;
        ExternalPresentationLedger ledger = new ExternalPresentationLedger();
        ledger.submit(request, 2);
        wrongEarliest.record(ledger.physicallyPresented(
                request, 1L, request.driverDesiredPresentTimeNs(),
                1_500_000_000L, 1_500_100_000L,
                100_000L, PANEL_NS, 1_000_000L, 5_000_000L), LEAD_NS);
        check(wrongEarliest.earliestPresentMisses() == 1L,
                "actual scanout before the earliest possible time rejects");

        ExternalPresentationEvidence legitimatelyLater =
                new ExternalPresentationEvidence();
        ExternalPresentationLedger laterLedger = new ExternalPresentationLedger();
        laterLedger.submit(request, 2);
        legitimatelyLater.record(laterLedger.physicallyPresented(
                request, 1L, request.driverDesiredPresentTimeNs(),
                1_500_000_000L, 1_499_900_000L,
                100_000L, PANEL_NS, 1_000_000L, 5_000_000L), LEAD_NS);
        check(legitimatelyLater.earliestPresentMisses() == 0L,
                "actual scanout may legitimately follow earliest-present time");

        ExternalPresentationEvidence tooEarly =
                new ExternalPresentationEvidence();
        long physicalScanNs = 2_000_000_000L;
        long driverBoundNs = physicalScanNs - LEAD_NS;
        long leftNs = 20_000_000_000L;
        FrameGenerationPresentationRequest earlyRequest =
                FrameGenerationPresentationRequest.between(
                        1L, 11L, 1L, leftNs, 2L,
                        leftNs + 33_792_000L, leftNs + 16_896_000L,
                        physicalScanNs, driverBoundNs, driverBoundNs,
                        0, 128, 72,
                        FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM);
        ExternalPresentationLedger earlyLedger = new ExternalPresentationLedger();
        earlyLedger.submit(earlyRequest, 2);
        long illegalActualNs = driverBoundNs - 1L;
        tooEarly.record(earlyLedger.physicallyPresented(
                earlyRequest, 1L, driverBoundNs,
                illegalActualNs, illegalActualNs,
                100_000L, PANEL_NS, 1_000_000L, 5_000_000L), LEAD_NS);
        check(tooEarly.earlyPresentViolations() == 1L,
                "scanout before earliest-present bound rejects");
    }

    private static void targetChangeStartsFreshTimingEvidence() {
        ExternalPresentationEvidence evidence = new ExternalPresentationEvidence();
        evidence.record(commit(1, 3_000_000_000L, 2,
                1_000_000L, 5_000_000L, 0L), LEAD_NS);
        check(evidence.physicalPresents() == 1L, "first target sample");
        evidence.record(commit(2, 3_008_448_000L, 1,
                500_000L, 3_000_000L, 0L), LEAD_NS);
        check(evidence.physicalPresents() == 1L,
                "new exact divisor starts fresh evidence");
        check(evidence.targetScansPerOutput() == 1,
                "new divisor identity retained");
        check(!evidence.timingQualified(),
                "old target cannot lend qualification to new target");
        check(evidence.firstActualPresentNs() == 3_008_448_000L &&
                        evidence.lastActualPresentNs() == 3_008_448_000L,
                "new target retains only its own timing endpoint");
    }

    private static void presentationEpochChangeStartsFreshTimingEvidence() {
        ExternalPresentationEvidence evidence = new ExternalPresentationEvidence();
        evidence.record(commit(1, 4_000_000_000L, 2,
                1_000_000L, 5_000_000L, 0L, 20L), LEAD_NS);
        evidence.record(commit(2, 4_016_896_000L, 2,
                1_000_000L, 5_000_000L, 0L, 21L), LEAD_NS);
        check(evidence.physicalPresents() == 1L,
                "new presentation epoch starts fresh evidence");
        check(evidence.presentationEpoch() == 21L,
                "current evidence epoch retained");
        check(evidence.identityMatches(2, PANEL_NS, 21L, 0),
                "exact target and epoch identity matches");
        check(!evidence.identityMatches(2, PANEL_NS, 20L, 0),
                "old epoch cannot inherit evidence");
        check(!evidence.identityMatches(2, PANEL_NS, 21L, 1),
                "another presentation-pipeline identity cannot inherit evidence");
    }

    private static ExternalPresentationLedger.Commit commit(
            long left, long actualNs, int scans, long enqueueNs, long gpuNs,
            long actualOffsetNs) {
        return commit(left, actualNs, scans, enqueueNs, gpuNs,
                actualOffsetNs, 11L);
    }

    private static ExternalPresentationLedger.Commit commit(
            long left, long actualNs, int scans, long enqueueNs, long gpuNs,
            long actualOffsetNs, long presentationEpoch) {
        long leftNs = 10_000_000_000L + left * 40_000_000L;
        long rightNs = leftNs + 33_792_000L;
        long physicalScanNs = actualNs;
        long driverBoundNs = physicalScanNs - LEAD_NS;
        FrameGenerationPresentationRequest request =
                FrameGenerationPresentationRequest.between(
                        1L, presentationEpoch, left, leftNs, left + 1L,
                        rightNs, leftNs + 16_896_000L,
                        physicalScanNs, driverBoundNs, driverBoundNs,
                        0, 128, 72,
                        FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM);
        ExternalPresentationLedger ledger = new ExternalPresentationLedger();
        ledger.submit(request, scans);
        long presentedNs = actualNs + actualOffsetNs;
        return ledger.physicallyPresented(request, 1L, driverBoundNs,
                presentedNs, presentedNs,
                100_000L, PANEL_NS, enqueueNs, gpuNs);
    }

    private static void near(double expected, double actual, double tolerance,
                             String message) {
        if (Math.abs(expected - actual) > tolerance)
            throw new AssertionError(message + " expected=" + expected +
                    " actual=" + actual);
    }

    private static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }
}
