package com.thorium.lucent.video;

/**
 * Drift-corrected physical scan lattice derived only from actual-present rows.
 *
 * <p>The Vulkan refresh query is the nominal period used to resolve how many
 * whole scans separate two timestamps. The planning period is a long-baseline
 * quotient over at least 30 independently counted scans from the first
 * actual-present timestamp across scheduler epochs, never a moving copy of the
 * latest row. A longer baseline reduces fence-timestamp noise in the estimate;
 * it does not qualify physical cadence or desired-to-actual phase.</p>
 */
public final class PhysicalPresentationClock {
    // Keep the measurement baseline in physical scans: approximately 250 ms
    // at 120 Hz and 500 ms at 60 Hz. A second, fixed 500-ms gate deadlocked
    // b14 at 120 Hz: 52 measured scans already proved oscillator drift, but
    // nominal-period targets left the unchanged 250-us compositor-token gate
    // before any more presents could extend the baseline. This is oscillator
    // estimation only, not qualification of desired-versus-actual scan phase.
    private static final long MIN_ESTIMATE_SCANS = 30L;
    private static final long MAX_PERIOD_ERROR_DIVISOR = 4L;

    private long nominalPeriodNs;
    private long anchorNs;
    private long lastActualNs;
    private long observedScans;
    private long estimatedPeriodNs;
    // Phase is local to the current presentation epoch. The frequency estimate
    // spans epochs; applying it to a fixed newer anchor otherwise integrates
    // every small frequency error over the entire epoch. Track phase separately
    // from frequency, smoothing independently returned rows rather than callback
    // timestamps. Keep the original epoch scan ordinal when projecting back to
    // an origin so output divisors retain their even/odd (etc.) scan identity.
    private long trackedPhaseNs;
    private static final long PHASE_FILTER_DIVISOR = 8L;
    // Scheduler/content epochs do not restart the physical oscillator. Keep its
    // measurement independent of the per-epoch planning phase and scan count.
    private long frequencyAnchorNs;
    private long frequencyLastActualNs;
    private long frequencyScans;
    private long frequencyDiscontinuities;
    private long sustainedAnchorNs;
    private long sustainedScans;
    private static final long TRIM_WINDOW_NS = 20_000_000_000L;
    private static final long TRIM_SAMPLE_NS = 250_000_000L;
    // Sparse endpoints bound storage without sampling callback clocks. Keep
    // the endpoint just before the window boundary, so evidence is >=20s.
    private final long[] trimTimes = new long[128];
    private final long[] trimScans = new long[128];
    private int trimHead, trimCount;

    private void resetTrimWindow(long actualNs) {
        trimHead = 0;
        trimCount = 1;
        trimTimes[0] = actualNs;
        trimScans[0] = 0L;
    }

    private void recordTrimEndpoint(long actualNs) {
        int last = (trimHead + trimCount - 1) % trimTimes.length;
        if (actualNs - trimTimes[last] < TRIM_SAMPLE_NS) return;
        if (trimCount == trimTimes.length) {
            trimHead = (trimHead + 1) % trimTimes.length;
            --trimCount;
        }
        int next = (trimHead + trimCount++) % trimTimes.length;
        trimTimes[next] = actualNs;
        trimScans[next] = sustainedScans;
    }

    /** Records one strictly newer physical scanout timestamp. */
    public boolean record(long actualPresentNs, long newNominalPeriodNs) {
        return record(actualPresentNs, newNominalPeriodNs, actualPresentNs);
    }

    /**
     * Records physical scanout while retaining a same-scan planning-domain
     * phase. SurfaceControl frame-timeline searches use AChoreographer's
     * expected-scan clock; physical cadence and drift remain derived solely
     * from the independently returned present-fence timestamp.
     */
    public boolean record(long actualPresentNs, long newNominalPeriodNs,
                          long planningPhaseNs) {
        if (actualPresentNs <= 0L || newNominalPeriodNs <= 0L ||
                planningPhaseNs <= 0L) return false;
        if (nominalPeriodNs == newNominalPeriodNs &&
                frequencyLastActualNs > 0L && actualPresentNs <= frequencyLastActualNs)
            return false;
        if (anchorNs == 0L || nominalPeriodNs != newNominalPeriodNs) {
            boolean retainSameModeEstimate = anchorNs == 0L &&
                    nominalPeriodNs == newNominalPeriodNs &&
                    estimatedPeriodNs > 0L;
            if (nominalPeriodNs != newNominalPeriodNs) {
                frequencyAnchorNs = 0L;
                frequencyLastActualNs = 0L;
                frequencyScans = 0L;
                sustainedAnchorNs = 0L;
                sustainedScans = 0L;
            }
            nominalPeriodNs = newNominalPeriodNs;
            anchorNs = planningPhaseNs;
            trackedPhaseNs = planningPhaseNs;
            lastActualNs = actualPresentNs;
            observedScans = 0L;
            if (!retainSameModeEstimate)
                estimatedPeriodNs = newNominalPeriodNs;
            recordFrequencySample(actualPresentNs);
            return true;
        }
        if (actualPresentNs <= lastActualNs) return false;
        long deltaNs = actualPresentNs - lastActualNs;
        long scanDelta = roundedPositiveQuotient(deltaNs, nominalPeriodNs);
        if (scanDelta <= 0L || observedScans > Long.MAX_VALUE - scanDelta)
            return false;
        long modeledDeltaNs = saturatingMultiply(nominalPeriodNs, scanDelta);
        if (modeledDeltaNs == Long.MAX_VALUE ||
                absoluteDifference(deltaNs, modeledDeltaNs) >
                        nominalPeriodNs / MAX_PERIOD_ERROR_DIVISOR)
            return false;
        observedScans += scanDelta;
        lastActualNs = actualPresentNs;
        recordFrequencySample(actualPresentNs);
        long phaseAdvanceNs = saturatingMultiply(estimatedPeriodNs, scanDelta);
        if (phaseAdvanceNs == Long.MAX_VALUE ||
                trackedPhaseNs > Long.MAX_VALUE - phaseAdvanceNs) {
            trackedPhaseNs = 0L;
        } else if (trackedPhaseNs > 0L) {
            long predictedPhaseNs = trackedPhaseNs + phaseAdvanceNs;
            trackedPhaseNs = predictedPhaseNs +
                    (planningPhaseNs - predictedPhaseNs) / PHASE_FILTER_DIVISOR;
        }
        return estimatedPeriodNs > 0L;
    }

    private void recordFrequencySample(long actualPresentNs) {
        if (frequencyAnchorNs == 0L) {
            frequencyAnchorNs = actualPresentNs;
            frequencyLastActualNs = actualPresentNs;
            sustainedAnchorNs = actualPresentNs;
            sustainedScans = 0L;
            resetTrimWindow(actualPresentNs);
            return;
        }
        long deltaNs = actualPresentNs - frequencyLastActualNs;
        long scans = roundedPositiveQuotient(deltaNs, nominalPeriodNs);
        long modeledNs = saturatingMultiply(nominalPeriodNs, scans);
        if (scans <= 0L || frequencyScans > Long.MAX_VALUE - scans ||
                modeledNs == Long.MAX_VALUE ||
                absoluteDifference(deltaNs, modeledNs) >
                        nominalPeriodNs / MAX_PERIOD_ERROR_DIVISOR) {
            // A fresh logical epoch can follow an ambiguous idle/mode phase
            // gap. Do not invent its scan count or include it in an estimate.
            // The physical cadence ledger independently retains the real gap.
            ++frequencyDiscontinuities;
            frequencyAnchorNs = actualPresentNs;
            frequencyLastActualNs = actualPresentNs;
            frequencyScans = 0L;
            sustainedAnchorNs = actualPresentNs;
            sustainedScans = 0L;
            resetTrimWindow(actualPresentNs);
            return;
        }
        // Long gaps may retain a useful planning oscillator estimate, but
        // cannot earn continuous evidence for changing guest/audio speed.
        if (deltaNs > 250_000_000L || sustainedAnchorNs == 0L ||
                sustainedScans > Long.MAX_VALUE - scans) {
            sustainedAnchorNs = actualPresentNs;
            sustainedScans = 0L;
            resetTrimWindow(actualPresentNs);
        } else {
            sustainedScans += scans;
            recordTrimEndpoint(actualPresentNs);
        }
        frequencyScans += scans;
        frequencyLastActualNs = actualPresentNs;
        if (frequencyScans >= MIN_ESTIMATE_SCANS)
            estimatedPeriodNs = roundedPositiveQuotient(
                    actualPresentNs - frequencyAnchorNs, frequencyScans);
    }

    public boolean available() { return anchorNs > 0L && estimatedPeriodNs > 0L; }
    public long anchorNs() { return anchorNs; }
    /**
     * Phase-tracked origin for future app-owned EGL plans only. This is not a
     * measured timestamp or acceptance evidence, and never rewrites a submitted
     * deadline. Subtracting the counted epoch scans (not resetting the origin to
     * the latest row) preserves divisor phase. The planner must still exclude
     * already submitted scan slots when this prospective estimate changes.
     */
    public long trackedPlanningAnchorNs() {
        if (!available() || trackedPhaseNs <= 0L) return 0L;
        long elapsedNs = saturatingMultiply(estimatedPeriodNs, observedScans);
        if (elapsedNs == Long.MAX_VALUE || elapsedNs >= trackedPhaseNs) return 0L;
        return trackedPhaseNs - elapsedNs;
    }
    /** Most recent independently observed physical scanout timestamp. */
    public long lastActualNs() { return lastActualNs; }
    public long planningPeriodNs() { return estimatedPeriodNs; }
    public long nominalPeriodNs() { return nominalPeriodNs; }
    public long observedScans() { return observedScans; }
    public long frequencyObservedScans() { return frequencyScans; }
    public long frequencyDiscontinuities() { return frequencyDiscontinuities; }

    /**
     * Frequency evidence for a future guest/audio trim, not cadence acceptance.
     * Planning can bootstrap after 30 scans; changing gameplay requires a much
     * longer observation and recent physical feedback. Zero means unavailable.
     * Return the full quotient rather than rounding the period to nanoseconds.
     */
    public double sustainedFrequencyHz(long nowNs) {
        if (!available() || nowNs < frequencyLastActualNs ||
                nowNs - frequencyLastActualNs > 250_000_000L ||
                sustainedAnchorNs <= 0L || sustainedScans < MIN_ESTIMATE_SCANS)
            return 0.0;
        long cutoff = frequencyLastActualNs - TRIM_WINDOW_NS;
        int endpoint = -1;
        for (int i = 0; i < trimCount; ++i) {
            int index = (trimHead + i) % trimTimes.length;
            if (trimTimes[index] > cutoff) break;
            endpoint = index;
        }
        if (endpoint < 0) return 0.0;
        long spanNs = frequencyLastActualNs - trimTimes[endpoint];
        long scans = sustainedScans - trimScans[endpoint];
        double hz = scans * 1_000_000_000.0 / spanNs;
        return Double.isFinite(hz) && hz > 0.0 ? hz : 0.0;
    }

    /**
     * Starts a new scheduler/presentation epoch without discarding the
     * already-measured oscillator baseline for the same physical refresh mode.
     *
     * <p>The new epoch still needs an independently returned actual-present
     * row before it becomes available: frequency evidence survives, never the
     * old planning phase. A scheduler-only re-prime does not change the panel
     * oscillator. Falling back to the nominal refresh
     * duration for another complete calibration baseline can drift beyond the
     * strict physical slot tolerance before the bounded Vulkan queue has
     * observed enough new rows to relearn the same period.</p>
     *
     * <p>If the next row reports a different nominal refresh identity,
     * {@link #record(long, long)} discards the inherited estimate and starts
     * from that new nominal period.</p>
     */
    public void beginPresentationEpoch() {
        anchorNs = 0L;
        trackedPhaseNs = 0L;
        lastActualNs = 0L;
        observedScans = 0L;
    }

    public void reset() {
        nominalPeriodNs = 0L;
        anchorNs = 0L;
        lastActualNs = 0L;
        observedScans = 0L;
        estimatedPeriodNs = 0L;
        trackedPhaseNs = 0L;
        frequencyAnchorNs = 0L;
        frequencyLastActualNs = 0L;
        frequencyScans = 0L;
        frequencyDiscontinuities = 0L;
        sustainedAnchorNs = 0L;
        sustainedScans = 0L;
        trimHead = trimCount = 0;
    }

    private static long roundedPositiveQuotient(long numerator,
                                                long denominator) {
        if (numerator <= 0L || denominator <= 0L) return 0L;
        long half = denominator / 2L;
        if (numerator > Long.MAX_VALUE - half) return 0L;
        return (numerator + half) / denominator;
    }

    private static long saturatingMultiply(long value, long multiplier) {
        if (value <= 0L || multiplier <= 0L) return 0L;
        if (value > Long.MAX_VALUE / multiplier) return Long.MAX_VALUE;
        return value * multiplier;
    }

    private static long absoluteDifference(long left, long right) {
        return left >= right ? left - right : right - left;
    }
}
