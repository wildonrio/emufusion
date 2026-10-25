package com.thorium.emufusion.video;

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
    private long offModelReanchors;
    private long sustainedAnchorNs;
    private long sustainedScans;
    private static final long TRIM_WINDOW_NS = 20_000_000_000L;
    private static final long TRIM_SAMPLE_NS = 250_000_000L;
    // Present gaps shorter than this keep the sustained window: one 383-ms
    // allocation stall restarted the full 20-s admission. The bridged scans
    // are still counted from the physical rows, and longer idles restart.
    public static final long SUSTAINED_GAP_BRIDGE_NS = 1_000_000_000L;
    private static final long SUSTAINED_CONTIGUOUS_GAP_NS = 250_000_000L;
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
        // Count scans with the measured period: over a multi-second gap the
        // nominal one drifts by the panel's offset (119.94 Hz on a nominal
        // 120 Hz Thor mode: 4 us a scan).
        long periodNs = estimatedPeriodNs > 0L ? estimatedPeriodNs : nominalPeriodNs;
        long scanDelta = roundedPositiveQuotient(deltaNs, periodNs);
        if (scanDelta <= 0L || observedScans > Long.MAX_VALUE - scanDelta)
            return false;
        long modeledDeltaNs = saturatingMultiply(periodNs, scanDelta);
        if (modeledDeltaNs == Long.MAX_VALUE ||
                absoluteDifference(deltaNs, modeledDeltaNs) >
                        nominalPeriodNs / MAX_PERIOD_ERROR_DIVISOR) {
            // Off the scan model: re-anchor on this row. Keeping the old
            // anchor made every later row look off-model as well, and the
            // clock accepted nothing until an epoch reset (God of War II after
            // a 4-s load, ~20 s without generation, 2026-10-13).
            ++offModelReanchors;
            lastActualNs = actualPresentNs;
            trackedPhaseNs = planningPhaseNs;
            recordFrequencySample(actualPresentNs);
            return false;
        }
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
        // A sub-second stall is bridged only when the measured period counts
        // the same whole scans as the nominal one (no off-by-one over 120).
        boolean bridgedGap = deltaNs > SUSTAINED_CONTIGUOUS_GAP_NS &&
                deltaNs < SUSTAINED_GAP_BRIDGE_NS &&
                roundedPositiveQuotient(deltaNs, estimatedPeriodNs) == scans;
        if ((deltaNs > SUSTAINED_CONTIGUOUS_GAP_NS && !bridgedGap) ||
                sustainedAnchorNs == 0L ||
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
    /** Rows that did not fit the scan model and re-anchored the clock. */
    public long offModelReanchors() { return offModelReanchors; }

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
        int endpoint = sustainedBaselineEndpoint();
        if (endpoint < 0) return seedConfirmedByShortBaseline() ? seededFrequencyHz : provisionalFrequencyHz();
        long spanNs = frequencyLastActualNs - trimTimes[endpoint];
        long scans = sustainedScans - trimScans[endpoint];
        double hz = scans * 1_000_000_000.0 / spanNs;
        return Double.isFinite(hz) && hz > 0.0 ? hz : 0.0;
    }

    /** True once this session has its own full trim-window frequency baseline. */
    public boolean hasSustainedBaseline() { return sustainedBaselineEndpoint() >= 0; }

    private int sustainedBaselineEndpoint() {
        long cutoff = frequencyLastActualNs - TRIM_WINDOW_NS;
        int endpoint = -1;
        for (int i = 0; i < trimCount; ++i) {
            int index = (trimHead + i) % trimTimes.length;
            if (trimTimes[index] > cutoff) break;
            endpoint = index;
        }
        return endpoint;
    }

    // A panel's oscillator does not change between sessions, but measuring it
    // to a few ppm takes a full trim window (20 s) of contiguous presents, and
    // generation waits for it -- every launch started with ~20-35 s of plain
    // output (Thor, 2026-10-11). A rate measured earlier for the same display
    // mode stands in until this session's own baseline exists, and only while
    // a live short measurement agrees with it.
    private double seededFrequencyHz;
    private static final long SEED_CONFIRM_MIN_SPAN_NS = 2_000_000_000L;
    private static final double SEED_CONFIRM_TOLERANCE = 3.0e-4;

    // Without a usable seed -- none yet, or a live short measurement that
    // disagrees with it: the Thor's 120 Hz mode measured anywhere from 119.76
    // to 119.93 Hz from session to session, against the seed's 300-ppm
    // tolerance -- the most recent PROVISIONAL_MIN_SPAN_NS, when its two
    // halves agree within PROVISIONAL_TOLERANCE, stands in until the full
    // window exists. Paced cores otherwise ran on their nominal clock for the
    // first 20 s, their images sweeping through the scan (Double Dash waited
    // 3-7 ms for the callback that showed them, against ~1 ms once locked and
    // phase-moved). It is never remembered (only a full baseline is), and the
    // full window refines it like any later measurement.
    private static final long PROVISIONAL_MIN_SPAN_NS = 8_000_000_000L;
    private static final double PROVISIONAL_TOLERANCE = 2.0e-4;

    private double provisionalFrequencyHz() {
        if (trimCount < 3) return 0.0;
        int start = recentTrimEndpoint(PROVISIONAL_MIN_SPAN_NS);
        if (start < 0) return 0.0;
        long first = trimTimes[start];
        long spanNs = frequencyLastActualNs - first;
        long middle = first + spanNs / 2L;
        int split = -1;
        for (int i = 1; i < trimCount; ++i) {
            int index = (start + i) % trimTimes.length;
            if (index == (trimHead + trimCount) % trimTimes.length) break;
            if (trimTimes[index] >= middle) {
                split = index;
                break;
            }
        }
        if (split < 0 || trimTimes[split] >= frequencyLastActualNs) return 0.0;
        double early = (trimScans[split] - trimScans[start]) * 1_000_000_000.0 /
                (trimTimes[split] - first);
        double late = (sustainedScans - trimScans[split]) * 1_000_000_000.0 /
                (frequencyLastActualNs - trimTimes[split]);
        double hz = (sustainedScans - trimScans[start]) * 1_000_000_000.0 / spanNs;
        return Double.isFinite(early) && Double.isFinite(late) && Double.isFinite(hz) &&
                early > 0.0 && late > 0.0 && Math.abs(early / late - 1.0) <= PROVISIONAL_TOLERANCE ?
                hz : 0.0;
    }

    /** A rate measured in an earlier session for this mode; 0 clears it. */
    public void seedFrequencyHz(double hz) {
        seededFrequencyHz = Double.isFinite(hz) && hz > 0.0 ? hz : 0.0;
    }

    // The panel settles after waking and entering the mode: Thor, Double Dash
    // on 3.2.107, successive 2-s windows measured 119.834, 119.862, 119.887,
    // 119.899 Hz, then steady. Short measurements therefore use the most
    // recent span, not the whole window since it began: from the start, a
    // seed within 190 ppm of the steady rate was refused for ~18 s.
    private int recentTrimEndpoint(long spanNs) {
        long cutoff = frequencyLastActualNs - spanNs;
        for (int i = trimCount - 1; i >= 0; --i) {
            int index = (trimHead + i) % trimTimes.length;
            if (trimTimes[index] <= cutoff) return index;
        }
        return -1;
    }

    private boolean seedConfirmedByShortBaseline() {
        if (!(seededFrequencyHz > 0.0) || trimCount < 2) return false;
        int start = recentTrimEndpoint(SEED_CONFIRM_MIN_SPAN_NS);
        if (start < 0) return false;
        long spanNs = frequencyLastActualNs - trimTimes[start];
        long scans = sustainedScans - trimScans[start];
        double shortHz = scans * 1_000_000_000.0 / spanNs;
        return Double.isFinite(shortHz) &&
                Math.abs(shortHz / seededFrequencyHz - 1.0) <= SEED_CONFIRM_TOLERANCE;
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
