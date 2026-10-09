package com.thorium.lucent.video;

/**
 * Immutable pixel identity for work that may finish before WSI ownership.
 *
 * <p>This deliberately excludes every physical-presentation deadline. A backend
 * may prepare only these exact pixels into private GPU storage; it must later
 * match a full {@link FrameGenerationPresentationRequest} before those pixels
 * can be copied into a swapchain image. Keeping the two identities separate
 * prevents expensive inference from acquiring or retaining WSI images.</p>
 */
public final class FrameGenerationPreparationRequest {
    private final long sessionEpoch;
    private final long presentationEpoch;
    private final long leftSequence;
    private final long leftTimestampNs;
    private final long rightSequence;
    private final long rightTimestampNs;
    private final long presentationTimestampNs;
    private final int outputWidth;
    private final int outputHeight;
    private final int outputFormat;
    private final double phase;

    private FrameGenerationPreparationRequest(
            long sessionEpoch, long presentationEpoch,
            long leftSequence, long leftTimestampNs,
            long rightSequence, long rightTimestampNs,
            long presentationTimestampNs,
            int outputWidth, int outputHeight, int outputFormat,
            double phase) {
        this.sessionEpoch = sessionEpoch;
        this.presentationEpoch = presentationEpoch;
        this.leftSequence = leftSequence;
        this.leftTimestampNs = leftTimestampNs;
        this.rightSequence = rightSequence;
        this.rightTimestampNs = rightTimestampNs;
        this.presentationTimestampNs = presentationTimestampNs;
        this.outputWidth = outputWidth;
        this.outputHeight = outputHeight;
        this.outputFormat = outputFormat;
        this.phase = phase;
    }

    /** Removes only WSI timing from an already validated presentation request. */
    public static FrameGenerationPreparationRequest from(
            FrameGenerationPresentationRequest request) {
        if (request == null)
            throw new IllegalArgumentException("presentation request is absent");
        return new FrameGenerationPreparationRequest(
                request.sessionEpoch(), request.presentationEpoch(),
                request.leftSequence(), request.leftTimestampNs(),
                request.rightSequence(), request.rightTimestampNs(),
                request.presentationTimestampNs(),
                request.outputWidth(), request.outputHeight(),
                request.outputFormat(), request.phase());
    }

    /**
     * Creates a private-output request directly from EmuFusion's exact
     * adjacent endpoint timeline, before any WSI deadline exists.
     */
    public static FrameGenerationPreparationRequest between(
            long sessionEpoch, long presentationEpoch,
            long leftSequence, long leftTimestampNs,
            long rightSequence, long rightTimestampNs,
            long presentationTimestampNs,
            int outputWidth, int outputHeight, int outputFormat) {
        requirePositive(sessionEpoch, "session epoch");
        requirePositive(presentationEpoch, "presentation epoch");
        requirePositive(leftSequence, "left endpoint sequence");
        requirePositive(leftTimestampNs, "left endpoint timestamp");
        if (leftSequence == Long.MAX_VALUE ||
                rightSequence != leftSequence + 1L)
            throw new IllegalArgumentException(
                    "preparation endpoints are not adjacent");
        if (rightTimestampNs <= leftTimestampNs)
            throw new IllegalArgumentException(
                    "preparation endpoint timestamps are unordered");
        if (presentationTimestampNs < leftTimestampNs ||
                presentationTimestampNs > rightTimestampNs)
            throw new IllegalArgumentException(
                    "frame-generation preparation extrapolates");
        if (outputWidth <= 0 || outputHeight <= 0)
            throw new IllegalArgumentException(
                    "preparation output geometry is invalid");
        if (outputFormat !=
                FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM)
            throw new IllegalArgumentException(
                    "preparation output format is unsupported");
        double phase = (double) (presentationTimestampNs - leftTimestampNs) /
                (double) (rightTimestampNs - leftTimestampNs);
        if (!Double.isFinite(phase) || phase < 0.0 || phase > 1.0)
            throw new IllegalArgumentException(
                    "frame-generation preparation phase is invalid");
        return new FrameGenerationPreparationRequest(
                sessionEpoch, presentationEpoch,
                leftSequence, leftTimestampNs,
                rightSequence, rightTimestampNs,
                presentationTimestampNs,
                outputWidth, outputHeight, outputFormat, phase);
    }

    private static void requirePositive(long value, String label) {
        if (value <= 0L)
            throw new IllegalArgumentException(label + " must be positive");
    }

    /**
     * True only when a later physical request asks for these exact prepared
     * pixels. Deadlines are intentionally not part of this comparison.
     */
    public boolean matches(FrameGenerationPresentationRequest request) {
        if (request == null) return false;
        return sessionEpoch == request.sessionEpoch() &&
                presentationEpoch == request.presentationEpoch() &&
                leftSequence == request.leftSequence() &&
                leftTimestampNs == request.leftTimestampNs() &&
                rightSequence == request.rightSequence() &&
                rightTimestampNs == request.rightTimestampNs() &&
                presentationTimestampNs == request.presentationTimestampNs() &&
                outputWidth == request.outputWidth() &&
                outputHeight == request.outputHeight() &&
                outputFormat == request.outputFormat() &&
                Double.doubleToLongBits(phase) ==
                        Double.doubleToLongBits(request.phase());
    }

    /** Exact private-output identity comparison. */
    public boolean matches(FrameGenerationPreparationRequest request) {
        if (request == null) return false;
        return sessionEpoch == request.sessionEpoch &&
                presentationEpoch == request.presentationEpoch &&
                leftSequence == request.leftSequence &&
                leftTimestampNs == request.leftTimestampNs &&
                rightSequence == request.rightSequence &&
                rightTimestampNs == request.rightTimestampNs &&
                presentationTimestampNs == request.presentationTimestampNs &&
                outputWidth == request.outputWidth &&
                outputHeight == request.outputHeight &&
                outputFormat == request.outputFormat &&
                Double.doubleToLongBits(phase) ==
                        Double.doubleToLongBits(request.phase);
    }

    public long sessionEpoch() { return sessionEpoch; }
    public long presentationEpoch() { return presentationEpoch; }
    public long leftSequence() { return leftSequence; }
    public long leftTimestampNs() { return leftTimestampNs; }
    public long rightSequence() { return rightSequence; }
    public long rightTimestampNs() { return rightTimestampNs; }
    public long presentationTimestampNs() { return presentationTimestampNs; }
    public int outputWidth() { return outputWidth; }
    public int outputHeight() { return outputHeight; }
    public int outputFormat() { return outputFormat; }
    public double phase() { return phase; }
    public boolean hasAdjacentPair() { return rightSequence != 0L; }
    public boolean isGenerated() { return phase > 0.0 && phase < 1.0; }
}
