package com.thorium.lucent.video;

/**
 * Fail-closed numeric content evidence for the qualification-only external
 * backend.  It proves exact endpoint passthrough, output non-duplication on
 * sampled moving pairs, and absence of the conservative post-present
 * scene-cut risk flag.  It does not claim ghosting-free motion: moving-video
 * manual/high-speed inspection remains a separate mandatory gate.
 */
public final class ExternalGeneratedContentEvidence {
    private static final long MIN_MOVING_ENDPOINT_MAD_PPM = 2_000L;
    private static final long MAX_ANALYSIS_WALL_NS = 1_000_000L;
    private static final long MIN_GENERATED_PROOFS = 30L;
    private static final long MIN_MOVING_GENERATED_PROOFS = 10L;

    private long presentationEpoch;
    private long proofs;
    private long endpointProofs;
    private long generatedProofs;
    private long movingGeneratedProofs;
    private long distinctMovingGeneratedProofs;
    private long sceneCutRiskGeneratedProofs;
    private long endpointPassthroughFailures;
    private long generatedEqualsLeft;
    private long generatedEqualsRight;
    private long lastPresentId;
    private long maxAnalysisWallNs;
    private long maxEndpointMadPpm;
    private long maxEndpointHistogramDistancePpm;
    private long maxOutputLeftMadPpm;
    private long maxOutputRightMadPpm;

    public void record(ExternalPresentationLedger.Commit row,
                       ExternalGeneratedContentProof proof) {
        if (row == null || proof == null || row.presentationEpoch <= 0L)
            throw new IllegalArgumentException("external content row is invalid");
        adoptEpoch(row.presentationEpoch);
        // A private generated output receives its native proof token before
        // WSI ownership. Endpoint rows submitted while that private work is
        // pending can therefore have newer proof tokens but earlier physical
        // present IDs. RifePresentationTransport already binds each returned
        // native proof token to the exact SubmittedPresentation that owns it;
        // the evidence reservoir must order the resulting rows by physical
        // presentation identity, not incorrectly require the two independent
        // sequence spaces to be equal or native-token monotonic.
        if (row.presentId <= lastPresentId)
            throw new IllegalStateException(
                    "external content presentation is not monotonic");
        lastPresentId = row.presentId;
        ++proofs;
        maxAnalysisWallNs = Math.max(maxAnalysisWallNs, proof.analysisWallNs);
        maxEndpointMadPpm = Math.max(maxEndpointMadPpm, proof.endpointMadPpm);
        maxEndpointHistogramDistancePpm = Math.max(
                maxEndpointHistogramDistancePpm,
                proof.endpointHistogramDistancePpm);
        maxOutputLeftMadPpm = Math.max(
                maxOutputLeftMadPpm, proof.outputLeftMadPpm);
        maxOutputRightMadPpm = Math.max(
                maxOutputRightMadPpm, proof.outputRightMadPpm);

        boolean endpointsSame = proof.leftChecksum == proof.rightChecksum;
        if ((proof.endpointMadPpm == 0L) != endpointsSame)
            throw new IllegalStateException(
                    "endpoint proof checksum/difference identity mismatch");
        double phase = row.request.phase();
        if (row.generated) {
            if (!(phase > 0.0 && phase < 1.0) || !Double.isFinite(phase))
                throw new IllegalStateException("generated content phase is invalid");
            ++generatedProofs;
            if (proof.sceneCutRisk) ++sceneCutRiskGeneratedProofs;
            if (proof.outputChecksum == proof.leftChecksum) ++generatedEqualsLeft;
            if (proof.outputChecksum == proof.rightChecksum) ++generatedEqualsRight;
            if (proof.endpointMadPpm >= MIN_MOVING_ENDPOINT_MAD_PPM) {
                ++movingGeneratedProofs;
                if (proof.outputChecksum != proof.leftChecksum &&
                        proof.outputChecksum != proof.rightChecksum)
                    ++distinctMovingGeneratedProofs;
            }
        } else {
            ++endpointProofs;
            boolean leftBoundary = phase == 0.0;
            boolean rightBoundary = phase == 1.0;
            boolean exact = leftBoundary ?
                    proof.outputChecksum == proof.leftChecksum :
                    rightBoundary && proof.outputChecksum == proof.rightChecksum;
            if (!exact) {
                ++endpointPassthroughFailures;
                throw new IllegalStateException(
                        "external endpoint proof is not exact passthrough");
            }
        }
    }

    /**
     * Records one physically presented private generated image when EmuFusion,
     * rather than the backend, owns the visible EGL swap.
     */
    public void recordAppOwnedGenerated(
            long epoch, long physicalFrameId,
            FrameGenerationPresentationRequest request,
            ExternalGeneratedContentProof proof) {
        if (epoch <= 0L || physicalFrameId <= 0L || request == null ||
                !request.isGenerated() ||
                request.presentationEpoch() != epoch || proof == null)
            throw new IllegalArgumentException(
                    "app-owned external content row is invalid");
        adoptEpoch(epoch);
        if (physicalFrameId <= lastPresentId)
            throw new IllegalStateException(
                    "app-owned content presentation is not monotonic");
        lastPresentId = physicalFrameId;
        ++proofs;
        maxAnalysisWallNs = Math.max(maxAnalysisWallNs, proof.analysisWallNs);
        maxEndpointMadPpm = Math.max(maxEndpointMadPpm, proof.endpointMadPpm);
        maxEndpointHistogramDistancePpm = Math.max(
                maxEndpointHistogramDistancePpm,
                proof.endpointHistogramDistancePpm);
        maxOutputLeftMadPpm = Math.max(
                maxOutputLeftMadPpm, proof.outputLeftMadPpm);
        maxOutputRightMadPpm = Math.max(
                maxOutputRightMadPpm, proof.outputRightMadPpm);
        boolean endpointsSame = proof.leftChecksum == proof.rightChecksum;
        if ((proof.endpointMadPpm == 0L) != endpointsSame)
            throw new IllegalStateException(
                    "endpoint proof checksum/difference identity mismatch");
        double phase = request.phase();
        if (!(phase > 0.0 && phase < 1.0) || !Double.isFinite(phase))
            throw new IllegalStateException("generated content phase is invalid");
        ++generatedProofs;
        if (proof.sceneCutRisk) ++sceneCutRiskGeneratedProofs;
        if (proof.outputChecksum == proof.leftChecksum) ++generatedEqualsLeft;
        if (proof.outputChecksum == proof.rightChecksum) ++generatedEqualsRight;
        if (proof.endpointMadPpm >= MIN_MOVING_ENDPOINT_MAD_PPM) {
            ++movingGeneratedProofs;
            if (proof.outputChecksum != proof.leftChecksum &&
                    proof.outputChecksum != proof.rightChecksum)
                ++distinctMovingGeneratedProofs;
        }
    }

    /** Starts an empty content-evidence partition without counting a row. */
    public void beginEpoch(long epoch) {
        if (epoch <= 0L)
            throw new IllegalArgumentException(
                    "external content epoch identity is invalid");
        adoptEpoch(epoch);
    }

    /** Restarts numeric proof for a new physical timing window in one epoch. */
    public void restartWindow(long epoch) {
        if (epoch <= 0L)
            throw new IllegalArgumentException(
                    "external content window identity is invalid");
        presentationEpoch = epoch;
        clearMeasurements();
    }

    /** Numeric qualification component only; never substitutes for visual QA. */
    public boolean numericProofPassed() {
        return generatedProofs >= MIN_GENERATED_PROOFS &&
                movingGeneratedProofs >= MIN_MOVING_GENERATED_PROOFS &&
                distinctMovingGeneratedProofs == movingGeneratedProofs &&
                sceneCutRiskGeneratedProofs == 0L &&
                endpointPassthroughFailures == 0L &&
                maxAnalysisWallNs <= MAX_ANALYSIS_WALL_NS;
    }

    public boolean identityMatches(long expectedPresentationEpoch) {
        return presentationEpoch == expectedPresentationEpoch;
    }

    public long presentationEpoch() { return presentationEpoch; }
    public long proofs() { return proofs; }
    public long endpointProofs() { return endpointProofs; }
    public long generatedProofs() { return generatedProofs; }
    public long movingGeneratedProofs() { return movingGeneratedProofs; }
    public long distinctMovingGeneratedProofs() {
        return distinctMovingGeneratedProofs;
    }
    public long sceneCutRiskGeneratedProofs() {
        return sceneCutRiskGeneratedProofs;
    }
    public long endpointPassthroughFailures() {
        return endpointPassthroughFailures;
    }
    public long generatedEqualsLeft() { return generatedEqualsLeft; }
    public long generatedEqualsRight() { return generatedEqualsRight; }
    public long maxAnalysisWallNs() { return maxAnalysisWallNs; }
    public long maxEndpointMadPpm() { return maxEndpointMadPpm; }
    public long maxEndpointHistogramDistancePpm() {
        return maxEndpointHistogramDistancePpm;
    }
    public long maxOutputLeftMadPpm() { return maxOutputLeftMadPpm; }
    public long maxOutputRightMadPpm() { return maxOutputRightMadPpm; }

    private void adoptEpoch(long epoch) {
        if (presentationEpoch == epoch) return;
        presentationEpoch = epoch;
        clearMeasurements();
    }

    private void clearMeasurements() {
        proofs = 0L;
        endpointProofs = 0L;
        generatedProofs = 0L;
        movingGeneratedProofs = 0L;
        distinctMovingGeneratedProofs = 0L;
        sceneCutRiskGeneratedProofs = 0L;
        endpointPassthroughFailures = 0L;
        generatedEqualsLeft = 0L;
        generatedEqualsRight = 0L;
        lastPresentId = 0L;
        maxAnalysisWallNs = 0L;
        maxEndpointMadPpm = 0L;
        maxEndpointHistogramDistancePpm = 0L;
        maxOutputLeftMadPpm = 0L;
        maxOutputRightMadPpm = 0L;
    }
}
