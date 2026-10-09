package com.thorium.lucent.video;

public final class PhysicalPresentationClockTest {
    public static void main(String[] ignored) {
        longBaselineLearnsPhysicalPeriodWithoutMovingAnchor();
        calibrationRequiresThirtyPhysicalScansAtEachRefresh();
        unavailableAndBadRowsCannotEarnCalibration();
        freshEpochPartitionsPhaseButNotContinuousPhysicalFrequency();
        thorB14SparsePhysicalRowsBreakNominalClockDeadlock();
        skippedScansDoNotDistortTheEstimate();
        schedulerEpochCarriesPeriodButRequiresFreshPhysicalPhase();
        thorR203QueueTailUsesCarriedPeriodBeforeRelearn();
        refreshChangeRejectsCarriedPeriod();
        inconsistentRowsAndRefreshChangesFailClosedOrReset();
        shortSchedulerEpochsMustNotFreezeANoisyFrequencyEstimate();
        ambiguousEpochGapCannotEarnFrequencyScans();
        sustainedFrequencyRequiresLongFreshPhysicalEvidence();
        longIdleCannotQualifyGuestClock();
        sustainedFrequencyTracksRecentOscillatorInsteadOfSessionAverage();
        recentFrequencyCountsSkippedScansAndBoundsFenceNoise();
        System.out.println("PhysicalPresentationClockTest passed");
    }

    private static void recentFrequencyCountsSkippedScansAndBoundsFenceNoise() {
        PhysicalPresentationClock clock = new PhysicalPresentationClock();
        long physical = 8_335_556L, nominal = 8_333_333L;
        long time = 1_000_000_000L;
        clock.record(time, nominal);
        long last = time;
        for (int i = 1; i <= 18000; ++i) {
            // Both one- and three-scan observations; no frame duplication is
            // inferred from missing feedback. Alternate +/-20us fence noise.
            time += physical * (i % 7 == 0 ? 3 : 1);
            last = time + (i % 2 == 0 ? 20_000L : -20_000L);
            check(clock.record(last, nominal), "noisy skipped-scan row accepted");
            if (i > 2500) {
                double rate = clock.sustainedFrequencyHz(last);
                check(rate > 0.0 && Math.abs(rate - 1e9 / physical) < 0.00025,
                        "rolling estimate counts physical scans and bounds endpoint noise");
            }
        }
        clock.beginPresentationEpoch();
        clock.record(last + 1_000_000_000L, nominal);
        check(clock.sustainedFrequencyHz(last + 1_000_000_000L) == 0.0,
                "wrapped rolling history must not survive a long idle as trim evidence");
    }

    private static void sustainedFrequencyTracksRecentOscillatorInsteadOfSessionAverage() {
        // Synthetic oscillator step, not a replay of Thor's incomplete fence trace.
        PhysicalPresentationClock clock = new PhysicalPresentationClock();
        long now = 1_000_000_000L, nominal = 8_333_333L;
        long oldPeriod = 8_337_154L, newPeriod = 8_335_556L;
        clock.record(now, nominal);
        for (int i = 0; i < 14400; ++i) {
            now += oldPeriod;
            check(clock.record(now, nominal), "old oscillator accepted");
        }
        for (int i = 0; i < 3000; ++i) {
            now += newPeriod;
            check(clock.record(now, nominal), "new oscillator accepted");
        }
        double actual = clock.sustainedFrequencyHz(now);
        check(Math.abs(actual - 1e9 / newPeriod) < 0.000001,
                "25 seconds of new physical evidence must replace session-average rate; actual=" + actual);
    }

    private static void longIdleCannotQualifyGuestClock() {
        PhysicalPresentationClock clock = new PhysicalPresentationClock();
        long first = 1_000_000_000L, period = 8_333_333L;
        clock.record(first, period);
        long resumed = first + 3000 * period;
        clock.record(resumed, period);
        for (int i = 1; i <= 30; ++i) clock.record(resumed + i * period, period);
        check(clock.available(), "planning still has its oscillator");
        check(clock.sustainedFrequencyHz(resumed + 30 * period) == 0.0,
                "idle plus short resumed burst cannot count as sustained observation");
        for (int i = 31; i <= 2500; ++i) clock.record(resumed + i * period, period);
        check(clock.sustainedFrequencyHz(resumed + 2500 * period) > 0.0,
                "fresh continuous window reacquires evidence after idle");
    }

    private static void sustainedFrequencyRequiresLongFreshPhysicalEvidence() {
        PhysicalPresentationClock clock = new PhysicalPresentationClock();
        long start = 1_000_000_000L, period = 8_337_154L;
        clock.record(start, 8_333_333L);
        for (int i = 1; i <= 30; ++i) clock.record(start + i * period, 8_333_333L);
        check(clock.sustainedFrequencyHz(start + 30 * period) == 0.0,
                "short planning calibration cannot trim gameplay");
        for (int i = 31; i <= 2500; ++i) clock.record(start + i * period, 8_333_333L);
        long now = start + 2500 * period;
        check(Math.abs(clock.sustainedFrequencyHz(now) - 1e9 / period) < 1e-9,
                "physical quotient retains fractional refresh");
        check(clock.sustainedFrequencyHz(now + 250_000_001L) == 0.0,
                "stale feedback cannot trim gameplay");
        clock.beginPresentationEpoch();
        check(clock.sustainedFrequencyHz(now) == 0.0, "new epoch needs fresh phase");
        clock.record(now + period, 8_333_333L);
        check(clock.sustainedFrequencyHz(now + period) > 0.0, "same-mode frequency retained");
        clock.record(now + period * 3, 16_666_667L);
        check(clock.sustainedFrequencyHz(now + period * 3) == 0.0, "mode change discards evidence");
        clock.reset();
        check(clock.sustainedFrequencyHz(now) == 0.0, "reset revokes evidence");
    }

    private static void shortSchedulerEpochsMustNotFreezeANoisyFrequencyEstimate() {
        // Deterministic noise/epoch model, NOT a reconstruction of missing Thor
        // fences. 51d1 shows ~150-ms scheduler epochs and later token mismatches;
        // this isolates whether short epochs prevent independent clock learning.
        PhysicalPresentationClock clock = new PhysicalPresentationClock();
        long first = 900_000_000_000L;
        long period = 8_333_333L;
        check(clock.record(first + 360_000L, period, first), "noisy first fence");
        for (int scan = 1; scan <= 30; ++scan)
            check(clock.record(first + period * scan, period,
                    first + period * scan), "initial measured scan");
        eq(period - 12_000L, clock.planningPeriodNs(),
                "short baseline honestly contains first-fence noise");
        for (int scan = 31; scan <= 1200; ++scan) {
            if (scan % 12 == 7) {
                clock.beginPresentationEpoch();
                check(!clock.available(), "logical epoch still needs fresh phase");
            }
            check(clock.record(first + period * scan, period,
                    first + period * scan), "independent later physical scan");
        }
        check(abs(clock.planningPeriodNs() - period) <= 300L,
                "short scheduler epochs must not freeze 12000-ns period error");
        // The clock must not repair already-issued targets or relax token gates.
        long oldTarget = 323_128_521_405_345L;
        check(CompositorFrameTimeline.selectRefreshSafeTarget(oldTarget, period,
                323_128_485_305_483L, new long[]{371_472_004L},
                new long[]{323_128_521_915_665L},
                new long[]{323_128_511_582_332L}, 1) == null,
                "51d1's recorded +510320-ns target mismatch remains rejected");
    }

    private static void calibrationRequiresThirtyPhysicalScansAtEachRefresh() {
        long[] nominals = {8_333_333L, 16_666_666L};
        long[] physicals = {8_329_228L, 16_658_994L};
        for (int mode = 0; mode < nominals.length; ++mode) {
            PhysicalPresentationClock clock = new PhysicalPresentationClock();
            long actual = 10_000_000_000L;
            long planning = actual - 100_000L;
            check(clock.record(actual, nominals[mode], planning),
                    "independent physical row anchors each refresh");
            for (int scan = 1; scan < 30; ++scan) {
                check(clock.record(actual + physicals[mode] * scan,
                        nominals[mode], planning + nominals[mode] * scan),
                        "short-baseline row remains admissible");
                eq(nominals[mode], clock.planningPeriodNs(),
                        "fewer than 30 physical scans cannot earn an estimate");
            }
            check(clock.record(actual + physicals[mode] * 30L,
                    nominals[mode], planning + nominals[mode] * 30L),
                    "thirtieth physical scan completes the baseline");
            eq(physicals[mode], clock.planningPeriodNs(),
                    "period comes from actual scans, not nominal planning rows");
            eq(planning, clock.anchorNs(), "planning phase never moves");
            eq(30L, clock.observedScans(), "same scan count at both refreshes");
            long expectedNominalBaseline = mode == 0 ?
                    250_000_000L : 500_000_000L;
            check(abs(30L * nominals[mode] - expectedNominalBaseline) < 30L,
                    "refresh-derived baseline is 250 ms at 120 Hz, 500 ms at 60 Hz");
        }
    }

    private static void unavailableAndBadRowsCannotEarnCalibration() {
        PhysicalPresentationClock clock = new PhysicalPresentationClock();
        check(!clock.available(), "empty clock has no physical phase");
        check(!clock.record(0L, 8_333_333L), "zero actual row is unavailable");
        check(!clock.record(-1L, 8_333_333L), "negative actual row is unavailable");
        check(!clock.record(1L, 0L), "unknown refresh cannot anchor");
        check(!clock.record(1L, 8_333_333L, 0L),
                "unknown planning phase cannot anchor");
        check(!clock.available(), "missing rows never create an anchor");
        long first = 20_000_000_000L;
        long physical = 8_329_228L;
        check(clock.record(first, 8_333_333L), "bad-gap fixture anchors");
        long last = first + physical * 29L;
        check(clock.record(last, 8_333_333L), "29-scan sparse interval accepted");
        check(!clock.record(last, 8_333_333L), "duplicate cannot earn scan count");
        check(!clock.record(last - 1L, 8_333_333L),
                "reversed row cannot earn scan count");
        check(!clock.record(last + 4_000_000L, 8_333_333L),
                "bad half-scan gap cannot earn scan count");
        eq(29L, clock.observedScans(), "rejections preserve the physical count");
        eq(last, clock.lastActualNs(), "rejections preserve the last actual row");
        eq(8_333_333L, clock.planningPeriodNs(),
                "unverified rows cannot trigger early calibration");
        check(clock.record(last + physical, 8_333_333L),
                "next valid independent row completes the baseline");
        eq(physical, clock.planningPeriodNs(), "bad gap did not distort estimate");
    }

    private static void freshEpochPartitionsPhaseButNotContinuousPhysicalFrequency() {
        PhysicalPresentationClock clock = new PhysicalPresentationClock();
        long first = 30_000_000_000L;
        long nominal = 8_333_333L;
        long physical = 8_329_228L;
        check(clock.record(first, nominal), "old epoch anchors");
        check(clock.record(first + physical * 29L, nominal),
                "old epoch remains below the estimation baseline");
        clock.beginPresentationEpoch();
        check(!clock.available(), "new epoch needs its own physical row");
        eq(0L, clock.observedScans(), "old incomplete scans cannot carry over");
        long newFirst = first + physical * 50L;
        check(clock.record(newFirst, nominal), "new epoch anchors separately");
        check(clock.record(newFirst + physical, nominal), "first new scan accepted");
        eq(1L, clock.observedScans(), "not 29 old scans plus one new scan");
        eq(physical, clock.planningPeriodNs(),
                "continuous independent physical rows may complete frequency baseline");
        eq(51L, clock.frequencyObservedScans(),
                "frequency counts actual gap; per-epoch phase still counts only one");
        check(clock.record(newFirst + physical * 30L, nominal),
                "new epoch independently completes 30 scans");
        eq(physical, clock.planningPeriodNs(), "independent new estimate accepted");
        clock.reset();
        check(!clock.available(), "full reset revokes phase and estimate");
        eq(0L, clock.planningPeriodNs(), "full reset retains no learned period");
        eq(0L, clock.frequencyObservedScans(), "full reset revokes frequency evidence");
    }

    private static void ambiguousEpochGapCannotEarnFrequencyScans() {
        PhysicalPresentationClock clock = learnedSixtyHertzClock();
        long last = clock.lastActualNs();
        long measured = clock.planningPeriodNs();
        clock.beginPresentationEpoch();
        check(!clock.record(last, 16_666_666L),
                "new logical epoch cannot accept the same physical row twice");
        check(!clock.available(), "duplicate cannot restore phase");
        long first = last + 8_000_000L;
        check(clock.record(first, 16_666_666L), "fresh phase after ambiguous gap");
        eq(0L, clock.frequencyObservedScans(), "half scan cannot join old baseline");
        eq(1L, clock.frequencyDiscontinuities(), "frequency discontinuity stays visible");
        eq(measured, clock.planningPeriodNs(), "gap cannot manufacture new frequency");
        check(clock.record(first + measured * 30L, 16_666_666L), "new measured baseline");
        eq(30L, clock.frequencyObservedScans(), "only new unambiguous scans counted");
        check(clock.record(first + measured * 31L, 8_333_333L), "mode change");
        eq(0L, clock.frequencyObservedScans(), "mode change discards old frequency scans");
        eq(8_333_333L, clock.planningPeriodNs(), "mode change discards old estimate");
    }

    private static void thorB14SparsePhysicalRowsBreakNominalClockDeadlock() {
        // Immutable b14 REPORTED actual observations, 2026-09-04 19:26:03.996:
        // externalTimingStartNs=296109682162352,
        // externalTimingEndNs=296110115282195, externalPhysicalClockScans=52.
        // JNI added a constant startup-derived offset to the raw present fences.
        // That offset cancels from this period estimate, but these are NOT raw
        // scan timestamps or phase qualification. Only these two reported times
        // were logged; do not manufacture the 12 intermediate completions.
        long firstActual = 296_109_682_162_352L;
        long lastActual = 296_110_115_282_195L;
        long nominal = 8_333_333L;
        PhysicalPresentationClock clock = new PhysicalPresentationClock();
        check(clock.record(firstActual, nominal), "recorded physical window start");
        check(clock.record(lastActual, nominal), "recorded sparse physical window end");
        eq(52L, clock.observedScans(), "independent gap resolves the recorded 52 scans");
        eq(433_119_843L, lastActual - firstActual, "immutable measured span");
        eq(8_329_228L, clock.planningPeriodNs(),
                "433-ms actual baseline must not wait for fixed 500-ms gate");

        // Twelfth rejected live token, 19:26:03.629. It still MUST reject the
        // already-issued nominal target; a new clock estimate never rewrites
        // an immutable request or changes the selector's 250-us tolerance.
        long now = 296_110_183_737_509L;
        long oldTarget = 296_110_215_540_709L;
        // The log gives only the nearest of seven platform candidates. Zero
        // slots explicitly mean unavailable; no other timeline is invented.
        long[] ids = {363_145_149L, 0L, 0L, 0L, 0L, 0L, 0L};
        long[] expected = {296_110_215_257_665L, 0L, 0L, 0L, 0L, 0L, 0L};
        long[] deadlines = {296_110_204_924_332L, 0L, 0L, 0L, 0L, 0L, 0L};
        check(CompositorFrameTimeline.selectRefreshSafeTarget(oldTarget,
                nominal, now, ids, expected, deadlines, ids.length) == null,
                "recorded -283044-ns mismatch still fails the unchanged gate");

        // Counterfactual host planning check, not a claim of device completion:
        // use the two reported rows above as a modeled lattice. Both reported
        // timestamps precede now; the platform token retains
        // its original identity and timestamps. The log does not expose when
        // these two actual rows were polled, so this is not a full replay.
        check(lastActual < now, "future physical rows cannot inform this model");
        PhysicalPresentationDeadline next =
                PhysicalPresentationDeadline.nextAlignedOutput(
                        296_110_182_924_333L, clock.anchorNs(),
                        clock.planningPeriodNs(), 1, now, 0L);
        CompositorFrameTimeline.Selection selected =
                CompositorFrameTimeline.selectRefreshSafeTarget(
                        next.contentPresentationTimeNs(),
                        clock.planningPeriodNs(), now,
                        ids, expected, deadlines, ids.length);
        check(selected != null && selected.vsyncId() == ids[0],
                "measured period can select the exact unmodified future token");
        check(abs(selected.signedTargetErrorNs()) < 30_000L,
                "recorded token and measured physical lattice agree within 30 us");
        eq(expected[0], selected.tokenExpectedPresentationTimeNs(),
                "token time is never relabelled to manufacture a match");
        eq(firstActual, clock.anchorNs(), "actual lattice anchor stays immutable");
        // The same log reports all 14 normalized endpoint times one scan late.
        // Missing raw values/offset prevent separating real lateness from a
        // normalization artifact. This correction does not qualify either.
    }

    private static void longBaselineLearnsPhysicalPeriodWithoutMovingAnchor() {
        PhysicalPresentationClock clock = new PhysicalPresentationClock();
        long nominal = 8_333_333L;
        long actual = 100_000_000_000L;
        long physical = 8_335_700L;
        check(clock.record(actual, nominal), "first physical row anchors clock");
        long anchor = clock.anchorNs();
        for (int scan = 1; scan <= 120; ++scan)
            check(clock.record(actual + physical * scan, nominal),
                    "drifted physical row accepted");
        eq(anchor, clock.anchorNs(), "anchor is immutable");
        eq(actual + physical * 120L, clock.lastActualNs(),
                "latest physical scan remains independently available");
        eq(physical, clock.planningPeriodNs(),
                "long baseline recovers physical oscillator period");
        eq(120L, clock.observedScans(), "all physical scans counted");
    }

    private static void skippedScansDoNotDistortTheEstimate() {
        PhysicalPresentationClock clock = new PhysicalPresentationClock();
        long nominal = 8_333_333L;
        long physical = 8_335_700L;
        long actual = 200_000_000_000L;
        check(clock.record(actual, nominal), "skip test anchor");
        long scan = 0L;
        for (int row = 0; row < 50; ++row) {
            scan += row % 5 == 0 ? 3L : 1L;
            check(clock.record(actual + physical * scan, nominal),
                    "multi-scan interval accepted");
        }
        eq(scan, clock.observedScans(), "missing rows become exact scan gaps");
        eq(physical, clock.planningPeriodNs(),
                "scan gaps do not bias the physical period");
    }

    private static void inconsistentRowsAndRefreshChangesFailClosedOrReset() {
        PhysicalPresentationClock clock = new PhysicalPresentationClock();
        long actual = 300_000_000_000L;
        check(clock.record(actual, 8_333_333L), "initial row accepted");
        check(!clock.record(actual, 8_333_333L),
                "duplicate actual timestamp rejected");
        check(!clock.record(actual + 4_000_000L, 8_333_333L),
                "off-lattice physical interval rejected");
        check(clock.record(actual + 20_000_000L, 10_000_000L),
                "refresh identity change starts a fresh clock");
        eq(actual + 20_000_000L, clock.anchorNs(),
                "new refresh gets a new immutable anchor");
        eq(10_000_000L, clock.planningPeriodNs(),
                "new refresh starts from its nominal period");
        clock.reset();
        check(!clock.available(), "reset removes clock authority");
    }

    private static void schedulerEpochCarriesPeriodButRequiresFreshPhysicalPhase() {
        PhysicalPresentationClock clock = learnedSixtyHertzClock();
        long learned = clock.planningPeriodNs();
        long nextActual = clock.lastActualNs() + learned;

        clock.beginPresentationEpoch();
        check(!clock.available(),
                "new epoch cannot plan until its own actual scan anchors phase");
        eq(learned, clock.planningPeriodNs(),
                "scheduler-only epoch retains proven panel oscillator period");
        eq(0L, clock.observedScans(),
                "new epoch starts an independent scan baseline");

        check(clock.record(nextActual, 16_666_666L),
                "first new-epoch actual scan establishes fresh phase");
        eq(nextActual, clock.anchorNs(),
                "new epoch uses its own actual scan as phase anchor");
        eq(learned, clock.planningPeriodNs(),
                "fresh phase keeps the inherited same-mode period");
    }

    private static void refreshChangeRejectsCarriedPeriod() {
        PhysicalPresentationClock clock = learnedSixtyHertzClock();
        clock.beginPresentationEpoch();
        long nextActual = 500_000_000_000L;
        check(clock.record(nextActual, 8_333_333L),
                "new physical refresh starts a fresh clock");
        eq(8_333_333L, clock.planningPeriodNs(),
                "refresh identity change discards inherited period");
        eq(nextActual, clock.anchorNs(),
                "refresh change anchors on its own actual scan");
    }

    private static void thorR203QueueTailUsesCarriedPeriodBeforeRelearn() {
        PhysicalPresentationClock clock = learnedSixtyHertzClock();
        clock.beginPresentationEpoch();
        long epochAnchor = 770_745_409_964L;
        long row3138Actual = 771_261_740_641L;
        check(clock.record(epochAnchor, 16_666_666L),
                "r203 epoch tail anchors on its first current actual scan");

        long carriedTarget = epochAnchor +
                31L * clock.planningPeriodNs();
        long nominalTarget = epochAnchor + 31L * 16_666_666L;
        long tolerance = Math.round(16_666_666L * 0.02);
        check(abs(row3138Actual - carriedTarget) < tolerance,
                "carried physical period keeps r203 inside strict slot gate");
        check(abs(row3138Actual - nominalTarget) > tolerance,
                "nominal restart reproduces r203 strict slot rejection");
    }

    private static PhysicalPresentationClock learnedSixtyHertzClock() {
        PhysicalPresentationClock clock = new PhysicalPresentationClock();
        long nominal = 16_666_666L;
        long physical = 16_658_994L;
        long actual = 400_000_000_000L;
        check(clock.record(actual, nominal), "carry test anchor");
        for (int scan = 1; scan <= 120; ++scan)
            check(clock.record(actual + physical * scan, nominal),
                    "carry test physical row accepted");
        eq(physical, clock.planningPeriodNs(),
                "carry fixture learns physical period");
        return clock;
    }

    private static void eq(long expected, long actual, String message) {
        if (expected != actual)
            throw new AssertionError(message + " expected=" + expected +
                    " actual=" + actual);
    }

    private static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }

    private static long abs(long value) {
        return value >= 0L ? value : -value;
    }
}
