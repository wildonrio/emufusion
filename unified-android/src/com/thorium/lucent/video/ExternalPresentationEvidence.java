package com.thorium.lucent.video;

import java.util.Arrays;

/**
 * Fail-closed live timing evidence for an external frame-generation backend.
 *
 * <p>The input is already identity-joined by {@link ExternalPresentationLedger};
 * this class never treats submission or GPU completion as delivery. It checks
 * that the complete record+GPU interval fits the one selected output slot,
 * that the driver respects its earliest-present bound, and that actual scanout
 * lands on the independently modeled physical slot. Content quality and manual
 * motion inspection remain separate required evidence.</p>
 */
public final class ExternalPresentationEvidence {
    private static final int CAPACITY = 256;
    private static final int MIN_GENERATED_SAMPLES = 30;
    private static final long MIN_QUALIFIED_SPAN_NS = 2_000_000_000L;
    private static final long MIN_PRESENT_TOLERANCE_NS = 150_000L;
    private static final double MAX_PRESENT_ERROR_FRACTION = 0.02;

    private final long[] combinedDurationsNs = new long[CAPACITY];
    private final long[] presentMarginsNs = new long[CAPACITY];
    private int combinedHead;
    private int combinedCount;
    private int presentMarginHead;
    private int presentMarginCount;
    private int targetScansPerOutput;
    private int targetPresentationPipelineScans;
    private long targetRefreshDurationNs;
    private long presentationEpoch;
    private long firstActualPresentNs;
    private long lastActualPresentNs;
    private long physicalPresents;
    private long physicalEndpoints;
    private long physicalGenerated;
    private long deadlineMisses;
    private long desiredSlotMisses;
    private long maxEnqueueWallNs;
    private long maxGpuWorkNs;
    private long maxCombinedNs;
    private long maxDesiredSlotErrorNs;
    private long earliestPresentMisses;
    private long earlyPresentViolations;
    private long earlyDesiredSlotMisses;
    private long lateDesiredSlotMisses;
    private long minPresentMarginNs = Long.MAX_VALUE;
    private long maxPresentMarginNs;
    private long lastPresentMarginNs;
    private long minLateSlotPresentMarginNs = Long.MAX_VALUE;
    private long maxLateSlotPresentMarginNs;
    private long minSignedDesiredSlotErrorNs = Long.MAX_VALUE;
    private long maxSignedDesiredSlotErrorNs = Long.MIN_VALUE;
    private long lastSignedDesiredSlotErrorNs;
    private long maxEndpointSpanNs;
    private double minGeneratedPhase = Double.POSITIVE_INFINITY;
    private double maxGeneratedPhase = Double.NEGATIVE_INFINITY;

    public void record(ExternalPresentationLedger.Commit row,
                       long driverLeadNs) {
        if (row == null || row.scansPerOutput <= 0 || driverLeadNs < 0L)
            throw new IllegalArgumentException("external evidence row is invalid");
        if (row.presentMarginNs < 0L)
            throw new IllegalStateException(
                    "external presentation margin is invalid");
        long outputIntervalNs = saturatingMultiply(
                row.refreshDurationNs, row.scansPerOutput);
        if (outputIntervalNs <= driverLeadNs)
            throw new IllegalStateException("external output deadline is invalid");
        adoptTarget(row.scansPerOutput, row.refreshDurationNs,
                row.presentationEpoch,
                row.request.presentationPipelineScans());
        long combinedNs = saturatingAdd(row.enqueueWallNs, row.gpuWorkNs);
        if (combinedNs == Long.MAX_VALUE)
            throw new IllegalStateException("external work duration overflow");

        long intendedScanNs = row.request.desiredPhysicalPresentTimeNs();
        long requestedLeadNs = intendedScanNs -
                row.request.driverDesiredPresentTimeNs();
        long requestedPipelineNs = requestedLeadNs - driverLeadNs;
        long observedPipelineNs = saturatingMultiply(
                row.refreshDurationNs,
                row.request.presentationPipelineScans());
        long pipelineToleranceNs = Math.max(MIN_PRESENT_TOLERANCE_NS,
                Math.round(Math.max(1L, observedPipelineNs) *
                        MAX_PRESENT_ERROR_FRACTION));
        if (intendedScanNs <= 0L ||
                observedPipelineNs == Long.MAX_VALUE ||
                requestedPipelineNs < 0L ||
                absoluteDifference(requestedPipelineNs,
                        observedPipelineNs) > pipelineToleranceNs ||
                (!row.request.hasCompositorFrameTimeline() &&
                        row.request.hardCompletionDeadlineNs() !=
                                row.request.driverDesiredPresentTimeNs()) ||
                (row.request.hasCompositorFrameTimeline() &&
                        (row.request.hardCompletionDeadlineNs() !=
                                row.request.compositorFrameTimelineDeadlineNs() ||
                                row.request.hardCompletionDeadlineNs() >
                                        row.request.driverDesiredPresentTimeNs())) ||
                row.request.driverDesiredPresentTimeNs() >= intendedScanNs)
            throw new IllegalStateException(
                    "external request does not preserve its physical deadline contract");
        long desiredSlotErrorNs = absoluteDifference(
                row.actualPresentTimeNs, intendedScanNs);
        long signedDesiredSlotErrorNs = row.actualPresentTimeNs >= intendedScanNs ?
                desiredSlotErrorNs : -desiredSlotErrorNs;
        long toleranceNs = Math.max(MIN_PRESENT_TOLERANCE_NS,
                Math.round(outputIntervalNs * MAX_PRESENT_ERROR_FRACTION));

        if (firstActualPresentNs == 0L)
            firstActualPresentNs = row.actualPresentTimeNs;
        if (row.actualPresentTimeNs <= lastActualPresentNs)
            throw new IllegalStateException("external evidence is not monotonic");
        lastActualPresentNs = row.actualPresentTimeNs;
        ++physicalPresents;
        if (row.generated) {
            ++physicalGenerated;
            double phase = row.request.phase();
            if (!(phase > 0.0 && phase < 1.0) || !Double.isFinite(phase))
                throw new IllegalStateException("generated phase is invalid");
            minGeneratedPhase = Math.min(minGeneratedPhase, phase);
            maxGeneratedPhase = Math.max(maxGeneratedPhase, phase);
        } else {
            ++physicalEndpoints;
        }
        if (row.request.hasAdjacentPair()) {
            long spanNs = row.request.rightTimestampNs() -
                    row.request.leftTimestampNs();
            if (spanNs <= 0L)
                throw new IllegalStateException("endpoint span is invalid");
            maxEndpointSpanNs = Math.max(maxEndpointSpanNs, spanNs);
        }
        maxEnqueueWallNs = Math.max(maxEnqueueWallNs, row.enqueueWallNs);
        maxGpuWorkNs = Math.max(maxGpuWorkNs, row.gpuWorkNs);
        maxCombinedNs = Math.max(maxCombinedNs, combinedNs);
        maxDesiredSlotErrorNs = Math.max(maxDesiredSlotErrorNs,
                desiredSlotErrorNs);
        minSignedDesiredSlotErrorNs = Math.min(minSignedDesiredSlotErrorNs,
                signedDesiredSlotErrorNs);
        maxSignedDesiredSlotErrorNs = Math.max(maxSignedDesiredSlotErrorNs,
                signedDesiredSlotErrorNs);
        lastSignedDesiredSlotErrorNs = signedDesiredSlotErrorNs;
        if (combinedNs > outputIntervalNs - driverLeadNs) ++deadlineMisses;
        if (desiredSlotErrorNs > toleranceNs) {
            ++desiredSlotMisses;
            if (signedDesiredSlotErrorNs > 0L) {
                ++lateDesiredSlotMisses;
                minLateSlotPresentMarginNs = Math.min(
                        minLateSlotPresentMarginNs, row.presentMarginNs);
                maxLateSlotPresentMarginNs = Math.max(
                        maxLateSlotPresentMarginNs, row.presentMarginNs);
            } else {
                ++earlyDesiredSlotMisses;
            }
        }
        // VkPastPresentationTimingGOOGLE defines earliestPresentTime as the
        // time at which the image *could* have been displayed. It explicitly
        // may precede actualPresentTime when the application requested a
        // later presentation. Only an actual presentation before that lower
        // bound violates the contract; equality is not required.
        if (row.actualPresentTimeNs < row.earliestPresentTimeNs)
            ++earliestPresentMisses;
        if (row.actualPresentTimeNs <
                row.request.driverDesiredPresentTimeNs())
            ++earlyPresentViolations;
        minPresentMarginNs = Math.min(minPresentMarginNs, row.presentMarginNs);
        maxPresentMarginNs = Math.max(maxPresentMarginNs, row.presentMarginNs);
        lastPresentMarginNs = row.presentMarginNs;
        appendCombined(combinedNs);
        appendPresentMargin(row.presentMarginNs);
    }

    /**
     * Starts an empty evidence partition on a newly anchored presentation
     * epoch. The first physical row after an idle/re-prime boundary establishes
     * the new scan clock; it was planned from the previous clock and therefore
     * must not be judged against that stale lattice or qualify the new epoch.
     */
    public void beginEpoch(int scansPerOutput, long refreshDurationNs,
                           long newPresentationEpoch,
                           int newPresentationPipelineScans) {
        if (scansPerOutput <= 0 || refreshDurationNs <= 0L ||
                newPresentationEpoch <= 0L ||
                newPresentationPipelineScans < 0)
            throw new IllegalArgumentException(
                    "external evidence epoch identity is invalid");
        adoptTarget(scansPerOutput, refreshDurationNs,
                newPresentationEpoch, newPresentationPipelineScans);
    }

    public boolean timingQualified() {
        return physicalGenerated >= MIN_GENERATED_SAMPLES &&
                firstActualPresentNs > 0L &&
                lastActualPresentNs - firstActualPresentNs >=
                        MIN_QUALIFIED_SPAN_NS &&
                deadlineMisses == 0L && desiredSlotMisses == 0L &&
                earliestPresentMisses == 0L && earlyPresentViolations == 0L;
    }

    public long physicalPresents() { return physicalPresents; }
    public long firstActualPresentNs() { return firstActualPresentNs; }
    public long lastActualPresentNs() { return lastActualPresentNs; }
    public long physicalEndpoints() { return physicalEndpoints; }
    public long physicalGenerated() { return physicalGenerated; }
    public long deadlineMisses() { return deadlineMisses; }
    public long desiredSlotMisses() { return desiredSlotMisses; }
    public long earliestPresentMisses() { return earliestPresentMisses; }
    public long earlyPresentViolations() { return earlyPresentViolations; }
    public long earlyDesiredSlotMisses() { return earlyDesiredSlotMisses; }
    public long lateDesiredSlotMisses() { return lateDesiredSlotMisses; }
    public long minPresentMarginNs() {
        return physicalPresents == 0L ? 0L : minPresentMarginNs;
    }
    public long maxPresentMarginNs() { return maxPresentMarginNs; }
    public long lastPresentMarginNs() {
        return physicalPresents == 0L ? 0L : lastPresentMarginNs;
    }
    public long minLateSlotPresentMarginNs() {
        return lateDesiredSlotMisses == 0L ? 0L : minLateSlotPresentMarginNs;
    }
    public long maxLateSlotPresentMarginNs() {
        return lateDesiredSlotMisses == 0L ? 0L : maxLateSlotPresentMarginNs;
    }
    public long maxEnqueueWallNs() { return maxEnqueueWallNs; }
    public long maxGpuWorkNs() { return maxGpuWorkNs; }
    public long maxCombinedNs() { return maxCombinedNs; }
    public long maxDesiredSlotErrorNs() { return maxDesiredSlotErrorNs; }
    public long minSignedDesiredSlotErrorNs() {
        return physicalPresents == 0L ? 0L : minSignedDesiredSlotErrorNs;
    }
    public long maxSignedDesiredSlotErrorNs() {
        return physicalPresents == 0L ? 0L : maxSignedDesiredSlotErrorNs;
    }
    public long lastSignedDesiredSlotErrorNs() {
        return physicalPresents == 0L ? 0L : lastSignedDesiredSlotErrorNs;
    }
    public long maxEndpointSpanNs() { return maxEndpointSpanNs; }
    public double minGeneratedPhase() {
        return physicalGenerated == 0L ? 0.0 : minGeneratedPhase;
    }
    public double maxGeneratedPhase() {
        return physicalGenerated == 0L ? 0.0 : maxGeneratedPhase;
    }
    public int targetScansPerOutput() { return targetScansPerOutput; }
    public int targetPresentationPipelineScans() {
        return targetPresentationPipelineScans;
    }
    public long targetRefreshDurationNs() { return targetRefreshDurationNs; }
    public long presentationEpoch() { return presentationEpoch; }
    public boolean identityMatches(int scansPerOutput, long refreshDurationNs,
                                   long expectedPresentationEpoch,
                                   int expectedPresentationPipelineScans) {
        return targetScansPerOutput == scansPerOutput &&
                targetRefreshDurationNs == refreshDurationNs &&
                presentationEpoch == expectedPresentationEpoch &&
                targetPresentationPipelineScans ==
                        expectedPresentationPipelineScans;
    }

    /** Rolling p95 of record+GPU work; exact for all samples up to capacity. */
    public long combinedP95Ns() {
        return percentile(combinedDurationsNs, combinedHead, combinedCount, 0.95);
    }

    /** Rolling p05 of the driver's queue-processing margin. */
    public long presentMarginP05Ns() {
        return percentile(presentMarginsNs, presentMarginHead,
                presentMarginCount, 0.05);
    }

    /** Rolling median of the driver's queue-processing margin. */
    public long presentMarginP50Ns() {
        return percentile(presentMarginsNs, presentMarginHead,
                presentMarginCount, 0.50);
    }

    /** Rolling p95 of the driver's queue-processing margin. */
    public long presentMarginP95Ns() {
        return percentile(presentMarginsNs, presentMarginHead,
                presentMarginCount, 0.95);
    }

    private void appendCombined(long value) {
        if (combinedCount == CAPACITY) {
            combinedHead = (combinedHead + 1) % CAPACITY;
            --combinedCount;
        }
        combinedDurationsNs[(combinedHead + combinedCount) % CAPACITY] = value;
        ++combinedCount;
    }

    private void appendPresentMargin(long value) {
        if (presentMarginCount == CAPACITY) {
            presentMarginHead = (presentMarginHead + 1) % CAPACITY;
            --presentMarginCount;
        }
        presentMarginsNs[(presentMarginHead + presentMarginCount) % CAPACITY] =
                value;
        ++presentMarginCount;
    }

    private static long percentile(long[] values, int head, int count,
                                   double fraction) {
        if (count == 0) return 0L;
        long[] sorted = new long[count];
        for (int index = 0; index < count; ++index)
            sorted[index] = values[(head + index) % values.length];
        Arrays.sort(sorted);
        int rank = Math.max(0,
                (int) Math.ceil(sorted.length * fraction) - 1);
        return sorted[rank];
    }

    private void adoptTarget(int scansPerOutput, long refreshDurationNs,
                             long newPresentationEpoch,
                             int newPresentationPipelineScans) {
        if (targetScansPerOutput == scansPerOutput &&
                targetRefreshDurationNs == refreshDurationNs &&
                presentationEpoch == newPresentationEpoch &&
                targetPresentationPipelineScans ==
                        newPresentationPipelineScans) return;
        targetScansPerOutput = scansPerOutput;
        targetRefreshDurationNs = refreshDurationNs;
        presentationEpoch = newPresentationEpoch;
        targetPresentationPipelineScans = newPresentationPipelineScans;
        combinedHead = 0;
        combinedCount = 0;
        presentMarginHead = 0;
        presentMarginCount = 0;
        firstActualPresentNs = 0L;
        lastActualPresentNs = 0L;
        physicalPresents = 0L;
        physicalEndpoints = 0L;
        physicalGenerated = 0L;
        deadlineMisses = 0L;
        desiredSlotMisses = 0L;
        earliestPresentMisses = 0L;
        earlyPresentViolations = 0L;
        earlyDesiredSlotMisses = 0L;
        lateDesiredSlotMisses = 0L;
        minPresentMarginNs = Long.MAX_VALUE;
        maxPresentMarginNs = 0L;
        lastPresentMarginNs = 0L;
        minLateSlotPresentMarginNs = Long.MAX_VALUE;
        maxLateSlotPresentMarginNs = 0L;
        maxEnqueueWallNs = 0L;
        maxGpuWorkNs = 0L;
        maxCombinedNs = 0L;
        maxDesiredSlotErrorNs = 0L;
        minSignedDesiredSlotErrorNs = Long.MAX_VALUE;
        maxSignedDesiredSlotErrorNs = Long.MIN_VALUE;
        lastSignedDesiredSlotErrorNs = 0L;
        maxEndpointSpanNs = 0L;
        minGeneratedPhase = Double.POSITIVE_INFINITY;
        maxGeneratedPhase = Double.NEGATIVE_INFINITY;
    }

    private static long saturatingAdd(long left, long right) {
        if (left < 0L || right < 0L || left > Long.MAX_VALUE - right)
            return Long.MAX_VALUE;
        return left + right;
    }

    private static long saturatingMultiply(long value, int multiplier) {
        if (value <= 0L || multiplier <= 0 || value > Long.MAX_VALUE / multiplier)
            return 0L;
        return value * multiplier;
    }

    private static long absoluteDifference(long left, long right) {
        return left >= right ? left - right : right - left;
    }
}
