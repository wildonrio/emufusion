package com.thorium.lucent.video;

/**
 * Immutable EmuFusion-owned request for one timestamped output presentation.
 *
 * <p>This value is the backend boundary. The source authority and cadence
 * controller choose the retained endpoint interval and exact producer-clock
 * timestamp; an interpolation backend may render only this request. It cannot
 * invent another clock, phase, endpoint, or catch-up presentation.</p>
 */
public final class FrameGenerationPresentationRequest {
    /** Backend-neutral byte layout for an RGBA8 UNORM output image. */
    public static final int FORMAT_RGBA8_UNORM = 1;

    private final long sessionEpoch;
    private final long presentationEpoch;
    private final long leftSequence;
    private final long leftTimestampNs;
    private final long rightSequence;
    private final long rightTimestampNs;
    private final long presentationTimestampNs;
    private final long desiredPhysicalPresentTimeNs;
    private final long driverDesiredPresentTimeNs;
    private final long hardCompletionDeadlineNs;
    private final long queueReleaseNotBeforeNs;
    private final boolean immediatePriorPhysicalScanRelease;
    private final int presentationPipelineScans;
    private final int outputWidth;
    private final int outputHeight;
    private final int outputFormat;
    private final long compositorFrameTimelineVsyncId;
    private final long compositorTokenExpectedPresentationTimeNs;
    private final long compositorExpectedPresentationTimeNs;
    private final long compositorFrameTimelineDeadlineNs;
    private final double phase;

    private FrameGenerationPresentationRequest(
            long sessionEpoch, long presentationEpoch,
            long leftSequence, long leftTimestampNs,
            long rightSequence, long rightTimestampNs,
            long presentationTimestampNs, long desiredPhysicalPresentTimeNs,
            long driverDesiredPresentTimeNs, long hardCompletionDeadlineNs,
            int presentationPipelineScans,
            int outputWidth, int outputHeight, int outputFormat,
            long compositorFrameTimelineVsyncId,
            long compositorTokenExpectedPresentationTimeNs,
            long compositorExpectedPresentationTimeNs,
            long compositorFrameTimelineDeadlineNs, double phase) {
        this(sessionEpoch, presentationEpoch,
                leftSequence, leftTimestampNs, rightSequence, rightTimestampNs,
                presentationTimestampNs, desiredPhysicalPresentTimeNs,
                driverDesiredPresentTimeNs, hardCompletionDeadlineNs,
                presentationPipelineScans, outputWidth, outputHeight,
                outputFormat, compositorFrameTimelineVsyncId,
                compositorTokenExpectedPresentationTimeNs,
                compositorExpectedPresentationTimeNs,
                compositorFrameTimelineDeadlineNs, phase, 0L);
    }

    private FrameGenerationPresentationRequest(
            long sessionEpoch, long presentationEpoch,
            long leftSequence, long leftTimestampNs,
            long rightSequence, long rightTimestampNs,
            long presentationTimestampNs,
            long desiredPhysicalPresentTimeNs,
            long driverDesiredPresentTimeNs,
            long hardCompletionDeadlineNs,
            int presentationPipelineScans,
            int outputWidth, int outputHeight, int outputFormat,
            long compositorFrameTimelineVsyncId,
            long compositorTokenExpectedPresentationTimeNs,
            long compositorExpectedPresentationTimeNs,
            long compositorFrameTimelineDeadlineNs, double phase,
            long queueReleaseNotBeforeOverrideNs) {
        this.sessionEpoch = sessionEpoch;
        this.presentationEpoch = presentationEpoch;
        this.leftSequence = leftSequence;
        this.leftTimestampNs = leftTimestampNs;
        this.rightSequence = rightSequence;
        this.rightTimestampNs = rightTimestampNs;
        this.presentationTimestampNs = presentationTimestampNs;
        this.desiredPhysicalPresentTimeNs = desiredPhysicalPresentTimeNs;
        this.driverDesiredPresentTimeNs = driverDesiredPresentTimeNs;
        this.hardCompletionDeadlineNs = hardCompletionDeadlineNs;
        long releaseWindowNs = phase > 0.0 && phase < 1.0
                ? PhysicalPresentationDeadline.THOR_WSI_GENERATED_RELEASE_WINDOW_NS
                : PhysicalPresentationDeadline.THOR_WSI_ENDPOINT_RELEASE_WINDOW_NS;
        long defaultReleaseNotBeforeNs = Math.max(1L,
                hardCompletionDeadlineNs - releaseWindowNs);
        if (queueReleaseNotBeforeOverrideNs < 0L ||
                queueReleaseNotBeforeOverrideNs >= hardCompletionDeadlineNs)
            throw new IllegalArgumentException(
                    "queue release override escapes its physical deadline");
        this.queueReleaseNotBeforeNs = queueReleaseNotBeforeOverrideNs > 0L ?
                queueReleaseNotBeforeOverrideNs : defaultReleaseNotBeforeNs;
        this.immediatePriorPhysicalScanRelease =
                queueReleaseNotBeforeOverrideNs > 0L;
        this.presentationPipelineScans = presentationPipelineScans;
        this.outputWidth = outputWidth;
        this.outputHeight = outputHeight;
        this.outputFormat = outputFormat;
        this.compositorFrameTimelineVsyncId = compositorFrameTimelineVsyncId;
        this.compositorTokenExpectedPresentationTimeNs =
                compositorTokenExpectedPresentationTimeNs;
        this.compositorExpectedPresentationTimeNs =
                compositorExpectedPresentationTimeNs;
        this.compositorFrameTimelineDeadlineNs =
                compositorFrameTimelineDeadlineNs;
        this.phase = phase;
    }

    /**
     * Releases a Direct-WSI image immediately after an independently observed
     * predecessor scan when—and only when—this request targets the very next
     * physical scan.
     *
     * <p>The ordinary endpoint/generated windows prevent a buffer targeting a
     * later divisor slot from appearing on an intervening scan. They are not
     * needed after the immediately preceding scan has already been physically
     * observed: no queue operation performed afterward can travel backward to
     * that completed scan. Thor r165 showed that retaining the ordinary 4.5 ms
     * endpoint gate in this exact-next-scan case withheld an otherwise-ready
     * buffer beyond the 60 Hz composition cutoff. A multi-scan or uncertain
     * target retains the original immutable window.</p>
     */
    public FrameGenerationPresentationRequest
            withReleaseAfterImmediatePriorPhysicalScan(
            long priorActualPresentTimeNs, long panelPeriodNs) {
        requirePositive(priorActualPresentTimeNs,
                "prior actual presentation timestamp");
        requirePositive(panelPeriodNs, "panel period");
        if (hasCompositorFrameTimeline())
            throw new IllegalStateException(
                    "compositor-timeline requests own their release deadline");
        if (priorActualPresentTimeNs == Long.MAX_VALUE)
            return this;
        long targetDeltaNs = desiredPhysicalPresentTimeNs -
                priorActualPresentTimeNs;
        long toleranceNs = Math.max(500_000L, panelPeriodNs / 16L);
        if (targetDeltaNs <= 0L ||
                absoluteDifference(targetDeltaNs, panelPeriodNs) > toleranceNs)
            return this;
        long releaseNotBeforeNs = priorActualPresentTimeNs + 1L;
        if (releaseNotBeforeNs >= hardCompletionDeadlineNs)
            return this;
        return new FrameGenerationPresentationRequest(
                sessionEpoch, presentationEpoch,
                leftSequence, leftTimestampNs,
                rightSequence, rightTimestampNs,
                presentationTimestampNs, desiredPhysicalPresentTimeNs,
                driverDesiredPresentTimeNs, hardCompletionDeadlineNs,
                presentationPipelineScans, outputWidth, outputHeight,
                outputFormat, compositorFrameTimelineVsyncId,
                compositorTokenExpectedPresentationTimeNs,
                compositorExpectedPresentationTimeNs,
                compositorFrameTimelineDeadlineNs, phase,
                releaseNotBeforeNs);
    }

    /**
     * Releases a mode-aligned one-scan request immediately after its modeled
     * predecessor scan.
     *
     * <p>This authority is narrower than an ordinary early queue release: the
     * caller must have selected the target with
     * {@code nextAlignedOneScanOutputDirectAfterPredecessor}, which guarantees
     * that the predecessor is a future measured-lattice scan and leaves the
     * complete Direct prequeue reserve after it.  Vulkan's unchanged desired
     * time still forbids early visibility, and physical evidence still rejects
     * any row that misses the exact target.  No multi-scan request may use this
     * path.</p>
     */
    public FrameGenerationPresentationRequest
            withReleaseAfterModeAlignedPredecessorScan(long panelPeriodNs) {
        requirePositive(panelPeriodNs, "panel period");
        if (hasCompositorFrameTimeline())
            throw new IllegalStateException(
                    "compositor-timeline requests own their release deadline");
        if (desiredPhysicalPresentTimeNs <= panelPeriodNs) return this;
        long releaseNotBeforeNs =
                desiredPhysicalPresentTimeNs - panelPeriodNs + 1L;
        if (releaseNotBeforeNs <= 0L ||
                releaseNotBeforeNs >= hardCompletionDeadlineNs)
            return this;
        return new FrameGenerationPresentationRequest(
                sessionEpoch, presentationEpoch,
                leftSequence, leftTimestampNs,
                rightSequence, rightTimestampNs,
                presentationTimestampNs, desiredPhysicalPresentTimeNs,
                driverDesiredPresentTimeNs, hardCompletionDeadlineNs,
                presentationPipelineScans, outputWidth, outputHeight,
                outputFormat, compositorFrameTimelineVsyncId,
                compositorTokenExpectedPresentationTimeNs,
                compositorExpectedPresentationTimeNs,
                compositorFrameTimelineDeadlineNs, phase,
                releaseNotBeforeNs);
    }

    /** Exact real endpoint presentation when no adjacent right endpoint is needed. */
    public static FrameGenerationPresentationRequest endpoint(
            long sessionEpoch, long presentationEpoch,
            long sequence, long timestampNs,
            long desiredPhysicalPresentTimeNs,
            long driverDesiredPresentTimeNs,
            long hardCompletionDeadlineNs,
            int presentationPipelineScans,
            int outputWidth, int outputHeight, int outputFormat) {
        validateContract(sessionEpoch, presentationEpoch,
                desiredPhysicalPresentTimeNs, driverDesiredPresentTimeNs,
                hardCompletionDeadlineNs, presentationPipelineScans,
                outputWidth, outputHeight, outputFormat);
        requirePositive(sequence, "endpoint sequence");
        requirePositive(timestampNs, "endpoint timestamp");
        return new FrameGenerationPresentationRequest(
                sessionEpoch, presentationEpoch,
                sequence, timestampNs, 0L, 0L, timestampNs,
                desiredPhysicalPresentTimeNs, driverDesiredPresentTimeNs,
                hardCompletionDeadlineNs, presentationPipelineScans,
                outputWidth, outputHeight, outputFormat,
                0L, 0L, 0L, 0L, 0.0);
    }

    /** Exact request inside (or on either boundary of) one adjacent interval. */
    public static FrameGenerationPresentationRequest between(
            long sessionEpoch, long presentationEpoch,
            long leftSequence, long leftTimestampNs,
            long rightSequence, long rightTimestampNs,
            long presentationTimestampNs,
            long desiredPhysicalPresentTimeNs,
            long driverDesiredPresentTimeNs,
            long hardCompletionDeadlineNs,
            int presentationPipelineScans,
            int outputWidth, int outputHeight, int outputFormat) {
        validateContract(sessionEpoch, presentationEpoch,
                desiredPhysicalPresentTimeNs, driverDesiredPresentTimeNs,
                hardCompletionDeadlineNs, presentationPipelineScans,
                outputWidth, outputHeight, outputFormat);
        requirePositive(leftSequence, "left endpoint sequence");
        requirePositive(leftTimestampNs, "left endpoint timestamp");
        requirePositive(rightSequence, "right endpoint sequence");
        if (leftSequence == Long.MAX_VALUE || rightSequence != leftSequence + 1L)
            throw new IllegalArgumentException("frame-generation endpoints are not adjacent");
        if (rightTimestampNs <= leftTimestampNs)
            throw new IllegalArgumentException("frame-generation endpoint timestamps are unordered");
        if (presentationTimestampNs < leftTimestampNs ||
                presentationTimestampNs > rightTimestampNs)
            throw new IllegalArgumentException("frame-generation request extrapolates");
        double phase = (double) (presentationTimestampNs - leftTimestampNs) /
                (double) (rightTimestampNs - leftTimestampNs);
        if (!Double.isFinite(phase) || phase < 0.0 || phase > 1.0)
            throw new IllegalArgumentException("frame-generation phase is invalid");
        return new FrameGenerationPresentationRequest(
                sessionEpoch, presentationEpoch,
                leftSequence, leftTimestampNs, rightSequence, rightTimestampNs,
                presentationTimestampNs, desiredPhysicalPresentTimeNs,
                driverDesiredPresentTimeNs, hardCompletionDeadlineNs,
                presentationPipelineScans, outputWidth, outputHeight,
                outputFormat, 0L, 0L, 0L, 0L, phase);
    }

    /**
     * Binds the immediately preceding SurfaceFlinger row as a compositor-work
     * token while preserving the next row as the immutable visible target.
     * The separate driver timestamp is after the token's expected scan and
     * therefore forbids that predecessor from becoming visible early.
     */
    public FrameGenerationPresentationRequest withPrecedingCompositorFrameTimeline(
            long vsyncId, long tokenExpectedPresentationTimeNs,
            long targetExpectedPresentationTimeNs, long deadlineNs,
            long panelPeriodNs) {
        requirePositive(vsyncId, "compositor frame-timeline vsync ID");
        requirePositive(tokenExpectedPresentationTimeNs,
                "compositor token expected presentation timestamp");
        requirePositive(targetExpectedPresentationTimeNs,
                "compositor expected presentation timestamp");
        requirePositive(deadlineNs, "compositor frame-timeline deadline");
        requirePositive(panelPeriodNs, "panel period");
        if (deadlineNs >= tokenExpectedPresentationTimeNs)
            throw new IllegalArgumentException(
                    "compositor frame-timeline deadline is invalid");
        if (absoluteDifference(targetExpectedPresentationTimeNs,
                desiredPhysicalPresentTimeNs) >
                CompositorFrameTimeline.MAX_TARGET_ERROR_NS)
            throw new IllegalArgumentException(
                    "compositor timeline does not identify the requested scan");
        long tokenLeadNs = targetExpectedPresentationTimeNs -
                tokenExpectedPresentationTimeNs;
        if (tokenLeadNs <= 0L ||
                absoluteDifference(tokenLeadNs, panelPeriodNs) >
                        CompositorFrameTimeline.MAX_TARGET_ERROR_NS)
            throw new IllegalArgumentException(
                    "compositor token is not the immediately preceding scan");
        if (driverDesiredPresentTimeNs <=
                tokenExpectedPresentationTimeNs)
            throw new IllegalArgumentException(
                    "driver bound does not exclude the predecessor scan");
        if (deadlineNs > hardCompletionDeadlineNs)
            throw new IllegalArgumentException(
                    "compositor deadline is later than the owned submission cutoff");
        return new FrameGenerationPresentationRequest(
                sessionEpoch, presentationEpoch,
                leftSequence, leftTimestampNs,
                rightSequence, rightTimestampNs,
                presentationTimestampNs, desiredPhysicalPresentTimeNs,
                driverDesiredPresentTimeNs, deadlineNs,
                presentationPipelineScans, outputWidth, outputHeight,
                outputFormat, vsyncId,
                tokenExpectedPresentationTimeNs,
                targetExpectedPresentationTimeNs,
                deadlineNs, phase);
    }

    /**
     * Binds the exact visible target row. Its immutable deadline is earlier
     * than the independent target-minus-driver-lead timestamp, while the
     * token's expected presentation time is the requested physical scan.
     */
    public FrameGenerationPresentationRequest withTargetCompositorFrameTimeline(
            long vsyncId, long targetExpectedPresentationTimeNs,
            long deadlineNs) {
        requirePositive(vsyncId, "compositor frame-timeline vsync ID");
        requirePositive(targetExpectedPresentationTimeNs,
                "compositor expected presentation timestamp");
        requirePositive(deadlineNs, "compositor frame-timeline deadline");
        if (deadlineNs >= targetExpectedPresentationTimeNs)
            throw new IllegalArgumentException(
                    "compositor frame-timeline deadline is invalid");
        if (absoluteDifference(targetExpectedPresentationTimeNs,
                desiredPhysicalPresentTimeNs) >
                CompositorFrameTimeline.MAX_TARGET_ERROR_NS)
            throw new IllegalArgumentException(
                    "compositor timeline does not identify the requested scan");
        if (driverDesiredPresentTimeNs >= targetExpectedPresentationTimeNs)
            throw new IllegalArgumentException(
                    "driver bound does not precede the target scan");
        if (deadlineNs > hardCompletionDeadlineNs)
            throw new IllegalArgumentException(
                    "compositor deadline is later than the owned submission cutoff");
        return new FrameGenerationPresentationRequest(
                sessionEpoch, presentationEpoch,
                leftSequence, leftTimestampNs,
                rightSequence, rightTimestampNs,
                presentationTimestampNs, desiredPhysicalPresentTimeNs,
                driverDesiredPresentTimeNs, deadlineNs,
                presentationPipelineScans, outputWidth, outputHeight,
                outputFormat, vsyncId,
                targetExpectedPresentationTimeNs,
                targetExpectedPresentationTimeNs,
                deadlineNs, phase);
    }

    private static void validateContract(
            long sessionEpoch, long presentationEpoch,
            long desiredPhysicalPresentTimeNs,
            long driverDesiredPresentTimeNs,
            long hardCompletionDeadlineNs,
            int presentationPipelineScans,
            int outputWidth, int outputHeight, int outputFormat) {
        requirePositive(sessionEpoch, "session epoch");
        requirePositive(presentationEpoch, "presentation epoch");
        requirePositive(desiredPhysicalPresentTimeNs,
                "desired physical presentation timestamp");
        requirePositive(driverDesiredPresentTimeNs,
                "driver desired presentation timestamp");
        requirePositive(hardCompletionDeadlineNs, "hard completion deadline");
        if (driverDesiredPresentTimeNs >= desiredPhysicalPresentTimeNs)
            throw new IllegalArgumentException(
                    "driver earliest-present bound must precede its physical scan");
        // EGL may require queue completion well before the desired display
        // timestamp. An earlier cutoff is stricter, never permission to be late.
        // Backend-specific Vulkan evidence retains its own equality checks.
        if (hardCompletionDeadlineNs > driverDesiredPresentTimeNs)
            throw new IllegalArgumentException(
                    "completion deadline must not follow the driver-ready bound");
        if (presentationPipelineScans < 0 || presentationPipelineScans > 1)
            throw new IllegalArgumentException(
                    "presentation pipeline scan count is unsupported");
        if (outputWidth <= 0 || outputHeight <= 0)
            throw new IllegalArgumentException("output geometry is invalid");
        if (outputFormat != FORMAT_RGBA8_UNORM)
            throw new IllegalArgumentException("output format is unsupported");
    }

    private static void requirePositive(long value, String label) {
        if (value <= 0L) throw new IllegalArgumentException(label + " must be positive");
    }

    private static long absoluteDifference(long left, long right) {
        return left >= right ? left - right : right - left;
    }

    public long sessionEpoch() { return sessionEpoch; }
    public long presentationEpoch() { return presentationEpoch; }
    public long leftSequence() { return leftSequence; }
    public long leftTimestampNs() { return leftTimestampNs; }
    public long rightSequence() { return rightSequence; }
    public long rightTimestampNs() { return rightTimestampNs; }
    public long presentationTimestampNs() { return presentationTimestampNs; }
    public long desiredPhysicalPresentTimeNs() { return desiredPhysicalPresentTimeNs; }
    public long driverDesiredPresentTimeNs() { return driverDesiredPresentTimeNs; }
    public long hardCompletionDeadlineNs() { return hardCompletionDeadlineNs; }
    /** First monotonic instant at which the finished image may enter WSI. */
    public long queueReleaseNotBeforeNs() { return queueReleaseNotBeforeNs; }
    /** True only for a next-scan release proven by the preceding actual row. */
    public boolean immediatePriorPhysicalScanRelease() {
        return immediatePriorPhysicalScanRelease;
    }
    public int presentationPipelineScans() { return presentationPipelineScans; }
    public int outputWidth() { return outputWidth; }
    public int outputHeight() { return outputHeight; }
    public int outputFormat() { return outputFormat; }
    public long compositorFrameTimelineVsyncId() {
        return compositorFrameTimelineVsyncId;
    }
    public long compositorTokenExpectedPresentationTimeNs() {
        return compositorTokenExpectedPresentationTimeNs;
    }
    public long compositorExpectedPresentationTimeNs() {
        return compositorExpectedPresentationTimeNs;
    }
    public long compositorFrameTimelineDeadlineNs() {
        return compositorFrameTimelineDeadlineNs;
    }
    public boolean hasCompositorFrameTimeline() {
        return compositorFrameTimelineVsyncId > 0L;
    }
    public double phase() { return phase; }
    public boolean hasAdjacentPair() { return rightSequence != 0L; }
    public boolean isGenerated() { return phase > 0.0 && phase < 1.0; }
    public boolean presentsLeftEndpoint() { return phase == 0.0; }
    public boolean presentsRightEndpoint() { return hasAdjacentPair() && phase == 1.0; }
}
