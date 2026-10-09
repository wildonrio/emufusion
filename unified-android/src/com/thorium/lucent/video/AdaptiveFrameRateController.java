package com.thorium.lucent.video;

/**
 * Chooses a stable real-frame tier and schedules its promotion to presentation.
 *
 * <p>The legacy visual tiers are 60, 40, 30 and 20 fps. Falling below a
 * tier is acknowledged quickly; moving back up requires sustained headroom so
 * a game hovering around a boundary cannot make interpolation cadence judder.
 * This controller drops excess visual frames but never changes simulation or
 * audio time.
 */
public final class AdaptiveFrameRateController {
    public static final int PRESENT_NONE = 0;
    public static final int PRESENT_REAL = 1;
    public static final int PRESENT_SYNTHETIC = 2;
    // Tier labels are conservative measurements, not permission to change
    // the source clock. UniformFrameRatePlan alone authorizes exact doubling:
    // on 120 Hz, 20->40 / 30->60 / 60->120, with 40 Direct; on 60 Hz,
    // 30->60, with 20 and 60 Direct. Unsupported fractional conversions
    // remain unqualified Direct even when a nearby tier label exists.
    private static final int[] TIERS_120 = {60, 40, 30, 20};
    private static final int[] TIERS_60 = {60, 30, 20};
    private static final double SIXTY_HZ_PROTOCOL_MAX_PANEL_HZ = 90.0;
    private static final double MAX_GENERATION_FACTOR =
            UniformFrameRatePlan.MAX_GENERATION_FACTOR;
    private int[] tiers = TIERS_120;
    private static final int MIN_SAMPLES = 10;
    private static final int INITIAL_TIER_PERIODS = 90;
    // Once a tier has been acquired, change it only from a complete rolling
    // ten-second producer-time observation. Ninety 60-Hz samples are only
    // 1.5 seconds: real Wii/GC content contains bounded logo, blink and camera
    // intervals that made that short window alternate 60->50->60 even while
    // the surrounding unique throughput remained nominal 60. Ten seconds is
    // still dynamic, but cannot turn a momentary content pattern into visible
    // output-cadence churn.
    private static final long TIER_DECISION_WINDOW_NS = 10_000_000_000L;
    // The Thor's measured source/panel clocks can sit slightly above nominal
    // 60 (for example60.098 Hz). A 600-slot ring then spans less than the
    // required ten seconds and can never become settled evidence. Keep enough
    // headroom for arbitrary stable clocks near the supported ceiling.
    private static final int MAX_TIER_DECISION_PERIODS = 2048;
    // A clock that failed the strict canonical-period proof must not reclaim
    // the exact max-2x boundary from the first sliding ten-second window that
    // happens to look clean. Physical N64 PTS did exactly that, alternating
    // 40/60 every 10-45 seconds. Require a fresh uninterrupted thirty-second
    // timestamp proof for acquisition/re-acquisition; the initial 90-period
    // bootstrap remains available only when startup itself is already exact.
    private static final long CANONICAL_REACQUIRE_WINDOW_NS =
            30_000_000_000L;
    // Ten elapsed periods cover whole cycles of the native-60 visual schedules
    // used by common games: 5/6 (50 Hz), 4/6 (40 Hz), and 3/6 (30 Hz). A
    // bounded throughput window measures those rational schedules exactly;
    // an EWMA of individual periods oscillates at every long interval and can
    // reset tier votes forever even though long-run throughput is stable.
    private static final int RATE_WINDOW_PERIODS = 10;
    // A strict max-2x plan sits exactly on the 30->60 and 60->120
    // boundaries.  Immutable timestamps still contain bounded delivery and
    // nanosecond quantization jitter, so feeding their raw average into the
    // plan can alternate a nominal 29.999/30.001 source between 40 and 60 on
    // consecutive callbacks.  Normalize only clocks whose timestamp periods
    // prove one stable canonical identity.  The tolerances are deliberately
    // much narrower than the 29.97-vs-30 and 59.94-vs-60 separations, and the
    // RMS test rejects an unstable low/high mixture with the same flattering
    // mean.
    private static final double[] CANONICAL_TIMESTAMP_SOURCE_HZ = {
            20.0, 24000.0 / 1001.0, 24.0,
            30000.0 / 1001.0, 30.0, 40.0,
            60000.0 / 1001.0, 60.0
    };
    private static final double CANONICAL_MEAN_TOLERANCE_HZ = 0.025;
    // Retention starts only after an independently strict acquisition. TWINE
    // physically produced an otherwise exact 300-period window at
    // 29.950083 Hz: every span and submission ordinal was ordinary, yet the
    // 0.025-Hz acquisition tolerance revoked its already-proven30 identity.
    // Admit that bounded N64 clock bias only for retention. A true29.90 clock
    // remains outside this envelope and must still fall back to Direct.
    private static final double CANONICAL_RETENTION_MEAN_TOLERANCE_HZ = 0.060;
    // Ordinal-proven held frames (exact doubled/tripled spans) admitted by
    // the proven-duplicates clock matcher: acquisition and retention form a
    // Schmitt band so a game whose holds cluster near the bound does not
    // oscillate between a funded lattice and the 30-second re-acquisition.
    private static final int ACQUISITION_ORDINARY_PERCENT = 90;
    private static final int RETENTION_ORDINARY_PERCENT = 80;
    // Slot-lattice producers credit every dropped guest frame to its lattice
    // slot with the lattice-implied ordinal, so a held slot is proven rather
    // than inferred; Cemu titles on the Thor drop 10-25 percent under load
    // (wiiu-b37: 53 unique of 60) and the renderer bridges each single hold
    // by interpolation.  Wider budgets there keep the exact 60 lattice
    // instead of leaving the game direct at a wandering 42-56.
    private static final int SLOT_LATTICE_ACQUISITION_ORDINARY_PERCENT = 75;
    private static final int SLOT_LATTICE_RETENTION_ORDINARY_PERCENT = 65;

    private int acquisitionOrdinaryPercent() {
        return slotLatticeProducer ? SLOT_LATTICE_ACQUISITION_ORDINARY_PERCENT :
                ACQUISITION_ORDINARY_PERCENT;
    }

    private int retentionOrdinaryPercent() {
        return slotLatticeProducer ? SLOT_LATTICE_RETENTION_ORDINARY_PERCENT :
                RETENTION_ORDINARY_PERCENT;
    }
    // (2026-09-01) Slot-lattice producers (the Cemu/Eden native adapters)
    // stamp each present on the next real-time slot of the trusted timeline;
    // a guest frame that was never presented is a doubled span with ONE
    // submission.  Physically it is the held image the libretro path proves
    // with a doubled ordinal (Switch run switch-b36 logged 1005 such spans
    // as timeline discontinuities and cut the pair at each one), so in this
    // mode the missing submissions are credited to the span: the decision
    // ring records the lattice-implied ordinal gap and the pair is bridged.
    private boolean slotLatticeProducer;

    public void setSlotLatticeProducer(boolean value) {
        slotLatticeProducer = value;
    }
    private static final double CANONICAL_NEAREST_MARGIN_HZ = 0.015;
    // Choreographer's first bounded observation on the physical Thor measured
    // 120.0448 Hz while both the selected Android mode and HWC period identify
    // the panel as nominal120.  Treating that tiny startup bias as an arbitrary
    // faster panel makes a proven20 source miss the exact three-scan 20->40
    // plan and fall all the way to four scans (~30 Hz).  Panel clocks get a
    // separate tolerance that admits this measured bias but remains less than
    // half the 120-vs-120000/1001 separation (~0.120 Hz), so a timestamp-proven
    // 119.88-Hz rational mode cannot be rounded to120.
    private static final double PANEL_CANONICAL_MEAN_TOLERANCE_HZ = 0.055;
    private static final double PANEL_CANONICAL_NEAREST_MARGIN_HZ = 0.045;
    private static final double CANONICAL_PERIOD_RMS_FRACTION = 0.006;
    private static final double CANONICAL_PERIOD_MAX_FRACTION = 0.03;
    // Some emulator bridges expose an exact source grid through immutable
    // submission ordinals while SurfaceTexture delivery itself has bounded
    // scheduler jitter. Physical Ocarina is one such stream: every distinct
    // image advances exactly three producer submissions and its thirty-second
    // logical mean is nominal20, while individual delivery spans vary by about
    // fifteen percent. This wider proof is restricted to low clocks with a
    // non-unit ordinal grid, so it cannot canonize an ordinary jittery 57-59
    // stream or the legacy sequence++ near20 fixture.
    private static final double ORDINAL_GRID_PERIOD_RMS_FRACTION = 0.03;
    private static final double ORDINAL_GRID_PERIOD_MAX_FRACTION = 0.20;
    private static final double UNPROVEN_BOUNDARY_GUARD_HZ = 0.02;
    // The durable lower bound, not a momentary aggregate mean, decides whether
    // a strict 2x boundary is funded. Physical N64 Zelda varied from roughly
    // 19.3 to 21.1 unique images/second while its ten-second lower bound stayed
    // below20; the former +/-0.25-Hz neighborhood let those harmless high
    // clusters alternate the uniform target between30 and40. Cover the full
    // observed boundary-jitter envelope. A stable arbitrary21-Hz clock may
    // retain its measured identity but cannot qualify doubling on120.
    private static final double BOUNDARY_NEIGHBORHOOD_HZ = 1.5;
    private static final double CLEAR_DEFICIT_HZ = 1.0;
    // A source that sustains 50-59 over the ten-second decision window gets
    // the conservative40 tier label without changing its source clock. The
    // former 4-Hz hold (which kept Dolphin at "60" while it delivered a
    // genuine 57.8, run gc-b11) is reduced to the same one-Hz scheduler
    // allowance every other tier uses.  The complete-window mean, not a
    // one-second bucket, feeds this comparison.
    private static final double SIXTY_TIER_SCHEDULER_HOLD_HZ = 1.0;
    // The generator needs two temporally adjacent real images. Below the
    // lowest supported 20-FPS tier there is no honest fixed cadence to fill:
    // extrapolating an old vector for the missing 50+ ms turns ordinary
    // emulator slowdown into large smears and wobble. Keep presenting the
    // newest real image until the producer recovers instead.
    private static final double MIN_GENERATION_SOURCE_HZ = 20.0;

    // Display.getRefreshRate() describes the selected Android mode, but the
    // temporal contract is owned by the physical Choreographer clock.  Latch
    // one stable two-second observation per mode instead of rounding either
    // clock to an integer. Missed callbacks are normalized by their nearest
    // mode-period multiple; they therefore cannot make a 120-Hz panel look
    // like a slower arbitrary panel clock.
    private static final int PANEL_CLOCK_PERIODS = 240;
    private static final int PANEL_CLOCK_MAX_MULTIPLE = 8;
    private static final double PANEL_CLOCK_MODE_TOLERANCE_FRACTION = 0.05;
    private static final double PANEL_CLOCK_PERIOD_RMS_FRACTION = 0.002;
    private static final double PANEL_CLOCK_PERIOD_MAX_FRACTION = 0.01;
    private static final double[] CANONICAL_PANEL_HZ = {
            60000.0 / 1001.0, 60.0,
            120000.0 / 1001.0, 120.0
    };

    private double displayRefreshHz;
    /** Generation ceiling for the uniform plan; an external fixed-midpoint backend lowers it to 2. */
    private volatile double maxGenerationFactor = UniformFrameRatePlan.MAX_GENERATION_FACTOR;

    public void setMaxGenerationFactor(double factor) {
        maxGenerationFactor = Double.isFinite(factor)
                ? Math.min(UniformFrameRatePlan.MAX_GENERATION_FACTOR,
                        Math.max(1.0, factor)) : Double.NaN;
    }

    public double maxGenerationFactor() { return maxGenerationFactor; }
    private long displayPeriodNs;
    private double declaredDisplayRefreshHz;
    private long declaredDisplayPeriodNs;
    private double measuredDisplayRefreshHz;
    private final long[] panelPeriodsNs = new long[PANEL_CLOCK_PERIODS];
    // Long-baseline physical scan clock: whole accepted callback intervals
    // over tens of seconds resolve the panel to a few ppm, far finer than
    // the canonical latch above (which snaps 120.008 to 120.000). This is
    // measurement evidence; it does not itself synchronize any core clock.
    private static final long PANEL_BASELINE_MIN_SPAN_NS = 20_000_000_000L;
    private long panelBaselineStartNs;
    private long panelBaselineLastNs;
    private long panelBaselinePeriods;
    private long panelPeriodSumNs;
    private int panelPeriodIndex;
    private int panelPeriodCount;
    private long previousDisplayFrameNs;
    // Measure frames advanced over bounded elapsed time, then invert once.
    // This avoids both arithmetic-mean-of-Hz bias and periodic tier oscillation.
    private double measuredProducerPeriodNs;
    private final long[] producerPeriodsNs = new long[RATE_WINDOW_PERIODS];
    private long producerPeriodSumNs;
    private int producerPeriodIndex;
    private int producerPeriodCount;
    private long previousProducerNs;
    private long latestSequence;
    private long promotedSequence;
    private long lastPromotionNs;
    private long nextPromotionNs;
    private long nextPresentationNs;
    private int scheduledOutputFps;
    private boolean midpointPending;
    private long midpointPairSequence;
    private long midpointDueNs;
    private int midpointSlots = 1;
    private int midpointSlotIndex = 1;
    private long midpointPromotionNs;
    private float selectedPhase = 1f;
    private long dueSelectedCount;
    private long dueNoEndpointCount;
    private long duePhaseClampedCount;
    private long realPriorityCount;
    private long syntheticQuotaSkippedCount;
    private long syntheticSelectedCount;
    private long syntheticPairCreatedCount;
    private long syntheticNotReadyCount;
    private long duplicatePairSelectionCount;
    private long presentationCallbackCount;
    private long lastSelectedSyntheticPair;
    private long presentationEpoch = 1L;
    private int producerSamples;
    private int lockedSourceFps = 60;
    private int authoritativeSourceFps;
    // Preserve the declared/timestamp-proven source clock exactly.  The
    // integer companion remains only for legacy policy labels and callers;
    // scheduling, phase, and uniform-output selection use this double.
    private double authoritativeSourceHz;
    // Hardware libretro GLES producers stamp every submitted core frame on
    // the core's declared AV timeline. This clock is NOT the game's unique
    // image rate and can never select S/T; it exists only to prove whether
    // SurfaceTexture delivered every intervening producer buffer. A mismatch
    // discards that interpolation interval while preserving source evidence.
    private double producerTimelineHz;
    private long producerTimelineDiscontinuityCount;
    // Rendering capability is an independent contract from source-rate
    // measurement.  If the qualified generator rejects itself, presentation
    // must become endpoint-only immediately; it may not silently fall through
    // to an older motion implementation while continuing to claim x2 output.
    private boolean generationAvailable = true;
    // External qualification backends are certified against an explicit
    // endpoint/midpoint contract for integer 2x paths. Built-in timestamp
    // resampling retains its existing arbitrary-phase behavior unless its
    // owner opts into this stronger presentation contract.
    private boolean exactDoubleEndpointLatticeRequired;
    // A rejected generator must retain the source clock that was physically
    // measured at rejection.  Continuing to reinterpret later pixel changes
    // can make a direct-only fallback churn through lower policy tiers even
    // though the emulator callback clock itself is unchanged.
    private int directFallbackSourceFps;
    // Buffered presentation is deliberately separate from the legacy
    // arrival-driven selector while DisplayFrameGenerator migrates to an
    // endpoint texture FIFO.  The renderer owns the textures and passes the
    // exact active pair on every due output slot.  This controller owns only
    // the fixed temporal lattice and never infers readiness from producer
    // callback timing.
    // Output slots are selected from physical Choreographer callbacks. A
    // rational accumulator is used instead of nanosecond target deadlines: a
    // missed callback consumes at most one slot and can never be followed by a
    // catch-up burst. outputFps() admits only exact panel divisors, so every
    // committed target has one invariant integer callback gap.
    private int bufferedPacingPanelScans;
    private int bufferedPacingCountdown;
    private int bufferedScheduledSourceFps;
    private int bufferedScheduledOutputFps;
    // The source playhead is tied to the immutable timestamps of endpoints
    // selected at the proven source tier. Raw unique delivery remains a
    // separate measurement clock; controlled endpoint selection prevents a
    // 24.95-Hz callback stream in the 20-Hz tier from overflowing the FIFO.
    private long bufferedTimelineDisplayAnchorNs;
    private long bufferedTimelineSourceAnchorNs;
    private long bufferedLastTargetSourceNs;
    private long bufferedObservedPanelPeriodNs;
    private int bufferedAdvanceAfterPresentation;
    private int bufferedExpectedAdvance;
    private long bufferedLeftSequence;
    private long bufferedRightSequence;
    private long bufferedLeftTimestampNs;
    private long bufferedRightTimestampNs;
    private long bufferedMinimumReprimeSequence;
    private long bufferedLastSyntheticLeftSequence;
    private long bufferedLastSyntheticRightSequence;
    private long bufferedLastSyntheticTargetSourceNs;
    private long bufferedCreditedRightSequence;
    // Each adjacent real interval funds at most two successfully presented
    // output samples. Credits are consumed by every REAL or SYNTHETIC swap;
    // this is the rate-domain max-2x invariant needed when arbitrary-phase
    // resampling selects two synthetic timestamps inside one interval.
    private int bufferedOutputCredits;
    // Pre-snap timeline targets: monotonicity is judged on the raw playhead,
    // not on a committed target that the symmetric snap moved by up to half
    // an output period (GameCube run gc-b15: a repeated physical slot made
    // the raw target trail the snapped one by 14-540 us and every such
    // callback tore the epoch down as a "source-target-reversal").
    private long bufferedLastRawTargetSourceNs;
    private long bufferedPendingRawTargetSourceNs;
    // Endpoint-to-slot drift telemetry: the signed residue between the
    // timeline target and the retained endpoint at every REAL snap, sampled
    // against display time. Its slope exposes source-vs-scan clock mismatch;
    // renderer re-anchoring alone cannot prove core-clock synchronization.
    private static final int DRIFT_SAMPLES = 96;
    private final long[] driftDisplayNs = new long[DRIFT_SAMPLES];
    private final long[] driftOffsetNs = new long[DRIFT_SAMPLES];
    private int driftCount;
    private int driftIndex;
    private long driftLastSampleNs;
    private long driftLatestOffsetNs;
    private int bufferedPendingPresentation;
    private int bufferedPendingAdvance;
    private long bufferedPendingLeftSequence;
    private long bufferedPendingRightSequence;
    private long bufferedPendingLeftTimestampNs;
    private long bufferedPendingRightTimestampNs;
    private long bufferedPendingTargetSourceNs;
    // Choreographer callback that selected the pending future physical scan.
    // This is distinct from bufferedPendingDisplayFrameNs, which is the
    // immutable scan time itself.
    private long bufferedPendingSelectionCallbackNs;
    private long bufferedPendingDisplayFrameNs;
    private long bufferedLastRealDisplayFrameNs;
    private float bufferedPendingPhase;
    private boolean bufferedPendingPrime;
    private boolean bufferedPendingMidpointOmitted;
    private long bufferedPresentationEpoch = 1L;
    // Diagnostic-only reason for the most recent buffered epoch boundary.
    // This does not influence scheduling; it makes physical qualification
    // failures attributable without weakening any fail-closed predicate.
    private String bufferedLastEpochReason = "initial";
    private long bufferedPresentationCount;
    private long bufferedRealCount;
    private long bufferedSyntheticCount;
    private long bufferedUnderrunCount;
    private long bufferedUnavailableSlotCount;
    // Lifetime count of real-priority pair advances for which no midpoint
    // could be presented on the available output slots. Epoch resets must not
    // erase callback/physical-clock shortages from the evidence.
    private long bufferedMidpointOmittedCount;
    private long bufferedReprimeCount;
    private long bufferedDuplicateTargetCount;
    // Diagnostics for the slot-lattice one-scan waits (wiiu-b47).
    private long bufferedLeadWaitCount;
    private long bufferedDuplicateWaitCount;
    private long bufferedPrimeWaitCount;
    private int bufferedPrimeWaitStreak;
    private boolean bufferedStarving;
    private static final boolean BUFFERED_STARVATION_FALLBACK_ENABLED = false;
    private long bufferedStarvationPresentedSequence;
    private long bufferedStarvationPresentCount;
    public long bufferedStarvationPresentCount() { return bufferedStarvationPresentCount; }
    public long bufferedLeadWaitCount() { return bufferedLeadWaitCount; }
    public long bufferedDuplicateWaitCount() { return bufferedDuplicateWaitCount; }
    public long bufferedPrimeWaitCount() { return bufferedPrimeWaitCount; }
    private boolean bufferedPrimed;
    private boolean bufferedPrimeNeedsPacingRephase;
    // Tier changes use elapsed throughput over a complete decision window,
    // never consecutive classifications of the short display window. This is
    // what lets a nominal 30-FPS source wander around 29.9/30.1 without either
    // becoming stuck at 20 or falsely upgrading a genuinely sustained 29.x.
    private final long[] decisionPeriodsNs =
            new long[MAX_TIER_DECISION_PERIODS];
    // Exact producer-callback ordinals paired with decisionPeriodsNs. A gap
    // greater than one means the pixel signature omitted one or more otherwise
    // valid emulator callbacks. This lets tier selection distinguish a real
    // slower callback clock from incidental identical images on a nominal-60
    // stream without treating the callbacks themselves as unique pixels.
    private final int[] decisionSubmissionGaps =
            new int[MAX_TIER_DECISION_PERIODS];
    private long decisionPeriodSumNs;
    private int decisionPeriodIndex;
    private int decisionPeriodCount;
    private boolean tierAcquired;
    private long previousProducerSubmissionOrdinal;
    private double measuredSubmissionPeriodNs;
    private boolean producerSubmissionClockObserved;
    // A nominal boundary clock is latched only from stable immutable
    // timestamp periods.  Without this latch, a raw average that wanders by a
    // few millihertz around30/60 would change the selected panel divisor on
    // every producer frame and reset the presentation epoch continuously.
    private double provenTimestampSourceHz;
    // Generation admission is stricter than recognizing a nominal callback
    // grid.  This clock is populated only when the UNIQUE-image timestamps
    // themselves form one durable clock.  Ordinal-proven duplicate callbacks
    // may remain useful diagnostics, but they cannot fund generated output:
    // physical Ocarina exposed a nominal20 callback grid while its distinct
    // images contained 100-150-ms holes, and treating that as a uniform20
    // source produced a visibly broken 30-Hz target.
    private double qualifiedUniqueTimestampSourceHz;
    private boolean qualifiedUniqueTimestampClockRejected;
    private double replacementUniqueClockHz;
    private long replacementUniqueClockSinceNs;
    private long trimOldPeriodNs, trimNewPeriodNs, trimNewEvidenceNs;
    private long trimStartedProducerNs;
    private double trimPanelHz;
    private boolean trimSparseGapUsed;
    private long canonicalReacquireEvidenceNs;
    private double canonicalReacquireCandidateHz;
    private int canonicalReacquireAnomalies;
    private int canonicalReacquirePeriods;
    // Frozen diagnostic captured before a qualified source clock is cleared.
    // The ordinary post-rejection summary follows the new reacquisition
    // candidate and therefore cannot identify the exact interval(s) that
    // revoked the old authority.
    private double lastRejectedQualifiedTimestampSourceHz;
    private String lastRejectedQualifiedTimestampProof = "none";

    public AdaptiveFrameRateController(double displayRefreshHz) {
        setDisplayRefreshHz(displayRefreshHz);
    }

    private boolean physicalDisplayClockQualified;

    public void setPhysicalDisplayRefreshHz(double value) {
        if (!Double.isFinite(value) || value < 20.0 || value > 1000.0 ||
                Math.abs(value / declaredDisplayRefreshHz - 1.0) > 0.0075) return;
        measuredDisplayRefreshHz = value;
        displayRefreshHz = value;
        displayPeriodNs = Math.max(1L, Math.round(1e9 / value));
        physicalDisplayClockQualified = true;
        // The guest may now be retimed by its owner. Old canonical source
        // evidence cannot survive this boundary and mask the fractional PTS.
        setAuthoritativeSourceHz(authoritativeSourceHz);
    }

    /** Refines an already qualified oscillator without discarding real PTS evidence.
     * This does not qualify source timestamps or rewrite the source playhead. */
    public boolean refinePhysicalDisplayRefreshHz(double value) {
        if (trimNewPeriodNs != 0L || !physicalDisplayClockQualified || !Double.isFinite(value) ||
                value < 20.0 || value > 1000.0 ||
                Math.abs(value / declaredDisplayRefreshHz - 1.0) > 0.0075 ||
                Math.abs(value / displayRefreshHz - 1.0) > 0.0005)
            return false;
        if (qualifiedUniqueTimestampSourceHz > 0.0 && trimNewPeriodNs == 0L) {
            long divisor = Math.round(displayRefreshHz / qualifiedUniqueTimestampSourceHz);
            if (divisor > 0L && Math.abs(displayRefreshHz /
                    qualifiedUniqueTimestampSourceHz - divisor) < 0.001) {
                trimOldPeriodNs = Math.round(1e9 / qualifiedUniqueTimestampSourceHz);
                trimNewPeriodNs = Math.round(1e9 * divisor / value);
                trimNewEvidenceNs = 0L;
                trimSparseGapUsed = false;
                trimStartedProducerNs = previousProducerNs;
                trimPanelHz = value;
                // The guest receives the requested rate from the renderer.
                // Keep the existing source/output plan together until its
                // new intervals are observed; publishing just the faster
                // panel here makes the strict 2x cap choose Direct briefly.
                return true;
            }
        }
        // Initial physical measurement is published by setPhysicalDisplayRefreshHz.
        // Do not move that bootstrap clock every few seconds while the guest
        // is still earning source qualification. Without an observed divisor
        // there is no coordinated transition, and repeated changes prevent
        // the source from ever establishing a stable window.
        return false;
    }

    public void setDisplayRefreshHz(double value) {
        physicalDisplayClockQualified = false;
        if (displayPeriodNs != 0L) discardPendingMidpoint();
        if (!Double.isFinite(value) || value < 20.0 || value > 1000.0) value = 60.0;
        declaredDisplayRefreshHz = value;
        tiers = value < SIXTY_HZ_PROTOCOL_MAX_PANEL_HZ ? TIERS_60 : TIERS_120;
        declaredDisplayPeriodNs = Math.max(1L,
                Math.round(1_000_000_000.0 / value));
        measuredDisplayRefreshHz = 0.0;
        panelPeriodSumNs = 0L;
        panelPeriodIndex = 0;
        panelPeriodCount = 0;
        previousDisplayFrameNs = 0L;
        displayRefreshHz = value;
        displayPeriodNs = declaredDisplayPeriodNs;
        nextPresentationNs = 0L;
        scheduledOutputFps = 0;
        midpointDueNs = 0L;
        selectedPhase = 1f;
        ++presentationEpoch;
        resetBufferedPresentation();
    }

    /**
     * Observes one immutable Choreographer frame timestamp.
     *
     * <p>The selected Android mode remains the scale reference that separates
     * a delayed callback from a real slower panel. Every accepted interval is
     * divided by its nearest whole number of mode scans, then the normalized
     * single-scan periods must pass strict RMS and maximum-error bounds. The
     * first complete stable observation is latched for the life of that mode;
     * tiny rolling-window changes therefore cannot churn the presentation
     * epoch or target badge.</p>
     *
     * @return true only when a newly proven physical panel clock replaced the
     * declared mode clock and published one presentation epoch boundary.
     */
    public boolean observeDisplayFrameTime(long frameTimeNs) {
        if (frameTimeNs <= 0L) return false;
        if (previousDisplayFrameNs > 0L) {
            long deltaNs = frameTimeNs - previousDisplayFrameNs;
            if (deltaNs <= 0L) {
                clearPanelClockCandidate();
                previousDisplayFrameNs = frameTimeNs;
                return false;
            }
            long referencePeriodNs = measuredDisplayRefreshHz > 0.0 ?
                    displayPeriodNs : declaredDisplayPeriodNs;
            long multiple = Math.round((double) deltaNs /
                    Math.max(1L, referencePeriodNs));
            if (multiple < 1L || multiple > PANEL_CLOCK_MAX_MULTIPLE) {
                previousDisplayFrameNs = frameTimeNs;
                panelBaselineStartNs = 0L;
                panelBaselinePeriods = 0L;
                return false;
            }
            if (panelBaselineStartNs == 0L) {
                panelBaselineStartNs = previousDisplayFrameNs;
                panelBaselinePeriods = 0L;
            }
            panelBaselinePeriods += multiple;
            panelBaselineLastNs = frameTimeNs;
            double normalizedNs = (double) deltaNs / multiple;
            double modeFraction = Math.abs(normalizedNs -
                    declaredDisplayPeriodNs) / declaredDisplayPeriodNs;
            if (modeFraction <= PANEL_CLOCK_MODE_TOLERANCE_FRACTION)
                recordPanelPeriod(Math.max(1L, Math.round(normalizedNs)));
        }
        previousDisplayFrameNs = frameTimeNs;
        if (measuredDisplayRefreshHz > 0.0 ||
                panelPeriodCount < PANEL_CLOCK_PERIODS) return false;

        double meanPeriodNs = (double) panelPeriodSumNs / panelPeriodCount;
        double squaredFractionSum = 0.0;
        double maximumFraction = 0.0;
        for (int index = 0; index < panelPeriodCount; ++index) {
            double fraction = Math.abs(panelPeriodsNs[index] - meanPeriodNs) /
                    meanPeriodNs;
            squaredFractionSum += fraction * fraction;
            maximumFraction = Math.max(maximumFraction, fraction);
        }
        double rmsFraction = Math.sqrt(
                squaredFractionSum / panelPeriodCount);
        if (rmsFraction > PANEL_CLOCK_PERIOD_RMS_FRACTION ||
                maximumFraction > PANEL_CLOCK_PERIOD_MAX_FRACTION)
            return false;
        double candidateHz = 1_000_000_000.0 / meanPeriodNs;
        if (!Double.isFinite(candidateHz) || candidateHz < 20.0 ||
                candidateHz > 1000.0 || Math.abs(candidateHz -
                declaredDisplayRefreshHz) / declaredDisplayRefreshHz >
                        PANEL_CLOCK_MODE_TOLERANCE_FRACTION)
            return false;
        double canonicalHz = nearestCanonicalPanelHz(candidateHz);
        if (canonicalHz > 0.0) candidateHz = canonicalHz;

        measuredDisplayRefreshHz = candidateHz;
        displayRefreshHz = candidateHz;
        displayPeriodNs = Math.max(1L, Math.round(
                1_000_000_000.0 / candidateHz));
        resetPresentation();
        return true;
    }

    private static double nearestCanonicalPanelHz(double measuredHz) {
        double closest = 0.0;
        double closestError = Double.POSITIVE_INFINITY;
        double secondError = Double.POSITIVE_INFINITY;
        for (double candidate : CANONICAL_PANEL_HZ) {
            double error = Math.abs(measuredHz - candidate);
            if (error < closestError) {
                secondError = closestError;
                closestError = error;
                closest = candidate;
            } else if (error < secondError) {
                secondError = error;
            }
        }
        return closestError <= PANEL_CANONICAL_MEAN_TOLERANCE_HZ &&
                secondError - closestError >= PANEL_CANONICAL_NEAREST_MARGIN_HZ ?
                closest : 0.0;
    }

    private void recordPanelPeriod(long periodNs) {
        if (panelPeriodCount == panelPeriodsNs.length)
            panelPeriodSumNs -= panelPeriodsNs[panelPeriodIndex];
        else
            ++panelPeriodCount;
        panelPeriodsNs[panelPeriodIndex] = periodNs;
        panelPeriodSumNs += periodNs;
        panelPeriodIndex = (panelPeriodIndex + 1) % panelPeriodsNs.length;
    }

    private void clearPanelClockCandidate() {
        if (measuredDisplayRefreshHz > 0.0) return;
        panelPeriodSumNs = 0L;
        panelPeriodIndex = 0;
        panelPeriodCount = 0;
    }

    /** Records one unique image delivered by the emulator. */
    public boolean onProducerFrame(long nowNs) {
        return onProducerFrame(nowNs, 0L);
    }

    /**
     * Records one pixel-distinct image and the callback that produced it.
     *
     * <p>The ordinal is optional for compatibility. When supplied, skipped
     * ordinals are evidence of identical rendered images, not proof that the
     * emulator callback clock slowed. A durable downgrade based on such gaps
     * therefore needs to match one of the explicitly supported lower source
     * tiers; an irregular 54-58-Hz content signature cannot demote a previously
     * proven 60-Hz callback stream to the visibly uneven 50/100 schedule.</p>
     */
    /** Worst-second delivery ring: unique frames per rolling one-second
     * bucket on the producer clock. The minimum over the trailing full
     * buckets is the rate the game has PROVEN it can hold; tier upgrades
     * key on it so the lock converges to the HIGHEST tier the worst
     * delivery funds (user directive 2026-08-16) while a flattering mean
     * can never re-claim a tier whose floor the dips break. */
    // Six completed seconds: long enough that every physically observed dip
    // cadence (SM3DW starved a window every 2-5 s) lands inside any window,
    // short enough that a genuine recovery upgrades within the established
    // ~10 s tier-transition latency.
    private static final int WORST_SECOND_BUCKETS = 6;
    private final int[] worstSecondCounts = new int[WORST_SECOND_BUCKETS];
    private long worstSecondBucketStartNs;
    private int worstSecondBucketIndex;
    private int worstSecondFilled;

    private void observeWorstSecond(long nowNs) {
        if (worstSecondBucketStartNs == 0L) worstSecondBucketStartNs = nowNs;
        while (nowNs - worstSecondBucketStartNs >= 1_000_000_000L) {
            worstSecondBucketStartNs += 1_000_000_000L;
            worstSecondBucketIndex =
                    (worstSecondBucketIndex + 1) % WORST_SECOND_BUCKETS;
            worstSecondCounts[worstSecondBucketIndex] = 0;
            if (worstSecondFilled < WORST_SECOND_BUCKETS) ++worstSecondFilled;
        }
        ++worstSecondCounts[worstSecondBucketIndex];
    }

    /** Minimum completed one-second unique-frame count over the trailing
     * window, or 0 until the window has fully filled since the last stall. */
    double worstRecentSecondRate() {
        if (authoritativeSourceHz > 0.0) return authoritativeSourceHz;
        if (worstSecondFilled < WORST_SECOND_BUCKETS) return 0.0;
        int worst = Integer.MAX_VALUE;
        for (int index = 0; index < WORST_SECOND_BUCKETS; ++index) {
            if (index == worstSecondBucketIndex) continue;
            worst = Math.min(worst, worstSecondCounts[index]);
        }
        return worst == Integer.MAX_VALUE ? 0.0 : worst;
    }

    public boolean onProducerFrame(long nowNs, long submissionOrdinal) {
        if (authoritativeSourceHz > 0.0) {
            previousProducerNs = nowNs;
            previousProducerSubmissionOrdinal = submissionOrdinal;
            measuredProducerPeriodNs = 1_000_000_000.0 / authoritativeSourceHz;
            producerSamples = Math.max(producerSamples, MIN_SAMPLES);
            ++latestSequence;
            return true;
        }
        observeWorstSecond(nowNs);
        if (previousProducerNs > 0L) {
            long delta = nowNs - previousProducerNs;
            int submissionGap = 0;
            if (submissionOrdinal > 0L &&
                    previousProducerSubmissionOrdinal > 0L &&
                    submissionOrdinal > previousProducerSubmissionOrdinal) {
                long gap = submissionOrdinal - previousProducerSubmissionOrdinal;
                submissionGap = gap > Integer.MAX_VALUE ?
                        Integer.MAX_VALUE : (int) gap;
            }
            if (slotLatticeProducer && producerTimelineHz > 0.0 &&
                    submissionGap == 1) {
                double exactPeriods = delta * producerTimelineHz /
                        1_000_000_000.0;
                long timelinePeriods = Math.round(exactPeriods);
                if (timelinePeriods >= 2L && timelinePeriods <= 3L &&
                        Math.abs(exactPeriods - timelinePeriods) <= 0.001)
                    submissionGap = (int) timelinePeriods;
            }
            if (producerTimelineHz > 0.0 && submissionGap > 0 &&
                    !trustedProducerIntervalIsContinuous(delta, submissionGap)) {
                // The immutable PTS advanced by a different number of core
                // ticks than Java actually received. This is the exact
                // SurfaceTexture coalescing shape observed on physical
                // F-Zero: never insert the missing image, never interpolate
                // across it, and never poison/revoke the already-proven game
                // cadence with this transport loss.
                ++producerTimelineDiscontinuityCount;
                previousProducerNs = nowNs;
                previousProducerSubmissionOrdinal = submissionOrdinal;
                ++latestSequence;
                resetPresentation();
                return false;
            }
            if (submissionGap > 0) {
                double callbackPeriodNs = (double) delta / submissionGap;
                if (Double.isFinite(callbackPeriodNs) &&
                        callbackPeriodNs >= 1_000_000.0 &&
                        callbackPeriodNs <= 100_000_000.0) {
                    measuredSubmissionPeriodNs =
                            producerSubmissionClockObserved ?
                                    measuredSubmissionPeriodNs * 0.8 +
                                            callbackPeriodNs * 0.2 :
                                    callbackPeriodNs;
                    producerSubmissionClockObserved = true;
                }
            }
            // A pause is not a performance collapse. The newest frame remains
            // on screen and tier selection resumes when the game advances.
            if (delta >= 2_000_000L && delta <= 100_000_000L) {
                if (producerPeriodCount == RATE_WINDOW_PERIODS) {
                    producerPeriodSumNs -= producerPeriodsNs[producerPeriodIndex];
                } else {
                    ++producerPeriodCount;
                }
                producerPeriodsNs[producerPeriodIndex] = delta;
                producerPeriodSumNs += delta;
                producerPeriodIndex = (producerPeriodIndex + 1) % RATE_WINDOW_PERIODS;
                measuredProducerPeriodNs =
                        (double) producerPeriodSumNs / producerPeriodCount;
                if (producerSamples < Integer.MAX_VALUE) ++producerSamples;
                recordDecisionPeriod(delta, submissionGap);
                updateTier();
                updateProvenTimestampSourceClock();
            }
        }
        previousProducerNs = nowNs;
        previousProducerSubmissionOrdinal = submissionOrdinal;
        ++latestSequence;
        return true;
    }

    private boolean trustedProducerIntervalIsContinuous(
            long deltaNs, int deliveredSubmissionGap) {
        if (deltaNs <= 0L || deliveredSubmissionGap <= 0 ||
                !Double.isFinite(producerTimelineHz) ||
                producerTimelineHz <= 0.0) return false;
        double exactPeriods = deltaNs * producerTimelineHz / 1_000_000_000.0;
        long timelinePeriods = Math.round(exactPeriods);
        // Native timestamps are rounded once to integer nanoseconds, so the
        // residual is normally below one millionth of a period. One tenth of
        // one percent remains far below any real cadence distinction while
        // rejecting an arrival-time or driver-authored timestamp.
        return timelinePeriods >= 1L && timelinePeriods <= 120L &&
                Math.abs(exactPeriods - timelinePeriods) <= 0.001 &&
                timelinePeriods == deliveredSubmissionGap;
    }

    /**
     * Promotes the newest producer image only on the fixed selected-tier clock.
     * Extra producer frames are deliberately replaced by newer ones before the
     * deadline rather than creating an irregular 55/54/56 fps presentation.
     */
    public boolean promoteIfDue(long displayFrameNs) {
        return promoteIfDue(displayFrameNs, 0L);
    }

    private boolean promoteIfDue(long displayFrameNs, long nearestTickTolerance) {
        if (latestSequence == promotedSequence) return false;
        long period = sourcePeriodNs();
        // Source deadlines generally fall between physical display callbacks.
        // Select the nearest callback, rather than always the first callback
        // after the deadline. Always rounding upward turns a truthful 50-Hz
        // source into only 40-45 promoted endpoints on a 120-Hz panel.
        long selectedTime = displayFrameNs + nearestTickTolerance;
        if (promotedSequence != 0L && selectedTime < nextPromotionNs) return false;
        promotedSequence = latestSequence;
        lastPromotionNs = displayFrameNs;
        if (nextPromotionNs == 0L || displayFrameNs - nextPromotionNs > period * 3L)
            nextPromotionNs = displayFrameNs + period;
        else {
            do { nextPromotionNs += period; }
            while (nextPromotionNs <= displayFrameNs);
        }
        return true;
    }

    /**
     * Makes the one presentation decision for a physical display callback.
     *
     * <p>A real endpoint is considered on every callback and always wins a
     * tie. Each adjacent promoted pair then owns at most one midpoint quota.
     * This keeps real promotion and generated presentation on one clock: the
     * old independent clocks could skip a due endpoint on the fractional
     * 50-to-100 schedule and then manufacture more generated than promoted
     * frames. A return value other than {@link #PRESENT_NONE} authorizes
     * exactly one swap on this callback.</p>
     *
     * @param promotedImages number of endpoint images already promoted by the
     *                       renderer before this callback
     * @param syntheticReady whether the current pair has a safe motion field
     */
    public int selectPresentation(long displayFrameNs, int promotedImages,
                                  boolean syntheticReady) {
        ++presentationCallbackCount;
        boolean nominalDue = presentationDue(displayFrameNs);
        boolean oldMidpointPending = midpointPending;
        boolean promoted = promoteIfDue(displayFrameNs,
                Math.max(1L, displayPeriodNs / 2L));
        if (promoted) {
            if (oldMidpointPending) {
                ++syntheticQuotaSkippedCount;
                midpointPending = false;
            }
            if (!nominalDue || oldMidpointPending) ++realPriorityCount;
            selectedPhase = interpolation(displayFrameNs, promotedImages + 1);
            if (promotedImages > 0 && generatesIntermediateFrames()) {
                midpointPending = true;
                ++midpointPairSequence;
                ++syntheticPairCreatedCount;
                midpointSlots = legacyIntermediateSlotsPerPair();
                midpointSlotIndex = 1;
                midpointPromotionNs = displayFrameNs;
                midpointDueNs = legacyIntermediateDueNs();
            }
            ++dueSelectedCount;
            // A real endpoint consumes and rephases the output slot even when
            // it arrived on the fractional scheduler's normally skipped tick.
            scheduledOutputFps = outputFps();
            nextPresentationNs = displayFrameNs + outputPeriodNs();
            return PRESENT_REAL;
        }

        if (midpointPending) {
            long nearestTick = displayFrameNs + Math.max(1L, displayPeriodNs / 2L);
            if (nearestTick >= midpointDueNs) {
                midpointPending = false;
                selectedPhase = interpolation(displayFrameNs, promotedImages);
                if (!syntheticReady) {
                    ++syntheticNotReadyCount;
                    ++syntheticQuotaSkippedCount;
                    return PRESENT_NONE;
                }
                if (!(selectedPhase > 0f && selectedPhase < 1f)) {
                    ++duePhaseClampedCount;
                    ++syntheticQuotaSkippedCount;
                    return PRESENT_NONE;
                }
                ++dueSelectedCount;
                if (midpointSlotIndex == 1) {
                    if (midpointPairSequence <= lastSelectedSyntheticPair)
                        ++duplicatePairSelectionCount;
                    else lastSelectedSyntheticPair = midpointPairSequence;
                }
                ++syntheticSelectedCount;
                // Strict doubling owns one midpoint and never re-arms another
                // generated slot for this pair.
                // The midpoint is itself the selected output slot. Rephase so
                // a nearby fractional deadline cannot request a duplicate.
                scheduledOutputFps = outputFps();
                nextPresentationNs = displayFrameNs + outputPeriodNs();
                return PRESENT_SYNTHETIC;
            }
        }

        if (nominalDue) ++dueNoEndpointCount;
        return PRESENT_NONE;
    }

    /**
     * Selects one presentation from an explicitly retained endpoint pair.
     *
     * <p>The renderer, not producer callback timing, owns readiness. Generation
     * primes from a valid pair: {@code leftSequence > 0},
     * {@code rightSequence == leftSequence + 1}, and a completed motion estimate.
     * After priming, an exact phase-zero REAL needs only its retained left
     * endpoint; every fractional SYNTHETIC still requires its adjacent right
     * endpoint and motion field. The renderer must apply
     * {@link #bufferedEndpointAdvanceAfterPresentation()} after the successful
     * swap, then pass the resulting active pair on the next due call.</p>
     *
     * <p>The source position is a timestamp-derived phase on uniformly spaced
     * physical callback slots. A qualified doubling is REAL, SYNTHETIC,
     * REAL, SYNTHETIC. Direct-only and unqualified clocks never authorize
     * a generated phase. Retained endpoint credits bound the output count;
     * the renderer must independently validate actual pair spans and pixels.</p>
     */
    /**
     * Compatibility overload for host callers that do not own producer
     * timestamps. Production rendering must use the timestamped overload.
     */
    public int selectBufferedPresentation(
            long displayFrameNs, long leftSequence, long rightSequence,
            boolean pairReady) {
        long period = Math.max(1L, Math.round(1_000_000_000.0 /
                Math.max(1.0, measuredProducerHz() > 0.0 ?
                        measuredProducerHz() : lockedSourceFps())));
        long leftTimestampNs = leftSequence > 0L ?
                saturatingMultiply(leftSequence, period) : 0L;
        long rightTimestampNs = rightSequence > 0L ?
                saturatingMultiply(rightSequence, period) : 0L;
        return selectBufferedPresentation(displayFrameNs, leftSequence,
                leftTimestampNs, rightSequence, rightTimestampNs, pairReady);
    }

    public int selectBufferedPresentation(
            long displayFrameNs, long leftSequence, long leftTimestampNs,
            long rightSequence, long rightTimestampNs, boolean pairReady) {
        return selectBufferedPresentation(displayFrameNs,
                leftSequence, leftTimestampNs, 0L, 0L, 0L,
                rightSequence, rightTimestampNs, 0L, 0L, 0L, pairReady);
    }

    public int selectBufferedPresentation(
            long displayFrameNs, long physicalPresentationNs,
            long leftSequence, long leftTimestampNs,
            long rightSequence, long rightTimestampNs, boolean pairReady) {
        return selectBufferedPresentation(displayFrameNs,
                physicalPresentationNs,
                leftSequence, leftTimestampNs, 0L, 0L, 0L,
                rightSequence, rightTimestampNs, 0L, 0L, 0L, pairReady);
    }

    /**
     * Production overload carrying the classifier provenance for both
     * retained endpoints. Unique ordinals distinguish duplicate-covered time
     * from a skipped real image; candidate-loss ordinals prevent a retained
     * pair from crossing an asynchronous ownership failure.
     */
    public int selectBufferedPresentation(
            long displayFrameNs,
            long leftSequence, long leftTimestampNs,
            long leftUniqueSequence, long leftSubmission,
            long leftCandidateLoss,
            long rightSequence, long rightTimestampNs,
            long rightUniqueSequence, long rightSubmission,
            long rightCandidateLoss, boolean pairReady) {
        return selectBufferedPresentation(displayFrameNs, displayFrameNs,
                leftSequence, leftTimestampNs,
                leftUniqueSequence, leftSubmission, leftCandidateLoss,
                rightSequence, rightTimestampNs,
                rightUniqueSequence, rightSubmission, rightCandidateLoss,
                pairReady);
    }

    /**
     * Production timing contract.
     *
     * <p>{@code displayFrameNs} is the immutable Choreographer callback used
     * only for callback pacing. {@code physicalPresentationNs} is the future
     * scan for which the pixels are rendered and therefore owns interpolation
     * phase. Keeping them separate prevents every generated image from being
     * one panel scan behind its actual presentation.</p>
     */
    public int selectBufferedPresentation(
            long displayFrameNs, long physicalPresentationNs,
            long leftSequence, long leftTimestampNs,
            long leftUniqueSequence, long leftSubmission,
            long leftCandidateLoss,
            long rightSequence, long rightTimestampNs,
            long rightUniqueSequence, long rightSubmission,
            long rightCandidateLoss, boolean pairReady) {
        if (physicalPresentationNs <= 0L) {
            failBufferedPresentation("invalid-physical-presentation-time");
            return PRESENT_NONE;
        }
        if (bufferedLastSelectionDisplayFrameNs > 0L) {
            long callbackDeltaNs = displayFrameNs -
                    bufferedLastSelectionDisplayFrameNs;
            long minimumPeriodNs = Math.max(1L, displayPeriodNs / 2L);
            long maximumPeriodNs = Math.max(minimumPeriodNs,
                    displayPeriodNs * 2L);
            if (callbackDeltaNs >= minimumPeriodNs &&
                    callbackDeltaNs <= maximumPeriodNs) {
                bufferedObservedPanelPeriodNs =
                        bufferedObservedPanelPeriodNs <= 0L ? callbackDeltaNs :
                                (bufferedObservedPanelPeriodNs * 7L +
                                        callbackDeltaNs + 4L) / 8L;
            }
        }
        bufferedLastSelectionDisplayFrameNs = displayFrameNs;
        // Accumulate re-climb evidence continuously — including during the
        // dips a settled-tier comparison would never visit. The minimum
        // worst-second over the whole post-demotion hold is what a re-climb
        // must fund; sampling it only at expiry let a 6-second calm stretch
        // between recurring dips re-claim a tier the next dip would starve
        // (SMG2 Star Festival, run wii1 2026-08-17: 42 climb-starve-demote
        // round trips at the 60 tier while the scene dipped to 43-55 Hz).
        if (starvationDemotionCount > 0 &&
                displayFrameNs >= reclimbEvidenceStartNs) {
            double worst = worstRecentSecondRate();
            if (worst > 0.0) reclimbEvidenceMinRate =
                    Math.min(reclimbEvidenceMinRate, worst);
        }
        // A selected buffer is only evidence after eglSwapBuffers succeeds.
        // Re-entering selection with an uncommitted decision is a renderer
        // protocol failure, never permission to count or reuse that slot.
        if (bufferedPendingPresentation != PRESENT_NONE) {
            failBufferedPresentation("pending-decision-reentry");
            clearBufferedPendingDecision();
            return PRESENT_NONE;
        }
        if (!bufferedPresentationDue(displayFrameNs)) return PRESENT_NONE;

        double exactSourceHz = presentationSourceHz();
        // This integer is only the stable schedule identity/invariant bound;
        // exactSourceHz owns all timestamp phase math. Before tier acquisition
        // use the provisional bucket rather than the default60 compatibility
        // label or the callback-by-callback rounded measurement: the former
        // made output40 look invalid, while the latter reset the epoch as a
        // measured30.3/31.9 bootstrap clock crossed integer boundaries.
        boolean durableSchedule = authoritativeSourceHz > 0.0 ||
                hasSustainableGenerationRate();
        int source = authoritativeSourceHz > 0.0 ?
                Math.max(1, (int) Math.round(exactSourceHz)) :
                (tierAcquired ? lockedSourceFps() :
                        provisionalSourceFps(exactSourceHz));
        int output = outputFps();
        double exactOutputHz = targetOutputHz();
        boolean generatedSchedule = generationAvailable &&
                hasSustainableGenerationRate();
        if (!(exactSourceHz > 0.0) || !(exactOutputHz > 0.0) ||
                (generatedSchedule &&
                        (exactOutputHz + 1.0e-5 < exactSourceHz ||
                                exactOutputHz > exactSourceHz *
                                        MAX_GENERATION_FACTOR + 1.0e-5))) {
            failBufferedPresentation("invalid-source-output");
            return PRESENT_NONE;
        }
        // Provisional measured rates can cross integer labels on consecutive
        // callbacks. They are direct-only and therefore share one bootstrap
        // schedule identity; only a durable tier/divisor may rebuild the
        // buffered timeline.
        int scheduleSource = durableSchedule ? source : 0;
        int scheduleOutput = durableSchedule ? output : 0;
        if (bufferedScheduledSourceFps != scheduleSource ||
                bufferedScheduledOutputFps != scheduleOutput) {
            bufferedScheduledSourceFps = scheduleSource;
            bufferedScheduledOutputFps = scheduleOutput;
            bufferedPrimed = false;
            bufferedTimelineDisplayAnchorNs = 0L;
            bufferedLastRealDisplayFrameNs = 0L;
            bufferedTimelineSourceAnchorNs = 0L;
            bufferedLastTargetSourceNs = 0L;
            bufferedLastRawTargetSourceNs = 0L;
            bufferedExpectedAdvance = 0;
            bufferedAdvanceAfterPresentation = 0;
            bufferedLeftSequence = 0L;
            bufferedRightSequence = 0L;
            bufferedLeftTimestampNs = 0L;
            bufferedRightTimestampNs = 0L;
            bufferedMinimumReprimeSequence = 0L;
            bufferedCreditedRightSequence = 0L;
            bufferedOutputCredits = 0;
            bufferedLastEpochReason = "schedule-change";
            ++bufferedPresentationEpoch;
            // This callback supplied endpoints retained under the previous
            // schedule. Publish the boundary but do not also leave a pending
            // decision for Display to discard: that deterministic orphan was
            // observed as pending-decision-reentry on the next callback.
            return PRESENT_NONE;
        }

        boolean endpointReady = leftSequence > 0L && leftTimestampNs > 0L;
        boolean continuousSpan = endpointSpanContinuous(leftTimestampNs,
                rightTimestampNs, exactSourceHz,
                leftUniqueSequence, rightUniqueSequence,
                leftSubmission, rightSubmission,
                leftCandidateLoss, rightCandidateLoss,
                slotLatticeProducer);
        boolean rightStructurallyValid = rightSequence == 0L ||
                (rightSequence == leftSequence + 1L &&
                        continuousSpan);
        boolean structuralPair = endpointReady &&
                rightSequence == leftSequence + 1L &&
                continuousSpan;
        boolean validPair = structuralPair && pairReady;
        // Motion readiness may disappear independently of source delivery:
        // proof can be disabled, a dense epoch can be torn down, or a fresh
        // pair can still be waiting for its estimator.  None of those states
        // authorizes frame generation, but none may stall real endpoints
        // either.  Treat that pair as direct-only for this decision.  The
        // physical output lattice still consumes every selected slot, so a
        // later-ready estimate resumes without a catch-up burst.
        boolean wantsGeneratedOutput = generationAvailable &&
                hasSustainableGenerationRate() &&
                exactOutputHz > exactSourceHz + 1.0e-5;
        boolean directOnly = !wantsGeneratedOutput || !validPair;
        boolean pendingPrime = false;
        if (!bufferedPrimed) {
            // A lone retained REAL is always safe to show.  Only synthesis
            // needs a complete adjacent pair.  Requiring two endpoints even
            // for direct presentation made every legitimate held-image span
            // freeze the visible stream until several newer images happened
            // to arrive; safe re-prime must discard interpolation, not hide
            // independently classified real frames.
            // A generated schedule must start one retained endpoint behind
            // the producer and therefore cannot prime from a lone image. If
            // it did, a source endpoint arriving every other 120-Hz callback
            // would be shown immediately; its successor would only become
            // known on the following REAL slot, leaving no adjacent pair for
            // the intervening midpoint. That exact physical failure produced
            // S60/T120 with only 60 successful swaps on Thor. Wait for the
            // classified right endpoint and its completed motion estimate,
            // then anchor the visible timeline at the left endpoint. Direct
            // fallback remains independently allowed to show a lone REAL.
            // Structural look-ahead is the ownership requirement. If its
            // motion estimate failed, the exact left endpoint may still be
            // shown once and the unsafe fractional slot will fail closed;
            // requiring motion readiness here would freeze direct recovery.
            boolean knownUnsafeSuccessor = endpointReady &&
                    rightSequence > 0L && !structuralPair;
            boolean primeReady = wantsGeneratedOutput ?
                    (structuralPair || knownUnsafeSuccessor) : endpointReady;
            // Starvation fallback (2026-09-02, wiiu-b82): a generated schedule
            // that cannot prime -- the pair keeps being cut by held-frame
            // discontinuities on a heavy unpaced scene -- used to consume
            // slot after slot with PRESENT_NONE (35,600 prime waits, 2,751
            // epochs, ~20 presents per second on the panel while the game
            // rendered 55).  After six consecutive prime waits, each newly
            // retained left endpoint is shown once as an exact REAL through
            // the direct-only path, so the panel never falls below the
            // source rate; synthesis resumes as soon as a pair primes.
            // Once starving, every NEW left endpoint is shown immediately (the
            // streak is not re-armed per present: wiiu-b85 throttled the
            // fallback to one present per seven scans, 15 presents/s on the
            // panel).  Starvation ends when a pair primes normally.
            // REVERTED 2026-09-02 23:40 (wiiu-b86): the fallback fired on the
            // NATURAL wait for the right endpoint of a 20-Hz pair (six scans
            // between endpoints), primed the timeline in direct mode, and the
            // generated path then failed "advance-without-ready-pair" every
            // pair: 1874 epoch resets and ~6 presents per second on a
            // perfectly regular paced-20 source.  Kept as a disabled block
            // until a fallback that never primes the buffered timeline exists.
            if (BUFFERED_STARVATION_FALLBACK_ENABLED) {
                if (bufferedPrimeWaitStreak >= 6) bufferedStarving = true;
                if (wantsGeneratedOutput && !primeReady && endpointReady &&
                        leftSequence > bufferedMinimumReprimeSequence &&
                        bufferedStarving &&
                        leftSequence != bufferedStarvationPresentedSequence) {
                    bufferedStarvationPresentedSequence = leftSequence;
                    ++bufferedStarvationPresentCount;
                    directOnly = true;
                    primeReady = true;
                } else if (primeReady && wantsGeneratedOutput) {
                    bufferedStarving = false;
                }
            }
            if (!primeReady || leftSequence <= bufferedMinimumReprimeSequence) {
                ++bufferedPrimeWaitStreak;
                bufferedLastUnavailableReason = "priming";
                // Priming starvation is the renderer's missing look-ahead,
                // not the producer failing to fund an already-running
                // lattice; it must not vote for a starvation demotion.
                ++bufferedUnavailableSlotCount;
                ++bufferedPrimeWaitCount;
                bufferedPrimeNeedsPacingRephase = true;
                return PRESENT_NONE;
            }
            pendingPrime = true;
        } else {
            // The active FIFO pair is immutable until the prior committed
            // decision asks for one pop.  One pop must make the former right
            // endpoint the exact new left; a skipped/discontinuous pair must
            // re-prime instead of manufacturing motion across the gap.
            boolean correctAdvance;
            if (bufferedExpectedAdvance == 0) {
                boolean correctRight = bufferedRightSequence == 0L ?
                        rightStructurallyValid :
                        rightSequence == bufferedRightSequence &&
                                rightTimestampNs == bufferedRightTimestampNs;
                correctAdvance = endpointReady &&
                        leftSequence == bufferedLeftSequence &&
                        leftTimestampNs == bufferedLeftTimestampNs && correctRight;
            } else {
                correctAdvance = bufferedExpectedAdvance == 1 &&
                        bufferedRightSequence == bufferedLeftSequence + 1L &&
                        bufferedRightTimestampNs > bufferedLeftTimestampNs &&
                        leftSequence == bufferedRightSequence &&
                        leftTimestampNs == bufferedRightTimestampNs &&
                        rightStructurallyValid;
            }
            if (!correctAdvance) {
                bufferedLastMismatchDiagnostic =
                        "expected=" + bufferedExpectedAdvance +
                        ",controller=" + bufferedLeftSequence + "/" +
                                bufferedRightSequence +
                        ",renderer=" + leftSequence + "/" + rightSequence +
                        ",leftTsEqual=" +
                                (leftTimestampNs == bufferedLeftTimestampNs) +
                        ",rightTsEqual=" +
                                (rightTimestampNs == bufferedRightTimestampNs) +
                        ",rightStructural=" + rightStructurallyValid;
                failBufferedPresentation("endpoint-advance-mismatch");
                return PRESENT_NONE;
            }
        }

        // Track adjacent intervals and bounded output credits. These counters
        // do not independently certify a held/lost-frame bridge: per-pair
        // content and midpoint-count evidence remains required at rendering.
        if (pendingPrime && endpointReady && !structuralPair &&
                bufferedCreditedRightSequence == 0L) {
            // A classified source endpoint independently funds at most two
            // output samples.  Record its credit now so a discontinuity can
            // present the new REAL immediately; when its exact successor later
            // arrives, the ordinary pair path below contributes that new
            // endpoint's two credits without double-counting the left.
            bufferedCreditedRightSequence = leftSequence;
            int perEndpoint = outputCreditsPerEndpoint();
            bufferedOutputCredits = Math.min(perEndpoint,
                    bufferedOutputCredits + perEndpoint);
        }
        if (structuralPair && rightSequence != bufferedCreditedRightSequence) {
            if (!pendingPrime && bufferedCreditedRightSequence > 0L &&
                    rightSequence != bufferedCreditedRightSequence + 1L) {
                failBufferedPresentation("credited-pair-discontinuity");
                return PRESENT_NONE;
            }
            // A fresh retained pair contains TWO independently accepted real
            // endpoints.  Each endpoint funds at most two uniform output
            // samples, so the initial pair must enter with four credits.
            // Every later adjacent pair contributes only its newly introduced
            // right endpoint and therefore adds two.  Granting only two on
            // prime under-counted the left endpoint: after any tier/gap
            // re-prime, a harmless source/panel phase offset could spend both
            // credits before the next selected slot crossed the right
            // timestamp and then stall forever on an otherwise valid pair.
            int perEndpoint = outputCreditsPerEndpoint();
            // (2026-09-01, wiiu-b39) A bridged held/dropped frame spans two
            // (or three) source periods and therefore owns two (three) times
            // the output slots of an ordinary pair.  Crediting it like an
            // ordinary endpoint spent the ledger before the selected slot
            // reached the right timestamp, and the pair then stalled with
            // credits=0 / advance=0 until the FIFO coalesced into a reset --
            // once per second on Cemu (10-20 percent held slots), rarely on
            // Dolphin.  Credit the span the pair actually covers.
            int spanPeriods = 1;
            if (leftTimestampNs > 0L && rightTimestampNs > leftTimestampNs &&
                    Double.isFinite(exactSourceHz) && exactSourceHz > 0.0) {
                double exactPeriods = (rightTimestampNs - leftTimestampNs) *
                        exactSourceHz / 1_000_000_000.0;
                spanPeriods = (int) Math.max(1L, Math.min(3L,
                        Math.round(exactPeriods)));
            }
            int addedCredits = pendingPrime &&
                    bufferedCreditedRightSequence == 0L ?
                    (1 + spanPeriods) * perEndpoint :
                    spanPeriods * perEndpoint;
            bufferedCreditedRightSequence = rightSequence;
            bufferedOutputCredits = Math.min((1 + spanPeriods) * perEndpoint,
                    bufferedOutputCredits + addedCredits);
        }

        long targetSourceNs;
        if (pendingPrime) {
            bufferedTimelineDisplayAnchorNs = physicalPresentationNs;
            bufferedTimelineSourceAnchorNs = leftTimestampNs;
            targetSourceNs = leftTimestampNs;
        } else {
            long displayElapsedNs = physicalPresentationNs -
                    bufferedTimelineDisplayAnchorNs;
            if (displayElapsedNs < 0L) {
                failBufferedPresentation("display-time-reversal");
                return PRESENT_NONE;
            }
            targetSourceNs = saturatingAdd(bufferedTimelineSourceAnchorNs,
                    displayElapsedNs);
            // Predicted physical present times may step back by a fraction
            // of a scan between callbacks (WSI deadline re-targeting after a
            // late callback).  Clamp that sub-half-scan residue onto the
            // monotonic playhead; only a material reversal is an ownership
            // failure (Dreamcast/GameCube runs 2026-09-01 tore the epoch
            // down for reversals of tens of microseconds).
            if (targetSourceNs < bufferedLastRawTargetSourceNs &&
                    bufferedLastRawTargetSourceNs - targetSourceNs <=
                            Math.max(1L, displayPeriodNs / 2L))
                targetSourceNs = bufferedLastRawTargetSourceNs;
            if (targetSourceNs < bufferedLastRawTargetSourceNs) {
                bufferedLastMismatchDiagnostic =
                        "targetSource=" + targetSourceNs +
                        ",lastTargetSource=" + bufferedLastTargetSourceNs +
                        ",physical=" + physicalPresentationNs +
                        ",displayAnchor=" + bufferedTimelineDisplayAnchorNs +
                        ",sourceAnchor=" + bufferedTimelineSourceAnchorNs +
                        ",displayElapsed=" + displayElapsedNs;
                failBufferedPresentation("source-target-reversal");
                return PRESENT_NONE;
            }
        }

        final long rawTargetSourceNs = targetSourceNs;
        // The previous callback predicts a pair advance from the calibrated
        // display period. A tiny callback quantization difference may put the
        // new target just before the retained left timestamp; clamp only that
        // sub-half-vsync residue. A material reversal is an ownership failure.
        if (targetSourceNs < leftTimestampNs) {
            long leadNs = leftTimestampNs - targetSourceNs;
            if (leadNs > realEndpointSnapToleranceNs()) {
                // (2026-09-02, wiiu-b43) A slot-lattice producer stamps each
                // present on the NEAREST real-time lattice slot, so a stamp
                // may lead real time by up to half a source period; against
                // the display anchor that is a quantization artefact, not an
                // ownership reversal.  Waiting one scan costs one slot; the
                // reset it replaced cost 6-10 (342 such resets per run).
                if (slotLatticeProducer && Double.isFinite(exactSourceHz) &&
                        exactSourceHz > 0.0 &&
                        leadNs <= (long) (1_000_000_000.0 / exactSourceHz)) {
                    ++bufferedUnavailableSlotCount;
                    ++bufferedLeadWaitCount;
                    bufferedLastUnavailableReason = "endpoint-lead";
                    return PRESENT_NONE;
                }
                failBufferedPresentation("left-endpoint-lead-too-large");
                return PRESENT_NONE;
            }
            recordEndpointOffset(displayFrameNs, -leadNs);
            targetSourceNs = leftTimestampNs;
        }

        int presentation;
        float phase;
        int pendingAdvance;
        boolean pendingMidpointOmitted = false;
        boolean exactDoubleSchedule = exactDoubleEndpointLatticeRequired &&
                !directOnly && validPair &&
                source > 0 && output == source * 2;
        if (exactDoubleSchedule) {
            // Exact 2x paths are a causal endpoint/midpoint lattice, not an
            // arbitrary phase sampler.  A tiny measured panel/source clock
            // offset must occasionally omit a midpoint rather than turn the
            // entire stream into generated samples that never expose a real
            // endpoint. Prime at left, emit exactly one timestamp-derived
            // intermediate, then show and commit right before advancing to
            // the next adjacent pair.
            if (pendingPrime) {
                presentation = PRESENT_REAL;
                phase = 0f;
                targetSourceNs = leftTimestampNs;
                pendingAdvance = 0;
            } else if (saturatingAdd(targetSourceNs, 1_000L) >=
                    rightTimestampNs) {
                // A genuinely missed physical output slot may cross the
                // endpoint before this callback. Preserve the existing
                // no-catch-up contract by showing right once and abandoning
                // the midpoint rather than synthesizing stale time.
                presentation = PRESENT_REAL;
                phase = 1f;
                targetSourceNs = rightTimestampNs;
                pendingAdvance = 1;
                pendingMidpointOmitted =
                        bufferedLastSyntheticLeftSequence != leftSequence ||
                        bufferedLastSyntheticRightSequence != rightSequence;
            } else if (bufferedLastTargetSourceNs == leftTimestampNs) {
                long spanNs = rightTimestampNs - leftTimestampNs;
                if (targetSourceNs <= saturatingAdd(leftTimestampNs, 1_000L)) {
                    recordUnavailableSlot(displayFrameNs, "midpoint-target-not-after-left");
                    return PRESENT_NONE;
                }
                // Exact 2x is an endpoint/midpoint lattice. Do not let two
                // independently sampled physical-clock estimates choose two
                // slightly different phases for private preparation and the
                // later visible request. The immutable endpoint timestamps
                // define one exact integer-nanosecond midpoint for both.
                targetSourceNs = exactMidpointTimestampNs(
                        leftTimestampNs, rightTimestampNs);
                if (targetSourceNs <= leftTimestampNs ||
                        targetSourceNs >= rightTimestampNs) {
                    recordUnavailableSlot(displayFrameNs, "midpoint-not-interior");
                    return PRESENT_NONE;
                }
                phase = (float) ((double) (targetSourceNs - leftTimestampNs) /
                        (double) spanNs);
                presentation = PRESENT_SYNTHETIC;
                pendingAdvance = 0;
            } else {
                presentation = PRESENT_REAL;
                phase = 1f;
                targetSourceNs = rightTimestampNs;
                pendingAdvance = 1;
            }
        } else if (directOnly) {
            if (pendingPrime) {
                // Prime with the exact retained left endpoint.  The following
                // direct slot advances only when its adjacent right endpoint
                // is present; no duplicate swap is used to pad a gap.
                presentation = PRESENT_REAL;
                phase = 0f;
                targetSourceNs = leftTimestampNs;
                pendingAdvance = 0;
            } else if (endpointReady && targetSourceNs <=
                    saturatingAdd(leftTimestampNs, 1_000L)) {
                // The exact retained left endpoint is independently
                // presentable even while its successor is still being
                // classified. This consumes only the current uniform slot;
                // a late successor can never trigger a catch-up present.
                presentation = PRESENT_REAL;
                phase = 0f;
                targetSourceNs = leftTimestampNs;
                pendingAdvance = 0;
            } else if (structuralPair && saturatingAdd(targetSourceNs,
                    Math.max(1L, displayPeriodNs / 2L)) >= rightTimestampNs) {
                // Quantize the source deadline to its nearest physical panel
                // callback.  This is an endpoint present, never generation.
                presentation = PRESENT_REAL;
                phase = 1f;
                targetSourceNs = rightTimestampNs;
                pendingAdvance = 1;
            } else {
                recordUnavailableSlot(displayFrameNs, "direct-endpoint-not-due");
                return PRESENT_NONE;
            }
        } else if (validPair && targetSourceNs <=
                saturatingAdd(leftTimestampNs, realEndpointSnapToleranceNs())) {
            // A target that lands just after an exact left endpoint is that
            // endpoint.  The old sub-microsecond residue rule was asymmetric
            // with the early clamp above, so physical callback jitter decided
            // whether a due endpoint was shown as REAL or as a phase-0.001
            // synthetic: Ocarina 20->60 (2026-09-01, run n64-tier2)
            // presented 0 REAL and 120 synthetic per window.  With the
            // half-output-period window exactly one slot per interval is
            // the endpoint and no interior lattice sample can be absorbed.
            recordEndpointOffset(displayFrameNs,
                    targetSourceNs - leftTimestampNs);
            presentation = PRESENT_REAL;
            phase = 0f;
            targetSourceNs = leftTimestampNs;
            pendingAdvance = 0;
        } else
        // Symmetric snap at the right endpoint as well: a target inside half
        // an output period before the retained right endpoint is that
        // endpoint (no interior lattice sample lies that close), so every
        // endpoint is presented exactly once whichever side of a slot it
        // falls on.
        if (validPair && saturatingAdd(targetSourceNs,
                realEndpointSnapToleranceNs()) >= rightTimestampNs) {
            // A callback arrived later than the prediction. Present the exact
            // retained right endpoint now and rotate once after the successful
            // swap. Never extrapolate or authorize more than one catch-up.
            recordEndpointOffset(displayFrameNs,
                    targetSourceNs - rightTimestampNs);
            presentation = PRESENT_REAL;
            phase = 1f;
            targetSourceNs = rightTimestampNs;
            pendingAdvance = 1;
        } else {
            if (!validPair) {
                // A phase-zero retained endpoint may remain visible evidence,
                // but no fractional output exists without its exact successor.
                if (targetSourceNs != leftTimestampNs) {
                    recordUnavailableSlot(displayFrameNs, "successor-not-ready");
                    if (structuralPair) {
                        // Both retained textures exist, so readiness cannot
                        // improve merely by waiting for another producer
                        // callback. Rebuild the failed motion pair instead of
                        // leaving the presentation timeline permanently stuck.
                        failBufferedPresentation("motion-estimate-not-ready");
                        return PRESENT_NONE;
                    }
                    // A one-query classification delay must not destroy the
                    // retained endpoint or restart the presentation epoch.
                    // Consume this physical output slot without swapping and
                    // wait for the exact adjacent successor. When it arrives,
                    // the timestamp playhead may select that REAL endpoint on
                    // one later slot; it never emits an extra catch-up swap.
                    // A true pause/discontinuity is still rejected before this
                    // call by endpointSpanContinuous in the renderer.
                    return PRESENT_NONE;
                }
                presentation = PRESENT_REAL;
                phase = 0f;
                pendingAdvance = 0;
            } else {
                double fraction = (double) (targetSourceNs - leftTimestampNs) /
                        (double) (rightTimestampNs - leftTimestampNs);
                // Lattice snap (2026-09-02): when the pair spans an integer
                // number of output scans (x2: 2, a bridged held
                // pair: 6), the synthetic phases are exact k/N by construction
                // of the output lattice.  The playhead measured them as 0.44
                // and 0.77 on a paced 40->120 stretch (wiiu-b60 phase
                // diagnostic: a constant 2.7-ms offset from the priming slot's
                // predicted present time), which turns correct in-betweens
                // into uneven motion steps of 0.44/0.33/0.23 -- visible judder.
                // The lattice is the OUTPUT lattice (build 88 proof, wiiu-b88m:
                // 30 -> 60 on the 120-Hz panel spans four scans but two
                // outputs, and snapping to quarters put the synthetic at 0.75).
                long spanForSnapNs = rightTimestampNs - leftTimestampNs;
                long outputPeriodForSnapNs = bufferedUniformOutputPeriodNs();
                if (outputPeriodForSnapNs > 0L && spanForSnapNs > 0L) {
                    double outputs = (double) spanForSnapNs / (double) outputPeriodForSnapNs;
                    long n = Math.round(outputs);
                    if (n >= 2L && n <= 6L && Math.abs(outputs - n) <= 0.05 * n) {
                        long k = Math.round(fraction * n);
                        if (k >= 1L && k <= n - 1L) fraction = (double) k / (double) n;
                    }
                }
                phase = (float) Math.max(0.0, Math.min(1.0, fraction));
                presentation = phase <= 0f ? PRESENT_REAL : PRESENT_SYNTHETIC;
                // Rotate after this successful synthetic when the next
                // uniformly selected output slot reaches or passes right.
                // Display performs the rotation post-swap, so the expensive
                // solve never delays the current visible present. This is the
                // essential look-ahead step for arbitrary-phase 20->30,
                // 40->60 and 50->60 resampling: the next callback begins with
                // the pair that actually brackets its timestamp.
                long nextTargetSourceNs = saturatingAdd(targetSourceNs,
                        bufferedUniformOutputPeriodNs());
                // Cover integer period rounding and the Thor's measured
                // sub-millisecond callback-vs-mode skew, but stay well below
                // the 3.33-ms gap that distinguishes a genuine 50->60 sample
                // from the following source endpoint.
                // A quarter scan covers the measured callback/endpoint phase
                // skew on Thor (20->40 physically reached 1.003 ms beyond the
                // old 1-ms allowance) while remaining strictly below the
                // 3.333-ms gap that distinguishes a genuine 50->60 sample.
                long advanceToleranceNs = Math.max(1_000L,
                        displayPeriodNs / 4L);
                pendingAdvance = saturatingAdd(nextTargetSourceNs,
                        advanceToleranceNs) >=
                        rightTimestampNs ? 1 : 0;
            }
        }

        if (presentation == PRESENT_SYNTHETIC &&
                bufferedLastSyntheticLeftSequence == leftSequence &&
                bufferedLastSyntheticRightSequence == rightSequence &&
                targetSourceNs <= bufferedLastSyntheticTargetSourceNs) {
            if (slotLatticeProducer) {
                // Same quantization artefact as the lead wait above: the
                // display caught up on a clamped target.  Wait one scan.
                // Nothing is presented, so this is NOT a repeated producer-
                // clock sample: the evidence verifier rejects any HEALTH
                // window whose duplicate-pair-selection count is non-zero
                // ("v37 repeated a producer-clock sample", run wiiu-b48b).
                ++bufferedUnavailableSlotCount;
                ++bufferedDuplicateWaitCount;
                bufferedLastUnavailableReason = "duplicate-target";
                return PRESENT_NONE;
            }
            ++bufferedDuplicateTargetCount;
            failBufferedPresentation("duplicate-synthetic-target");
            return PRESENT_NONE;
        }
        if (bufferedOutputCredits <= 0) {
            recordUnavailableSlot(displayFrameNs, "output-credit-empty");
            return PRESENT_NONE;
        }
        // Rotation requires the retained right endpoint. When it is absent,
        // consume this physical output slot without swapping and wait for the
        // exact successor; no later callback can burst to catch up.
        if (pendingAdvance > 0 &&
                !(directOnly ? structuralPair : validPair)) {
            recordUnavailableSlot(displayFrameNs, "advance-successor-not-ready");
            failBufferedPresentation("advance-without-ready-pair");
            return PRESENT_NONE;
        }
        bufferedPrimeWaitStreak = 0;
        bufferedPendingPresentation = presentation;
        bufferedPendingPhase = phase;
        bufferedPendingAdvance = pendingAdvance;
        bufferedPendingSelectionCallbackNs = displayFrameNs;
        bufferedPendingDisplayFrameNs = physicalPresentationNs;
        bufferedPendingLeftSequence = leftSequence;
        bufferedPendingRightSequence = rightSequence;
        bufferedPendingLeftTimestampNs = leftTimestampNs;
        bufferedPendingRightTimestampNs = rightTimestampNs;
        bufferedPendingTargetSourceNs = targetSourceNs;
        bufferedPendingRawTargetSourceNs = rawTargetSourceNs;
        bufferedPendingPrime = pendingPrime;
        bufferedPendingMidpointOmitted = pendingMidpointOmitted;
        return presentation;
    }

    /**
     * Commits a selected decision only after the renderer knows whether its
     * visible swap succeeded. A failed swap invalidates the pair and requires
     * two newer endpoints; it never increments a user-facing frame count.
     */
    public void commitBufferedPresentation(boolean swapSucceeded) {
        if (bufferedPendingPresentation == PRESENT_NONE) return;
        if (!swapSucceeded) {
            failBufferedPresentation("swap-failed");
            clearBufferedPendingDecision();
            return;
        }

        if (bufferedPendingPrime) {
            bufferedPrimed = true;
            rephaseBufferedPacingAfterPrime();
            bufferedPrimeNeedsPacingRephase = false;
            ++bufferedReprimeCount;
        }
        bufferedLeftSequence = bufferedPendingLeftSequence;
        bufferedRightSequence = bufferedPendingRightSequence;
        bufferedLeftTimestampNs = bufferedPendingLeftTimestampNs;
        bufferedRightTimestampNs = bufferedPendingRightTimestampNs;
        bufferedLastTargetSourceNs = bufferedPendingTargetSourceNs;
        bufferedLastRawTargetSourceNs = bufferedPendingRawTargetSourceNs;
        if (bufferedPendingPresentation == PRESENT_REAL) {
            // The committed real present is the physical time anchor for
            // every following synthetic phase in this pair (see the
            // slot-offset phase computation in selectBufferedPresentation).
            bufferedLastRealDisplayFrameNs = bufferedPendingDisplayFrameNs;
            // A snapped REAL is content identity, not a new source-clock
            // origin. Re-anchoring to it erases accumulated source-time debt:
            // at 118.36 callbacks on a nominal120 panel, forcing A/G/B then
            // re-anchoring B consumes only59.18 real frames/s of a60Hz game.
            // Preserve the prime's continuous clock projection so a later
            // due slot can prioritize the exact right endpoint and honestly
            // omit its stale midpoint. Raw projection monotonicity, not the
            // snapped content timestamp, already guards time reversal above.
            recordEndpointOffset(bufferedPendingDisplayFrameNs,
                    bufferedPendingRawTargetSourceNs -
                            bufferedPendingTargetSourceNs);
            if (bufferedPendingMidpointOmitted)
                ++bufferedMidpointOmittedCount;
        }
        selectedPhase = bufferedPendingPhase;
        bufferedAdvanceAfterPresentation = bufferedPendingAdvance;
        bufferedExpectedAdvance = bufferedPendingAdvance;
        if (bufferedOutputCredits <= 0) {
            failBufferedPresentation("credit-underflow-on-commit");
            clearBufferedPendingDecision();
            return;
        }
        --bufferedOutputCredits;
        if (bufferedPendingPresentation == PRESENT_REAL) {
            ++bufferedRealCount;
        } else {
            bufferedLastSyntheticLeftSequence = bufferedPendingLeftSequence;
            bufferedLastSyntheticRightSequence = bufferedPendingRightSequence;
            bufferedLastSyntheticTargetSourceNs = bufferedPendingTargetSourceNs;
            ++bufferedSyntheticCount;
        }
        if (bufferedPendingAdvance == 1) {
            // The successful swap commits the endpoint rotation. Display
            // applies the same one-pop operation immediately after this
            // method returns, so retaining the old pair here and deferring
            // reconciliation until a later selected callback creates two
            // owners for one already-committed transition. On Thor's
            // measured 118.36-Hz callback clock that stale handshake drifted
            // into endpoint-advance-mismatch roughly once per second even
            // though every physical 60-Hz endpoint was contiguous.
            //
            // Move the controller to the exact committed right endpoint now.
            // Its successor may still be absent; right=0 is the explicit
            // look-ahead wait state and cannot authorize interpolation. A
            // Display-side failure while applying the pop still calls
            // resetPresentation(), so the two owners remain fail-closed.
            bufferedLeftSequence = bufferedPendingRightSequence;
            bufferedLeftTimestampNs = bufferedPendingRightTimestampNs;
            bufferedRightSequence = 0L;
            bufferedRightTimestampNs = 0L;
            bufferedExpectedAdvance = 0;
        }
        ++bufferedPresentationCount;
        clearBufferedPendingDecision();
    }

    public void abortBufferedPresentation() {
        commitBufferedPresentation(false);
    }

    /**
     * Defers one selected future output without consuming its divisor slot.
     *
     * <p>This is only for a transport that proves the preceding visible row's
     * immutable timed-release gate has not opened yet while the newly selected
     * target still remains safely in the future. The next physical callback may
     * select the same target once; no output, credit, endpoint advance, failure,
     * or catch-up counter is committed here.</p>
     */
    public void deferBufferedPresentationSlot() {
        if (bufferedPendingPresentation == PRESENT_NONE) return;
        bufferedPacingCountdown = 0;
        clearBufferedPendingDecision();
    }

    /**
     * Drops one selected physical output slot without invalidating its exact
     * retained endpoint pair.
     *
     * <p>This is narrower than {@link #abortBufferedPresentation()}: it is used
     * only when a nonblocking external backend reports that its preceding WSI
     * operation still owns the transport. The selected output lattice slot was
     * already consumed, so clearing the pending decision cannot create a retry
     * or catch-up burst. No swap, REAL/SYNTHETIC counter, endpoint advance, or
     * output credit is committed. The following ordinary divisor slot may use
     * the same exact pair at its newly timestamped phase.</p>
     */
    public void dropBufferedPresentationSlot() {
        if (bufferedPendingPresentation == PRESENT_NONE) return;
        bufferedLastUnavailableReason = "external-transport-busy";
        ++bufferedUnavailableSlotCount;
        ++bufferedUnderrunCount;
        clearBufferedPendingDecision();
    }

    /** Number of FIFO endpoints to pop after the selected swap succeeds. */
    public int bufferedEndpointAdvanceAfterPresentation() {
        return bufferedPendingPresentation == PRESENT_NONE ?
                bufferedAdvanceAfterPresentation : bufferedPendingAdvance;
    }

    /**
     * Whether the currently selected, still-uncommitted output belongs to the
     * exact endpoint/midpoint lattice used by an integer 2x backend.
     *
     * <p>The renderer asks this only while building private work behind the
     * selected visible WSI submission.  Use the immutable schedule identity
     * captured by selection rather than recomputing a tier from a later
     * producer observation.</p>
     */
    public boolean bufferedPendingExactDoubleSchedule() {
        return bufferedPendingPresentation != PRESENT_NONE &&
                exactDoubleEndpointLatticeRequired && generationAvailable &&
                bufferedScheduledSourceFps > 0 &&
                bufferedScheduledOutputFps ==
                        bufferedScheduledSourceFps * 2;
    }

    /** Interpolation phase selected by the most recent buffered decision. */
    public float bufferedSelectedPhase() {
        return bufferedPendingPresentation == PRESENT_NONE ?
                selectedPhase : bufferedPendingPhase;
    }

    /** Producer-clock position represented by the selected output sample. */
    public long bufferedSelectedTargetSourceNs() {
        return bufferedPendingPresentation == PRESENT_NONE ?
                bufferedLastTargetSourceNs : bufferedPendingTargetSourceNs;
    }

    /**
     * Pure preview of the producer timestamp represented by a future physical
     * scan on the already-committed buffered timeline.
     *
     * <p>This never selects or consumes an output slot. It exists so an
     * external backend can prepare the exact future pixels in private GPU
     * storage before WSI ownership begins. A zero result means that no stable
     * committed timeline exists yet.</p>
     */
    public long previewBufferedTargetSourceNs(long physicalPresentationNs) {
        if (!bufferedPrimed ||
                bufferedPendingPresentation != PRESENT_NONE ||
                bufferedTimelineDisplayAnchorNs <= 0L ||
                bufferedTimelineSourceAnchorNs <= 0L ||
                physicalPresentationNs < bufferedTimelineDisplayAnchorNs)
            return 0L;
        return saturatingAdd(bufferedTimelineSourceAnchorNs,
                physicalPresentationNs - bufferedTimelineDisplayAnchorNs);
    }

    /**
     * Pure preview of the source timestamp at a future physical scan after the
     * currently selected decision commits successfully.
     *
     * <p>The pending decision remains the controller's sole mutable owner. This
     * accessor neither commits it nor consumes another output slot. It exists
     * for a private external backend to prepare the following fractional image
     * while the selected REAL endpoint is being presented. In particular, an
     * exact 2x REAL-right decision advances the renderer from A/B to B/C; the
     * following midpoint must therefore be prepared from B/C, not the A/B pair
     * that the REAL is about to retire.</p>
     */
    public long previewBufferedTargetSourceNsAfterPendingCommit(
            long physicalPresentationNs) {
        if (bufferedPendingPresentation == PRESENT_NONE ||
                bufferedTimelineDisplayAnchorNs <= 0L ||
                bufferedTimelineSourceAnchorNs <= 0L ||
                physicalPresentationNs <= bufferedPendingDisplayFrameNs ||
                physicalPresentationNs < bufferedTimelineDisplayAnchorNs)
            return 0L;
        return saturatingAdd(bufferedTimelineSourceAnchorNs,
                physicalPresentationNs - bufferedTimelineDisplayAnchorNs);
    }

    /**
     * Exact target for a private output following the pending REAL decision.
     *
     * <p>Integer 2x paths are defined by their adjacent endpoint midpoint, so
     * their private and visible requests must not depend on a physical clock
     * that may be recalibrated between callbacks. Other uniform conversions
     * retain the continuous timestamp playhead until they receive their own
     * deterministic rational preparation contract.</p>
     */
    public long previewBufferedGeneratedTargetSourceNsAfterPendingCommit(
            long physicalPresentationNs,
            long leftTimestampNs, long rightTimestampNs) {
        if (leftTimestampNs <= 0L || rightTimestampNs <= leftTimestampNs)
            return 0L;
        double exactSourceHz = presentationSourceHz();
        int source = authoritativeSourceHz > 0.0 ?
                Math.max(1, (int) Math.round(exactSourceHz)) :
                (tierAcquired ? lockedSourceFps() :
                        provisionalSourceFps(exactSourceHz));
        if (exactDoubleEndpointLatticeRequired && generationAvailable &&
                hasSustainableGenerationRate() && source > 0 &&
                outputFps() == source * 2)
            return exactMidpointTimestampNs(
                    leftTimestampNs, rightTimestampNs);
        return previewBufferedTargetSourceNsAfterPendingCommit(
                physicalPresentationNs);
    }

    /**
     * True when the measured source clock and the selected output clock are
     * an exact doubling lattice within timestamp representation tolerance.
     * The tier label alone cannot authorize a generated conversion.
     */
    private boolean measuredIntegerLattice() {
        double source = presentationSourceHz();
        double output = targetOutputHz();
        return source > 0.0 && Math.abs(output - 2.0 * source) <= 1.0e-5;
    }

    /** Two only for exact integer doubling, otherwise zero. */
    private static int integerLatticeFactor(int source, int output) {
        return source > 0 && output == source * 2 ? 2 : 0;
    }

    /**
     * Symmetric endpoint snap: half an output period on either side of a
     * retained endpoint.  Output slots are one output period apart, so the
     * slot nearest an endpoint is always inside this window and exactly one
     * slot per source interval presents the exact endpoint; every interior
     * sample of an integer lattice (>= one output period away) and every
     * neighbouring slot stays outside it.  Unqualified direct plans keep the
     * former half-scan clamp.
     */
    private long realEndpointSnapToleranceNs() {
        int scans = Math.max(1, panelScansPerOutput());
        return Math.max(1_000L, displayPeriodNs * scans / 2L - 1L);
    }

    /** Overflow-safe floor of the exact midpoint between ordered timestamps. */
    public static long exactMidpointTimestampNs(
            long leftTimestampNs, long rightTimestampNs) {
        if (leftTimestampNs <= 0L || rightTimestampNs <= leftTimestampNs)
            return 0L;
        return leftTimestampNs +
                (rightTimestampNs - leftTimestampNs) / 2L;
    }

    /**
     * Pure preview of whether the next selection call on this callback will
     * consume a divisor-lattice output slot.
     *
     * <p>External inference uses this before starting private GPU work. It
     * must not mutate the countdown: {@link #selectBufferedPresentation} is
     * still the sole owner that consumes the callback slot. Preparing on an
     * intervening non-output callback fills the backend's one private slot
     * with a timestamp the later selected callback can never use.</p>
     */
    public boolean previewBufferedPresentationDue(long displayFrameNs) {
        if (displayFrameNs <= 0L) return false;
        if (!generationAvailable || !hasSustainableGenerationRate() ||
                !uniformOutputQualified()) return true;
        int scans = panelScansPerOutput();
        if (scans < 1) return false;
        if (bufferedPacingPanelScans != scans) return true;
        return bufferedPacingCountdown == 0;
    }

    public boolean bufferedPrimed() { return bufferedPrimed; }
    public long bufferedMinimumReprimeSequence() {
        return bufferedMinimumReprimeSequence;
    }
    public int bufferedOutputCredits() { return bufferedOutputCredits; }
    public int bufferedExpectedAdvance() { return bufferedExpectedAdvance; }
    public long bufferedRetainedLeftSequence() { return bufferedLeftSequence; }
    public long bufferedRetainedRightSequence() { return bufferedRightSequence; }
    public String bufferedLastMismatchDiagnostic() {
        return bufferedLastMismatchDiagnostic;
    }

    public long bufferedPresentationEpoch() { return bufferedPresentationEpoch; }
    public String bufferedLastEpochReason() { return bufferedLastEpochReason; }
    public long bufferedPresentationCount() { return bufferedPresentationCount; }
    public long bufferedRealCount() { return bufferedRealCount; }
    public long bufferedSyntheticCount() { return bufferedSyntheticCount; }
    public long bufferedUnderrunCount() { return bufferedUnderrunCount; }
    public long bufferedUnavailableSlotCount() { return bufferedUnavailableSlotCount; }
    public long bufferedMidpointOmittedCount() { return bufferedMidpointOmittedCount; }
    public long bufferedReprimeCount() { return bufferedReprimeCount; }
    public long bufferedDuplicateTargetCount() { return bufferedDuplicateTargetCount; }

    private boolean bufferedPresentationDue(long displayFrameNs) {
        if (displayFrameNs <= 0L) return false;
        // Until immutable UNIQUE-image timestamps prove a durable uniform
        // generation clock, present every classified endpoint on the first
        // available panel callback.  Pacing an irregular direct stream from a
        // rounded tier suppressed real endpoints and made the fallback more
        // choppy than the emulator.  This path cannot fabricate duplicates:
        // selection still requires a newly retained endpoint.
        if (!generationAvailable || !hasSustainableGenerationRate() ||
                !uniformOutputQualified()) return true;
        int scans = panelScansPerOutput();
        if (scans < 1) return false;
        if (bufferedPacingPanelScans != scans) {
            bufferedPacingPanelScans = scans;
            // Make the first callback a selected slot. Every later selected
            // slot is exactly `scans` physical callbacks away.
            bufferedPacingCountdown = 0;
        }
        if (bufferedPacingCountdown > 0) {
            --bufferedPacingCountdown;
            return false;
        }
        bufferedPacingCountdown = scans - 1;
        return true;
    }

    /** Nominal source-timeline distance between uniformly selected slots. */
    private long bufferedUniformOutputPeriodNs() {
        int scans = panelScansPerOutput();
        if (scans < 1) return Long.MAX_VALUE;
        // The mode advertises nominal 120 Hz, while Thor's physical callback
        // stream is about 118.36 Hz. Pair rotation predicts the *next selected
        // callback*, so using the nominal 8.333-ms period can miss a 20->40
        // right boundary by only a few microseconds, spend both source credits,
        // and deadlock on the old pair forever. Phase itself still uses the
        // actual presentation timestamp above; this observed period is only a
        // bounded one-slot look-ahead for post-swap endpoint ownership.
        long panelPeriodNs = bufferedObservedPanelPeriodNs > 0L ?
                bufferedObservedPanelPeriodNs : displayPeriodNs;
        return saturatingMultiply(panelPeriodNs, scans);
    }

    /**
     * Anchors the physical-slot accumulator to the retained source timeline.
     *
     * <p>Before a pair exists, unavailable callbacks still consume output
     * slots so the renderer can never catch up in a burst. Once the first
     * buffered REAL is successfully visible, however, that arbitrary startup
     * phase must not decide the lifetime 80/100 cadence. For outputs above
     * half the panel rate, select the immediately following callback and let
     * the reduced rational accumulator place the compensating skip. Divisor
     * outputs begin from zero and retain their exact 2/3-callback spacing.</p>
     */
    private void rephaseBufferedPacingAfterPrime() {
        if (!generationAvailable || !hasSustainableGenerationRate() ||
                !uniformOutputQualified()) return;
        int outputScans = panelScansPerOutput();
        long panelPeriodNs = bufferedObservedPanelPeriodNs > 0L ?
                bufferedObservedPanelPeriodNs : displayPeriodNs;
        long leadNs = bufferedPendingDisplayFrameNs -
                bufferedPendingSelectionCallbackNs;
        if (outputScans < 1 || panelPeriodNs <= 0L || leadNs <= 0L) return;

        // A buffered decision renders for a FUTURE physical scan. Pacing the
        // following decision from the Java submission callback instead of
        // that scan permanently subtracts the initial pipeline distance from
        // every later backend deadline. On Thor's 20->40 path that left only
        // two scans; physical r92 eventually latched 0.285 ms after
        // SurfaceFlinger's deadline and was deferred by one whole scan.
        //
        // Consume only the intervening callbacks, then select again on the
        // prior frame's physical scan. That decision targets the following
        // divisor slot and therefore restores the full three-scan 20->40 lead
        // without adding, dropping, retrying, or catching up an output. Once
        // aligned, the ordinary divisor countdown stays phase-stable.
        long roundedLeadScans = Math.round(
                (double) leadNs / (double) panelPeriodNs);
        if (roundedLeadScans < 1L) return;
        int callbacksToPhysicalScan = (int) Math.min(
                (long) outputScans, roundedLeadScans);
        bufferedPacingPanelScans = outputScans;
        bufferedPacingCountdown = callbacksToPhysicalScan - 1;
    }

    /**
     * Returns whether two accepted images are close enough in producer time to
     * form one interpolation interval. Sequence adjacency alone is insufficient:
     * the last image before a loading/static pause and the first changing image
     * afterward are adjacent unique samples but must never be slowly morphed
     * across the whole pause.
     */
    public static boolean endpointSpanContinuous(
            long leftTimestampNs, long rightTimestampNs, int sourceFps) {
        return endpointSpanContinuous(leftTimestampNs, rightTimestampNs,
                (double) sourceFps);
    }

    /** A span of 1.5 to 2.5 source periods: exactly one held or lost frame. */
    public static boolean endpointSpanBridgesOneHeldFrame(
            long leftTimestampNs, long rightTimestampNs, double sourceHz) {
        return endpointSpanBridgesHeldFrames(leftTimestampNs, rightTimestampNs,
                sourceHz, 1);
    }

    /**
     * @param maxHeldFrames 1 bridges one held/dropped frame (a span of two
     *        source periods); 2 also bridges two consecutive dropped frames
     *        (three periods) -- slot-lattice producers under load drop pairs
     *        of frames, and cutting the pair there cost a four-endpoint
     *        re-prime of 6-13 empty scans each time (wiiu-b45: 571 cuts).
     */
    public static boolean endpointSpanBridgesHeldFrames(
            long leftTimestampNs, long rightTimestampNs, double sourceHz,
            int maxHeldFrames) {
        if (leftTimestampNs <= 0L || rightTimestampNs <= leftTimestampNs ||
                !Double.isFinite(sourceHz) || sourceHz <= 0.0) return false;
        double exactPeriods = (rightTimestampNs - leftTimestampNs) *
                sourceHz / 1_000_000_000.0;
        return exactPeriods >= 1.5 &&
                exactPeriods <= 1.5 + Math.max(1, maxHeldFrames);
    }

    public static boolean endpointSpanContinuous(
            long leftTimestampNs, long rightTimestampNs, double sourceHz) {
        if (leftTimestampNs <= 0L || rightTimestampNs <= leftTimestampNs ||
                !Double.isFinite(sourceHz) || sourceHz <= 0.0) return false;
        long spanNs = rightTimestampNs - leftTimestampNs;
        // Presentation endpoints are the exact classified unique-image stream.
        // One sequence step must therefore represent roughly one measured
        // source period; pixel-identical callbacks are held frames and never
        // extend a pair. The former 4.5-period allowance could make a two-
        // endpoint pair cover six 20->40 output slots, exhausting the honest
        // 2x ledger and freezing on the pair.
        // Permit bounded scheduling jitter up to 1.5 periods, but treat a
        // genuinely missing/late interval as a cut and re-prime. Never morph
        // or extrapolate across it.
        long maxSpanNs = Math.max(1L,
                (long) Math.ceil(1_500_000_000.0 / sourceHz));
        return spanNs <= maxSpanNs;
    }

    /**
     * True only when a classified producer callback occupies the immediately
     * following slot of an already-proven source clock.
     *
     * <p>This is intentionally much stricter than endpointSpanContinuous(): a
     * pixel-identical callback may be retained as the real source endpoint it
     * actually delivered, but it may never be used to bridge a late, missing,
     * or fractional-host callback.  The renderer additionally requires an
     * independently qualified source before calling this predicate.</p>
     */
    public static boolean duplicateOccupiesNextSourceSlot(
            long leftTimestampNs, long rightTimestampNs, double sourceHz,
            long leftSubmission, long rightSubmission) {
        if (leftTimestampNs <= 0L || rightTimestampNs <= leftTimestampNs ||
                !Double.isFinite(sourceHz) || sourceHz <= 0.0 ||
                leftSubmission <= 0L || rightSubmission <= leftSubmission)
            return false;
        double exactPeriods = (rightTimestampNs - leftTimestampNs) *
                sourceHz / 1_000_000_000.0;
        return Math.abs(exactPeriods - 1.0) <=
                CANONICAL_PERIOD_MAX_FRACTION;
    }

    /**
     * Binds a production pair to consecutive classified unique images in one
     * ownership epoch. Pixel-identical callbacks are held images, not new
     * endpoints, and cannot extend the interval: interpolating across such a
     * hold would begin motion before the later changed image actually exists.
     */
    public static boolean endpointSpanContinuous(
            long leftTimestampNs, long rightTimestampNs, double sourceHz,
            long leftUniqueSequence, long rightUniqueSequence,
            long leftSubmission, long rightSubmission,
            long leftCandidateLoss, long rightCandidateLoss) {
        return endpointSpanContinuous(leftTimestampNs, rightTimestampNs,
                sourceHz, leftUniqueSequence, rightUniqueSequence,
                leftSubmission, rightSubmission, leftCandidateLoss,
                rightCandidateLoss, false);
    }

    /**
     * @param missingSubmissionBridges retained for source compatibility only;
     *        missing guest frames never authorize a longer interpolation pair.
     */
    public static boolean endpointSpanContinuous(
            long leftTimestampNs, long rightTimestampNs, double sourceHz,
            long leftUniqueSequence, long rightUniqueSequence,
            long leftSubmission, long rightSubmission,
            long leftCandidateLoss, long rightCandidateLoss,
            boolean missingSubmissionBridges) {
        // Zero provenance is reserved for the compatibility overload used by
        // host callers. Production always supplies positive classifier and
        // submission ordinals; it must prove exactly one unique-image advance
        // and an unchanged ownership-loss epoch.
        boolean hasProvenance = leftUniqueSequence > 0L ||
                rightUniqueSequence > 0L || leftSubmission > 0L ||
                rightSubmission > 0L || leftCandidateLoss > 0L ||
                rightCandidateLoss > 0L;
        if (!hasProvenance)
            return endpointSpanContinuous(leftTimestampNs, rightTimestampNs,
                    sourceHz);
        long uniqueAdvance = rightUniqueSequence - leftUniqueSequence;
        if (leftCandidateLoss != rightCandidateLoss ||
                leftUniqueSequence <= 0L || uniqueAdvance != 1L ||
                leftSubmission <= 0L || rightSubmission <= leftSubmission ||
                leftTimestampNs <= 0L || rightTimestampNs <= leftTimestampNs ||
                !Double.isFinite(sourceHz) || sourceHz <= 0.0) return false;
        // Unique-image adjacency does not turn two or three source periods
        // into one valid pair. Holding/missing a frame ends interpolation;
        // preserve real endpoints and re-prime, never fill several slots by
        // inventing multiple fractions from the same images.
        return endpointSpanContinuous(leftTimestampNs, rightTimestampNs,
                sourceHz);
    }

    private int callbacksUntilNextBufferedSlot() {
        return Math.max(1, bufferedPacingCountdown + 1);
    }

    /** Starved output slots inside one rolling window demote the tier: a
     * mean-supported tier whose fifth-percentile delivery cannot fund it
     * presents visible hiccups every dip (SM3DW on Cemu measured 31-60 Hz
     * around a mean-locked 40, 2026-08-16). One steady lower tier is the
     * smoother truth. The demotion holds off mean-driven re-upgrades long
     * enough that the producer must prove sustained headroom without a
     * single starved slot before the tier may rise again. */
    private static final long STARVATION_DEMOTION_WINDOW_NS = 8_000_000_000L;
    // Proportional, not absolute: a proven 60 tier legitimately holds a
    // ~58.7 Hz physical source with ~1% of panel slots left empty (Wii r52),
    // while SM3DW's 31-60 Hz swings around a mean-locked 40 starve >20% of
    // slots during every dip. Three percent of the rolling window's output
    // demand separates those regimes with margin on both sides.
    private static final int STARVATION_DEMOTION_PERCENT = 3;
    private static final long STARVATION_UPGRADE_HOLD_NS = 30_000_000_000L;
    // Two material-starvation windows within this horizon = chronic: the
    // tier outruns what the source delivers smoothly even if between-burst
    // seconds look full.
    private static final long CHRONIC_STARVATION_HORIZON_NS = 20_000_000_000L;
    private long lastMaterialStarvationNs = Long.MIN_VALUE / 2;
    // Re-climb evidence: after a starvation demotion, an upgrade must be
    // funded by the MINIMUM worst-second observed across the whole hold —
    // not just the six seconds in the ring at expiry. The first 8 s after
    // the demotion are settle grace (the ring still holds the dip that
    // caused it).
    private static final long RECLIMB_EVIDENCE_GRACE_NS = 8_000_000_000L;
    private long reclimbEvidenceStartNs = Long.MAX_VALUE;
    private double reclimbEvidenceMinRate = Double.MAX_VALUE;

    private int nextHigherTier(int tier) {
        int candidate = tier;
        for (int index = tiers.length - 1; index >= 0; --index) {
            if (tiers[index] > tier) { candidate = tiers[index]; break; }
        }
        return candidate;
    }
    private long starvationWindowStartNs;
    private int starvationSlotsInWindow;
    private long starvationUpgradeHoldUntilNs;
    private long starvationDemotionCount;
    private long bufferedLastSelectionDisplayFrameNs;
    private String bufferedLastMismatchDiagnostic = "none";

    public long starvationDemotionCount() { return starvationDemotionCount; }

    private int nextLowerTier(int tier) {
        for (int candidate : tiers) if (candidate < tier) return candidate;
        return tier;
    }

    private String bufferedLastUnavailableReason = "none";
    public String bufferedLastUnavailableReason() { return bufferedLastUnavailableReason; }

    private void recordUnavailableSlot(long displayFrameNs, String reason) {
        bufferedLastUnavailableReason = reason;
        ++bufferedUnavailableSlotCount;
        // Renderer/FIFO starvation is not source-rate evidence. The physical
        // ALBW trace on 2026-08-20 delivered roughly 60 unique endpoints while
        // this path successively rewrote the source as 50, 40 and 30. That
        // suppressed real emulator frames and drove top-panel cadence into the
        // low forties. Source tiers are owned exclusively by immutable
        // producer timestamps in updateTier(). Starvation remains telemetry
        // and may fail generation closed, but it must never lower the source.
    }

    private void failBufferedPresentation(String reason) {
        bufferedLastEpochReason = reason == null ? "unknown-failure" : reason;
        ++bufferedUnderrunCount;
        bufferedMinimumReprimeSequence = Math.max(bufferedMinimumReprimeSequence,
                Math.max(Math.max(bufferedLeftSequence, bufferedRightSequence),
                        Math.max(bufferedPendingLeftSequence,
                                bufferedPendingRightSequence)));
        bufferedPrimed = false;
        bufferedTimelineDisplayAnchorNs = 0L;
        bufferedLastRealDisplayFrameNs = 0L;
        bufferedTimelineSourceAnchorNs = 0L;
        bufferedLastTargetSourceNs = 0L;
        bufferedLastRawTargetSourceNs = 0L;
        bufferedAdvanceAfterPresentation = 0;
        bufferedExpectedAdvance = 0;
        bufferedCreditedRightSequence = 0L;
        bufferedOutputCredits = 0;
        bufferedPrimeNeedsPacingRephase = true;
        ++bufferedPresentationEpoch;
    }

    private void clearBufferedPendingDecision() {
        bufferedPendingPresentation = PRESENT_NONE;
        bufferedPendingAdvance = 0;
        bufferedPendingLeftSequence = 0L;
        bufferedPendingRightSequence = 0L;
        bufferedPendingLeftTimestampNs = 0L;
        bufferedPendingRightTimestampNs = 0L;
        bufferedPendingTargetSourceNs = 0L;
        bufferedPendingSelectionCallbackNs = 0L;
        bufferedPendingPhase = 0f;
        bufferedPendingPrime = false;
        bufferedPendingMidpointOmitted = false;
    }

    private void recordEndpointOffset(long displayNs, long offsetNs) {
        driftLatestOffsetNs = offsetNs;
        if (displayNs - driftLastSampleNs < 250_000_000L && driftCount > 0)
            return;
        driftLastSampleNs = displayNs;
        driftDisplayNs[driftIndex] = displayNs;
        driftOffsetNs[driftIndex] = offsetNs;
        driftIndex = (driftIndex + 1) % DRIFT_SAMPLES;
        if (driftCount < DRIFT_SAMPLES) ++driftCount;
    }

    private void resetEndpointDrift() {
        driftCount = 0;
        driftIndex = 0;
        driftLastSampleNs = 0L;
        driftLatestOffsetNs = 0L;
    }

    /** Latest signed target-minus-endpoint residue at a REAL snap, ns. */
    public long endpointOffsetNs() { return driftLatestOffsetNs; }

    /**
     * Least-squares slope of the endpoint residue over the trailing samples
     * (microseconds of source lag gained per second of display time), or 0
     * until at least eight seconds of samples exist.  Positive means the
     * source timeline falls behind the scan lattice.
     */
    public double endpointDriftUsPerSecond() {
        if (driftCount < 8) return 0.0;
        int first = (driftIndex + DRIFT_SAMPLES - driftCount) % DRIFT_SAMPLES;
        long t0 = driftDisplayNs[first];
        double sumT = 0.0, sumO = 0.0, sumTT = 0.0, sumTO = 0.0;
        for (int i = 0; i < driftCount; ++i) {
            int index = (first + i) % DRIFT_SAMPLES;
            double t = (driftDisplayNs[index] - t0) / 1.0e9;
            double o = driftOffsetNs[index] / 1.0e3;
            sumT += t; sumO += o; sumTT += t * t; sumTO += t * o;
        }
        double n = driftCount;
        double span = (driftDisplayNs[(first + driftCount - 1) % DRIFT_SAMPLES]
                - t0) / 1.0e9;
        double denominator = n * sumTT - sumT * sumT;
        if (span < 8.0 || denominator <= 0.0) return 0.0;
        return (n * sumTO - sumT * sumO) / denominator;
    }

    /** Display-time span covered by the drift samples, seconds. */
    public double endpointDriftSpanSeconds() {
        if (driftCount < 2) return 0.0;
        int first = (driftIndex + DRIFT_SAMPLES - driftCount) % DRIFT_SAMPLES;
        int last = (first + driftCount - 1) % DRIFT_SAMPLES;
        return (driftDisplayNs[last] - driftDisplayNs[first]) / 1.0e9;
    }

    private void resetBufferedPresentation() {
        resetEndpointDrift();
        bufferedLastEpochReason = "presentation-reset";
        bufferedPacingPanelScans = 0;
        bufferedPacingCountdown = 0;
        // resetBufferedPresentation already publishes an epoch boundary.
        // Keep the schedule identity synchronized with that reset so the next
        // callback does not publish a redundant second boundary solely
        // because these fields were zeroed.
        boolean durableSchedule = authoritativeSourceHz > 0.0 ||
                hasSustainableGenerationRate();
        bufferedScheduledSourceFps = durableSchedule ?
                (authoritativeSourceHz > 0.0 ?
                        Math.max(1, (int) Math.round(
                                presentationSourceHz())) :
                        lockedSourceFps()) : 0;
        bufferedScheduledOutputFps = durableSchedule ? outputFps() : 0;
        bufferedTimelineDisplayAnchorNs = 0L;
        bufferedLastRealDisplayFrameNs = 0L;
        bufferedTimelineSourceAnchorNs = 0L;
        bufferedLastTargetSourceNs = 0L;
        bufferedLastRawTargetSourceNs = 0L;
        bufferedAdvanceAfterPresentation = 0;
        bufferedExpectedAdvance = 0;
        bufferedLeftSequence = 0L;
        bufferedRightSequence = 0L;
        bufferedLeftTimestampNs = 0L;
        bufferedRightTimestampNs = 0L;
        bufferedMinimumReprimeSequence = 0L;
        bufferedLastSyntheticLeftSequence = 0L;
        bufferedLastSyntheticRightSequence = 0L;
        bufferedLastSyntheticTargetSourceNs = 0L;
        bufferedCreditedRightSequence = 0L;
        bufferedOutputCredits = 0;
        bufferedPrimeNeedsPacingRephase = false;
        clearBufferedPendingDecision();
        bufferedPrimed = false;
        ++bufferedPresentationEpoch;
    }

    private static long saturatingAdd(long left, long right) {
        if (right > 0L && left > Long.MAX_VALUE - right) return Long.MAX_VALUE;
        if (right < 0L && left < Long.MIN_VALUE - right) return Long.MIN_VALUE;
        return left + right;
    }

    private static long saturatingMultiply(long value, long multiplier) {
        if (value <= 0L || multiplier <= 0L) return 0L;
        if (value > Long.MAX_VALUE / multiplier) return Long.MAX_VALUE;
        return value * multiplier;
    }

    public float selectedInterpolation() { return selectedPhase; }
    public long selectedPairSequence() { return midpointPairSequence; }
    public long dueSelectedCount() { return dueSelectedCount; }
    public long dueNoEndpointCount() { return dueNoEndpointCount; }
    public long duePhaseClampedCount() { return duePhaseClampedCount; }
    public long realPriorityCount() { return realPriorityCount; }
    public long syntheticQuotaSkippedCount() { return syntheticQuotaSkippedCount; }
    public long syntheticSelectedCount() { return syntheticSelectedCount; }
    public long syntheticPairCreatedCount() { return syntheticPairCreatedCount; }
    public long syntheticNotReadyCount() { return syntheticNotReadyCount; }
    public long duplicatePairSelectionCount() { return duplicatePairSelectionCount; }
    public long presentationCallbackCount() { return presentationCallbackCount; }
    public long presentationEpoch() { return presentationEpoch; }
    public int syntheticQuotaPending() { return midpointPending ? 1 : 0; }
    public long lastSelectedSyntheticPair() { return lastSelectedSyntheticPair; }

    /**
     * Reconciles a complete presentation window with endpoints that were
     * actually promoted. Producer signatures can arrive in bursts even when
     * their average interval suggests a higher tier. A lower achieved rate is
     * source starvation, not a renderer miss: step the advertised tier down
     * using the same Schmitt floor and require fresh producer evidence before
     * any later upgrade.
     */
    public boolean observePromotionWindow(long elapsedNs, long promotions) {
        // Renderer consumption is not source-rate evidence. A delayed
        // signature result, missing look-ahead endpoint or skipped generated
        // slot can lower promotions without lowering the emulator's unique
        // producer clock. Feeding that shortfall back into the source tier
        // caused the exact 60/120 <-> 50/100 oscillation seen on physical Wii.
        // Immutable producer timestamps are the sole tier authority; HEALTH
        // still reports promotion shortfall independently.
        return false;
    }

    /**
     * Compatibility hook retained while the renderer migrates to the buffered
     * selector. Presentation shortfall must never rewrite a source rate that
     * was measured from unique endpoint timestamps. The former implementation
     * converted missed midpoint quotas into a fictitious lower source tier;
     * on a 120-Hz panel that turned a proven 60-Hz GameCube stream into the
     * visibly uneven 50-to-100 5:6 cadence.
     */
    public boolean observeAttainableCadenceWindow(
            long elapsedNs, long promotions, long synthetics, long presents,
            long syntheticPairsCreated, long quotaSkipped,
            long openingQuota, long closingQuota, long dueNoEndpoint,
            long phaseClamped, long syntheticNotReady,
            long duplicatePairSelection, long callbacks, long epoch) {
        return false;
    }

    public int attainableCadenceCapFps() { return 60; }

    /** Interpolation phase from the previous promoted image to the current one. */
    public float interpolation(long displayFrameNs, int promotedImages) {
        if (promotedImages < 2 || !generatesIntermediateFrames()) return 1f;
        long elapsed = Math.max(0L, displayFrameNs - lastPromotionNs);
        long period = sourcePeriodNs();
        // Interpolation is defined only between the two decoded endpoints.
        // Once the current endpoint has been reached, hold it. Predicting past
        // it is not interpolation and becomes especially destructive when a
        // heavy emulator such as aPS3e delivers only 12-15 distinct FPS.
        return Math.min(1f, (float) elapsed / period);
    }

    /** True only while real endpoints arrive fast enough for a supported tier. */
    public boolean hasSustainableGenerationRate() {
        if (authoritativeSourceHz > 0.0) return latestSequence > 0L;
        return latestSequence > 0L &&
                qualifiedUniqueTimestampSourceHz >=
                        MIN_GENERATION_SOURCE_HZ;
    }

    public int lockedSourceFps() {
        if (authoritativeSourceHz > 0.0) return authoritativeSourceFps;
        // Once the complete immutable unique-timestamp window has qualified a
        // source, every public/scheduler integer identity must describe that
        // same authority.  Falling through to the ten-period delivery ring
        // made physical Ocarina alternate20->18->20 while its exact20-Hz
        // qualified clock and uniform20->40 plan never changed, resetting the
        // buffered evidence epoch sixteen times in r78.  A true source change
        // still revokes qualifiedUniqueTimestampSourceHz in the strict proof
        // path before this branch can preserve the old identity.
        if (generationAvailable && qualifiedUniqueTimestampSourceHz > 0.0)
            return downgradeTierFor(qualifiedUniqueTimestampSourceHz,
                    lockedSourceFps);
        if (!generationAvailable && directFallbackSourceFps > 0)
            return directFallbackSourceFps;
        if (tierAcquired &&
                (measuredProducerHz() >= MIN_GENERATION_SOURCE_HZ ||
                        measuredSubmissionHz() >= MIN_GENERATION_SOURCE_HZ))
            return lockedSourceFps;
        // Tier voting needs a complete window, but presentation must not claim
        // or submit a default 60/120 cadence while a slow producer is still
        // being measured. After the first valid elapsed interval, expose the
        // measured unique-image rate and stay direct-only until MIN_SAMPLES.
        if (!tierAcquired && producerSamples > 0)
            return provisionalSourceFps(measuredProducerHz());
        if (producerSamples > 0 &&
                measuredProducerHz() < MIN_GENERATION_SOURCE_HZ)
            return measuredSourceFps();
        return lockedSourceFps;
    }

    /**
     * Nominal integer label for the selected buffer-update target.
     *
     * <p>The actual decision is made in {@link UniformFrameRatePlan} without
     * rounding either clock.  This compatibility accessor is retained for the
     * existing Android telemetry/schema; scheduling and future evidence can
     * use {@link #targetOutputHz()} and {@link #panelScansPerOutput()} to keep
     * canonical fractional clocks exact.  Successful physical presentation
     * counters, not this target, own the user-visible delivered rate.</p>
     */
    /** At most two output samples may be funded by one source endpoint. */
    private int outputCreditsPerEndpoint() {
        return 2;
    }

    /** Intermediate slots the legacy arrival scheduler owns per pair. */
    private int legacyIntermediateSlotsPerPair() {
        return 1;
    }

    /**
     * Compatibility hook: delivery tiers never authorize changes to gameplay
     * speed. Bounded synchronization belongs to the core clock policy, which
     * knows the declared timing; zero always leaves that authority untouched.
     */
    public int pacingSourceFps(double emulatorClockHz) {
        return 0;
    }

    public int outputFps() {
        double source = presentationSourceHz();
        if (!generationAvailable || !hasSustainableGenerationRate())
            return Math.max(1, (int) Math.round(
                    Math.min(displayRefreshHz, source)));
        UniformFrameRatePlan plan = currentUniformOutputPlan();
        return Math.max(1, (int) Math.round(plan.outputHz()));
    }

    /** Exact selected panel-divisor output clock, prior to UI rounding. */
    public double targetOutputHz() {
        if (!generationAvailable || !hasSustainableGenerationRate())
            return Math.min(displayRefreshHz, presentationSourceHz());
        return currentUniformOutputPlan().outputHz();
    }

    /** Number of physical panel scans occupied by every qualified output. */
    public int panelScansPerOutput() {
        if (!generationAvailable || !hasSustainableGenerationRate()) return 0;
        return currentUniformOutputPlan().panelScansPerOutput();
    }

    /** Whether the selected generated target satisfies the uniform divisor rule. */
    public boolean uniformOutputQualified() {
        return generationAvailable && hasSustainableGenerationRate() &&
                currentUniformOutputPlan().qualified();
    }

    /**
     * Candidate generated target for backend path certification.
     *
     * <p>Backend selection must be evaluated while the visible session is
     * still endpoint-only.  Using {@link #outputFps()} in that state returns
     * the Direct source cadence and makes a qualified 20-to-40 backend
     * impossible to activate.  This accessor exposes the timing authority's
     * measured uniform plan without enabling generation or changing any
     * presentation state.</p>
     */
    public int candidateGeneratedOutputFps() {
        if (!hasSustainableGenerationRate()) return 0;
        UniformFrameRatePlan plan = currentUniformOutputPlan();
        return plan.qualified() ?
                Math.max(1, (int) Math.round(plan.outputHz())) : 0;
    }

    /**
     * Source identity paired with the independently inspected generated plan.
     *
     * <p>An endpoint-only fallback deliberately preserves the last acquired
     * tier when a renderer fails, so renderer starvation can never rewrite a
     * proven emulator clock.  That preserved tier is not, however, allowed to
     * veto a later complete unique-timestamp proof.  Ocarina physically starts
     * with a 60-Hz menu and then proves an exact 20-Hz gameplay clock; using
     * the preserved 60 label to authorize the otherwise valid 20-to-40 plan
     * makes that path impossible forever.  This accessor returns only the
     * same durable timestamp authority that funds the candidate output.</p>
     */
    public int candidateGeneratedSourceFps() {
        if (!hasSustainableGenerationRate()) return 0;
        double source = presentationSourceHz();
        return Math.max(1, tierFor(source));
    }

    /** Integer panel divisor paired with {@link #candidateGeneratedOutputFps()}. */
    public int candidateGeneratedPanelScansPerOutput() {
        if (!hasSustainableGenerationRate()) return 0;
        UniformFrameRatePlan plan = currentUniformOutputPlan();
        return plan.qualified() ? plan.panelScansPerOutput() : 0;
    }

    private UniformFrameRatePlan currentUniformOutputPlan() {
        // Keep the acquired integer tier as the conservative admission floor,
        // but plan against the complete-window timestamp clock itself.  The
        // physical Thor path measures approximately 60.098 source on a
        // 120.052-Hz mode; throwing away those fractions makes every-scan
        // output look (incorrectly) greater than 2x.  Conversely a proven
        // 59.94 source on an exact 120.000-Hz clock must select the two-scan
        // 60-Hz divisor rather than being rounded up to a fictitious60/120.
        double source = presentationSourceHz();
        if (authoritativeSourceHz <= 0.0 &&
                qualifiedUniqueTimestampSourceHz <= 0.0) {
            // A complete stable arbitrary clock may plan from its measured
            // value.  Until that evidence exists, stay just below a nearby
            // exact 2x tier boundary.  This is a conservative one-time
            // qualification state, not a rounded source identity: the public
            // S clock remains the measured timestamp rate.
            double boundary = tierAcquired ? lockedSourceFps() :
                    provisionalSourceFps(source);
            int settledPeriods =
                    decisionPeriodsForElapsed(TIER_DECISION_WINDOW_NS);
            double lowerBound = conservativeTimestampLowerBoundHz();
            if (settledPeriods <= 0 ||
                    (Math.abs(source - boundary) <=
                            BOUNDARY_NEIGHBORHOOD_HZ &&
                            lowerBound + 1.0e-5 < boundary)) {
                source = Math.min(source,
                        boundary - UNPROVEN_BOUNDARY_GUARD_HZ);
            }
        }
        return UniformFrameRatePlan.select(source, displayRefreshHz, maxGenerationFactor);
    }


    public int panelFps() { return Math.max(1, (int) Math.round(displayRefreshHz)); }
    public double panelHz() { return displayRefreshHz; }
    public long panelPeriodNs() { return displayPeriodNs; }
    public double declaredPanelHz() { return declaredDisplayRefreshHz; }
    public boolean panelClockMeasured() {
        return measuredDisplayRefreshHz > 0.0;
    }

    /** Physical scan clock from whole callback intervals, or 0 until 20 s. */
    public double longBaselinePanelHz() {
        long span = panelBaselineLastNs - panelBaselineStartNs;
        if (panelBaselineStartNs <= 0L || panelBaselinePeriods <= 0L ||
                span < PANEL_BASELINE_MIN_SPAN_NS) return 0.0;
        return panelBaselinePeriods * 1_000_000_000.0 / span;
    }

    /**
     * Physical-to-declared panel clock ratio (1.0 until measured), bounded
     * to the mode tolerance. This diagnostic does not change gameplay speed;
     * a core adapter must separately implement and prove bounded clock trim.
     */
    public double panelClockRatio() {
        double measured = longBaselinePanelHz();
        if (measured <= 0.0 || declaredDisplayRefreshHz <= 0.0) return 1.0;
        double ratio = measured / declaredDisplayRefreshHz;
        return Math.abs(ratio - 1.0) <= 0.005 ? ratio : 1.0;
    }
    public int panelClockSamplesForDiagnostics() { return panelPeriodCount; }

    /** Enables x2 scheduling only while a qualified renderer can synthesize. */
    public void setGenerationAvailable(boolean value) {
        if (generationAvailable == value) return;
        if (!value) {
            // A renderer failure must not rewrite the emulator's source rate.
            // Physical ALBW delivered a stable ~60-Hz unique producer clock,
            // but the starved presentation/FIFO clock measured ~50; using the
            // latter here made the fail-safe itself force 50 and left the top
            // panel at 43-46 actual Hz. Preserve the producer-owned acquired
            // tier. During bootstrap, use only the unique producer clock.
            directFallbackSourceFps = tierAcquired ?
                    Math.max(1, lockedSourceFps) :
                    (producerSamples > 0 ?
                            provisionalSourceFps(measuredProducerHz()) : 0);
        } else {
            // Backend admission is evaluated from a complete immutable
            // unique-timestamp clock.  Atomically join the public locked tier
            // to that same proof before exposing the generated schedule. This
            // is not a renderer-driven downgrade: no presentation, readiness,
            // or submission counter participates in the decision.
            if (authoritativeSourceHz <= 0.0 &&
                    qualifiedUniqueTimestampSourceHz > 0.0) {
                lockedSourceFps = tierFor(qualifiedUniqueTimestampSourceHz);
                tierAcquired = true;
            }
            directFallbackSourceFps = 0;
        }
        generationAvailable = value;
        resetPresentation();
    }

    public void setExactDoubleEndpointLatticeRequired(boolean value) {
        if (exactDoubleEndpointLatticeRequired == value) return;
        exactDoubleEndpointLatticeRequired = value;
        resetPresentation();
    }

    public boolean generationAvailable() { return generationAvailable; }

    public boolean tierAcquiredForDiagnostics() { return tierAcquired; }
    public int producerSamplesForDiagnostics() { return producerSamples; }
    public int decisionPeriodsForDiagnostics() { return decisionPeriodCount; }

    /**
     * Source clock used by the renderer's endpoint sampler. During bootstrap
     * this follows the honest measured direct rate; after acquisition it is
     * one of the supported 20/30/40/50/60 tiers. Pixel-change observations
     * decide this rate, but repeated emulator callbacks may still be retained
     * as temporal endpoints at this rate so a static image cannot tear down
     * an otherwise healthy presentation lattice.
     */
    public int presentationSourceFps() {
        return Math.max(1, (int) Math.round(presentationSourceHz()));
    }

    /** Exact source clock used by endpoint selection and temporal phase. */
    public double presentationSourceHz() {
        if (authoritativeSourceHz > 0.0) return authoritativeSourceHz;
        if (qualifiedUniqueTimestampSourceHz > 0.0)
            return qualifiedUniqueTimestampSourceHz;
        double measured = sustainedMeasuredSourceHz();
        if (!tierAcquired && Double.isFinite(measured) && measured > 0.0)
            return provisionalSourceFps(measured);
        if (Double.isFinite(measured) && measured > 0.0)
            return measured;
        return Math.max(1.0, lockedSourceFps());
    }

    /**
     * Returns a canonical clock only when the immutable timestamp periods
     * themselves establish it.  A close aggregate average is insufficient:
     * a 29.7/30.3 alternation averages near30 but is not a stable30 clock and
     * must continue to use its measured rate in the strict divisor plan.
     */
    private static double nearestCanonicalTimestampSourceHz(double measuredHz) {
        double closest = 0.0;
        double closestError = Double.POSITIVE_INFINITY;
        double secondError = Double.POSITIVE_INFINITY;
        for (double candidate : CANONICAL_TIMESTAMP_SOURCE_HZ) {
            double error = Math.abs(measuredHz - candidate);
            if (error < closestError) {
                secondError = closestError;
                closest = candidate;
                closestError = error;
            } else if (error < secondError) {
                secondError = error;
            }
        }
        return closestError <= CANONICAL_MEAN_TOLERANCE_HZ &&
                secondError - closestError >= CANONICAL_NEAREST_MARGIN_HZ ?
                closest : 0.0;
    }

    private boolean producerTimestampPeriodsMatch(double rateHz) {
        if (producerPeriodCount < RATE_WINDOW_PERIODS) return false;
        return timestampPeriodsMatch(rateHz, producerPeriodsNs,
                producerPeriodCount, 0, false);
    }

    private boolean decisionTimestampPeriodsMatch(double rateHz, int count) {
        return count > 0 && timestampPeriodsMatch(rateHz, decisionPeriodsNs,
                count, decisionPeriodIndex, true);
    }

    /**
     * Returns a clock only when the classified UNIQUE-image timestamps in the
     * requested window describe one stable cadence. Exact canonical clocks
     * retain their rational value; every other stable source keeps its
     * measured value instead of being forced onto a 10-Hz tier.
     *
     * <p>Submission ordinals deliberately do not participate here. They can
     * prove that callbacks were duplicates, but duplicate callbacks are not
     * unique source endpoints and cannot fund generated presentations.</p>
     */
    private double provenDecisionUniqueTimestampSourceHz(int count) {
        int sampleCount = Math.min(count, decisionPeriodCount);
        if (sampleCount <= 0) return 0.0;
        double measured = decisionRateHz(sampleCount);
        if (!Double.isFinite(measured) ||
                measured < MIN_GENERATION_SOURCE_HZ) return 0.0;
        if (physicalDisplayClockQualified)
            return decisionTimestampPeriodsMatch(measured, sampleCount) ? measured : 0.0;
        double canonical = nearestCanonicalTimestampSourceHz(measured);
        if (canonical > 0.0 &&
                decisionTimestampPeriodsMatch(canonical, sampleCount))
            return canonical;
        return decisionTimestampPeriodsMatch(measured, sampleCount) ?
                measured : 0.0;
    }

    /**
     * Proves a canonical image clock across a durable window while preserving
     * explicitly observed duplicate callbacks.  A repeated image can make two
     * adjacent unique endpoints span two source periods; treating that 2x span
     * as clock jitter made a physical nominal-30 N64 run alternate 40/60 every
     * time one repeat entered or left the ten-second window.
     *
     * <p>The exception is deliberately narrow. At least 99% of intervals must
     * be ordinary one-period spans. A two-period span is accepted only when
     * the immutable callback ordinal advances by exactly twice the window's
     * modal ordinary gap. Unexplained loss, a three-period pause, or an
     * unstable 29.7/30.3 mixture still fails the original RMS/max tests.</p>
     */
    private boolean decisionTimestampPeriodsMatchWithProvenDuplicates(
            double rateHz, int count) {
        // (2026-09-01) Acquisition admits up to ten percent ordinal-proven
        // held frames: Metroid Prime on Dolphin natively holds ~4 percent of
        // its frames at any pace (run gc-b22) and still owns an exact 60-Hz
        // submission lattice; every held span must still be exactly two
        // periods with a doubled submission ordinal.
        return decisionTimestampPeriodsMatchWithProvenDuplicates(
                rateHz, count, acquisitionOrdinaryPercent(),
                CANONICAL_MEAN_TOLERANCE_HZ);
    }

    /**
     * Retains an already independently proven clock through the slightly
     * denser held-frame pattern observed in physical Ocarina gameplay.
     * Acquisition remains on the stricter 99-percent rule above.  This path
     * never authorizes interpolation across a doubled endpoint span: the
     * renderer's independent endpointSpanContinuous() check still rejects and
     * re-primes that pair. Exact half-period phase corrections are handled by
     * the separate predicate below. This path only prevents ordinal-proven
     * held-image spans from erasing the established source identity.
     */
    private boolean decisionTimestampPeriodsRetainProvenClock(
            double rateHz, int count) {
        // (2026-09-01, gc-b28) Retention admits 80 percent ordinary periods:
        // Metroid Prime's held frames cluster (10.6 percent in one 27-s
        // window) and revoking at the acquisition bound re-entered the
        // 30-second re-acquisition every time the clock qualified.
        return decisionTimestampPeriodsMatchWithProvenDuplicates(
                rateHz, count, retentionOrdinaryPercent(),
                CANONICAL_RETENTION_MEAN_TOLERANCE_HZ) ||
                decisionTimestampPeriodsRetainAcrossSparseMissingEndpoints(
                        rateHz, count) ||
                decisionTimestampPeriodsRetainAcrossSparsePhaseCorrection(
                        rateHz, count);
    }

    /**
     * Retains an already-proven clock through a sparse set of missing or
     * explicitly held source endpoints in a complete ten-second window.
     *
     * <p>Physical F-Zero r241 contained 598 exact 60-Hz periods and one exact
     * doubled period whose submission ordinal advanced normally. F-Zero r243
     * then proved that one complete window can contain both that unexplained
     * form and ordinal-proven doubled spans. Revoking the independently
     * proven 60-Hz clock merely because the two already-safe anomaly classes
     * coexist disabled an otherwise deadline-clean 60-to-120 path for the
     * entire session. This
     * exception cannot acquire a clock and cannot authorize interpolation
     * across the bad pair: {@link #endpointSpanContinuous} still rejects it,
     * and the renderer re-primes without catch-up. At least 99 percent of the
     * durable window must remain strict ordinary periods; crossing that bound
     * revokes the clock within a fraction of a second after a real tier
     * change. All ordinary periods independently retain their strict
     * mean/RMS/max proof.</p>
     */
    private boolean decisionTimestampPeriodsRetainAcrossSparseMissingEndpoints(
            double rateHz, int count) {
        int sampleCount = Math.min(count, decisionPeriodCount);
        if (!Double.isFinite(rateHz) || rateHz <= 0.0 || sampleCount < 100)
            return false;
        double canonicalPeriodNs = 1_000_000_000.0 / rateHz;
        int anomalyCount = 0;
        int maximumMissing = Math.max(1, sampleCount / 100);
        int ordinaryCount = 0;
        long ordinaryElapsedNs = 0L;
        double squaredFractionSum = 0.0;
        double maximumFraction = 0.0;
        int ordinaryGap = 0;
        int index = decisionPeriodIndex;
        for (int offset = 0; offset < sampleCount; ++offset) {
            index = (index + decisionPeriodsNs.length - 1) %
                    decisionPeriodsNs.length;
            long periodNs = decisionPeriodsNs[index];
            double ratio = periodNs / canonicalPeriodNs;
            double fraction = Math.abs(ratio - 1.0);
            int gap = decisionSubmissionGaps[index];
            if (fraction <= CANONICAL_PERIOD_MAX_FRACTION) {
                ++ordinaryCount;
                ordinaryElapsedNs += periodNs;
                squaredFractionSum += fraction * fraction;
                maximumFraction = Math.max(maximumFraction, fraction);
                if (ordinaryGap == 0) ordinaryGap = gap;
                else if (gap != ordinaryGap) return false;
                continue;
            }
            if (++anomalyCount > maximumMissing ||
                    Math.abs(ratio - 2.0) > 0.03)
                return false;
        }
        if (anomalyCount < 1 ||
                ordinaryCount != sampleCount - anomalyCount ||
                ordinaryCount <= 0 || ordinaryElapsedNs <= 0L ||
                ordinaryGap <= 0)
            return false;

        // Validate each doubled span independently. A gap equal to the modal
        // ordinary ordinal is an unexplained missing unique endpoint; a gap
        // twice the modal ordinary ordinal is an explicitly observed held or
        // duplicate source slot. Both forms already fail the renderer's
        // endpointSpanContinuous() check. A mixed window is therefore no less
        // safe than either form alone, provided their combined density stays
        // under the same strict one-percent ceiling.
        index = decisionPeriodIndex;
        for (int offset = 0; offset < sampleCount; ++offset) {
            index = (index + decisionPeriodsNs.length - 1) %
                    decisionPeriodsNs.length;
            long periodNs = decisionPeriodsNs[index];
            double ratio = periodNs / canonicalPeriodNs;
            if (Math.abs(ratio - 1.0) <=
                    CANONICAL_PERIOD_MAX_FRACTION)
                continue;
            int gap = decisionSubmissionGaps[index];
            if (gap != ordinaryGap &&
                    (long) gap != (long) ordinaryGap * 2L)
                return false;
        }
        double ordinaryRateHz = ordinaryCount * 1_000_000_000.0 /
                ordinaryElapsedNs;
        double rmsFraction = Math.sqrt(
                squaredFractionSum / ordinaryCount);
        return Math.abs(ordinaryRateHz - rateHz) <=
                        CANONICAL_RETENTION_MEAN_TOLERANCE_HZ &&
                rmsFraction <= CANONICAL_PERIOD_RMS_FRACTION &&
                maximumFraction <= CANONICAL_PERIOD_MAX_FRACTION;
    }

    /**
     * Retains an independently proven clock across a bounded set of timestamp
     * phase corrections in a complete decision window. TWINE r200 exposed the
     * rolling window with 299 ordinary 30-Hz periods and one 50-ms (1.5x)
     * edge. r202 captured one complete adjacent 16.67-ms/50-ms (0.5x/1.5x)
     * pair. r228 captured 297 ordinary intervals plus one complete pair and
     * one rolling-window boundary residue. r229 then captured two complete
     * 16.67/50-ms correction pairs among 296 ordinary periods. The native
     * transport timestamps the core's 60-Hz frame ordinal: these exact
     * half-period/one-and-a-half-period edges are therefore bounded phase
     * corrections around the independently proven 30-Hz image clock, not
     * observations of a new source rate. The renderer retains their exact
     * timestamps and resamples causally between adjacent accepted images.
     *
     * <p>This exception cannot acquire a clock and cannot normalize an exact
     * missing endpoint: exactly one span must lie strictly between 1.25x and
     * 1.75x, retain the ordinary submission gap, and all remaining periods
     * must independently satisfy the original strict RMS/max/mean proof. A
     * lone short or long span may remain anywhere in the rolling window: it
     * is still only one out of at least 100 periods, and forcing it to revoke
     * the clock as soon as it moved one slot away from the edge made r204
     * tear down one source callback after a valid activation. A complete
     * multi-span correction must contain both short and long edges, have at
     * most one unmatched rolling-window boundary edge, preserve the ordinary
     * submission ordinal, remain within one half-period of accumulated phase,
     * and leave the exact canonical period as the strict majority. The
     * corrections need not be adjacent: physical TWINE r212
     * retained one earlier short phase step and later emitted its balancing
     * long step after 298 ordinary intervals. This is structural rather than
     * a density threshold: r229 and r230 observed four and seven edges in
     * otherwise equivalent ten-second windows. A 2x span, a non-half-period
     * edge, repeated one-sided stalls, corrections that displace the canonical
     * period as the mode, a cumulative excursion beyond one half-period, a new
     * stable clock, or a genuine 29.90-Hz source still revokes the identity.</p>
     */
    private boolean decisionTimestampPeriodsRetainAcrossSparsePhaseCorrection(
            double rateHz, int count) {
        int sampleCount = Math.min(count, decisionPeriodCount);
        if (!Double.isFinite(rateHz) || rateHz <= 0.0 || sampleCount < 100)
            return false;

        double canonicalPeriodNs = 1_000_000_000.0 / rateHz;
        int[] ordinaryGapHistogram = new int[65];
        int ordinary = 0;
        int discontinuities = 0;
        int shortDiscontinuities = 0;
        int longDiscontinuities = 0;
        int discontinuityGap = 0;
        double shortRatioSum = 0.0;
        double longRatioSum = 0.0;
        long ordinaryElapsedNs = 0L;
        double squaredFractionSum = 0.0;
        double maximumFraction = 0.0;
        // A proven canonical period must remain the strict mode. Do not use a
        // percentage cap here: the native timestamp is derived from the core
        // frame ordinal, and r229/r230 showed that the same bounded +/- one-
        // tick correction pattern can cross an arbitrary 1% or 2% cutoff.
        // Exact alternating corrections remain zero-drift source phase; once
        // they equal or outnumber ordinary periods, the old clock is no longer
        // the independently dominant identity and must be reacquired.
        int maximumDiscontinuities = Math.max(1,
                (sampleCount - 1) / 2);
        double correctionBalance = 0.0;
        double maximumCorrectionExcursion = 0.0;
        int index = decisionPeriodIndex;
        for (int offset = 0; offset < sampleCount; ++offset) {
            index = (index + decisionPeriodsNs.length - 1) %
                    decisionPeriodsNs.length;
            long periodNs = decisionPeriodsNs[index];
            double ratio = periodNs / canonicalPeriodNs;
            double fraction = Math.abs(ratio - 1.0);
            int gap = decisionSubmissionGaps[index];
            if (fraction <= CANONICAL_PERIOD_MAX_FRACTION) {
                ++ordinary;
                ordinaryElapsedNs += periodNs;
                squaredFractionSum += fraction * fraction;
                maximumFraction = Math.max(maximumFraction, fraction);
                if (gap > 0 && gap < ordinaryGapHistogram.length)
                    ++ordinaryGapHistogram[gap];
            } else {
                ++discontinuities;
                if (discontinuities > maximumDiscontinuities) return false;
                if (discontinuityGap == 0) discontinuityGap = gap;
                else if (gap != discontinuityGap) return false;
                if (Math.abs(ratio - 0.5) <= 0.03) {
                    ++shortDiscontinuities;
                    shortRatioSum += ratio;
                    correctionBalance += ratio - 1.0;
                } else if (Math.abs(ratio - 1.5) <= 0.03) {
                    ++longDiscontinuities;
                    longRatioSum += ratio;
                    correctionBalance += ratio - 1.0;
                } else return false;
                maximumCorrectionExcursion = Math.max(
                        maximumCorrectionExcursion,
                        Math.abs(correctionBalance));
                if (maximumCorrectionExcursion > 0.55) return false;
            }
        }
        if (discontinuities < 1 ||
                ordinary != sampleCount - discontinuities ||
                ordinaryElapsedNs <= 0L || ordinary <= discontinuities ||
                Math.abs(correctionBalance) > 0.55) return false;

        int modalGap = 0;
        int modalCount = 0;
        for (int gap = 1; gap < ordinaryGapHistogram.length; ++gap) {
            if (ordinaryGapHistogram[gap] > modalCount) {
                modalGap = gap;
                modalCount = ordinaryGapHistogram[gap];
            }
        }
        if (modalGap <= 0 || discontinuityGap != modalGap ||
                modalCount * 100 < ordinary * 99) return false;
        if (discontinuities == 1) {
            // One sparse timestamp-phase correction does not become stronger
            // evidence of a different source clock merely because ordinary
            // samples advance the rolling-window edge past it. It remains one
            // bounded core-ordinal phase edge; a second unbalanced anomaly
            // below still revokes the identity.
            if (shortDiscontinuities + longDiscontinuities != 1)
                return false;
        } else {
            // A rolling window may contain complete half-period phase
            // corrections plus one unmatched edge whose balancing half has
            // just left or not yet entered the window. r228 produced the
            // exact 1.5x/0.5x/1.5x shape; r229 produced two complete pairs.
            // Require both signs, no more than one unmatched edge, and a
            // balanced average correction. The running excursion check above
            // additionally forbids two same-direction steps from accumulating
            // into a hidden missing endpoint.
            if (shortDiscontinuities == 0 || longDiscontinuities == 0 ||
                    Math.abs(shortDiscontinuities -
                            longDiscontinuities) > 1)
                return false;
            double averageShort = shortRatioSum / shortDiscontinuities;
            double averageLong = longRatioSum / longDiscontinuities;
            if (Math.abs(averageShort + averageLong - 2.0) > 0.03)
                return false;
        }

        double ordinaryRateHz = ordinary * 1_000_000_000.0 /
                ordinaryElapsedNs;
        double rmsFraction = Math.sqrt(squaredFractionSum / ordinary);
        return Math.abs(ordinaryRateHz - rateHz) <=
                        CANONICAL_RETENTION_MEAN_TOLERANCE_HZ &&
                rmsFraction <= CANONICAL_PERIOD_RMS_FRACTION &&
                maximumFraction <= CANONICAL_PERIOD_MAX_FRACTION;
    }

    private boolean decisionTimestampPeriodsMatchWithProvenDuplicates(
            double rateHz, int count, int minimumOrdinaryPercent,
            double meanToleranceHz) {
        int sampleCount = Math.min(count, decisionPeriodCount);
        if (!Double.isFinite(rateHz) || rateHz <= 0.0 || sampleCount <= 0)
            return false;

        double canonicalPeriodNs = 1_000_000_000.0 / rateHz;
        int[] ordinaryGapHistogram = new int[65];
        int ordinary = 0;
        int index = decisionPeriodIndex;
        for (int offset = 0; offset < sampleCount; ++offset) {
            index = (index + decisionPeriodsNs.length - 1) %
                    decisionPeriodsNs.length;
            long periodNs = decisionPeriodsNs[index];
            int multiple = (int) Math.round(periodNs / canonicalPeriodNs);
            if (multiple != 1) continue;
            double fraction = Math.abs(periodNs - canonicalPeriodNs) /
                    canonicalPeriodNs;
            if (fraction > CANONICAL_PERIOD_MAX_FRACTION) continue;
            ++ordinary;
            int gap = decisionSubmissionGaps[index];
            if (gap > 0 && gap < ordinaryGapHistogram.length)
                ++ordinaryGapHistogram[gap];
        }
        if (ordinary * 100 < sampleCount * minimumOrdinaryPercent)
            return false;

        int modalGap = 0;
        int modalCount = 0;
        for (int gap = 1; gap < ordinaryGapHistogram.length; ++gap) {
            if (ordinaryGapHistogram[gap] > modalCount) {
                modalGap = gap;
                modalCount = ordinaryGapHistogram[gap];
            }
        }
        boolean hasOrdinalEvidence = modalGap > 0;

        double squaredFractionSum = 0.0;
        double maximumFraction = 0.0;
        int logicalPeriods = 0;
        int provenPeriods = 0;
        int unexplainedAnomalies = 0;
        long elapsedNs = 0L;
        index = decisionPeriodIndex;
        for (int offset = 0; offset < sampleCount; ++offset) {
            index = (index + decisionPeriodsNs.length - 1) %
                    decisionPeriodsNs.length;
            long periodNs = decisionPeriodsNs[index];
            int multiple = (int) Math.round(periodNs / canonicalPeriodNs);
            // (2026-09-01) up to a triple span (two consecutive held frames)
            // is tolerated when its submission ordinal proves it.  A span
            // that is neither ordinary nor an ordinal-proven hold (a 1.5- or
            // 3.5-period residue, or a hold whose ordinal disagrees) is an
            // unexplained anomaly: up to one percent of the window is skipped
            // rather than failing the whole proof (Dolphin gc-b24: 8 of 1730,
            // all with ordinalBad, blocked the otherwise exact 60-Hz lattice).
            boolean anomaly = multiple < 1 || multiple > 3;
            if (!anomaly && multiple > 1) {
                anomaly = !hasOrdinalEvidence ||
                        decisionSubmissionGaps[index] != modalGap * multiple;
            } else if (!anomaly && hasOrdinalEvidence &&
                    decisionSubmissionGaps[index] != modalGap) {
                anomaly = true;
            }
            double normalizedPeriodNs = anomaly ? 0.0 :
                    (double) periodNs / multiple;
            double fraction = anomaly ? 0.0 : Math.abs(
                    normalizedPeriodNs - canonicalPeriodNs) /
                    canonicalPeriodNs;
            if (!anomaly && fraction > CANONICAL_PERIOD_MAX_FRACTION)
                anomaly = true;
            if (anomaly) {
                if (++unexplainedAnomalies * 100 > sampleCount) return false;
                continue;
            }
            squaredFractionSum += fraction * fraction;
            maximumFraction = Math.max(maximumFraction, fraction);
            logicalPeriods += multiple;
            elapsedNs += periodNs;
            ++provenPeriods;
        }
        if (elapsedNs <= 0L || logicalPeriods <= 0 || provenPeriods <= 0)
            return false;
        double logicalRateHz = logicalPeriods * 1_000_000_000.0 / elapsedNs;
        double rmsFraction = Math.sqrt(squaredFractionSum / provenPeriods);
        return Math.abs(logicalRateHz - rateHz) <= meanToleranceHz &&
                rmsFraction <= CANONICAL_PERIOD_RMS_FRACTION &&
                maximumFraction <= CANONICAL_PERIOD_MAX_FRACTION;
    }

    /**
     * Proves a low canonical source clock from the complete immutable
     * timestamp/ordinal grid. The ordinal is evidence about which producer
     * callback created each distinct image; it never substitutes submission
     * count for elapsed source time because the logical mean and every
     * normalized timestamp span must independently pass below.
     */
    private boolean decisionTimestampPeriodsMatchWithOrdinalGrid(
            double rateHz, int count) {
        int sampleCount = Math.min(count, decisionPeriodCount);
        if (!Double.isFinite(rateHz) || rateHz <= 0.0 || rateHz > 30.0 ||
                sampleCount <= 0) return false;

        int[] gapHistogram = new int[65];
        int index = decisionPeriodIndex;
        for (int offset = 0; offset < sampleCount; ++offset) {
            index = (index + decisionPeriodsNs.length - 1) %
                    decisionPeriodsNs.length;
            int gap = decisionSubmissionGaps[index];
            if (gap > 0 && gap < gapHistogram.length) ++gapHistogram[gap];
        }
        int modalGap = 0;
        int modalCount = 0;
        for (int gap = 2; gap < gapHistogram.length; ++gap) {
            if (gapHistogram[gap] > modalCount) {
                modalGap = gap;
                modalCount = gapHistogram[gap];
            }
        }
        if (modalGap < 2 || modalCount * 100 < sampleCount * 99) return false;

        double canonicalPeriodNs = 1_000_000_000.0 / rateHz;
        double squaredFractionSum = 0.0;
        double maximumFraction = 0.0;
        int logicalPeriods = 0;
        long elapsedNs = 0L;
        index = decisionPeriodIndex;
        for (int offset = 0; offset < sampleCount; ++offset) {
            index = (index + decisionPeriodsNs.length - 1) %
                    decisionPeriodsNs.length;
            int gap = decisionSubmissionGaps[index];
            if (gap <= 0 || gap % modalGap != 0) return false;
            int multiple = gap / modalGap;
            if (multiple < 1 || multiple > 2) return false;
            long periodNs = decisionPeriodsNs[index];
            double normalizedPeriodNs = (double) periodNs / multiple;
            double fraction = Math.abs(
                    normalizedPeriodNs - canonicalPeriodNs) /
                    canonicalPeriodNs;
            squaredFractionSum += fraction * fraction;
            maximumFraction = Math.max(maximumFraction, fraction);
            logicalPeriods += multiple;
            elapsedNs += periodNs;
        }
        if (elapsedNs <= 0L || logicalPeriods <= 0) return false;
        double logicalRateHz = logicalPeriods * 1_000_000_000.0 / elapsedNs;
        double rmsFraction = Math.sqrt(squaredFractionSum / sampleCount);
        return Math.abs(logicalRateHz - rateHz) <=
                        CANONICAL_MEAN_TOLERANCE_HZ &&
                rmsFraction <= ORDINAL_GRID_PERIOD_RMS_FRACTION &&
                maximumFraction <= ORDINAL_GRID_PERIOD_MAX_FRACTION;
    }

    private double provenDecisionCanonicalSourceHz(int count) {
        return provenDecisionCanonicalSourceHz(count,
                acquisitionOrdinaryPercent());
    }

    private double provenDecisionCanonicalSourceHz(int count,
                                                   int ordinaryPercent) {
        double closest = 0.0;
        double closestError = Double.POSITIVE_INFINITY;
        double secondError = Double.POSITIVE_INFINITY;
        int sampleCount = Math.min(count, decisionPeriodCount);
        if (sampleCount <= 0) return 0.0;
        long elapsedNs = 0L;
        int index = decisionPeriodIndex;
        for (int offset = 0; offset < sampleCount; ++offset) {
            index = (index + decisionPeriodsNs.length - 1) %
                    decisionPeriodsNs.length;
            elapsedNs += decisionPeriodsNs[index];
        }
        if (elapsedNs <= 0L) return 0.0;
        for (double candidate : CANONICAL_TIMESTAMP_SOURCE_HZ) {
            if (!decisionTimestampPeriodsMatchWithProvenDuplicates(
                    candidate, sampleCount, ordinaryPercent,
                    CANONICAL_MEAN_TOLERANCE_HZ) &&
                    !decisionTimestampPeriodsMatchWithOrdinalGrid(
                            candidate, sampleCount)) continue;
            double canonicalPeriodNs = 1_000_000_000.0 / candidate;
            int logicalPeriods = 0;
            index = decisionPeriodIndex;
            for (int offset = 0; offset < sampleCount; ++offset) {
                index = (index + decisionPeriodsNs.length - 1) %
                        decisionPeriodsNs.length;
                logicalPeriods += Math.max(1, (int) Math.round(
                        decisionPeriodsNs[index] / canonicalPeriodNs));
            }
            double logicalRate = logicalPeriods * 1_000_000_000.0 /
                    elapsedNs;
            double error = Math.abs(logicalRate - candidate);
            if (error < closestError) {
                secondError = closestError;
                closestError = error;
                closest = candidate;
            } else if (error < secondError) {
                secondError = error;
            }
        }
        return closestError <= CANONICAL_MEAN_TOLERANCE_HZ &&
                secondError - closestError >= CANONICAL_NEAREST_MARGIN_HZ ?
                closest : 0.0;
    }

    private static boolean timestampPeriodsMatch(
            double rateHz, long[] periods, int count, int nextIndex,
            boolean newestFirst) {
        if (!Double.isFinite(rateHz) || rateHz <= 0.0 || count <= 0)
            return false;

        double canonicalPeriodNs = 1_000_000_000.0 / rateHz;
        double squaredFractionSum = 0.0;
        double maximumFraction = 0.0;
        int index = nextIndex;
        for (int offset = 0; offset < count; ++offset) {
            if (newestFirst) {
                index = (index + periods.length - 1) % periods.length;
            } else {
                index = offset;
            }
            double fraction = Math.abs(
                    periods[index] - canonicalPeriodNs) /
                    canonicalPeriodNs;
            squaredFractionSum += fraction * fraction;
            maximumFraction = Math.max(maximumFraction, fraction);
        }
        double rmsFraction = Math.sqrt(
                squaredFractionSum / count);
        return rmsFraction <= CANONICAL_PERIOD_RMS_FRACTION &&
                maximumFraction <= CANONICAL_PERIOD_MAX_FRACTION;
    }

    private boolean replacementUniqueClockStable(double measuredHz) {
        if (!physicalDisplayClockQualified || !qualifiedUniqueTimestampClockRejected)
            return true;
        if (replacementUniqueClockSinceNs == 0L ||
                previousProducerNs < replacementUniqueClockSinceNs ||
                Math.abs(measuredHz - replacementUniqueClockHz) > 1e-5) {
            replacementUniqueClockHz = measuredHz;
            replacementUniqueClockSinceNs = previousProducerNs;
            return false;
        }
        // Full-window period/ordinal proof remains necessary. Relatching a
        // moving average immediately would reject it again a frame later.
        return previousProducerNs - replacementUniqueClockSinceNs >= 1_000_000_000L;
    }

    /** Retains prior proof only across an explicitly requested, observed trim.
     * New intervals match the old or new integer clock within 1 ns, except
     * one ordinal-proven held image which earns no evidence. No samples are
     * rewritten; other stalls/irregular intervals end this bridge. */
    private boolean retainObservedClockTrim() {
        if (trimNewPeriodNs == 0L) return false;
        if (!physicalDisplayClockQualified || qualifiedUniqueTimestampSourceHz <= 0.0 ||
                decisionPeriodCount == 0 || previousProducerNs < trimStartedProducerNs ||
                previousProducerNs - trimStartedProducerNs > 15_000_000_000L) {
            trimNewPeriodNs = 0L;
            return false;
        }
        int newest = (decisionPeriodIndex + decisionPeriodsNs.length - 1) %
                decisionPeriodsNs.length;
        long observed = decisionPeriodsNs[newest];
        // A single held image does not change the oscillator. Require an
        // independently counted two-submission gap on the already-observed
        // new clock; it earns no new clock evidence. The presentation path
        // still rejects interpolation across a non-continuous endpoint pair.
        if (!trimSparseGapUsed && trimNewEvidenceNs > 0L &&
                decisionSubmissionGaps[newest] == 2 &&
                Math.abs(observed - 2L * trimNewPeriodNs) <= 2L) {
            trimSparseGapUsed = true;
            return true;
        }
        if (Math.abs(observed - trimNewPeriodNs) <= 1L) {
            trimNewEvidenceNs += observed;
            if (trimNewEvidenceNs >= 250_000_000L) {
                qualifiedUniqueTimestampSourceHz = 1e9 / trimNewPeriodNs;
                provenTimestampSourceHz = qualifiedUniqueTimestampSourceHz;
                measuredDisplayRefreshHz = trimPanelHz;
                displayRefreshHz = trimPanelHz;
                displayPeriodNs = Math.max(1L, Math.round(1e9 / trimPanelHz));
            }
            if (trimNewEvidenceNs >= TIER_DECISION_WINDOW_NS + trimNewPeriodNs)
                trimNewPeriodNs = 0L;
            return true;
        }
        if (trimNewEvidenceNs == 0L &&
                previousProducerNs - trimStartedProducerNs < 1_000_000_000L &&
                Math.abs(observed - trimOldPeriodNs) <= 1L)
            return true;
        trimNewPeriodNs = 0L;
        return false;
    }

    private void updateProvenTimestampSourceClock() {
        if (authoritativeSourceHz > 0.0) return;

        if (retainObservedClockTrim()) return;

        // A complete ten-second unique-image window is the general source
        // authority. It supports arbitrary stable clocks while refusing an
        // attractive mean assembled from irregular 50/100/150-ms gaps.
        int uniquePeriods =
                decisionPeriodsForElapsed(TIER_DECISION_WINDOW_NS);
        if (uniquePeriods > 0) {
            double uniqueClock =
                    provenDecisionUniqueTimestampSourceHz(uniquePeriods);
            if (!(uniqueClock > 0.0)) {
                replacementUniqueClockHz = 0.0;
                replacementUniqueClockSinceNs = 0L;
            }
            if (qualifiedUniqueTimestampSourceHz > 0.0) {
                // Once the panel clock is authoritative, a nearby old source
                // clock is not interchangeable with its corrected divisor.
                // Allow timestamp quantization, not the canonical-rate band.
                double tolerance = physicalDisplayClockQualified ? 1e-5 :
                        Math.max(CANONICAL_MEAN_TOLERANCE_HZ,
                                qualifiedUniqueTimestampSourceHz * .001);
                // A previously proven source clock survives a sparse,
                // ordinal-proven missing endpoint.  The renderer separately
                // rejects that doubled timestamp span in
                // endpointSpanContinuous(), resets/re-primes the pair and
                // emits no catch-up output.  Revoking the clock itself made
                // three such spans in a thirty-second Ocarina trace tear down
                // 20->40 for the full re-acquisition hold even though the
                // remaining 594 intervals were exact 50-ms source periods.
                // Acquisition is deliberately unchanged: an irregular stream
                // cannot establish this authority in the first place.
                boolean exactUniqueClock = uniqueClock > 0.0 &&
                        Math.abs(uniqueClock -
                                qualifiedUniqueTimestampSourceHz) <= tolerance;
                boolean provenSparseGapClock =
                        (!physicalDisplayClockQualified || uniqueClock <= 0.0 ||
                                exactUniqueClock) &&
                        decisionTimestampPeriodsRetainProvenClock(
                                qualifiedUniqueTimestampSourceHz,
                                uniquePeriods);
                if (exactUniqueClock || provenSparseGapClock) {
                    // Keep the latched clock immutable while the complete
                    // window remains within its strict stability envelope or
                    // its narrow, ordinal-proven sparse-gap envelope.
                    provenTimestampSourceHz =
                            qualifiedUniqueTimestampSourceHz;
                    canonicalReacquireEvidenceNs = 0L;
                    canonicalReacquireCandidateHz = 0.0;
                    return;
                }
                lastRejectedQualifiedTimestampSourceHz =
                        qualifiedUniqueTimestampSourceHz;
                lastRejectedQualifiedTimestampProof =
                        timestampClockRejectionSummary(
                                qualifiedUniqueTimestampSourceHz,
                                uniquePeriods);
                qualifiedUniqueTimestampSourceHz = 0.0;
                qualifiedUniqueTimestampClockRejected = true;
                replacementUniqueClockHz = 0.0;
                replacementUniqueClockSinceNs = 0L;
                provenTimestampSourceHz = 0.0;
                canonicalReacquireEvidenceNs = 0L;
                canonicalReacquireCandidateHz = 0.0;
            } else if (uniqueClock > 0.0 &&
                    (!qualifiedUniqueTimestampClockRejected ||
                            decisionPeriodsForElapsed(
                                    CANONICAL_REACQUIRE_WINDOW_NS) > 0) &&
                    replacementUniqueClockStable(uniqueClock)) {
                qualifiedUniqueTimestampSourceHz = uniqueClock;
                lastRejectedQualifiedTimestampSourceHz = 0.0;
                lastRejectedQualifiedTimestampProof = "none";
                qualifiedUniqueTimestampClockRejected = false;
                provenTimestampSourceHz = uniqueClock;
                canonicalReacquireEvidenceNs = 0L;
                canonicalReacquireCandidateHz = 0.0;
                resetPresentation();
                return;
            }
        }

        if (provenTimestampSourceHz <= 0.0 && decisionPeriodCount > 0) {
            int newest = (decisionPeriodIndex + decisionPeriodsNs.length - 1) %
                    decisionPeriodsNs.length;
            long newestPeriodNs = Math.max(0L, decisionPeriodsNs[newest]);
            double candidate = strictCanonicalForPeriod(newestPeriodNs,
                    canonicalReacquireCandidateHz);
            // (2026-09-01) An exact doubled period against the running
            // candidate is one held frame, not a new clock: keep the
            // evidence.  Metroid Prime on Dolphin holds a frame every ~25
            // and the reset here kept canonicalEvidenceMs at 0 forever
            // (gc-b25) while the complete window was 96 percent ordinary.
            // A doubled period of the running candidate is one held frame
            // whatever canonical clock it happens to resemble on its own
            // (a 33.3-ms hold of a 60-Hz candidate reads as "30 Hz" and
            // was counted as a candidate mismatch, run gc-b27).
            boolean heldFrameOfCandidate =
                    canonicalReacquireCandidateHz > 0.0 &&
                    Math.abs(newestPeriodNs * canonicalReacquireCandidateHz /
                            1_000_000_000.0 - 2.0) <= 0.03;
            boolean anomalyOfCandidate = !heldFrameOfCandidate &&
                    canonicalReacquireCandidateHz > 0.0 &&
                    (candidate <= 0.0 ||
                     Math.abs(candidate - canonicalReacquireCandidateHz) >
                            CANONICAL_MEAN_TOLERANCE_HZ);
            if (heldFrameOfCandidate) {
                ++canonicalReacquirePeriods;
                canonicalReacquireEvidenceNs = saturatingAdd(
                        canonicalReacquireEvidenceNs, newestPeriodNs);
            } else if (anomalyOfCandidate &&
                    (canonicalReacquireAnomalies + 1) * 100 <=
                            canonicalReacquirePeriods + 1) {
                // One unexplained span per hundred (the same budget the
                // complete-window proof applies) keeps the evidence; the
                // proof below still judges the whole window.
                ++canonicalReacquireAnomalies;
                ++canonicalReacquirePeriods;
                canonicalReacquireEvidenceNs = saturatingAdd(
                        canonicalReacquireEvidenceNs, newestPeriodNs);
            } else if (candidate <= 0.0 || anomalyOfCandidate) {
                canonicalReacquireEvidenceNs = 0L;
                canonicalReacquireCandidateHz = 0.0;
                canonicalReacquireAnomalies = 0;
                canonicalReacquirePeriods = 0;
            } else {
                if (canonicalReacquireCandidateHz <= 0.0) {
                    canonicalReacquireAnomalies = 0;
                    canonicalReacquirePeriods = 0;
                }
                canonicalReacquireCandidateHz = candidate;
                ++canonicalReacquirePeriods;
                canonicalReacquireEvidenceNs = saturatingAdd(
                        canonicalReacquireEvidenceNs, newestPeriodNs);
            }
        }

        double shortRate = measuredProducerHz();
        double shortCanonical = nearestCanonicalTimestampSourceHz(shortRate);
        if (shortCanonical > 0.0 &&
                producerTimestampPeriodsMatch(shortCanonical) &&
                provenTimestampSourceHz > 0.0 &&
                Math.abs(provenTimestampSourceHz - shortCanonical) <=
                        CANONICAL_MEAN_TOLERANCE_HZ) {
            // The short ring may confirm an already-settled identity, but it
            // must never acquire or re-acquire one.  Physical N64 proof
            // toggled 40/60 on adjacent callbacks when a ten-period cluster
            // briefly resembled30 immediately after the durable timestamp
            // window had rejected that identity. Only the complete settled
            // window below may establish a canonical clock.
            return;
        }

        if (provenTimestampSourceHz > 0.0) {
            int retentionPeriods =
                    decisionPeriodsForElapsed(TIER_DECISION_WINDOW_NS);
            if (retentionPeriods <= 0) return;
            double retainedCanonical =
                    provenDecisionCanonicalSourceHz(retentionPeriods,
                            retentionOrdinaryPercent());
            if (retainedCanonical > 0.0 &&
                    Math.abs(retainedCanonical - provenTimestampSourceHz) <=
                            CANONICAL_MEAN_TOLERANCE_HZ) {
                if (qualifiedUniqueTimestampSourceHz <= 0.0 &&
                        authoritativeSourceHz <= 0.0 &&
                        decisionPeriodCount > 0) {
                    // (2026-09-01) A canonical identity proven by the
                    // 90-period bootstrap but never funded (the strict
                    // unique proof refuses any held frame) used to sit here
                    // forever: retention succeeded every callback and
                    // returned before the re-acquisition window below could
                    // run.  Retained evidence funds generation after the
                    // same complete thirty-second duplicates proof.
                    int newest = (decisionPeriodIndex +
                            decisionPeriodsNs.length - 1) %
                            decisionPeriodsNs.length;
                    canonicalReacquireEvidenceNs = saturatingAdd(
                            canonicalReacquireEvidenceNs,
                            Math.max(0L, decisionPeriodsNs[newest]));
                    if (canonicalReacquireEvidenceNs >=
                            CANONICAL_REACQUIRE_WINDOW_NS) {
                        int fundingPeriods = decisionPeriodsForElapsed(
                                CANONICAL_REACQUIRE_WINDOW_NS);
                        if (fundingPeriods > 0 &&
                                decisionTimestampPeriodsMatchWithProvenDuplicates(
                                        provenTimestampSourceHz,
                                        fundingPeriods)) {
                            qualifiedUniqueTimestampSourceHz =
                                    provenTimestampSourceHz;
                            qualifiedUniqueTimestampClockRejected = false;
                            lastRejectedQualifiedTimestampSourceHz = 0.0;
                            lastRejectedQualifiedTimestampProof = "none";
                            lockedSourceFps = tierFor(provenTimestampSourceHz);
                            tierAcquired = true;
                            canonicalReacquireEvidenceNs = 0L;
                            resetPresentation();
                        }
                    }
                } else {
                    canonicalReacquireEvidenceNs = 0L;
                }
                canonicalReacquireCandidateHz = 0.0;
                return;
            }
            double settledRate = decisionRateHz(retentionPeriods);
            if (settledRate < MIN_GENERATION_SOURCE_HZ) return;
            // The complete window must continue proving both the canonical
            // mean and its per-period stability. A 29.7/30.3 alternation has
            // a near-perfect30 mean but is not a30 clock; retaining the old
            // identity through that window would violate the exact timestamp
            // contract. Clear it without inventing a replacement. A later
            // identity must fund the longer re-acquisition window below.
            provenTimestampSourceHz = 0.0;
            canonicalReacquireEvidenceNs = 0L;
            canonicalReacquireCandidateHz = 0.0;
            return;
        }

        // A complete thirty-second low-rate ordinal grid is itself the
        // uninterrupted acquisition proof. It does not depend on the strict
        // per-period accumulator above, whose purpose is to reject ordinary
        // callback jitter without ordinal identity.
        int gridAcquisitionPeriods =
                decisionPeriodsForElapsed(CANONICAL_REACQUIRE_WINDOW_NS);
        if (gridAcquisitionPeriods > 0) {
            double gridCanonical =
                    provenDecisionCanonicalSourceHz(gridAcquisitionPeriods);
            if (gridCanonical > 0.0 && gridCanonical <= 30.0 &&
                    decisionTimestampPeriodsMatchWithOrdinalGrid(
                            gridCanonical, gridAcquisitionPeriods)) {
                provenTimestampSourceHz = gridCanonical;
                canonicalReacquireEvidenceNs = 0L;
                canonicalReacquireCandidateHz = 0.0;
                return;
            }
        }

        if (canonicalReacquireEvidenceNs < CANONICAL_REACQUIRE_WINDOW_NS)
            return;
        int acquisitionPeriods =
                decisionPeriodsForElapsed(CANONICAL_REACQUIRE_WINDOW_NS);
        if (acquisitionPeriods <= 0) return;
        double acquiredCanonical =
                provenDecisionCanonicalSourceHz(acquisitionPeriods);
        if (acquiredCanonical > 0.0 &&
                Math.abs(acquiredCanonical - canonicalReacquireCandidateHz) <=
                        CANONICAL_MEAN_TOLERANCE_HZ) {
            provenTimestampSourceHz = acquiredCanonical;
            canonicalReacquireEvidenceNs = 0L;
            canonicalReacquireCandidateHz = 0.0;
            // (2026-09-01, gc-b28) The complete thirty-second window proven
            // on the duplicates matcher IS the unique-image lattice with at
            // most ten percent ordinal-proven held frames, each of which the
            // renderer bridges by interpolation.  Metroid Prime proved that
            // window twice per session while the strict ten-second unique
            // proof (zero held frames) qualified once in five minutes, so the
            // proven lattice funds generation directly.  The low-rate
            // ordinal grid stays diagnostic-only.
            if (authoritativeSourceHz <= 0.0 &&
                    decisionTimestampPeriodsMatchWithProvenDuplicates(
                            acquiredCanonical, acquisitionPeriods)) {
                qualifiedUniqueTimestampSourceHz = acquiredCanonical;
                qualifiedUniqueTimestampClockRejected = false;
                lastRejectedQualifiedTimestampSourceHz = 0.0;
                lastRejectedQualifiedTimestampProof = "none";
                // Join the public tier to the proven lattice (gc-b29: the
                // health line reported lockedFps=40 from the 57.8-Hz
                // delivery vote while 60 real + 60 generated were presented).
                lockedSourceFps = tierFor(acquiredCanonical);
                tierAcquired = true;
                resetPresentation();
            }
        }
    }

    private static double strictCanonicalForPeriod(
            long periodNs, double preferredHz) {
        if (periodNs <= 0L) return 0.0;
        double best = 0.0;
        double bestFraction = Double.POSITIVE_INFINITY;
        for (double candidate : CANONICAL_TIMESTAMP_SOURCE_HZ) {
            double canonicalPeriodNs = 1_000_000_000.0 / candidate;
            // This is only the elapsed-time accumulator that decides when a
            // full acquisition proof may run. A pixel-identical logical frame
            // legitimately leaves adjacent unique endpoints two canonical
            // periods apart. Do not erase the accumulated thirty seconds for
            // that 2x span: the final decision-window proof below still
            // requires the callback ordinal to advance by exactly twice its
            // modal gap, and rejects unexplained loss or longer pauses.
            for (int multiple = 1; multiple <= 2; ++multiple) {
                double expectedPeriodNs = canonicalPeriodNs * multiple;
                double fraction = Math.abs(periodNs - expectedPeriodNs) /
                        expectedPeriodNs;
                if (fraction > CANONICAL_PERIOD_RMS_FRACTION) continue;
                if (preferredHz > 0.0 &&
                        Math.abs(candidate - preferredHz) <=
                                CANONICAL_MEAN_TOLERANCE_HZ) return candidate;
                if (fraction < bestFraction) {
                    bestFraction = fraction;
                    best = candidate;
                }
            }
        }
        return best;
    }

    private double conservativeTimestampLowerBoundHz() {
        int periods = decisionPeriodsForElapsed(TIER_DECISION_WINDOW_NS);
        if (periods > 0) {
            double settled = decisionRateHz(periods);
            // Once a settled window exists it is the authority. Taking the
            // maximum with the ten-period ring let a brief high cluster fund
            // 60 while the durable lower bound still required40, recreating
            // the per-callback plan churn this guard exists to prevent.
            return timestampLowerBoundHz(settled,
                    decisionPeriodsNs, periods, decisionPeriodIndex, true);
        }
        return 0.0;
    }

    private static double timestampLowerBoundHz(
            double rateHz, long[] periods, int count, int nextIndex,
            boolean newestFirst) {
        if (!Double.isFinite(rateHz) || rateHz <= 0.0 ||
                count < RATE_WINDOW_PERIODS) return 0.0;
        double meanPeriodNs = 1_000_000_000.0 / rateHz;
        double squaredFractionSum = 0.0;
        int index = nextIndex;
        for (int offset = 0; offset < count; ++offset) {
            if (newestFirst) {
                index = (index + periods.length - 1) % periods.length;
            } else {
                index = offset;
            }
            double fraction = (periods[index] - meanPeriodNs) / meanPeriodNs;
            squaredFractionSum += fraction * fraction;
        }
        double rmsFraction = Math.sqrt(squaredFractionSum / count);
        // Three RMS widths are intentionally conservative. An exact arbitrary
        // clock such as the measured60.098 source retains essentially zero
        // width and can prove the one-scan120.052 plan. A jittered mean that
        // merely crosses30/60 cannot fund the boundary until its lower bound
        // does too.
        return Math.max(0.0, rateHz * (1.0 - 3.0 * rmsFraction));
    }

    /** True only on display callbacks selected for a real output submission. */
    public boolean presentationDue(long displayFrameNs) {
        int output = outputFps();
        if (scheduledOutputFps != output) {
            scheduledOutputFps = output;
            nextPresentationNs = 0L;
        }
        long period = outputPeriodNs();
        if (nextPresentationNs == 0L ||
                displayFrameNs - nextPresentationNs > period * 3L) {
            nextPresentationNs = displayFrameNs + period;
            return true;
        }
        // Choreographer timestamps use integer nanoseconds. At 120 Hz three
        // rounded callbacks total 24,999,999 ns, one nanosecond before an exact
        // 40-Hz deadline. Select the nearest physical-vsync tick rather than
        // turning that rounding residue into a visible four-tick gap followed
        // by a compensating two-tick gap.
        long nearestTickTolerance = Math.max(1L, displayPeriodNs / 4L);
        long selectedTime = displayFrameNs + nearestTickTolerance;
        if (selectedTime < nextPresentationNs) return false;
        do { nextPresentationNs += period; }
        while (nextPresentationNs <= selectedTime);
        return true;
    }

    public double measuredProducerHz() {
        if (authoritativeSourceHz > 0.0) return authoritativeSourceHz;
        return measuredProducerPeriodNs <= 0.0 ? 0.0 :
                1_000_000_000.0 / measuredProducerPeriodNs;
    }

    /** Complete-window unique-source throughput for truthful UI reporting. */
    public double sustainedMeasuredSourceHz() {
        if (authoritativeSourceHz > 0.0) return authoritativeSourceHz;
        int periods = decisionPeriodsForElapsed(TIER_DECISION_WINDOW_NS);
        double settled = periods > 0 ? decisionRateHz(periods) : 0.0;
        return settled > 0.0 ? settled : measuredProducerHz();
    }

    /** Physical emulator callback rate reconstructed from unique-frame ordinals. */
    public double measuredSubmissionHz() {
        return !producerSubmissionClockObserved ||
                measuredSubmissionPeriodNs <= 0.0 ? 0.0 :
                1_000_000_000.0 / measuredSubmissionPeriodNs;
    }

    public double provenTimestampSourceHzForDiagnostics() {
        return provenTimestampSourceHz;
    }

    public double qualifiedUniqueTimestampSourceHzForDiagnostics() {
        return qualifiedUniqueTimestampSourceHz;
    }

    /** Declared core tick clock used only to detect transport coalescing. */
    public double producerTimelineHzForDiagnostics() {
        return producerTimelineHz;
    }

    /** Number of immutable PTS spans whose core ticks were not all delivered. */
    public long producerTimelineDiscontinuityCountForDiagnostics() {
        return producerTimelineDiscontinuityCount;
    }

    /** Diagnostic only: elapsed strict evidence funding the next full proof. */
    public long canonicalReacquireEvidenceNsForDiagnostics() {
        return canonicalReacquireEvidenceNs;
    }

    /** Diagnostic only: canonical identity currently funding reacquisition. */
    public double canonicalReacquireCandidateHzForDiagnostics() {
        return canonicalReacquireCandidateHz;
    }

    public double lastRejectedQualifiedTimestampSourceHzForDiagnostics() {
        return lastRejectedQualifiedTimestampSourceHz;
    }

    public String lastRejectedQualifiedTimestampProofForDiagnostics() {
        return lastRejectedQualifiedTimestampProof;
    }

    /**
     * Captures the exact durable-window intervals that revoked a qualified
     * clock. This is read-only evidence: it never participates in admission,
     * retention, target selection, or presentation.
     */
    private String timestampClockRejectionSummary(double rateHz, int count) {
        int sampleCount = Math.min(count, decisionPeriodCount);
        if (!Double.isFinite(rateHz) || rateHz <= 0.0 || sampleCount <= 0)
            return "rate=0.000,count=" + sampleCount;
        double canonicalPeriodNs = 1_000_000_000.0 / rateHz;
        int anomalyCount = 0;
        StringBuilder anomalies = new StringBuilder();
        long ordinaryElapsedNs = 0L;
        int ordinaryCount = 0;
        int index = decisionPeriodIndex;
        for (int offset = 0; offset < sampleCount; ++offset) {
            index = (index + decisionPeriodsNs.length - 1) %
                    decisionPeriodsNs.length;
            long periodNs = decisionPeriodsNs[index];
            double ratio = periodNs / canonicalPeriodNs;
            if (Math.abs(ratio - 1.0) <= CANONICAL_PERIOD_MAX_FRACTION) {
                ordinaryElapsedNs += periodNs;
                ++ordinaryCount;
                continue;
            }
            ++anomalyCount;
            if (anomalyCount <= 4) {
                if (anomalies.length() > 0) anomalies.append(';');
                anomalies.append("o").append(offset)
                        .append("=").append(periodNs)
                        .append("ns/")
                        .append(String.format(java.util.Locale.US,
                                "%.6fx", ratio))
                        .append("/g")
                        .append(decisionSubmissionGaps[index]);
            }
        }
        double ordinaryHz = ordinaryElapsedNs <= 0L ? 0.0 :
                ordinaryCount * 1_000_000_000.0 / ordinaryElapsedNs;
        return String.format(java.util.Locale.US,
                "rate=%.3f,count=%d,ordinary=%d,ordinaryHz=%.6f," +
                        "anomalies=%d,detail=%s",
                rateHz, sampleCount, ordinaryCount, ordinaryHz,
                anomalyCount, anomalies.length() == 0 ? "none" : anomalies);
    }

    /**
     * Read-only aggregate of the current durable canonical-clock evidence.
     * This deliberately does not participate in selection. It exposes whether
     * a physical failure is mean-rate drift, per-period delivery jitter, an
     * unproved duplicate span, or simply an incomplete observation window.
     */
    public String canonicalProofSummaryForDiagnostics() {
        return canonicalProofSummaryForDiagnostics(
                CANONICAL_REACQUIRE_WINDOW_NS);
    }

    /**
     * Read-only aggregate over the exact window that can revoke an already
     * qualified source clock.  The longer canonical proof above is useful for
     * acquisition, but it hid the individual ten-second interval responsible
     * for a physical active-path teardown (TWINE r190).
     */
    public String canonicalRetentionProofSummaryForDiagnostics() {
        return canonicalProofSummaryForDiagnostics(TIER_DECISION_WINDOW_NS);
    }

    private String canonicalProofSummaryForDiagnostics(long windowNs) {
        double candidate = canonicalReacquireCandidateHz;
        if (candidate <= 0.0) {
            candidate = nearestCanonicalTimestampSourceHz(
                    sustainedMeasuredSourceHz());
        }
        int sampleCount = decisionPeriodsForElapsed(windowNs);
        if (sampleCount <= 0) sampleCount = Math.min(decisionPeriodCount,
                MAX_TIER_DECISION_PERIODS);
        if (candidate <= 0.0 || sampleCount <= 0) {
            return "candidate=0.000,count=" + sampleCount;
        }

        double canonicalPeriodNs = 1_000_000_000.0 / candidate;
        int[] ordinaryGapHistogram = new int[65];
        int one = 0;
        int two = 0;
        int other = 0;
        int index = decisionPeriodIndex;
        for (int offset = 0; offset < sampleCount; ++offset) {
            index = (index + decisionPeriodsNs.length - 1) %
                    decisionPeriodsNs.length;
            long periodNs = decisionPeriodsNs[index];
            int multiple = (int) Math.round(periodNs / canonicalPeriodNs);
            if (multiple == 1) {
                ++one;
                int gap = decisionSubmissionGaps[index];
                if (gap > 0 && gap < ordinaryGapHistogram.length)
                    ++ordinaryGapHistogram[gap];
            } else if (multiple == 2) ++two;
            else ++other;
        }
        int modalGap = 0;
        int modalCount = 0;
        for (int gap = 1; gap < ordinaryGapHistogram.length; ++gap) {
            if (ordinaryGapHistogram[gap] > modalCount) {
                modalGap = gap;
                modalCount = ordinaryGapHistogram[gap];
            }
        }

        int ordinalBad = 0;
        int logicalPeriods = 0;
        long elapsedNs = 0L;
        double squaredFractionSum = 0.0;
        double maximumFraction = 0.0;
        index = decisionPeriodIndex;
        for (int offset = 0; offset < sampleCount; ++offset) {
            index = (index + decisionPeriodsNs.length - 1) %
                    decisionPeriodsNs.length;
            long periodNs = decisionPeriodsNs[index];
            int multiple = (int) Math.round(periodNs / canonicalPeriodNs);
            if (multiple < 1) multiple = 1;
            if (multiple > 2) multiple = 2;
            int gap = decisionSubmissionGaps[index];
            if (modalGap > 0 && gap != modalGap * multiple) ++ordinalBad;
            double normalizedPeriodNs = (double) periodNs / multiple;
            double fraction = Math.abs(normalizedPeriodNs -
                    canonicalPeriodNs) / canonicalPeriodNs;
            squaredFractionSum += fraction * fraction;
            maximumFraction = Math.max(maximumFraction, fraction);
            logicalPeriods += multiple;
            elapsedNs += periodNs;
        }
        double logicalRateHz = elapsedNs <= 0L ? 0.0 :
                logicalPeriods * 1_000_000_000.0 / elapsedNs;
        double rmsFraction = Math.sqrt(squaredFractionSum / sampleCount);
        return String.format(java.util.Locale.US,
                "candidate=%.3f,count=%d,one=%d,two=%d,other=%d," +
                        "modalGap=%d,ordinalBad=%d,logicalHz=%.4f," +
                        "rmsPpm=%d,maxPpm=%d",
                candidate, sampleCount, one, two, other, modalGap,
                ordinalBad, logicalRateHz,
                Math.round(rmsFraction * 1_000_000.0),
                Math.round(maximumFraction * 1_000_000.0));
    }

    /**
     * Installs the immutable clock stamped by the hardware producer.
     *
     * <p>This is intentionally not source-rate authority: a 60-Hz core can
     * render a 20- or 30-Hz game. It validates only the transport span between
     * two classified images. Changing the trust boundary discards all prior
     * rate evidence so unstamped and stamped timestamps can never be joined.</p>
     */
    public void setProducerTimelineHz(double value) {
        double sanitized = Double.isFinite(value) && value >= 1.0 &&
                value <= 1000.0 ? value : 0.0;
        if (Double.doubleToLongBits(sanitized) ==
                Double.doubleToLongBits(producerTimelineHz)) return;
        producerTimelineHz = sanitized;
        producerTimelineDiscontinuityCount = 0L;
        provenTimestampSourceHz = 0.0;
        qualifiedUniqueTimestampSourceHz = 0.0;
        qualifiedUniqueTimestampClockRejected = false;
        canonicalReacquireEvidenceNs = 0L;
        canonicalReacquireCandidateHz = 0.0;
        producerSamples = 0;
        producerPeriodIndex = 0;
        producerPeriodCount = 0;
        producerPeriodSumNs = 0L;
        measuredProducerPeriodNs = 0.0;
        clearDecisionPeriods();
        tierAcquired = authoritativeSourceHz > 0.0;
        previousProducerNs = 0L;
        previousProducerSubmissionOrdinal = 0L;
        measuredSubmissionPeriodNs = 0.0;
        producerSubmissionClockObserved = false;
        java.util.Arrays.fill(worstSecondCounts, 0);
        worstSecondBucketStartNs = 0L;
        worstSecondBucketIndex = 0;
        worstSecondFilled = 0;
        resetPresentation();
    }

    /**
     * Uses a core's declared video clock for systems whose video callback is
     * itself the authoritative scan cadence. Static pixels are still a real
     * core frame on those systems and must not be mistaken for slowdown.
     */
    public void setAuthoritativeSourceHz(double value) {
        provenTimestampSourceHz = 0.0;
        qualifiedUniqueTimestampSourceHz = 0.0;
        qualifiedUniqueTimestampClockRejected = false;
        canonicalReacquireEvidenceNs = 0L;
        canonicalReacquireCandidateHz = 0.0;
        if (!Double.isFinite(value) || value < MIN_GENERATION_SOURCE_HZ) {
            authoritativeSourceHz = 0.0;
            authoritativeSourceFps = 0;
        } else {
            authoritativeSourceHz = value;
            authoritativeSourceFps = Math.max(1, (int) Math.round(value));
            lockedSourceFps = tierFor(value);
            measuredProducerPeriodNs = 1_000_000_000.0 / authoritativeSourceHz;
        }
        producerSamples = 0;
        producerPeriodIndex = 0;
        producerPeriodCount = 0;
        producerPeriodSumNs = 0L;
        clearDecisionPeriods();
        tierAcquired = authoritativeSourceHz > 0.0;
        previousProducerNs = 0L;
        previousProducerSubmissionOrdinal = 0L;
        measuredSubmissionPeriodNs = 0.0;
        producerSubmissionClockObserved = false;
        resetPresentation();
    }

    public boolean usesAuthoritativeSourceRate() {
        return authoritativeSourceHz > 0.0;
    }

    public boolean generatesIntermediateFrames() {
        return generationAvailable && hasSustainableGenerationRate() &&
                currentUniformOutputPlan().generatesIntermediateFrames();
    }

    public void resetPresentation() {
        discardPendingMidpoint();
        promotedSequence = 0L;
        lastPromotionNs = 0L;
        nextPromotionNs = 0L;
        nextPresentationNs = 0L;
        scheduledOutputFps = 0;
        midpointDueNs = 0L;
        selectedPhase = 1f;
        ++presentationEpoch;
        resetBufferedPresentation();
    }

    private void updateTier() {
        if (producerSamples < MIN_SAMPLES) return;
        // A rejected generator must become direct-only, but it must not freeze
        // a provisional lower source tier forever. ALBW acquired 50 during
        // startup, rejected generation, and then delivered a sustained
        // producerHz ~= 60 while the controller kept presenting only 50. Keep
        // durable producer voting alive so direct fallback can climb to the
        // highest source tier it subsequently proves. The downgrade branch
        // below remains disabled in fallback mode: pixel/content activity
        // after rejection is not sufficient evidence to throw real frames
        // away or make the direct cadence churn downward.
        boolean directFallbackMode = !generationAvailable && tierAcquired;
        int periods;
        if (!tierAcquired) {
            if (decisionPeriodCount < INITIAL_TIER_PERIODS) return;
            periods = INITIAL_TIER_PERIODS;
        } else {
            periods = decisionPeriodsForElapsed(TIER_DECISION_WINDOW_NS);
            if (periods <= 0) return;
        }
        double settledRateHz = decisionRateHz(periods);
        int settledTier = tierFor(settledRateHz);
        boolean acquiredNow = !tierAcquired;
        tierAcquired = true;
        if (acquiredNow) {
            // Bootstrap from the measured tier itself. Schmitt hold applies
            // only after a tier has honestly been acquired; otherwise the
            // default 60 would conceal a real 50/40/30/20 source.
            if (settledTier != lockedSourceFps) applyTier(settledTier);
        } else if (settledTier > lockedSourceFps) {
            // Upgrades honor the exact user-facing tier boundary. A genuine
            // sustained 29.8 source that started at 20 therefore cannot claim
            // 30/60. Climb ONE tier at a time, and only when the trailing
            // WORST one-second delivery already funds the higher tier's
            // floor: the lock then converges to the HIGHEST tier the game's
            // worst delivery can hold (user directive 2026-08-16 — never
            // park a 50-capable game below what it sustains), while a mean
            // that flatters a wobbly source cannot re-claim a tier its dips
            // would starve (the wiiu19 cascade). The post-demotion hold
            // still spaces attempts after a proven failure, and a climb
            // that starves simply demotes again through the material
            // threshold.
            int candidateTier = Math.min(settledTier,
                    nextHigherTier(lockedSourceFps));
            // +2 frames absorbs one-second bucket quantization: a true-60
            // stream legitimately counts 58 in a bucket whose boundaries
            // split two frame intervals (physically hit on Dolphin GC,
            // run gc2 2026-08-17: worst seconds of 57-58 pinned a 60
            // source at the 50 tier forever). A real dip (SM3DW's 31-45)
            // stays far below any higher floor even with the allowance.
            // After a proven climb failure, six calm seconds in the ring are
            // not enough: the minimum worst-second across the whole hold
            // must fund the higher floor, so a scene whose dips recur every
            // 10-30 s can never round-trip climb/starve/demote against them
            // (SMG2 Star Festival, run wii1 2026-08-17). A source that
            // genuinely recovered holds the floor for the entire hold and
            // still climbs at expiry.
            // +3 (vs the instantaneous gate's +2): the minimum over a 30 s
            // window meets more bucket-quantization splits than a 6-bucket
            // ring — a true-60 stream's worst count can touch 57 (gc2) —
            // while a real recurring dip (43-55, SMG2/SM3DW) still sits far
            // below any higher floor.
            boolean heldEvidence = starvationDemotionCount == 0 ||
                    (reclimbEvidenceMinRate != Double.MAX_VALUE &&
                            reclimbEvidenceMinRate + 3.0 >=
                                    tierFloorHz(candidateTier));
            if (candidateTier > lockedSourceFps &&
                    bufferedLastSelectionDisplayFrameNs >=
                            starvationUpgradeHoldUntilNs &&
                    heldEvidence &&
                    worstRecentSecondRate() + 2.0 >= tierFloorHz(candidateTier))
                applyTier(candidateTier);
            else if (candidateTier > lockedSourceFps &&
                    bufferedLastSelectionDisplayFrameNs >=
                            starvationUpgradeHoldUntilNs &&
                    !heldEvidence) {
                // The hold expired without continuous funding: restart the
                // evidence window instead of leaving expiry in the past,
                // where any later 6-second calm stretch would climb with a
                // stale minimum.
                starvationUpgradeHoldUntilNs =
                        bufferedLastSelectionDisplayFrameNs +
                                STARVATION_UPGRADE_HOLD_NS;
                reclimbEvidenceStartNs = bufferedLastSelectionDisplayFrameNs;
                reclimbEvidenceMinRate = Double.MAX_VALUE;
            }
        } else if (!directFallbackMode && settledTier < lockedSourceFps) {
            // A complete history can straddle qualification startup or a
            // brief renderer-load transition. Do not let that stale average
            // demote an acquired 60-Hz source while the current short window
            // is still inside the same 60-tier Schmitt band. A sustained true
            // 55-Hz source has both windows below the boundary and still moves
            // to the 50 tier.
            int candidateTier = downgradeTierFor(settledRateHz, lockedSourceFps);
            // The submission clock may vouch for a held 60 tier only against
            // static-content undercounting. When the window is an EXACT
            // supported duplicate schedule (physically hit on the Thor,
            // 2026-08-15: ARMSX2 submitting each 30-fps frame twice kept
            // max(unique=30, submissions=60) inside the hold band and the
            // tier stayed 60 for many minutes, presenting 120 with
            // motionless synthetics between duplicate endpoints), the unique
            // clock owns the decision and the duplicate-schedule machinery
            // below demotes truthfully. Irregular static runs still fail its
            // exactness test and keep the hold.
            boolean exactDuplicateSchedule =
                    candidateTier >= (int) MIN_GENERATION_SOURCE_HZ &&
                    candidateTier < lockedSourceFps &&
                    duplicateFilteredDowngradeIsSupported(
                            settledRateHz, candidateTier, periods);
            // The submission clock may vouch for a held 60 only against
            // genuinely static content (few unique images per submission).
            // A core that submits 60 and yields 55-57 unique images is
            // dropping frames under load (Dolphin, run gc-b16), not idling,
            // and the protocol demotes it to the tier it can hold.
            double submissionHz = measuredSubmissionHz();
            // A slot-lattice producer submits only the frames its guest
            // presented, so its submission clock is the delivery rate; the
            // trusted lattice itself is the scan cadence that vouches for the
            // 60 tier (wiiu-b37 flipped 40<->60 every few seconds on a
            // 53-unique stream, resetting the clock evidence each time).
            if (slotLatticeProducer && producerTimelineHz > 0.0)
                submissionHz = Math.max(submissionHz, producerTimelineHz);
            double uniqueHz = measuredProducerHz();
            // (2026-09-01, gc-b22) A game that natively holds ~4 percent of
            // its frames keeps the 60 lattice of its submission clock; the
            // generator interpolates across ordinal-proven held frames.
            boolean currentSixtyClockHealthy = lockedSourceFps == 60 &&
                    (uniqueHz >=
                            tierFloorHz(60) - SIXTY_TIER_SCHEDULER_HOLD_HZ ||
                     (submissionHz >=
                            tierFloorHz(60) - SIXTY_TIER_SCHEDULER_HOLD_HZ &&
                      !exactDuplicateSchedule));
            int hystereticTier = currentSixtyClockHealthy ? lockedSourceFps :
                    candidateTier;
            if (hystereticTier < lockedSourceFps &&
                    duplicateFilteredDowngradeIsSupported(
                            settledRateHz, hystereticTier, periods))
                applyTier(hystereticTier);
        }
        // Initial acquisition is intentionally quick. Start the durable
        // observation after it so those 90 bootstrap periods cannot be reused
        // as most of the evidence for an immediate opposite transition.
        if (acquiredNow) {
            // Ninety immutable periods may establish the initial canonical
            // identity when their mean and every-period stability pass the
            // same strict proof used by the durable window. This preserves a
            // prompt exact60->120 or exact30->60 startup without reviving the
            // unsafe ten-period re-acquisition path.
            double bootstrapCanonical =
                    provenDecisionCanonicalSourceHz(periods);
            if (bootstrapCanonical > 0.0)
                provenTimestampSourceHz = bootstrapCanonical;
            // Generation may start from the bootstrap only when the
            // classified unique-image periods themselves are stable. A
            // canonical callback grid inferred through held duplicates stays
            // diagnostic-only and cannot fund synthetic presentations.
            double bootstrapUnique =
                    provenDecisionUniqueTimestampSourceHz(periods);
            if (bootstrapUnique > 0.0) {
                qualifiedUniqueTimestampSourceHz = bootstrapUnique;
                qualifiedUniqueTimestampClockRejected = false;
                provenTimestampSourceHz = bootstrapUnique;
            }
            canonicalReacquireEvidenceNs = 0L;
            canonicalReacquireCandidateHz = 0.0;
            clearDecisionPeriods();
        }
    }

    private void recordDecisionPeriod(long periodNs, int submissionGap) {
        if (decisionPeriodCount == decisionPeriodsNs.length)
            decisionPeriodSumNs -= decisionPeriodsNs[decisionPeriodIndex];
        else
            ++decisionPeriodCount;
        decisionPeriodsNs[decisionPeriodIndex] = periodNs;
        decisionSubmissionGaps[decisionPeriodIndex] = submissionGap;
        decisionPeriodSumNs += periodNs;
        decisionPeriodIndex = (decisionPeriodIndex + 1) % decisionPeriodsNs.length;
    }

    private void clearDecisionPeriods() {
        trimNewPeriodNs = 0L;
        trimNewEvidenceNs = 0L;
        decisionPeriodIndex = 0;
        decisionPeriodCount = 0;
        decisionPeriodSumNs = 0L;
    }

    /**
     * A direct slower producer has callback-ordinal gaps of one and retains the
     * established floor behavior (for example a true 55-Hz clock maps to 50).
     * If the apparent deficit came from pixel-identical callbacks, require the
     * complete observation to land close to an explicit supported lower tier.
     * This preserves exact 5/6, 2/3, 1/2 and 1/3 duplicate schedules while an
     * irregular content pause cannot manufacture a new presentation lattice.
     */
    private boolean duplicateFilteredDowngradeIsSupported(
            double measuredHz, int proposedTier, int periods) {
        // A static-content transition can make a mixed ten-second window pass
        // numerically through 20 Hz even though its ordinal-reconstructed
        // callback clock remains the already-proven tier and its current
        // unique-image rate is below every supported generation tier. That is
        // not evidence of a new fixed 20-Hz source; it is merely sparse pixel
        // change. Exact 50/40/30 duplicate schedules still have a current
        // unique rate at or above the supported 20-Hz floor and continue into
        // the rational-pattern check below.
        if (measuredProducerHz() < MIN_GENERATION_SOURCE_HZ &&
                measuredSubmissionHz() >= tierFloorHz(lockedSourceFps))
            return false;
        int count = Math.min(periods, decisionPeriodCount);
        int index = decisionPeriodIndex;
        boolean ordinalEvidence = false;
        boolean skippedCallback = false;
        for (int offset = 0; offset < count; ++offset) {
            index = (index + decisionSubmissionGaps.length - 1) %
                    decisionSubmissionGaps.length;
            int gap = decisionSubmissionGaps[index];
            if (gap <= 0) continue;
            ordinalEvidence = true;
            if (gap > 1) skippedCallback = true;
        }
        if (!ordinalEvidence || !skippedCallback) return true;
        // Tier protocol 2026-09-01: skipped callbacks under mostly-moving
        // content are dropped frames, not a content pause.  A core that
        // submits 60 and yields 56-58 unique moving images (Dolphin, run
        // gc-b19: 512 endpoint-span rejections per session at the held 60)
        // gets a conservative delivery-tier label. Static
        // content (few unique images per submission) keeps the old rule.
        return Math.abs(measuredHz - proposedTier) <= 2.0;
    }

    /** Number of newest periods covering at least the requested producer time. */
    private int decisionPeriodsForElapsed(long requiredNs) {
        if (requiredNs <= 0L || decisionPeriodSumNs < requiredNs) return 0;
        long sum = 0L;
        int count = 0;
        int index = decisionPeriodIndex;
        while (count < decisionPeriodCount && sum < requiredNs) {
            index = (index + decisionPeriodsNs.length - 1) %
                    decisionPeriodsNs.length;
            sum += decisionPeriodsNs[index];
            ++count;
        }
        return sum >= requiredNs ? count : 0;
    }

    private double decisionRateHz(int periods) {
        int count = Math.min(periods, decisionPeriodCount);
        long sum = 0L;
        int index = decisionPeriodIndex;
        for (int offset = 0; offset < count; ++offset) {
            index = (index + decisionPeriodsNs.length - 1) %
                    decisionPeriodsNs.length;
            sum += decisionPeriodsNs[index];
        }
        return sum <= 0L ? 0.0 : count * 1_000_000_000.0 / sum;
    }

    private void applyTier(int tier) {
        discardPendingMidpoint();
        provenTimestampSourceHz = 0.0;
        qualifiedUniqueTimestampSourceHz = 0.0;
        qualifiedUniqueTimestampClockRejected = false;
        canonicalReacquireEvidenceNs = 0L;
        canonicalReacquireCandidateHz = 0.0;
        lockedSourceFps = tier;
        // Keep the public/direct scheduler clock synchronized when durable
        // producer evidence upgrades a generator-rejected session.
        if (!generationAvailable && directFallbackSourceFps > 0)
            directFallbackSourceFps = tier;
        nextPromotionNs = 0L;
        nextPresentationNs = 0L;
        scheduledOutputFps = 0;
        midpointDueNs = 0L;
        selectedPhase = 1f;
        ++presentationEpoch;
        // A source-tier decision changes both the uniform output lattice and
        // the cadence used to select endpoint timestamps. An endpoint pair
        // retained under the old tier is therefore not evidence for the new
        // timeline: a startup 20/30-Hz pair can be wider than the legal 60-Hz
        // continuity bound. Keeping it left the controller permanently
        // unprimed while the renderer continued to hold that same stale pair.
        // Publish an epoch boundary and require the renderer to re-prime from
        // endpoints selected under this tier instead of replaying old pixels.
        resetBufferedPresentation();
    }

    private long legacyIntermediateDueNs() {
        return midpointPromotionNs +
                sourcePeriodNs() * midpointSlotIndex / (midpointSlots + 1);
    }

    private void discardPendingMidpoint() {
        if (midpointPending) {
            midpointPending = false;
            ++syntheticQuotaSkippedCount;
        }
    }

    private int tierFor(double measuredHz) {
        // Small tolerance absorbs scheduler quantization around nominal rates;
        // the slow-upgrade vote requirement supplies the real recovery margin.
        // Nanosecond timestamps cannot represent 60/30 Hz periods exactly.
        // The 0.1-Hz allowance absorbs only that clock quantization; 59.8,
        // 39.8 and 29.8 remain in their lower contract buckets.  There is no
        // 50 bucket: 40.0-59.8 is the 40 tier on a 120-Hz panel and, with no
        // 40 divisor on a 60-Hz panel, 30.0-59.8 is the 30 tier there.
        if (measuredHz >= 59.9) return 60;
        if (tiers == TIERS_60) return measuredHz >= 29.9 ? 30 : 20;
        if (measuredHz >= 39.9) return 40;
        if (measuredHz >= 29.9) return 30;
        return 20;
    }

    /** Protocol tiers for the active panel, highest first. */
    public int[] protocolTiers() { return tiers.clone(); }

    private int tierIndex(int tier) {
        for (int index = 0; index < tiers.length; ++index)
            if (tiers[index] == tier) return index;
        return tiers.length - 1;
    }

    private static double tierFloorHz(int tier) {
        if (tier >= 60) return 59.9;
        if (tier >= 40) return 39.9;
        if (tier >= 30) return 29.9;
        return MIN_GENERATION_SOURCE_HZ;
    }

    private int downgradeTierFor(double measuredHz, int currentTier) {
        int currentIndex = tierIndex(currentTier);
        // Stateful Schmitt boundary: once a tier has been honestly acquired at
        // its exact threshold, ordinary scheduler bias may hold it by at most
        // one FPS. It must sustain a clear >1-FPS deficit to move down. This is
        // deliberately asymmetric with upgrades, so 29.8 cannot acquire 30
        // from 20, while a nominal-30 game measured at 29.5 does not toggle
        // 30->20->30 every three seconds.
        double hold = currentTier == 60 ? SIXTY_TIER_SCHEDULER_HOLD_HZ :
                CLEAR_DEFICIT_HZ;
        if (currentIndex < tiers.length - 1 &&
                measuredHz < tierFloorHz(currentTier) - hold)
            return tierFor(measuredHz);
        return currentTier;
    }

    private long sourcePeriodNs() {
        // Legacy arrival-driven promotion remains tier-based. The production
        // buffered scheduler derives phase from immutable endpoint timestamps
        // and presentationSourceHz instead of this compatibility path.
        return Math.max(1L, Math.round(1_000_000_000.0 / lockedSourceFps()));
    }

    private long outputPeriodNs() {
        return Math.max(1L, Math.round(1_000_000_000.0 / outputFps()));
    }

    private int measuredSourceFps() {
        return Math.max(1, (int) Math.round(measuredProducerHz()));
    }

    /** Stable policy tier during decoder warm-up, before durable acquisition. */
    private int provisionalSourceFps(double measuredHz) {
        if (!Double.isFinite(measuredHz) || measuredHz <= 0.0) return 60;
        if (measuredHz < MIN_GENERATION_SOURCE_HZ - 2.0)
            return Math.max(1, (int) Math.round(measuredHz));
        if (measuredHz >= 55.0) return 60;
        if (tiers == TIERS_60) return measuredHz >= 25.0 ? 30 : 20;
        if (measuredHz >= 35.0) return 40;
        if (measuredHz >= 25.0) return 30;
        return 20;
    }
}
