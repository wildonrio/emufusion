import importlib.util
import unittest
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VERIFIER = ROOT / "unified-android/tools/verify_rife_frame_generation_timing.py"
SPEC = importlib.util.spec_from_file_location("rife_timing", VERIFIER)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def line(**overrides):
    values = {
        "generator": 4,
        "role": "primary",
        "displayId": 0,
        "externalBackend": "RIFE",
        "source": "30.000",
        "target": "59.186",
        "panel": "118.371212",
        "panelMeasured": 1,
        "swap": "59.100",
        "schedulerEpoch": 9,
        "schedulerUnderrun": 0,
        "physicalAvailable": 1,
        "physicalBackend": "vulkan",
        "externalAppOwned": 0,
        "physical": "59.186",
        "physicalQualified": 0,
        "physicalSamples": 130,
        "physicalPresented": 130,
        "physicalDropped": 0,
        "physicalUnavailable": 0,
        "physicalPending": 1,
        "externalSubmitted": 131,
        "externalFrameTimelineCallbacks": 240,
        "externalFrameTimelineMatched": 200,
        "externalFrameTimelineUnavailable": 0,
        "externalFrameTimelineCommitted": 131,
        "externalFrameTimelineNativeCallbackSequence": 239,
        "externalFrameTimelineNativeFrameTimeNs": 12_345_678_000,
        "externalFrameTimelineErrorMaxNs": 25_000,
        "externalFrameTimelineProbeLive": 0,
        "externalFrameTimelineProbeNoLive": 0,
        "externalFrameTimelineProbeErrorSignedMinNs": 0,
        "externalFrameTimelineProbeErrorSignedMaxNs": 0,
        "externalFrameTimelineProbeErrorSignedLastNs": 0,
        "externalPhysicalEndpoint": 65,
        "externalPhysicalGenerated": 65,
        "externalTimingQualified": 1,
        "externalTimingEpoch": 9,
        "externalTimingWindow": 0,
        "externalTimingDroppedBaseline": 0,
        "externalTimingUnavailableBaseline": 0,
        "externalTimingSamples": 130,
        "externalTimingEndpoint": 65,
        "externalTimingGenerated": 65,
        "externalTimingStartNs": 1_000_000_000_000,
        "externalTimingEndNs": 1_002_179_584_000,
        "externalTimingScans": 2,
        "externalTimingPipelineScans": 0,
        "externalTimingRefreshNs": 8_448_000,
        "externalDeadlineMisses": 0,
        "externalDesiredSlotMisses": 0,
        "externalEarliestPresentMisses": 0,
        "externalEarlyPresentViolations": 0,
        "externalEarlySlotMisses": 0,
        "externalLateSlotMisses": 0,
        "externalPresentMarginMinNs": 300_000,
        "externalPresentMarginP05Ns": 350_000,
        "externalPresentMarginP50Ns": 600_000,
        "externalPresentMarginP95Ns": 900_000,
        "externalPresentMarginMaxNs": 1_000_000,
        "externalPresentMarginLastNs": 700_000,
        "externalLateSlotMarginMinNs": 0,
        "externalLateSlotMarginMaxNs": 0,
        "externalEnqueueMaxNs": 2_000_000,
        "externalGpuMaxNs": 6_000_000,
        "externalCombinedP95Ns": 7_500_000,
        "externalCombinedMaxNs": 8_000_000,
        "externalBindMaxNs": 0,
        "externalSwapMaxNs": 0,
        "externalGpuBudgetMisses": 0,
        "externalSlotErrorMaxNs": 200_000,
        "externalSlotErrorSignedMinNs": -200_000,
        "externalSlotErrorSignedMaxNs": 150_000,
        "externalSlotErrorSignedLastNs": 20_000,
        "externalPhysicalClockPeriodNs": 8_448_000,
        "externalPhysicalClockScans": 258,
        "externalPhysicalClockCalibrated": 1,
        "externalPhysicalClockCalibrationPresents": 4,
        "externalPhaseMin": "0.250000",
        "externalPhaseMax": "0.750000",
        "externalContentNumericPassed": 1,
        "externalContentEpoch": 9,
        "externalContentProofs": 130,
        "externalContentEndpoints": 65,
        "externalContentGenerated": 65,
        "externalContentMovingGenerated": 50,
        "externalContentDistinctMovingGenerated": 50,
        "externalContentSceneCutRisk": 0,
        "externalUnsafePairs": 0,
        "externalContentEndpointFailures": 0,
        "externalContentEqualsLeft": 0,
        "externalContentEqualsRight": 0,
        "externalContentAnalysisMaxNs": 200_000,
        "externalContentEndpointMadMaxPpm": 200_000,
        "externalContentHistogramMaxPpm": 100_000,
        "externalContentOutputLeftMadMaxPpm": 150_000,
        "externalContentOutputRightMadMaxPpm": 160_000,
        "externalContentManualPassed": 0,
    }
    values.update(overrides)
    return "I/DisplayFrameGenerator: App swap cadence " + " ".join(
        f"{key}={value}" for key, value in values.items())


def app_owned_line(**overrides):
    values = {
        "physicalBackend": "egl-app-owned",
        "externalAppOwned": 1,
        "externalFrameTimelineCallbacks": 240,
        "externalFrameTimelineMatched": 0,
        "externalFrameTimelineUnavailable": 0,
        "externalFrameTimelineCommitted": 0,
        "externalFrameTimelineNativeCallbackSequence": 0,
        "externalFrameTimelineNativeFrameTimeNs": 0,
        "externalFrameTimelineErrorMaxNs": 0,
        "externalFrameTimelineProbeLive": 0,
        "externalFrameTimelineProbeNoLive": 0,
        "externalFrameTimelineProbeErrorSignedMinNs": 0,
        "externalFrameTimelineProbeErrorSignedMaxNs": 0,
        "externalFrameTimelineProbeErrorSignedLastNs": 0,
        "externalTimingWindow": 1,
        "externalTimingDroppedBaseline": 0,
        "externalTimingUnavailableBaseline": 0,
        "externalPresentMarginMinNs": 0,
        "externalPresentMarginP05Ns": 0,
        "externalPresentMarginP50Ns": 0,
        "externalPresentMarginP95Ns": 0,
        "externalPresentMarginMaxNs": 0,
        "externalPresentMarginLastNs": 0,
        "externalLateSlotMarginMinNs": 0,
        "externalLateSlotMarginMaxNs": 0,
        "externalEnqueueMaxNs": 300_000,
        "externalBindMaxNs": 300_000,
        "externalSwapMaxNs": 400_000,
        "externalGpuBudgetMisses": 0,
        "externalCombinedP95Ns": 600_000,
        "externalCombinedMaxNs": 700_000,
        "externalPhysicalClockCalibrationPresents": 130,
        "externalContentProofs": 65,
        "externalContentEndpoints": 0,
        "externalContentGenerated": 65,
    }
    values.update(overrides)
    return line(**values)


class RifeFrameGenerationTimingTest(unittest.TestCase):
    def test_blocking_swap_duration_does_not_replace_deadline_or_scan_evidence(self):
        # Device observed 12.2ms blocking swap at 120Hz, with earlier queue
        # submission and on-time scanout. A long duration alone is not judder.
        values = dict(externalSwapMaxNs=20_000_000,
                      externalCombinedMaxNs=20_000_001)
        self.assertTrue(MODULE.verify_timing(app_owned_line(**values))["timingPassed"])
        for failure in (dict(externalDeadlineMisses=1),
                        dict(externalDesiredSlotMisses=1, externalLateSlotMisses=1),
                        dict(schedulerUnderrun=1),
                        dict(externalGpuBudgetMisses=1)):
            with self.subTest(failure=failure):
                with self.assertRaises(MODULE.EvidenceError):
                    MODULE.verify_timing(app_owned_line(**values, **failure))
        with self.assertRaisesRegex(MODULE.EvidenceError, "critical path accounting"):
            MODULE.verify_timing(app_owned_line(externalCombinedMaxNs=800_000))

    def test_chunked_snapshot_roundtrip_and_fail_closed_damage(self):
        snapshot = MODULE.PREFIX + app_owned_line().split(MODULE.PREFIX, 1)[1]
        crc = zlib.crc32(snapshot.encode())
        pieces = [snapshot[i:i+700] for i in range(0, len(snapshot), 700)]
        parts = [f'CadenceSnapshot id=42:4:1 part={i+1}/{len(pieces)} crc={crc} data={s}'
                 for i, s in enumerate(pieces)]
        self.assertEqual(MODULE.verify_timing('\n'.join(parts)),
                         MODULE.verify_timing(snapshot))
        for damaged in (parts[:-1], parts[1:], parts[::-1],
                        parts + parts, [parts[0] + 'x'] + parts[1:],
                        parts[:1] + parts[:1] + parts[1:]):
            with self.subTest(damaged=damaged[0][:70]):
                with self.assertRaises(MODULE.EvidenceError):
                    MODULE.verify_timing('\n'.join(damaged))
        interleaved = []
        for part in parts:
            interleaved.extend((part, 'unrelated log entry',
                                part.replace('id=42:4:1', 'id=42:4:2')))
        self.assertEqual(MODULE.snapshot_lines('\n'.join(interleaved)),
                         [snapshot, snapshot])

    def test_missing_outputs_fail_independently_of_runtime_qualified_flag(self):
        for factory in (line, app_owned_line):
            for count in (-1, 1, 299):
                with self.subTest(factory=factory.__name__, count=count):
                    with self.assertRaisesRegex(MODULE.EvidenceError,
                                                "scheduler underrun"):
                        MODULE.verify_timing(factory(schedulerUnderrun=count))
            with self.assertRaisesRegex(MODULE.EvidenceError, "scheduler underrun"):
                MODULE.verify_timing(factory(schedulerUnderrun=1) + '\n' + factory())

    def test_exact_timing_component_passes_but_never_claims_visual_qualification(self):
        report = MODULE.verify_timing(line())
        self.assertTrue(report["timingPassed"])
        self.assertTrue(report["numericContentPassed"])
        self.assertFalse(report["contentQualityPassed"])
        self.assertFalse(report["qualified"])
        self.assertEqual(report["deadlineBudgetNs"], 14_896_000)
        self.assertEqual(report["handledUnsafePairs"], 0)

    def test_latest_epoch_must_be_qualified_and_identity_matched(self):
        with self.assertRaisesRegex(MODULE.EvidenceError, "another presentation epoch"):
            MODULE.verify_timing(line(externalTimingEpoch=8))
        with self.assertRaisesRegex(MODULE.EvidenceError,
                                    "presentation pipeline"):
            MODULE.verify_timing(line(externalTimingPipelineScans=1))
        with self.assertRaisesRegex(MODULE.EvidenceError, "not qualified"):
            MODULE.verify_timing("\n".join((line(), line(
                schedulerEpoch=10, externalTimingEpoch=10,
                externalTimingQualified=0, physicalQualified=0))))
        with self.assertRaisesRegex(MODULE.EvidenceError, "latest.*not RIFE"):
            MODULE.verify_timing("\n".join((line(), line(
                physicalBackend="egl", physicalQualified=0,
                externalTimingQualified=0))))
        with self.assertRaisesRegex(MODULE.EvidenceError,
                                    "not the RIFE backend"):
            MODULE.verify_timing(app_owned_line(externalBackend="Direct"))
        with self.assertRaisesRegex(MODULE.EvidenceError,
                                    "no frame-generation timing records"):
            MODULE.verify_timing(app_owned_line(), role="secondary",
                                 display_id=4)

    def test_app_owned_egl_timing_passes_without_fabricating_wsi_fields(self):
        report = MODULE.verify_timing(app_owned_line())
        self.assertTrue(report["timingPassed"])
        self.assertTrue(report["numericContentPassed"])
        self.assertTrue(report["appOwnedPresentation"])
        self.assertEqual(report["kind"], "rife-app-owned-timing-only")
        self.assertEqual(report["contentProofs"], 65)
        self.assertEqual(report["deadlineBudgetNs"], 16_896_000)

    def test_runtime_span_and_raw_surfaceflinger_overlap_are_required(self):
        start = 2_000_000_000_000
        interval = 16_896_000
        samples = 720
        end = start + (samples - 1) * interval
        physical = [start + index * interval for index in range(128)]
        report = MODULE.verify_timing(app_owned_line(
            physicalPresented=samples, physicalPending=1,
            externalSubmitted=samples + 1,
            externalPhysicalEndpoint=samples // 2,
            externalPhysicalGenerated=samples // 2,
            externalTimingSamples=samples,
            externalTimingEndpoint=samples // 2,
            externalTimingGenerated=samples // 2,
            externalTimingStartNs=start, externalTimingEndNs=end,
            externalPhysicalClockScans=(samples - 1) * 2,
            externalPhysicalClockCalibrationPresents=samples,
            externalContentProofs=samples // 2,
            externalContentGenerated=samples // 2),
            role="primary", display_id=0,
            actual_present_timestamps=physical,
            minimum_span_ns=MODULE.MIN_RUNTIME_SPAN_NS)
        self.assertEqual(report["surfaceFlingerRawOverlapFrames"], 128)
        with self.assertRaisesRegex(MODULE.EvidenceError, "too short"):
            MODULE.verify_timing(app_owned_line(),
                minimum_span_ns=MODULE.MIN_RUNTIME_SPAN_NS)
        with self.assertRaisesRegex(MODULE.EvidenceError,
                                    "SurfaceFlinger overlap"):
            MODULE.verify_timing(app_owned_line(
                physicalPresented=samples, physicalPending=1,
                externalSubmitted=samples + 1,
                externalPhysicalEndpoint=samples // 2,
                externalPhysicalGenerated=samples // 2,
                externalTimingSamples=samples,
                externalTimingEndpoint=samples // 2,
                externalTimingGenerated=samples // 2,
                externalTimingStartNs=start, externalTimingEndNs=end,
                externalPhysicalClockScans=(samples - 1) * 2,
                externalPhysicalClockCalibrationPresents=samples,
                externalContentProofs=samples // 2,
                externalContentGenerated=samples // 2),
                actual_present_timestamps=[end + interval * index
                                           for index in range(128)],
                minimum_span_ns=MODULE.MIN_RUNTIME_SPAN_NS)

    def test_app_owned_egl_identity_and_critical_path_fail_closed(self):
        with self.assertRaisesRegex(MODULE.EvidenceError,
                                    "ownership identity"):
            MODULE.verify_timing(app_owned_line(externalAppOwned=0))
        with self.assertRaisesRegex(MODULE.EvidenceError,
                                    "SurfaceControl frame timeline"):
            MODULE.verify_timing(app_owned_line(
                externalFrameTimelineMatched=1))
        with self.assertRaisesRegex(MODULE.EvidenceError,
                                    "display-callback evidence"):
            MODULE.verify_timing(app_owned_line(
                externalFrameTimelineCallbacks=0))
        with self.assertRaisesRegex(MODULE.EvidenceError,
                                    "unavailable WSI present margins"):
            MODULE.verify_timing(app_owned_line(
                externalPresentMarginMaxNs=1))
        with self.assertRaisesRegex(MODULE.EvidenceError,
                                    "bind/swap critical path"):
            MODULE.verify_timing(app_owned_line(
                externalBindMaxNs=299_999))
        with self.assertRaisesRegex(MODULE.EvidenceError,
                                    "adjacent-endpoint GPU budget"):
            MODULE.verify_timing(app_owned_line(
                externalGpuBudgetMisses=1))
        with self.assertRaisesRegex(MODULE.EvidenceError,
                                    "endpoint span"):
            MODULE.verify_timing(app_owned_line(
                externalGpuMaxNs=33_333_334))
        with self.assertRaisesRegex(MODULE.EvidenceError,
                                    "bound to its timing epoch"):
            MODULE.verify_timing(app_owned_line(
                externalPhysicalClockCalibrationPresents=129))

    def test_app_owned_content_proves_only_physically_presented_generated_rows(self):
        with self.assertRaisesRegex(MODULE.EvidenceError,
                                    "app-owned generated/content"):
            MODULE.verify_timing(app_owned_line(
                externalContentEndpoints=1,
                externalContentProofs=66))
        with self.assertRaisesRegex(MODULE.EvidenceError,
                                    "app-owned generated/content"):
            MODULE.verify_timing(app_owned_line(
                externalContentGenerated=64,
                externalContentProofs=64))

    def test_submission_physical_and_kind_conservation_are_exact(self):
        with self.assertRaisesRegex(MODULE.EvidenceError, "submission/physical"):
            MODULE.verify_timing(line(externalSubmitted=132))
        with self.assertRaisesRegex(MODULE.EvidenceError, "frame-timeline"):
            MODULE.verify_timing(line(externalFrameTimelineCommitted=130))
        with self.assertRaisesRegex(MODULE.EvidenceError, "frame-timeline"):
            MODULE.verify_timing(line(
                externalFrameTimelineCallbacks=199,
                externalFrameTimelineMatched=200))
        with self.assertRaisesRegex(MODULE.EvidenceError, "frame-timeline"):
            MODULE.verify_timing(line(
                externalFrameTimelineNativeCallbackSequence=0))
        with self.assertRaisesRegex(MODULE.EvidenceError, "frame-timeline"):
            MODULE.verify_timing(line(
                externalFrameTimelineNativeFrameTimeNs=0))
        with self.assertRaisesRegex(MODULE.EvidenceError,
                                    "miss diagnostics"):
            MODULE.verify_timing(line(
                externalFrameTimelineUnavailable=2,
                externalFrameTimelineProbeLive=1,
                externalFrameTimelineProbeNoLive=0,
                externalFrameTimelineProbeErrorSignedMinNs=8_000_000,
                externalFrameTimelineProbeErrorSignedMaxNs=8_000_000,
                externalFrameTimelineProbeErrorSignedLastNs=8_000_000))
        with self.assertRaisesRegex(MODULE.EvidenceError,
                                    "nearest-slot diagnostics"):
            MODULE.verify_timing(line(
                externalFrameTimelineUnavailable=1,
                externalFrameTimelineProbeLive=1,
                externalFrameTimelineProbeErrorSignedMinNs=8_000_000,
                externalFrameTimelineProbeErrorSignedMaxNs=9_000_000,
                externalFrameTimelineProbeErrorSignedLastNs=10_000_000))
        with self.assertRaisesRegex(MODULE.EvidenceError,
                                    "false slot"):
            MODULE.verify_timing(line(
                externalFrameTimelineUnavailable=1,
                externalFrameTimelineProbeNoLive=1,
                externalFrameTimelineProbeErrorSignedLastNs=1))
        with self.assertRaisesRegex(MODULE.EvidenceError, "target-window"):
            MODULE.verify_timing(line(externalTimingGenerated=64))
        with self.assertRaisesRegex(MODULE.EvidenceError, "lifetime physical"):
            MODULE.verify_timing(line(externalPhysicalGenerated=64))

    def test_prior_direct_unavailable_is_rebased_but_current_epoch_is_clean(self):
        prior = app_owned_line(
            schedulerEpoch=8, externalTimingEpoch=8,
            externalTimingWindow=3,
            externalTimingQualified=0, externalContentEpoch=8,
            physicalPresented=124, physicalPending=0,
            physicalUnavailable=6, externalSubmitted=130,
            externalTimingUnavailableBaseline=6,
            externalPhysicalEndpoint=62, externalPhysicalGenerated=62)
        current = app_owned_line(
            externalTimingWindow=4, physicalUnavailable=6,
            externalTimingUnavailableBaseline=6, externalSubmitted=137)
        report = MODULE.verify_timing("\n".join((prior, current)))
        self.assertTrue(report["timingPassed"])

        failed_current = app_owned_line(
            externalTimingWindow=4, physicalUnavailable=7,
            externalTimingUnavailableBaseline=6, externalSubmitted=138)
        with self.assertRaisesRegex(MODULE.EvidenceError,
                                    "selected epoch contains"):
            MODULE.verify_timing("\n".join((prior, failed_current)))

        with self.assertRaisesRegex(MODULE.EvidenceError,
                                    "selected epoch contains"):
            MODULE.verify_timing(app_owned_line(
                physicalUnavailable=1,
                externalTimingUnavailableBaseline=0,
                externalSubmitted=132))

        recovered_same_scheduler_epoch = app_owned_line(
            physicalUnavailable=7,
            externalTimingWindow=5,
            externalTimingUnavailableBaseline=7,
            externalSubmitted=138)
        report = MODULE.verify_timing("\n".join(
            (prior, failed_current, recovered_same_scheduler_epoch)))
        self.assertTrue(report["timingPassed"])

        with self.assertRaisesRegex(MODULE.EvidenceError,
                                    "outcome baseline"):
            MODULE.verify_timing(app_owned_line(
                physicalUnavailable=1,
                externalTimingUnavailableBaseline=2,
                externalSubmitted=132))

        with self.assertRaisesRegex(MODULE.EvidenceError,
                                    "window identity regressed"):
            MODULE.verify_timing("\n".join((
                app_owned_line(externalTimingWindow=3),
                app_owned_line(externalTimingWindow=2))))

    def test_long_epoch_keeps_rolling_cadence_separate_from_kind_ledger(self):
        timing_start = 3_000_000_000_000
        timing_interval = 3 * 8_333_463
        timing_samples = 1_226
        report = MODULE.verify_timing(line(
            source="20.000", target="40.000", panel="119.995421",
            swap="39.998", physical="40.000", physicalSamples=256,
            physicalPresented=7_253, physicalPending=1,
            externalSubmitted=7_254,
            externalFrameTimelineCallbacks=9_000,
            externalFrameTimelineMatched=8_000,
            externalFrameTimelineCommitted=7_254,
            externalPhysicalEndpoint=6_640,
            externalPhysicalGenerated=613,
            externalTimingSamples=timing_samples,
            externalTimingEndpoint=613,
            externalTimingGenerated=613,
            externalTimingScans=3,
            externalTimingRefreshNs=8_333_463,
            externalTimingStartNs=timing_start,
            externalTimingEndNs=(timing_start +
                                 (timing_samples - 1) * timing_interval),
            externalPhysicalClockPeriodNs=8_333_463,
            externalPhysicalClockScans=3_678,
            externalPhaseMin="0.500000", externalPhaseMax="0.500000",
            externalContentProofs=1_226,
            externalContentEndpoints=613,
            externalContentGenerated=613,
            externalContentMovingGenerated=530,
            externalContentDistinctMovingGenerated=530,
        ))
        self.assertEqual(report["physicalSamples"], 1_226)
        self.assertEqual(report["physicalGenerated"], 613)

        with self.assertRaisesRegex(MODULE.EvidenceError,
                                    "cadence ring has insufficient"):
            MODULE.verify_timing(line(physicalSamples=16))

    def test_deadline_slot_and_phase_fail_closed(self):
        with self.assertRaisesRegex(MODULE.EvidenceError, "work or physical"):
            MODULE.verify_timing(line(externalDeadlineMisses=1))
        with self.assertRaisesRegex(MODULE.EvidenceError, "early physical cutoff"):
            MODULE.verify_timing(line(externalCombinedMaxNs=14_896_001))
        with self.assertRaisesRegex(MODULE.EvidenceError, "desired slot tolerance"):
            MODULE.verify_timing(line(externalSlotErrorMaxNs=400_000))
        with self.assertRaisesRegex(MODULE.EvidenceError,
                                    "physical-present lower bound"):
            MODULE.verify_timing(line(externalEarliestPresentMisses=1))
        with self.assertRaisesRegex(MODULE.EvidenceError, "direction accounting"):
            MODULE.verify_timing(line(externalLateSlotMisses=1))
        with self.assertRaisesRegex(MODULE.EvidenceError, "signed physical"):
            MODULE.verify_timing(line(externalSlotErrorSignedLastNs=300_000))
        with self.assertRaisesRegex(MODULE.EvidenceError, "scan clock"):
            MODULE.verify_timing(line(externalPhysicalClockScans=10))
        with self.assertRaisesRegex(MODULE.EvidenceError, "calibration boundary"):
            MODULE.verify_timing(line(externalPhysicalClockCalibrated=0))
        with self.assertRaisesRegex(MODULE.EvidenceError, "margin distribution"):
            MODULE.verify_timing(line(externalPresentMarginP05Ns=200_000))
        with self.assertRaisesRegex(MODULE.EvidenceError, "without a late slot"):
            MODULE.verify_timing(line(externalLateSlotMarginMaxNs=1))
        with self.assertRaisesRegex(MODULE.EvidenceError, "phases"):
            MODULE.verify_timing(line(externalPhaseMin="0.000000"))

    def test_content_proof_is_epoch_bound_and_fail_closed(self):
        with self.assertRaisesRegex(MODULE.EvidenceError, "unavailable or stale"):
            MODULE.verify_timing(line(externalContentEpoch=8))
        with self.assertRaisesRegex(MODULE.EvidenceError, "conservation"):
            MODULE.verify_timing(line(externalContentGenerated=64))
        with self.assertRaisesRegex(MODULE.EvidenceError, "duplicated"):
            MODULE.verify_timing(line(externalContentDistinctMovingGenerated=49))
        with self.assertRaisesRegex(MODULE.EvidenceError, "scene-cut"):
            MODULE.verify_timing(line(externalContentSceneCutRisk=1))
        with self.assertRaisesRegex(MODULE.EvidenceError, "nonblocking"):
            MODULE.verify_timing(line(externalContentAnalysisMaxNs=1_000_001))
        with self.assertRaisesRegex(MODULE.EvidenceError, "final visual"):
            MODULE.verify_timing(line(physicalQualified=1,
                                      externalContentManualPassed=1))

    def test_detected_unsafe_pairs_are_reported_and_never_regress(self):
        report = MODULE.verify_timing(line(externalUnsafePairs=3))
        self.assertEqual(report["handledUnsafePairs"], 3)
        with self.assertRaisesRegex(MODULE.EvidenceError, "counter is invalid"):
            MODULE.verify_timing(line(externalUnsafePairs=-1))
        with self.assertRaisesRegex(MODULE.EvidenceError, "counter regressed"):
            MODULE.verify_timing("\n".join((
                line(externalUnsafePairs=3),
                line(externalUnsafePairs=2),
            )))

    def test_long_campaign_keeps_independent_segments_and_totals_one_minute(self):
        def segment(index, start_ns):
            span_ns = 16_000_000_000
            return {
                "generator": 7, "role": "primary", "displayId": 0,
                "presentationEpoch": 100 + index,
                "timingWindow": 200 + index,
                "timingStartNs": start_ns,
                "timingEndNs": start_ns + span_ns,
                "sourceHz": 60.0, "targetHz": 120.0,
                "actualPhysicalHz": 119.99, "scansPerOutput": 1,
                "timingPassed": True, "numericContentPassed": True,
                "contentQualityPassed": False,
                "appOwnedPresentation": True,
                "surfaceFlingerRawOverlapFrames": 120,
                "physicalSamples": 1_920,
                "physicalEndpoints": 960,
                "physicalGenerated": 960,
                "contentProofs": 960,
                "movingGeneratedProofs": 960,
            }

        reports = [segment(index, 1_000_000_000_000 + index * 20_000_000_000)
                   for index in range(4)]
        campaign = MODULE.verify_campaign(reports)
        self.assertTrue(campaign["timingPassed"])
        self.assertFalse(campaign["qualified"])
        self.assertEqual(campaign["segmentCount"], 4)
        self.assertEqual(campaign["totalMovingSpanNs"], 64_000_000_000)
        self.assertEqual(campaign["physicalGenerated"], 3_840)

        with self.assertRaisesRegex(MODULE.EvidenceError, "too few"):
            MODULE.verify_campaign(reports[:2])
        with self.assertRaisesRegex(MODULE.EvidenceError, "span is too short"):
            MODULE.verify_campaign(reports[:3])

        duplicate = [dict(value) for value in reports]
        duplicate[1]["presentationEpoch"] = duplicate[0]["presentationEpoch"]
        duplicate[1]["timingWindow"] = duplicate[0]["timingWindow"]
        with self.assertRaisesRegex(MODULE.EvidenceError, "reused"):
            MODULE.verify_campaign(duplicate)

        overlap = [dict(value) for value in reports]
        overlap[1]["timingStartNs"] = overlap[0]["timingEndNs"] - 1
        overlap[1]["timingEndNs"] = overlap[1]["timingStartNs"] + \
                16_000_000_000
        with self.assertRaisesRegex(MODULE.EvidenceError, "overlaps"):
            MODULE.verify_campaign(overlap)

        changed = [dict(value) for value in reports]
        changed[-1]["targetHz"] = 60.0
        with self.assertRaisesRegex(MODULE.EvidenceError, "cadence identity"):
            MODULE.verify_campaign(changed)

        no_overlap = [dict(value) for value in reports]
        no_overlap[-1]["surfaceFlingerRawOverlapFrames"] = 0
        with self.assertRaisesRegex(MODULE.EvidenceError,
                                    "SurfaceFlinger overlap"):
            MODULE.verify_campaign(no_overlap)

        no_motion = [dict(value) for value in reports]
        no_motion[-1]["movingGeneratedProofs"] = 0
        with self.assertRaisesRegex(MODULE.EvidenceError, "moving generated"):
            MODULE.verify_campaign(no_motion)

    def test_archived_campaign_partitions_process_local_identities_by_session(self):
        def segment(session, index, start_ns):
            return {
                "captureSession": session,
                # Generator/epoch/window are process-local and may repeat in
                # another independently bound capture session.
                "generator": 1, "role": "primary", "displayId": 0,
                "presentationEpoch": 100 + index,
                "timingWindow": 200 + index,
                "timingStartNs": start_ns,
                "timingEndNs": start_ns + 16_000_000_000,
                "sourceHz": 60.0, "targetHz": 120.0,
                "actualPhysicalHz": 119.99, "scansPerOutput": 1,
                "timingPassed": True, "numericContentPassed": True,
                "contentQualityPassed": False,
                "appOwnedPresentation": True,
                "surfaceFlingerRawOverlapFrames": 120,
                "physicalSamples": 1_920,
                "physicalEndpoints": 960,
                "physicalGenerated": 960,
                "contentProofs": 960,
                "movingGeneratedProofs": 960,
            }

        reports = [
            segment("session-a", 0, 1_000_000_000),
            segment("session-a", 1, 20_000_000_000),
            # Simulate a reboot/process restart: both monotonic time and the
            # process-local timing identity repeat, but the archive session
            # binding is distinct.
            segment("session-b", 0, 1_000_000_000),
            segment("session-b", 1, 20_000_000_000),
        ]
        campaign = MODULE.verify_campaign(reports)
        self.assertEqual(campaign["captureSessionCount"], 2)
        self.assertEqual(campaign["totalMovingSpanNs"], 64_000_000_000)

        mixed = [dict(value) for value in reports]
        mixed[-1].pop("captureSession")
        with self.assertRaisesRegex(MODULE.EvidenceError,
                                    "bound and unbound"):
            MODULE.verify_campaign(mixed)

        overlap = [dict(value) for value in reports]
        overlap[1]["timingStartNs"] = overlap[0]["timingEndNs"] - 1
        overlap[1]["timingEndNs"] = overlap[1]["timingStartNs"] + \
                16_000_000_000
        with self.assertRaisesRegex(MODULE.EvidenceError, "overlaps"):
            MODULE.verify_campaign(overlap)

    def test_missing_duplicate_or_nonfinite_fields_reject(self):
        malformed = line().replace(" externalGpuMaxNs=6000000", "")
        with self.assertRaisesRegex(MODULE.EvidenceError, "missing"):
            MODULE.verify_timing(malformed)
        with self.assertRaisesRegex(MODULE.EvidenceError, "duplicate"):
            MODULE.verify_timing(line() + " externalGpuMaxNs=6000000")
        with self.assertRaisesRegex(MODULE.EvidenceError, "non-finite"):
            MODULE.verify_timing(line(physical="nan"))


if __name__ == "__main__":
    unittest.main()
