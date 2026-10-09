package com.thorium.lucent.video;

import java.util.Arrays;

/**
 * Fail-closed timing evidence for an external generator whose completed image
 * is presented by EmuFusion through its own EGL window.
 *
 * <p>Unlike the legacy Vulkan-WSI evidence, this path has no backend-visible
 * surface, swapchain present ID, earliest-present time, or queue margin.
 * EmuFusion owns the immutable request, EGL timestamp, draw, swap, Android
 * frame ID, and physical-present timestamp.  Qualification therefore binds
 * those facts directly and never fabricates unavailable WSI fields.</p>
 */
public final class AppOwnedExternalPresentationEvidence {
    private static final int CAPACITY = 256;
    private static final int MIN_GENERATED_SAMPLES = 30;
    private static final long MIN_QUALIFIED_SPAN_NS = 2_000_000_000L;
    private static final long MIN_PRESENT_TOLERANCE_NS = 150_000L;
    private static final double MAX_PRESENT_ERROR_FRACTION = 0.02;

    private final long[] criticalDurationsNs = new long[CAPACITY];
    private int criticalHead;
    private int criticalCount;
    private int targetScansPerOutput;
    private long targetPanelPeriodNs;
    private long presentationEpoch;
    private long lastFrameId;
    private long firstActualPresentNs;
    private long lastActualPresentNs;
    private long physicalPresents;
    private long physicalEndpoints;
    private long physicalGenerated;
    private long submissionDeadlineMisses;
    private long submissionDurationOverruns;
    private long desiredSlotMisses;
    private long earlyDesiredSlotMisses;
    private long lateDesiredSlotMisses;
    private long gpuBudgetMisses;
    private long maxBindWallNs;
    private long maxSwapWallNs;
    private long maxGpuWorkNs;
    private long maxCriticalWallNs;
    private long maxDesiredSlotErrorNs;
    private long minSignedDesiredSlotErrorNs = Long.MAX_VALUE;
    private long maxSignedDesiredSlotErrorNs = Long.MIN_VALUE;
    private long lastSignedDesiredSlotErrorNs;
    private long maxEndpointSpanNs;
    private double minGeneratedPhase = Double.POSITIVE_INFINITY;
    private double maxGeneratedPhase = Double.NEGATIVE_INFINITY;

    public void record(
            FrameGenerationPresentationRequest request,
            long frameId, long actualPresentTimeNs,
            int scansPerOutput, long panelPeriodNs,
            long bindWallNs, long swapWallNs, long swapCompletedNs,
            long gpuWorkNs) {
        if (request == null || frameId <= 0L || actualPresentTimeNs <= 0L ||
                scansPerOutput <= 0 || panelPeriodNs <= 0L ||
                bindWallNs <= 0L || swapWallNs <= 0L ||
                swapCompletedNs <= 0L || gpuWorkNs < 0L ||
                request.presentationPipelineScans() != 0)
            throw new IllegalArgumentException(
                    "app-owned presentation evidence row is invalid");
        adoptTarget(scansPerOutput, panelPeriodNs,
                request.presentationEpoch());
        if (frameId <= lastFrameId ||
                actualPresentTimeNs <= lastActualPresentNs)
            throw new IllegalStateException(
                    "app-owned physical evidence is not monotonic");
        lastFrameId = frameId;
        lastActualPresentNs = actualPresentTimeNs;
        if (firstActualPresentNs == 0L)
            firstActualPresentNs = actualPresentTimeNs;

        long outputIntervalNs = checkedMultiply(panelPeriodNs, scansPerOutput);
        long criticalWallNs = checkedAdd(bindWallNs, swapWallNs);
        long desiredNs = request.desiredPhysicalPresentTimeNs();
        long desiredSlotErrorNs = absoluteDifference(
                actualPresentTimeNs, desiredNs);
        long signedDesiredSlotErrorNs = actualPresentTimeNs >= desiredNs ?
                desiredSlotErrorNs : -desiredSlotErrorNs;
        long toleranceNs = Math.max(MIN_PRESENT_TOLERANCE_NS,
                Math.round(outputIntervalNs * MAX_PRESENT_ERROR_FRACTION));
        if (desiredNs <= 0L ||
                request.driverDesiredPresentTimeNs() <= 0L ||
                request.driverDesiredPresentTimeNs() >= desiredNs ||
                request.hardCompletionDeadlineNs() !=
                        request.driverDesiredPresentTimeNs() ||
                request.hasCompositorFrameTimeline())
            throw new IllegalStateException(
                    "app-owned request does not preserve its physical contract");

        ++physicalPresents;
        if (request.isGenerated()) {
            if (gpuWorkNs <= 0L || !request.hasAdjacentPair() ||
                    !(request.phase() > 0.0 && request.phase() < 1.0) ||
                    !Double.isFinite(request.phase()))
                throw new IllegalStateException(
                        "app-owned generated evidence identity is invalid");
            ++physicalGenerated;
            long endpointSpanNs = request.rightTimestampNs() -
                    request.leftTimestampNs();
            if (endpointSpanNs <= 0L)
                throw new IllegalStateException(
                        "app-owned endpoint span is invalid");
            maxEndpointSpanNs = Math.max(maxEndpointSpanNs, endpointSpanNs);
            minGeneratedPhase = Math.min(minGeneratedPhase, request.phase());
            maxGeneratedPhase = Math.max(maxGeneratedPhase, request.phase());
            if (gpuWorkNs > endpointSpanNs) ++gpuBudgetMisses;
        } else {
            if (gpuWorkNs != 0L ||
                    (request.phase() != 0.0 && request.phase() != 1.0))
                throw new IllegalStateException(
                        "app-owned endpoint evidence is not exact passthrough");
            ++physicalEndpoints;
        }
        // A blocking swap can consume an interval while an earlier submission
        // still has ample deadline lead. Duration is capacity telemetry, not
        // proof of a missed immutable deadline or physical display slot.
        if (criticalWallNs > outputIntervalNs) ++submissionDurationOverruns;
        if (swapCompletedNs > request.hardCompletionDeadlineNs())
            ++submissionDeadlineMisses;
        if (desiredSlotErrorNs > toleranceNs) {
            ++desiredSlotMisses;
            if (signedDesiredSlotErrorNs < 0L)
                ++earlyDesiredSlotMisses;
            else
                ++lateDesiredSlotMisses;
        }
        maxBindWallNs = Math.max(maxBindWallNs, bindWallNs);
        maxSwapWallNs = Math.max(maxSwapWallNs, swapWallNs);
        maxGpuWorkNs = Math.max(maxGpuWorkNs, gpuWorkNs);
        maxCriticalWallNs = Math.max(maxCriticalWallNs, criticalWallNs);
        maxDesiredSlotErrorNs = Math.max(
                maxDesiredSlotErrorNs, desiredSlotErrorNs);
        minSignedDesiredSlotErrorNs = Math.min(
                minSignedDesiredSlotErrorNs, signedDesiredSlotErrorNs);
        maxSignedDesiredSlotErrorNs = Math.max(
                maxSignedDesiredSlotErrorNs, signedDesiredSlotErrorNs);
        lastSignedDesiredSlotErrorNs = signedDesiredSlotErrorNs;
        appendCritical(criticalWallNs);
    }

    public void beginEpoch(int scansPerOutput, long panelPeriodNs,
                           long epoch) {
        if (scansPerOutput <= 0 || panelPeriodNs <= 0L || epoch <= 0L)
            throw new IllegalArgumentException(
                    "app-owned evidence epoch identity is invalid");
        adoptTarget(scansPerOutput, panelPeriodNs, epoch);
    }

    /**
     * Starts a fresh qualified observation window without changing scheduler
     * ownership.
     *
     * <p>Android keeps only a short frame-event history. A frame whose display
     * timestamp is still pending when that history wraps is reported as
     * unavailable, not as physically dropped. That must invalidate every
     * timing sample collected before it, but it must not fabricate a drop or
     * tear down an otherwise smooth presentation schedule. The caller records
     * the unavailable outcome separately, then uses this method so only a new
     * clean two-second/generated-sample window can qualify.</p>
     */
    public void restartWindow(int scansPerOutput, long panelPeriodNs,
                              long epoch) {
        if (scansPerOutput <= 0 || panelPeriodNs <= 0L || epoch <= 0L)
            throw new IllegalArgumentException(
                    "app-owned evidence window identity is invalid");
        targetScansPerOutput = scansPerOutput;
        targetPanelPeriodNs = panelPeriodNs;
        presentationEpoch = epoch;
        clearMeasurements();
    }

    public boolean timingQualified() {
        return physicalGenerated >= MIN_GENERATED_SAMPLES &&
                firstActualPresentNs > 0L &&
                lastActualPresentNs - firstActualPresentNs >=
                        MIN_QUALIFIED_SPAN_NS &&
                submissionDeadlineMisses == 0L &&
                desiredSlotMisses == 0L && gpuBudgetMisses == 0L;
    }

    public boolean identityMatches(int scansPerOutput, long panelPeriodNs,
                                   long epoch) {
        return targetScansPerOutput == scansPerOutput &&
                targetPanelPeriodNs == panelPeriodNs &&
                presentationEpoch == epoch;
    }

    public long physicalPresents() { return physicalPresents; }
    public long firstActualPresentNs() { return firstActualPresentNs; }
    public long lastActualPresentNs() { return lastActualPresentNs; }
    public long physicalEndpoints() { return physicalEndpoints; }
    public long physicalGenerated() { return physicalGenerated; }
    public long submissionDeadlineMisses() { return submissionDeadlineMisses; }
    public long submissionDurationOverruns() { return submissionDurationOverruns; }
    public long desiredSlotMisses() { return desiredSlotMisses; }
    public long earlyDesiredSlotMisses() { return earlyDesiredSlotMisses; }
    public long lateDesiredSlotMisses() { return lateDesiredSlotMisses; }
    public long gpuBudgetMisses() { return gpuBudgetMisses; }
    public long maxBindWallNs() { return maxBindWallNs; }
    public long maxSwapWallNs() { return maxSwapWallNs; }
    public long maxGpuWorkNs() { return maxGpuWorkNs; }
    public long maxCriticalWallNs() { return maxCriticalWallNs; }
    public long criticalP95Ns() {
        return percentile(criticalDurationsNs, criticalHead,
                criticalCount, 0.95);
    }
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
    public long targetPanelPeriodNs() { return targetPanelPeriodNs; }
    public long presentationEpoch() { return presentationEpoch; }

    private void adoptTarget(int scansPerOutput, long panelPeriodNs,
                             long epoch) {
        if (targetScansPerOutput == scansPerOutput &&
                targetPanelPeriodNs == panelPeriodNs &&
                presentationEpoch == epoch) return;
        targetScansPerOutput = scansPerOutput;
        targetPanelPeriodNs = panelPeriodNs;
        presentationEpoch = epoch;
        clearMeasurements();
    }

    private void clearMeasurements() {
        criticalHead = 0;
        criticalCount = 0;
        lastFrameId = 0L;
        firstActualPresentNs = 0L;
        lastActualPresentNs = 0L;
        physicalPresents = 0L;
        physicalEndpoints = 0L;
        physicalGenerated = 0L;
        submissionDeadlineMisses = 0L;
        submissionDurationOverruns = 0L;
        desiredSlotMisses = 0L;
        earlyDesiredSlotMisses = 0L;
        lateDesiredSlotMisses = 0L;
        gpuBudgetMisses = 0L;
        maxBindWallNs = 0L;
        maxSwapWallNs = 0L;
        maxGpuWorkNs = 0L;
        maxCriticalWallNs = 0L;
        maxDesiredSlotErrorNs = 0L;
        minSignedDesiredSlotErrorNs = Long.MAX_VALUE;
        maxSignedDesiredSlotErrorNs = Long.MIN_VALUE;
        lastSignedDesiredSlotErrorNs = 0L;
        maxEndpointSpanNs = 0L;
        minGeneratedPhase = Double.POSITIVE_INFINITY;
        maxGeneratedPhase = Double.NEGATIVE_INFINITY;
    }

    private void appendCritical(long value) {
        if (criticalCount == CAPACITY) {
            criticalHead = (criticalHead + 1) % CAPACITY;
            --criticalCount;
        }
        criticalDurationsNs[(criticalHead + criticalCount) % CAPACITY] = value;
        ++criticalCount;
    }

    private static long percentile(long[] values, int head, int count,
                                   double fraction) {
        if (count == 0) return 0L;
        long[] sorted = new long[count];
        for (int index = 0; index < count; ++index)
            sorted[index] = values[(head + index) % values.length];
        Arrays.sort(sorted);
        int rank = Math.max(0,
                (int)Math.ceil(sorted.length * fraction) - 1);
        return sorted[rank];
    }

    private static long checkedAdd(long left, long right) {
        if (left <= 0L || right <= 0L || left > Long.MAX_VALUE - right)
            throw new IllegalStateException(
                    "app-owned critical-path duration overflow");
        return left + right;
    }

    private static long checkedMultiply(long value, long multiplier) {
        if (value <= 0L || multiplier <= 0L ||
                value > Long.MAX_VALUE / multiplier)
            throw new IllegalStateException(
                    "app-owned output interval overflow");
        return value * multiplier;
    }

    private static long absoluteDifference(long left, long right) {
        return left >= right ? left - right : right - left;
    }
}
