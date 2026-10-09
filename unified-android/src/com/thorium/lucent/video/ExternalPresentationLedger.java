package com.thorium.lucent.video;

import java.util.ArrayDeque;

/**
 * Exact in-order join between backend submissions and physical-present rows.
 *
 * <p>Submission never advances delivered counters. Only a matching monotonic
 * physical timestamp can be committed, which keeps target, generated work,
 * queue completion, and actual scanout as distinct accounting domains.</p>
 */
public final class ExternalPresentationLedger {
    private static final int MAX_PENDING = 16;

    private final ArrayDeque<Pending> pending = new ArrayDeque<>();
    private long submitted;
    private long physicallyPresented;
    private long physicalEndpoints;
    private long physicalGenerated;
    private long physicalDropped;
    private long lastPresentId;
    private long lastDesiredPresentNs;
    private long lastActualPresentNs;
    private long lastContentPresentNs;

    public void submit(FrameGenerationPresentationRequest request,
                       int scansPerOutput) {
        if (request == null || scansPerOutput <= 0 ||
                request.sessionEpoch() <= 0L || request.presentationEpoch() <= 0L)
            throw new IllegalArgumentException("external submission is invalid");
        if (pending.size() >= MAX_PENDING)
            throw new IllegalStateException("external presentation ledger is full");
        pending.addLast(new Pending(request, scansPerOutput));
        ++submitted;
    }

    public boolean canSubmit() { return pending.size() < MAX_PENDING; }

    public Commit physicallyPresented(
            FrameGenerationPresentationRequest request,
            long presentId, long desiredPresentTimeNs, long actualPresentTimeNs,
            long earliestPresentTimeNs, long presentMarginNs,
            long refreshDurationNs, long enqueueWallNs, long gpuWorkNs) {
        Pending expected = pending.peekFirst();
        long droppedBefore = presentId - lastPresentId - 1L;
        long expectedPlatformDesiredNs = platformDesiredPresentTimeNs(request);
        if (expected == null || droppedBefore < 0L ||
                droppedBefore >= pending.size() ||
                desiredPresentTimeNs != expectedPlatformDesiredNs ||
                desiredPresentTimeNs <= lastDesiredPresentNs ||
                actualPresentTimeNs <= lastActualPresentNs ||
                request.presentationTimestampNs() <= lastContentPresentNs ||
                earliestPresentTimeNs <= 0L || refreshDurationNs <= 0L ||
                presentMarginNs < 0L ||
                enqueueWallNs <= 0L || gpuWorkNs <= 0L)
            throw new IllegalStateException(
                    "external physical presentation does not match submission");
        java.util.Iterator<Pending> iterator = pending.iterator();
        for (long index = 0L; index < droppedBefore; ++index) iterator.next();
        expected = iterator.next();
        if (!sameRequest(expected.request, request))
            throw new IllegalStateException(
                    "external physical presentation does not match submission");
        for (long index = 0L; index < droppedBefore; ++index)
            pending.removeFirst();
        pending.removeFirst();
        physicalDropped += droppedBefore;
        lastPresentId = presentId;
        lastDesiredPresentNs = desiredPresentTimeNs;
        lastActualPresentNs = actualPresentTimeNs;
        lastContentPresentNs = request.presentationTimestampNs();
        ++physicallyPresented;
        if (request.isGenerated()) ++physicalGenerated;
        else ++physicalEndpoints;
        return new Commit(request, presentId, desiredPresentTimeNs,
                actualPresentTimeNs, earliestPresentTimeNs, presentMarginNs,
                expected.scansPerOutput, expected.presentationEpoch,
                refreshDurationNs, enqueueWallNs,
                gpuWorkNs, droppedBefore);
    }

    /**
     * Retires one exact compositor-rejected submission without fabricating a
     * physical timestamp or delivered frame.
     *
     * <p>Drops are strictly in order. Advancing the presentation ID and
     * content/desired clocks prevents a later row from relabeling this
     * submission, while the actual-present clock and delivered counters remain
     * untouched.</p>
     */
    public Drop physicallyDropped(
            FrameGenerationPresentationRequest request,
            long presentId, long refreshDurationNs) {
        Pending expected = pending.peekFirst();
        long expectedPlatformDesiredNs = platformDesiredPresentTimeNs(request);
        if (expected == null || presentId != lastPresentId + 1L ||
                refreshDurationNs <= 0L ||
                expectedPlatformDesiredNs <= lastDesiredPresentNs ||
                request.presentationTimestampNs() <= lastContentPresentNs ||
                !sameRequest(expected.request, request))
            throw new IllegalStateException(
                    "external physical drop does not match submission");
        pending.removeFirst();
        lastPresentId = presentId;
        lastDesiredPresentNs = expectedPlatformDesiredNs;
        lastContentPresentNs = request.presentationTimestampNs();
        ++physicalDropped;
        return new Drop(request, presentId, expected.scansPerOutput,
                expected.presentationEpoch, refreshDurationNs);
    }

    public int pendingCount() { return pending.size(); }
    public long submittedCount() { return submitted; }
    public long physicallyPresentedCount() { return physicallyPresented; }
    public long physicalEndpointCount() { return physicalEndpoints; }
    public long physicalGeneratedCount() { return physicalGenerated; }
    public long physicalDroppedCount() { return physicalDropped; }

    /**
     * Both Android presentation transports consume the earlier driver request.
     * The exact content scan remains independently bound in the request and is
     * the only slot against which {@link ExternalPresentationEvidence} judges
     * physical delivery.
     *
     * <p>SurfaceControl promises to try at or after its desired time, and
     * {@code VK_GOOGLE_display_timing} is likewise an earliest-display request.
     * Passing the exact scan boundary to Vulkan caused r114's frequent
     * one-scan-late results.  This ledger validates the native request without
     * conflating it with the later content/acceptance timestamp.</p>
     */
    private static long platformDesiredPresentTimeNs(
            FrameGenerationPresentationRequest request) {
        if (request == null) return 0L;
        return request.driverDesiredPresentTimeNs();
    }

    private static boolean sameRequest(
            FrameGenerationPresentationRequest left,
            FrameGenerationPresentationRequest right) {
        return left != null && right != null &&
                left.leftSequence() == right.leftSequence() &&
                left.leftTimestampNs() == right.leftTimestampNs() &&
                left.rightSequence() == right.rightSequence() &&
                left.rightTimestampNs() == right.rightTimestampNs() &&
                left.presentationTimestampNs() == right.presentationTimestampNs() &&
                left.desiredPhysicalPresentTimeNs() ==
                        right.desiredPhysicalPresentTimeNs() &&
                left.driverDesiredPresentTimeNs() ==
                        right.driverDesiredPresentTimeNs() &&
                left.hardCompletionDeadlineNs() ==
                        right.hardCompletionDeadlineNs() &&
                left.presentationPipelineScans() ==
                        right.presentationPipelineScans() &&
                left.sessionEpoch() == right.sessionEpoch() &&
                left.presentationEpoch() == right.presentationEpoch() &&
                left.outputWidth() == right.outputWidth() &&
                left.outputHeight() == right.outputHeight() &&
                left.outputFormat() == right.outputFormat() &&
                Double.doubleToLongBits(left.phase()) ==
                        Double.doubleToLongBits(right.phase());
    }

    private static final class Pending {
        final FrameGenerationPresentationRequest request;
        final int scansPerOutput;
        final long presentationEpoch;
        Pending(FrameGenerationPresentationRequest request, int scansPerOutput) {
            this.request = request;
            this.scansPerOutput = scansPerOutput;
            this.presentationEpoch = request.presentationEpoch();
        }
    }

    public static final class Commit {
        public final FrameGenerationPresentationRequest request;
        public final long presentId;
        public final long desiredPresentTimeNs;
        public final long actualPresentTimeNs;
        public final long earliestPresentTimeNs;
        public final long presentMarginNs;
        public final int scansPerOutput;
        public final long presentationEpoch;
        public final long refreshDurationNs;
        public final long enqueueWallNs;
        public final long gpuWorkNs;
        public final boolean generated;
        public final long droppedBefore;

        private Commit(FrameGenerationPresentationRequest request,
                       long presentId, long desiredPresentTimeNs,
                       long actualPresentTimeNs, long earliestPresentTimeNs,
                       long presentMarginNs, int scansPerOutput,
                       long presentationEpoch,
                       long refreshDurationNs, long enqueueWallNs,
                       long gpuWorkNs, long droppedBefore) {
            this.request = request;
            this.presentId = presentId;
            this.desiredPresentTimeNs = desiredPresentTimeNs;
            this.actualPresentTimeNs = actualPresentTimeNs;
            this.earliestPresentTimeNs = earliestPresentTimeNs;
            this.presentMarginNs = presentMarginNs;
            this.scansPerOutput = scansPerOutput;
            this.presentationEpoch = presentationEpoch;
            this.refreshDurationNs = refreshDurationNs;
            this.enqueueWallNs = enqueueWallNs;
            this.gpuWorkNs = gpuWorkNs;
            this.generated = request.isGenerated();
            this.droppedBefore = droppedBefore;
        }
    }

    public static final class Drop {
        public final FrameGenerationPresentationRequest request;
        public final long presentId;
        public final int scansPerOutput;
        public final long presentationEpoch;
        public final long refreshDurationNs;

        private Drop(FrameGenerationPresentationRequest request,
                     long presentId, int scansPerOutput,
                     long presentationEpoch, long refreshDurationNs) {
            this.request = request;
            this.presentId = presentId;
            this.scansPerOutput = scansPerOutput;
            this.presentationEpoch = presentationEpoch;
            this.refreshDurationNs = refreshDurationNs;
        }
    }
}
