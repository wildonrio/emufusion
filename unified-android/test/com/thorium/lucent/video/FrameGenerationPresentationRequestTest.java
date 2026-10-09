package com.thorium.lucent.video;

public final class FrameGenerationPresentationRequestTest {
    private static void eglQueueDeadlineSurvivesRequestConstruction() {
        PhysicalPresentationDeadline deadline = PhysicalPresentationDeadline.nextEgl(
                191101134694229L, 8337285L, 10337285L, 191101129350067L, 0L, 1000000L);
        FrameGenerationPresentationRequest endpoint = FrameGenerationPresentationRequest.endpoint(
                1, 1, 10, 1000000000L, deadline.contentPresentationTimeNs(),
                deadline.driverDesiredPresentTimeNs(), deadline.hardCompletionDeadlineNs(),
                0, 256, 192, FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM);
        FrameGenerationPresentationRequest midpoint = FrameGenerationPresentationRequest.between(
                1, 1, 10, 1000000000L, 11, 1016666666L, 1008333333L,
                deadline.contentPresentationTimeNs(), deadline.driverDesiredPresentTimeNs(),
                deadline.hardCompletionDeadlineNs(), 0, 256, 192,
                FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM);
        equal(deadline.hardCompletionDeadlineNs(), endpoint.hardCompletionDeadlineNs(), "EGL endpoint queue cutoff");
        equal(deadline.hardCompletionDeadlineNs(), midpoint.hardCompletionDeadlineNs(), "EGL midpoint queue cutoff");
        require(midpoint.phase() == 0.5, "EGL queue timing cannot change midpoint");
    }
    public static void main(String[] args) {
        eglQueueDeadlineSurvivesRequestConstruction();
        exactInteriorPhaseUsesEndpointTimestamps();
        boundariesAreEndpointsNotGeneratedFrames();
        standaloneEndpointNeedsNoFabricatedRightImage();
        preparationIdentityExcludesOnlyPhysicalDeadline();
        preparationCanPrecedeWsiDeadline();
        immediateNextPhysicalScanReleasesAfterObservedPredecessor();
        modeAlignedRequestReleasesAfterItsPredecessorTarget();
        rejectsExtrapolationAndDiscontinuity();
        predecessorFrameTimelineIsImmutableAndScanBound();
        targetFrameTimelineIsImmutableAndScanBound();
        System.out.println("FrameGenerationPresentationRequestTest passed");
    }

    private static void
            immediateNextPhysicalScanReleasesAfterObservedPredecessor() {
        long priorActualNs = 1_000_072_000L;
        long panelPeriodNs = 16_666_667L;
        long nextTargetNs = 1_016_666_667L;
        FrameGenerationPresentationRequest nextScan =
                FrameGenerationPresentationRequest.endpoint(
                        3L, 4L, 9L, 800_000_000L,
                        nextTargetNs, nextTargetNs - 2_000_000L,
                        nextTargetNs - 2_000_000L, 0, 64, 64,
                        FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM);
        FrameGenerationPresentationRequest released = nextScan.
                withReleaseAfterImmediatePriorPhysicalScan(
                        priorActualNs, panelPeriodNs);
        require(released.immediatePriorPhysicalScanRelease(),
                "next-scan request carries explicit release authority");
        equal(priorActualNs + 1L, released.queueReleaseNotBeforeNs(),
                "next scan releases only after observed predecessor");
        equal(nextScan.desiredPhysicalPresentTimeNs(),
                released.desiredPhysicalPresentTimeNs(),
                "release correction preserves physical target");
        equal(nextScan.hardCompletionDeadlineNs(),
                released.hardCompletionDeadlineNs(),
                "release correction preserves hard deadline");

        long laterTargetNs = nextTargetNs + panelPeriodNs;
        FrameGenerationPresentationRequest laterScan =
                FrameGenerationPresentationRequest.endpoint(
                        3L, 4L, 10L, 833_333_333L,
                        laterTargetNs, laterTargetNs - 2_000_000L,
                        laterTargetNs - 2_000_000L, 0, 64, 64,
                        FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM);
        FrameGenerationPresentationRequest unchanged = laterScan.
                withReleaseAfterImmediatePriorPhysicalScan(
                        priorActualNs, panelPeriodNs);
        require(!unchanged.immediatePriorPhysicalScanRelease(),
                "multi-scan target cannot claim predecessor authority");
        equal(laterScan.queueReleaseNotBeforeNs(),
                unchanged.queueReleaseNotBeforeNs(),
                "multi-scan target retains guarded release window");
    }

    private static void
            modeAlignedRequestReleasesAfterItsPredecessorTarget() {
        long panelPeriodNs = 16_666_667L;
        long targetNs = 2_050_000_001L;
        FrameGenerationPresentationRequest request =
                FrameGenerationPresentationRequest.endpoint(
                        3L, 4L, 11L, 900_000_000L,
                        targetNs, targetNs - 2_000_000L,
                        targetNs - 2_000_000L, 0, 64, 64,
                        FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM);
        FrameGenerationPresentationRequest released = request.
                withReleaseAfterModeAlignedPredecessorScan(panelPeriodNs);
        require(released.immediatePriorPhysicalScanRelease(),
                "mode-aligned request carries explicit predecessor release");
        equal(targetNs - panelPeriodNs + 1L,
                released.queueReleaseNotBeforeNs(),
                "mode-aligned request opens only after predecessor target");
        equal(targetNs, released.desiredPhysicalPresentTimeNs(),
                "mode-aligned release preserves exact physical target");
        equal(request.hardCompletionDeadlineNs(),
                released.hardCompletionDeadlineNs(),
                "mode-aligned release preserves hard cutoff");
    }

    private static void exactInteriorPhaseUsesEndpointTimestamps() {
        FrameGenerationPresentationRequest request =
                FrameGenerationPresentationRequest.between(
                        7L, 9L,
                        41L, 1_000_000_000L,
                        42L, 1_050_000_000L,
                        1_020_000_000L, 2_002_000_000L,
                        1_999_000_000L, 1_999_000_000L,
                        0, 320, 240,
                        FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM);
        equal(0.4, request.phase(), 1e-12, "exact phase");
        require(request.isGenerated(), "interior timestamp is generated");
        equal(41L, request.leftSequence(), "left sequence");
        equal(42L, request.rightSequence(), "right sequence");
        equal(1_020_000_000L, request.presentationTimestampNs(), "content timestamp");
        equal(7L, request.sessionEpoch(), "session epoch");
        equal(9L, request.presentationEpoch(), "presentation epoch");
        equal(2_002_000_000L, request.desiredPhysicalPresentTimeNs(),
                "physical scan timestamp");
        equal(1_999_000_000L, request.driverDesiredPresentTimeNs(),
                "driver earliest-present bound");
        equal(1_999_000_000L, request.hardCompletionDeadlineNs(),
                "hard completion deadline");
        equal(0L, request.presentationPipelineScans(),
                "ordinary request has no presentation-pipeline offset");
        equal(1_994_000_000L, request.queueReleaseNotBeforeNs(),
                "bounded WSI release opening");
        equal(320L, request.outputWidth(), "output width");
        equal(240L, request.outputHeight(), "output height");
        equal(FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM,
                request.outputFormat(), "output format");
    }

    private static void boundariesAreEndpointsNotGeneratedFrames() {
        FrameGenerationPresentationRequest left =
                FrameGenerationPresentationRequest.between(
                        1L, 1L, 1L, 100L, 2L, 200L, 100L,
                        300L, 290L, 290L, 0, 64, 64,
                        FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM);
        FrameGenerationPresentationRequest right =
                FrameGenerationPresentationRequest.between(
                        1L, 1L, 1L, 100L, 2L, 200L, 200L,
                        300L, 290L, 290L, 0, 64, 64,
                        FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM);
        require(left.presentsLeftEndpoint() && !left.isGenerated(), "left boundary");
        require(right.presentsRightEndpoint() && !right.isGenerated(), "right boundary");
    }

    private static void standaloneEndpointNeedsNoFabricatedRightImage() {
        FrameGenerationPresentationRequest endpoint =
                FrameGenerationPresentationRequest.endpoint(
                        2L, 3L, 9L, 500L,
                        10_010_000L, 10_000_000L, 10_000_000L,
                        0, 64, 64,
                        FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM);
        require(!endpoint.hasAdjacentPair(), "standalone endpoint has no pair");
        require(endpoint.presentsLeftEndpoint(), "standalone endpoint phase");
        require(!endpoint.isGenerated(), "standalone endpoint is real");
        equal(5_500_000L, endpoint.queueReleaseNotBeforeNs(),
                "endpoint uses its later physical release boundary");
    }

    private static void preparationIdentityExcludesOnlyPhysicalDeadline() {
        FrameGenerationPresentationRequest first =
                FrameGenerationPresentationRequest.between(
                        7L, 9L, 41L, 1_000L, 42L, 1_050L, 1_020L,
                        2_100L, 2_000L, 2_000L, 0, 192, 108,
                        FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM);
        FrameGenerationPresentationRequest laterDeadline =
                FrameGenerationPresentationRequest.between(
                        7L, 9L, 41L, 1_000L, 42L, 1_050L, 1_020L,
                        2_200L, 2_100L, 2_100L, 0, 192, 108,
                        FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM);
        FrameGenerationPresentationRequest otherPhase =
                FrameGenerationPresentationRequest.between(
                        7L, 9L, 41L, 1_000L, 42L, 1_050L, 1_025L,
                        2_200L, 2_100L, 2_100L, 0, 192, 108,
                        FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM);
        FrameGenerationPresentationRequest otherEpoch =
                FrameGenerationPresentationRequest.between(
                        7L, 10L, 41L, 1_000L, 42L, 1_050L, 1_020L,
                        2_200L, 2_100L, 2_100L, 0, 192, 108,
                        FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM);
        FrameGenerationPreparationRequest prepared =
                FrameGenerationPreparationRequest.from(first);
        require(prepared.matches(first), "preparation matches original request");
        require(prepared.matches(laterDeadline),
                "preparation is independent of later WSI deadline");
        require(!prepared.matches(otherPhase),
                "preparation rejects a different source timestamp");
        require(!prepared.matches(otherEpoch),
                "preparation rejects a different presentation epoch");
        require(prepared.isGenerated(), "prepared midpoint remains generated");
        equal(192L, prepared.outputWidth(), "prepared width");
        equal(108L, prepared.outputHeight(), "prepared height");
    }

    private static void preparationCanPrecedeWsiDeadline() {
        FrameGenerationPreparationRequest prepared =
                FrameGenerationPreparationRequest.between(
                        7L, 9L, 41L, 1_000L, 42L, 1_050L, 1_020L,
                        192, 108,
                        FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM);
        FrameGenerationPresentationRequest later =
                FrameGenerationPresentationRequest.between(
                        7L, 9L, 41L, 1_000L, 42L, 1_050L, 1_020L,
                        2_100L, 2_000L, 2_000L, 0, 192, 108,
                        FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM);
        require(prepared.matches(later),
                "deadline-free preparation matches later WSI request");
        equal(0.4, prepared.phase(), 1e-12,
                "deadline-free preparation phase");
        rejects(() -> FrameGenerationPreparationRequest.between(
                7L, 9L, 41L, 1_000L, 43L, 1_050L, 1_020L,
                192, 108,
                FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM),
                "preparation sequence gap");
        rejects(() -> FrameGenerationPreparationRequest.between(
                7L, 9L, 41L, 1_000L, 42L, 1_050L, 1_051L,
                192, 108,
                FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM),
                "preparation extrapolation");
    }

    private static void rejectsExtrapolationAndDiscontinuity() {
        rejects(() -> FrameGenerationPresentationRequest.between(
                1L, 1L, 1L, 100L, 3L, 200L, 150L,
                300L, 290L, 290L, 0, 64, 64,
                FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM), "sequence gap");
        rejects(() -> FrameGenerationPresentationRequest.between(
                1L, 1L, 1L, 100L, 2L, 90L, 100L,
                300L, 290L, 290L, 0, 64, 64,
                FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM), "timestamp reversal");
        rejects(() -> FrameGenerationPresentationRequest.between(
                1L, 1L, 1L, 100L, 2L, 200L, 99L,
                300L, 290L, 290L, 0, 64, 64,
                FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM), "left extrapolation");
        rejects(() -> FrameGenerationPresentationRequest.between(
                1L, 1L, 1L, 100L, 2L, 200L, 201L,
                300L, 290L, 290L, 0, 64, 64,
                FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM), "right extrapolation");
        rejects(() -> FrameGenerationPresentationRequest.endpoint(
                1L, 1L, 0L, 100L, 300L, 290L, 290L,
                0, 64, 64, FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM),
                "zero sequence");
        rejects(() -> FrameGenerationPresentationRequest.endpoint(
                1L, 1L, 1L, 100L, 300L, 300L, 300L,
                0, 64, 64, FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM),
                "driver bound does not precede physical scan");
        rejects(() -> FrameGenerationPresentationRequest.endpoint(
                1L, 1L, 1L, 100L, 300L, 290L, 291L,
                0, 64, 64, FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM),
                "completion follows driver-ready bound");
        rejects(() -> FrameGenerationPresentationRequest.endpoint(
                1L, 1L, 1L, 100L, 300L, 290L, 290L,
                2, 64, 64, FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM),
                "unsupported presentation pipeline");
    }

    private static void predecessorFrameTimelineIsImmutableAndScanBound() {
        FrameGenerationPresentationRequest plain =
                FrameGenerationPresentationRequest.between(
                        5L, 6L, 10L, 1_000_000_000L,
                        11L, 1_050_000_000L, 1_025_000_000L,
                        2_000_000_000L, 1_998_000_000L,
                        1_998_000_000L, 0, 320, 240,
                        FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM);
        require(!plain.hasCompositorFrameTimeline(),
                "ordinary backend request must not fabricate a timeline");
        FrameGenerationPresentationRequest bound =
                plain.withPrecedingCompositorFrameTimeline(
                        123L, 1_991_666_667L, 2_000_000_000L,
                        1_984_000_000L, 8_333_333L);
        require(bound.hasCompositorFrameTimeline() &&
                bound.compositorFrameTimelineVsyncId() == 123L &&
                bound.compositorTokenExpectedPresentationTimeNs() ==
                        1_991_666_667L &&
                bound.compositorExpectedPresentationTimeNs() ==
                        2_000_000_000L &&
                bound.compositorFrameTimelineDeadlineNs() == 1_984_000_000L &&
                bound.driverDesiredPresentTimeNs() == 1_998_000_000L &&
                bound.hardCompletionDeadlineNs() == 1_984_000_000L,
                "timeline identity must survive immutable request binding");
        rejects(() -> plain.withPrecedingCompositorFrameTimeline(
                124L, 1_991_666_667L, 2_000_250_001L,
                1_984_000_000L, 8_333_333L),
                "timeline target outside tolerance");
        rejects(() -> plain.withPrecedingCompositorFrameTimeline(
                124L, 1_991_666_667L, 2_000_000_000L,
                1_991_666_667L, 8_333_333L),
                "timeline deadline after expected scan");
        rejects(() -> plain.withPrecedingCompositorFrameTimeline(
                124L, 1_990_000_000L, 2_000_000_000L,
                1_984_000_000L, 8_333_333L),
                "non-preceding token period");
        rejects(() -> plain.withPrecedingCompositorFrameTimeline(
                124L, 1_999_000_000L, 2_000_000_000L,
                1_990_000_000L, 1_000_000L),
                "driver bound must exclude predecessor visibility");
    }

    private static void targetFrameTimelineIsImmutableAndScanBound() {
        FrameGenerationPresentationRequest plain =
                FrameGenerationPresentationRequest.between(
                        5L, 6L, 10L, 1_000_000_000L,
                        11L, 1_050_000_000L, 1_025_000_000L,
                        2_000_000_000L, 1_998_000_000L,
                        1_998_000_000L, 0, 320, 240,
                        FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM);
        FrameGenerationPresentationRequest bound =
                plain.withTargetCompositorFrameTimeline(
                        223L, 2_000_000_000L, 1_989_666_667L);
        require(bound.hasCompositorFrameTimeline() &&
                bound.compositorFrameTimelineVsyncId() == 223L &&
                bound.compositorTokenExpectedPresentationTimeNs() ==
                        2_000_000_000L &&
                bound.compositorExpectedPresentationTimeNs() ==
                        2_000_000_000L &&
                bound.compositorFrameTimelineDeadlineNs() == 1_989_666_667L &&
                bound.driverDesiredPresentTimeNs() == 1_998_000_000L &&
                bound.hardCompletionDeadlineNs() == 1_989_666_667L,
                "exact target timeline identity must survive binding");
        rejects(() -> plain.withTargetCompositorFrameTimeline(
                224L, 2_000_250_001L, 1_989_666_667L),
                "exact target outside tolerance");
        rejects(() -> plain.withTargetCompositorFrameTimeline(
                224L, 2_000_000_000L, 2_000_000_000L),
                "target deadline after expected scan");
        rejects(() -> plain.withTargetCompositorFrameTimeline(
                224L, 1_997_000_000L, 1_989_666_667L),
                "driver bound must precede target visibility");
    }

    private interface Action { void run(); }

    private static void rejects(Action action, String label) {
        try {
            action.run();
            throw new AssertionError(label + " was accepted");
        } catch (IllegalArgumentException expected) {
            // Expected.
        }
    }

    private static void require(boolean condition, String label) {
        if (!condition) throw new AssertionError(label);
    }

    private static void equal(long expected, long actual, String label) {
        if (expected != actual)
            throw new AssertionError(label + " expected=" + expected + " actual=" + actual);
    }

    private static void equal(double expected, double actual, double tolerance, String label) {
        if (Math.abs(expected - actual) > tolerance)
            throw new AssertionError(label + " expected=" + expected + " actual=" + actual);
    }
}
