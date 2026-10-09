#!/usr/bin/env python3

import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "verify_frame_generation_evidence.py"
SPEC = importlib.util.spec_from_file_location("frame_generation_verifier", MODULE_PATH)
VERIFIER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(VERIFIER)


LABELS = (
    ("latticeRegionSamples", "lattice_samples"),
    ("latticeBackwardCoherentRegions", "lattice_backward_coherent"),
    ("latticeForwardCoherentRegions", "lattice_forward_coherent"),
    ("latticeBackwardBoundaryRegions", "lattice_backward_boundary"),
    ("latticeForwardBoundaryRegions", "lattice_forward_boundary"),
    ("latticeBackwardCoherentBoundaryRegions", "lattice_backward_coherent_boundary"),
    ("latticeForwardCoherentBoundaryRegions", "lattice_forward_coherent_boundary"),
    ("latticeBackwardCoherentRegionCount", "lattice_backward_count"),
    ("latticeForwardCoherentRegionCount", "lattice_forward_count"),
    ("latticeBackwardBoundaryRegionCount", "lattice_backward_boundary_count"),
    ("latticeForwardBoundaryRegionCount", "lattice_forward_boundary_count"),
    ("latticeBackwardCoherentBoundaryRegionCount", "lattice_backward_coherent_boundary_count"),
    ("latticeForwardCoherentBoundaryRegionCount", "lattice_forward_coherent_boundary_count"),
    ("latticeBackwardPeakSupport", "lattice_backward_peak_support"),
    ("latticeForwardPeakSupport", "lattice_forward_peak_support"),
    ("regionalFlowRegionSamples", "regional_samples"),
    ("regionalBackwardSupportedRegions", "regional_backward_supported"),
    ("regionalForwardSupportedRegions", "regional_forward_supported"),
    ("regionalBackwardNeighborRegions", "regional_backward_neighbor"),
    ("regionalForwardNeighborRegions", "regional_forward_neighbor"),
    ("regionalBackwardConstantNeighborRegions", "regional_backward_constant_neighbor"),
    ("regionalForwardConstantNeighborRegions", "regional_forward_constant_neighbor"),
    ("regionalBackwardGradientNeighborRegions", "regional_backward_gradient_neighbor"),
    ("regionalForwardGradientNeighborRegions", "regional_forward_gradient_neighbor"),
    ("regionalBackwardAcceptedRegions", "regional_backward_accepted"),
    ("regionalForwardAcceptedRegions", "regional_forward_accepted"),
    ("regionalBackwardAcceptedBoundaryRegions", "regional_backward_accepted_boundary"),
    ("regionalForwardAcceptedBoundaryRegions", "regional_forward_accepted_boundary"),
    ("regionalBackwardCycleAcceptedRegions", "regional_backward_cycle"),
    ("regionalForwardCycleAcceptedRegions", "regional_forward_cycle"),
    ("regionalBackwardAcceptedRegionCount", "regional_backward_count"),
    ("regionalForwardAcceptedRegionCount", "regional_forward_count"),
    ("regionalBackwardAcceptedBoundaryRegionCount", "regional_backward_accepted_boundary_count"),
    ("regionalForwardAcceptedBoundaryRegionCount", "regional_forward_accepted_boundary_count"),
    ("regionalBackwardCycleAcceptedRegionCount", "regional_backward_cycle_count"),
    ("regionalForwardCycleAcceptedRegionCount", "regional_forward_cycle_count"),
    ("regionalBackwardSupportedRegionCount", "regional_backward_supported_count"),
    ("regionalForwardSupportedRegionCount", "regional_forward_supported_count"),
    ("regionalBackwardNeighborRegionCount", "regional_backward_neighbor_count"),
    ("regionalForwardNeighborRegionCount", "regional_forward_neighbor_count"),
    ("regionalBackwardConstantNeighborRegionCount", "regional_backward_constant_neighbor_count"),
    ("regionalForwardConstantNeighborRegionCount", "regional_forward_constant_neighbor_count"),
    ("regionalBackwardGradientNeighborRegionCount", "regional_backward_gradient_neighbor_count"),
    ("regionalForwardGradientNeighborRegionCount", "regional_forward_gradient_neighbor_count"),
    ("regionalBackwardPeakSupport", "regional_backward_support"),
    ("regionalForwardPeakSupport", "regional_forward_support"),
    ("regionalBackwardPeakConfidence", "regional_backward_confidence"),
    ("regionalForwardPeakConfidence", "regional_forward_confidence"),
    ("activeMotionVectors", "active"),
    ("confidentMotionVectors", "confident"),
    ("motionVectorCells", "cells"),
    ("proofSamples", "proof"),
    ("syntheticProofSamples", "synthetic"),
    ("syntheticDistinctFromEndpoints", "distinct"),
    ("changingProofOutputs", "changing"),
    ("eligibleSyntheticPixels", "eligible_pixels"),
    ("substantiveSyntheticPixels", "substantive_pixels"),
    ("nonCrossfadeSyntheticPixels", "non_crossfade_pixels"),
    ("motionEligibleProofSamples", "motion_eligible_samples"),
    ("motionCorrelatedProofSamples", "correlated_samples"),
    ("v21DirectionallyEligibleSyntheticPixels", "motion_eligible_pixels"),
    ("v21CorrectVectorPredictedSyntheticPixels", "motion_synthesized_pixels"),
    ("windowElapsedMs", "window_ms"),
    ("windowStartNs", "window_start_ns"),
    ("windowEndNs", "window_end_ns"),
    ("windowPresents", "window_presents"),
    ("windowGenerated", "window_generated"),
    ("windowPromoted", "window_promoted"),
)


def health_values(end_ns, proof, *, locked=60, presents=1000, generated=500,
                  promoted=500):
    samples = proof * 96
    pixels = proof * 200
    values = {
        "lattice_samples": samples,
        "regional_samples": samples,
        "lattice_backward_coherent": proof * 60,
        "lattice_forward_coherent": proof * 60,
        "lattice_backward_boundary": proof * 20,
        "lattice_forward_boundary": proof * 20,
        "lattice_backward_coherent_boundary": proof * 10,
        "lattice_forward_coherent_boundary": proof * 10,
        "regional_backward_supported": proof * 50,
        "regional_forward_supported": proof * 50,
        "regional_backward_neighbor": proof * 40,
        "regional_forward_neighbor": proof * 40,
        "regional_backward_constant_neighbor": proof * 25,
        "regional_forward_constant_neighbor": proof * 25,
        "regional_backward_gradient_neighbor": proof * 25,
        "regional_forward_gradient_neighbor": proof * 25,
        "regional_backward_accepted": proof * 30,
        "regional_forward_accepted": proof * 30,
        "regional_backward_accepted_boundary": proof * 5,
        "regional_forward_accepted_boundary": proof * 5,
        "regional_backward_cycle": proof * 20,
        "regional_forward_cycle": proof * 20,
        "proof": proof,
        "synthetic": proof,
        "distinct": proof,
        "changing": proof,
        "eligible_pixels": pixels,
        "substantive_pixels": pixels * 3 // 4,
        "non_crossfade_pixels": pixels * 3 // 4,
        "motion_eligible_samples": proof,
        "correlated_samples": proof,
        "motion_eligible_pixels": pixels,
        "motion_synthesized_pixels": pixels * 3 // 4,
    }
    for key in (
            "lattice_backward_count", "lattice_forward_count",
            "lattice_backward_boundary_count", "lattice_forward_boundary_count",
            "lattice_backward_coherent_boundary_count",
            "lattice_forward_coherent_boundary_count",
            "regional_backward_count", "regional_forward_count",
            "regional_backward_accepted_boundary_count",
            "regional_forward_accepted_boundary_count",
            "regional_backward_cycle_count", "regional_forward_cycle_count",
            "regional_backward_supported_count", "regional_forward_supported_count",
            "regional_backward_neighbor_count", "regional_forward_neighbor_count",
            "regional_backward_constant_neighbor_count",
            "regional_forward_constant_neighbor_count",
            "regional_backward_gradient_neighbor_count",
            "regional_forward_gradient_neighbor_count"):
        values[key] = 20 if proof else 0
    for key in ("lattice_backward_peak_support", "lattice_forward_peak_support",
                "regional_backward_support", "regional_forward_support",
                "regional_backward_confidence", "regional_forward_confidence"):
        values[key] = 200 if proof else 0
    values.update({
        "active": 100 if proof else 0,
        "confident": 100 if proof else 0,
        "cells": 1296,
        "window_ms": 1000,
        "window_start_ns": end_ns - 1_000_000_000,
        "window_end_ns": end_ns,
        "window_presents": 120,
        "window_generated": 120 - locked,
        "window_promoted": locked,
    })
    values.update({
        "presents": presents,
        "generated": generated,
        "promoted": promoted,
        "real": promoted,
        "submitted": promoted,
    })
    return values


def health_line(values):
    locked = values.get("locked", 60)
    output = min(120, locked * 2)
    prefix = (
        "I/EmuFusionFrameGen( 123): Presentation health generator=1 role=primary "
        "displayId=0 proofContract=native-pixel-refined-regional-flow-v22-x2-presented "
        f"proofSchemaVersion=22 presents={values['presents']} "
        f"generated={values['generated']} real={values['real']} "
        f"promoted={values['promoted']} submitted={values['submitted']} "
        f"producerHz=60.00 lockedFps={locked} outputFps={output} panelFps=120"
    )
    return prefix + " " + " ".join(
        f"{label}={values[key]}" for label, key in LABELS)


class EvidenceFixture:
    def __init__(self, directory: Path, *, transition=False, prior_proof=0,
                 proof_increment=60):
        self.directory = directory
        self.log = directory / "logcat.txt"
        self.latency = directory / "latency.txt"
        self.manifest = directory / "qualification.json"
        base = prior_proof
        if transition:
            tiers = (60, 50, 50, 50, 50)
            ends = (2_000_000_000, 3_000_000_000, 4_000_000_000,
                    15_000_000_000, 16_000_000_000)
            proofs = (base, base, base + proof_increment // 2,
                      base + proof_increment, base + proof_increment)
            deltas = (0, 120, 240, 1560, 1680)
        else:
            tiers = (60, 60, 60, 60)
            ends = (2_000_000_000, 3_000_000_000,
                    14_000_000_000, 15_000_000_000)
            proofs = (base, base + proof_increment // 2,
                      base + proof_increment, base + proof_increment)
            deltas = (0, 120, 1440, 1560)
        rows = []
        for end, proof, delta, tier in zip(ends, proofs, deltas, tiers):
            output = min(120, tier * 2)
            promoted_delta = round(delta * tier / output)
            generated_delta = promoted_delta
            delta = generated_delta + promoted_delta
            values = health_values(
                end, proof, locked=tier, presents=1000 + delta,
                generated=500 + generated_delta,
                promoted=500 + promoted_delta)
            values["window_presents"] = output
            values["window_generated"] = tier
            values["window_promoted"] = tier
            values["locked"] = tier
            rows.append(health_line(values))
        self.rows = rows
        header = [
            "I/EmuFusionFrameGen( 123): Frame generator attached generator=1 "
            "role=primary displayId=0 "
            "proofContract=native-pixel-refined-regional-flow-v22-x2-presented "
            "proofSchemaVersion=22",
            "I/InWindowGameHost( 123): In-window route accepted engine=mesen system=nes",
            "I/EmuFusionFrameGen( 123): Qualification proof generator=1 enabled=true "
            "proofContract=native-pixel-refined-regional-flow-v22-x2-presented "
            "proofSchemaVersion=22",
        ]
        self.log.write_text("\n".join(header + rows) + "\n", encoding="utf-8")
        final_output = min(120, tiers[-1] * 2)
        refresh = 8_333_333
        output_period = round(1_000_000_000 / final_output)
        timestamp = ends[-1] - 1_000_000_000
        deadline = 0
        tolerance = refresh // 4
        timestamps = []
        while timestamp < ends[-1]:
            selected = timestamp + tolerance
            if deadline == 0 or selected >= deadline:
                timestamps.append(timestamp)
                if deadline == 0:
                    deadline = timestamp + output_period
                else:
                    while deadline <= selected:
                        deadline += output_period
            timestamp += refresh
        self.latency.write_text(
            str(refresh) + "\n" + "".join(
                f"{stamp} {stamp} {stamp}\n" for stamp in timestamps),
            encoding="utf-8")
        segment = {
            "segmentId": "nes-tier",
            "kind": "transition" if transition else "steady",
            "startWindowEndNs": ends[0],
            "proofBaselineWindowEndNs": ends[0],
            "endWindowEndNs": ends[-1],
            "maxFallbackPresents": 0,
        }
        if transition:
            segment.update({
                "expectedFromFps": 60,
                "expectedToFps": 50,
                "maxTransitionMs": 2000,
                "proofBaselineWindowEndNs": ends[1],
            })
        else:
            segment["expectedLockedFps"] = 60
        self.document = {
            "schemaVersion": 1,
            "evidence": {
                "logSha256": VERIFIER._sha256(self.log),
                "latencySha256": VERIFIER._sha256(self.latency),
            },
            "identity": {
                "sessionId": "nes-session-1",
                "systemId": "nes",
                "gameId": "super-mario-bros",
                "coreId": "mesen",
                "packageName": "com.thorium.preview",
                "romSha256": "1" * 64,
                "coreSha256": "2" * 64,
                "apkSha256": "3" * 64,
                "pid": 123,
                "generator": 1,
                "role": "primary",
                "displayId": 0,
                "sessionStartNs": 1,
                "sessionEndNs": ends[-1] + 1_000_000_000,
            },
            "segments": [segment],
        }
        self.write_manifest()

    def write_manifest(self):
        self.manifest.write_text(json.dumps(self.document), encoding="utf-8")

    def rebind_evidence(self):
        self.document["evidence"]["logSha256"] = VERIFIER._sha256(self.log)
        self.document["evidence"]["latencySha256"] = VERIFIER._sha256(self.latency)
        self.write_manifest()

    def verify(self):
        return VERIFIER.verify(
            self.log, self.latency, qualification_path=self.manifest,
            segment_id="nes-tier")


def quantized_timestamps(panel, output, count, start=1_000_000_000):
    panel_period = round(1_000_000_000 / panel)
    output_period = round(1_000_000_000 / output)
    timestamps = []
    now = start
    deadline = 0
    tolerance = panel_period // 4
    for _ in range(panel * count):
        selected = now + tolerance
        if deadline == 0 or selected >= deadline:
            timestamps.append(now)
            if deadline == 0:
                deadline = now + output_period
            else:
                while deadline <= selected:
                    deadline += output_period
        now += panel_period
    return timestamps

class FrameGenerationEvidenceTest(unittest.TestCase):
    def test_v38_vector_trajectory_keeps_hard_edge_proof_fail_closed(self):
        # Physical Wii r49 shape: a translated opaque edge can equal one raw
        # endpoint at a fixed coordinate, while independently following the
        # selected motion vector exactly.
        values = {
            "eligible_pixels": 5437,
            "substantive_pixels": 2334,
            "non_crossfade_pixels": 3909,
            "motion_eligible_samples": 26,
            "correlated_samples": 20,
            "motion_eligible_pixels": 5437,
            "motion_synthesized_pixels": 5437,
        }
        self.assertEqual([], VERIFIER._motion_content_failures(
            values, vector_trajectory_contract=True))
        legacy = VERIFIER._motion_content_failures(
            values, vector_trajectory_contract=False)
        self.assertTrue(any("materially depart" in failure
                            for failure in legacy))

        weak_vector = dict(values, motion_synthesized_pixels=2500)
        self.assertTrue(any("selected vectors" in failure for failure in
                            VERIFIER._motion_content_failures(
                                weak_vector,
                                vector_trajectory_contract=True)))
        crossfade = dict(values, non_crossfade_pixels=2500)
        self.assertTrue(any("crossfade" in failure for failure in
                            VERIFIER._motion_content_failures(
                                crossfade,
                                vector_trajectory_contract=True)))

    def test_segment_endpoint_backlog_conservation_accepts_carried_work(self):
        baseline = {"promoted": 1319, "real": 1335, "submitted": 1337}
        end = {"promoted": 2280, "real": 2295, "submitted": 2297}
        segment = {"promoted": 961, "real": 960, "submitted": 960}
        self.assertTrue(VERIFIER._segment_endpoint_backlogs_valid(
            baseline, end, segment))

        # The opening accepted backlog can fund one extra promotion, but it
        # cannot manufacture an endpoint or an uploaded candidate.
        self.assertFalse(VERIFIER._segment_endpoint_backlogs_valid(
            baseline, end, dict(segment, promoted=962)))
        self.assertFalse(VERIFIER._segment_endpoint_backlogs_valid(
            baseline, end, dict(segment, real=961)))

    def test_v37_segment_max_2x_includes_only_bounded_retained_endpoints(self):
        # r53 consumed 898 new endpoints after a baseline that already owned
        # an active pair/FIFO. The renderer may use that bounded retained work.
        self.assertTrue(VERIFIER._v37_segment_source_evidence_valid({
            "presents": 1800, "promoted": 898,
        }))
        limit = 2 * (898 + VERIFIER.V37_MAX_RETAINED_ENDPOINTS)
        self.assertTrue(VERIFIER._v37_segment_source_evidence_valid({
            "presents": limit, "promoted": 898,
        }))
        self.assertFalse(VERIFIER._v37_segment_source_evidence_valid({
            "presents": limit + 1, "promoted": 898,
        }))

        # Physical PS2 r04 ended on a 998 ms HEALTH boundary: rate arithmetic
        # yields 120.24048096 versus 2*59.11823647+2=120.23647294 and used to
        # reject by 0.004 Hz. Exact segment ownership is 2400 presents from
        # 1198 newly promoted endpoints plus a bounded retained pair/FIFO.
        self.assertTrue(VERIFIER._v37_segment_source_evidence_valid({
            "presents": 2400, "promoted": 1198,
        }))

    def test_v37_final_max_2x_gate_uses_exact_counts_not_rounded_rates(self):
        source = MODULE_PATH.read_text(encoding="utf-8")
        final = source.split(
            '"generator did not present at its reported output target"', 1
        )[1].split('if v36_evidence_contract', 1)[0]
        self.assertIn("_v37_segment_source_evidence_valid(values)", final)
        self.assertNotIn("present_rate <= 2.0 * promoted_rate", final)

    def test_v37_window_max_2x_uses_only_bounded_fifo_carry(self):
        # Physical GC r60 opened a one-second HEALTH window with retained
        # producer work and then committed 120 outputs while promoting 58 new
        # endpoints.  The active pair plus four-entry FIFO is sufficient
        # bounded evidence; one endpoint beyond that exact capacity is not.
        base = {
            "panel": 120, "locked": 60, "output": 120,
            "window_presents": 120, "window_generated": 62,
            "window_real_priority": 58, "window_synthetic_selected": 62,
            "window_promoted": 58, "window_duplicate_pair_selection": 0,
        }
        self.assertEqual([], VERIFIER._v37_output_accounting_hierarchy(base))
        impossible = dict(base, window_promoted=53)
        self.assertIn(
            "v37 output exceeds twice its consumed source evidence",
            VERIFIER._v37_output_accounting_hierarchy(impossible))

    def test_schema37_window_duration_precedes_contract_rate_use(self):
        source = MODULE_PATH.read_text(encoding="utf-8")
        accounting = source.index(
            'maximum_fallback = segment["maxFallbackPresents"]')
        duration = source.index(
            'window_seconds = values["window_ms"] / 1000.0', accounting)
        first_rate_use = source.index('/ window_seconds', accounting)
        self.assertLess(duration, first_rate_use)

    def test_schema37_fractional_only_segment_uses_present_wall_not_real_wall(self):
        wall = {
            "dense_gpu_budget_us": 7333,
            "dense_promotion_wall_samples": 0,
            "dense_promotion_wall_total_us": 0,
            "dense_promotion_wall_p95_us": 10427,
            "dense_promotion_wall_max_us": 16888,
            "dense_signature_wall_samples": 899,
            "dense_signature_wall_total_us": 106223,
            "dense_signature_wall_p95_us": 143,
            "dense_signature_wall_max_us": 2811,
            "dense_proof_wall_samples": 0,
            "dense_proof_wall_total_us": 0,
            "dense_proof_wall_p95_us": 0,
            "dense_proof_wall_max_us": 0,
        }
        self.assertTrue(VERIFIER._dense_v28_wall_telemetry_valid(wall, True))
        self.assertFalse(VERIFIER._dense_v28_wall_telemetry_valid(wall, False))
        wall.update({
            "dense_promotion_wall_samples": 120,
            "dense_promotion_wall_total_us": 120000,
            "dense_promotion_wall_p95_us": 1000,
            "dense_promotion_wall_max_us": 2000,
        })
        self.assertTrue(VERIFIER._dense_v28_wall_telemetry_valid(wall, False))

    def test_schema36_rational_output_policy_and_accounting(self):
        cases = (
            # source, output, exact REAL, generated
            (60, 120, 60, 60),
            (50, 60, 10, 50),
            (40, 60, 20, 40),
            (30, 60, 30, 30),
            (20, 40, 20, 20),
        )
        for source, output, exact_real, generated in cases:
            with self.subTest(source=source, output=output):
                self.assertEqual(
                    output, VERIFIER._schema36_output_fps(120, source))
                self.assertEqual(
                    (exact_real, generated),
                    VERIFIER._schema36_rational_rates(source, output))
                record = {
                    "panel": 120, "locked": source, "output": output,
                    "window_presents": output,
                    "window_real_priority": exact_real,
                    "window_generated": generated,
                    "window_promoted": source,
                    "window_synthetic_selected": generated,
                    "window_synthetic_quota_opening": 0,
                    "window_synthetic_pair_created": generated,
                    "window_synthetic_quota_skipped": 0,
                    "synthetic_quota_pending": 0,
                }
                self.assertEqual(
                    [], VERIFIER._v36_output_accounting_hierarchy(record))

        old_x2 = {
            "panel": 120, "locked": 50, "output": 100,
            "window_presents": 100, "window_real_priority": 50,
            "window_generated": 50, "window_promoted": 50,
            "window_synthetic_selected": 50,
            "window_synthetic_quota_opening": 0,
            "window_synthetic_pair_created": 50,
            "window_synthetic_quota_skipped": 0,
            "synthetic_quota_pending": 0,
        }
        self.assertTrue(any(
            "rational panel policy" in failure for failure in
            VERIFIER._v36_output_accounting_hierarchy(old_x2)))

    def test_schema37_plus_uses_exact_panel_capped_two_x_targets(self):
        self.assertEqual(
            [40, 60, 80, 100, 120],
            [VERIFIER._schema37_output_fps(120, source)
             for source in (20, 30, 40, 50, 60)])
        self.assertEqual(
            [40, 60, 60, 60, 60],
            [VERIFIER._schema37_output_fps(60, source)
             for source in (20, 30, 40, 50, 60)])

    def test_runtime_runner_splits_schema36_by_epoch_and_has_time_for_proof(self):
        import sys
        runner_path = Path(__file__).parents[1] / "run_runtime_acceptance_qa.py"
        runner_name = "framegen_runtime_runner_test"
        runner_spec = importlib.util.spec_from_file_location(
            runner_name, runner_path)
        runner = importlib.util.module_from_spec(runner_spec)
        assert runner_spec.loader is not None
        sys.path.insert(0, str(runner_path.parent))
        sys.modules[runner_name] = runner
        try:
            runner_spec.loader.exec_module(runner)
        finally:
            sys.path.pop(0)
            sys.modules.pop(runner_name, None)
        self.assertGreaterEqual(
            runner.FRAMEGEN_CURRENT_STEADY_DEADLINE_SECONDS, 52.0)
        records = [{
            "pid": 1, "generator": 1, "locked": 50,
            "proof_schema_version": 36,
            "window_presentation_epoch": 9,
            "proof_evidence_presentation_epoch": 9,
            "window_end_ns": end_ns,
        } for end_ns in (2_000_000_000, 3_200_000_000,
                          14_000_000_000, 15_200_000_000)]
        segment, _end = runner._steady_framegen_segment(
            records, "primary", 0)
        self.assertEqual(9, segment["expectedPresentationEpoch"])
        mixed = [dict(record) for record in records]
        mixed[1].update({"window_presentation_epoch": 8,
                         "proof_evidence_presentation_epoch": 8})
        with self.assertRaisesRegex(RuntimeError, "not steady for 11 seconds"):
            runner._steady_framegen_segment(mixed, "primary", 0)

    def test_schema36_segment_is_bound_to_one_presentation_evidence_epoch(self):
        records = []
        for index, end_ns in enumerate((2_000_000_000, 3_000_000_000,
                                        14_000_000_000, 15_000_000_000)):
            record = health_values(end_ns, index * 10, locked=50)
            record.update({
                "locked": 50, "proof_schema_version": 36,
                "window_presentation_epoch": 9,
                "proof_evidence_presentation_epoch": 9,
            })
            records.append(record)
        segment = {
            "segmentId": "epoch-9", "kind": "steady",
            "startWindowEndNs": 2_000_000_000,
            "proofBaselineWindowEndNs": 2_000_000_000,
            "endWindowEndNs": 15_000_000_000,
            "maxFallbackPresents": 0, "expectedLockedFps": 50,
            "expectedPresentationEpoch": 9,
        }
        result = VERIFIER._validate_segment(segment, records)
        self.assertEqual(50, result[-1]["expectedLockedFps"])
        mixed = [dict(record) for record in records]
        mixed[2]["window_presentation_epoch"] = 10
        mixed[2]["proof_evidence_presentation_epoch"] = 10
        with self.assertRaisesRegex(ValueError, "mixes presentation evidence"):
            VERIFIER._validate_segment(segment, mixed)

    def test_segment_rebases_async_atlas_and_matching_wall_counters_atomically(self):
        keys = (
            "proof", "dense_proof_atlas_enqueued",
            "dense_proof_atlas_completed", "dense_callback_delta_samples",
            "dense_callback_delta_total_us", "dense_present_wall_samples",
            "dense_present_wall_total_us", "dense_swap_wall_samples",
            "dense_swap_wall_total_us", "dense_proof_enqueue_wall_samples",
            "dense_proof_enqueue_wall_total_us",
            "dense_proof_poll_wall_samples", "dense_proof_poll_wall_total_us",
        )
        baseline = {key: 10 for key in keys}
        baseline.update({
            "dense_proof_atlas_pending": 0,
            "dense_callback_delta_total_us": 100,
            "dense_present_wall_total_us": 100,
            "dense_swap_wall_total_us": 100,
            "dense_proof_enqueue_wall_total_us": 100,
            "dense_proof_poll_wall_total_us": 100,
        })
        end = {key: 40 for key in keys}
        end.update({
            "dense_proof_atlas_pending": 0,
            "dense_callback_delta_total_us": 400,
            "dense_present_wall_total_us": 400,
            "dense_swap_wall_total_us": 400,
            "dense_proof_enqueue_wall_total_us": 400,
            "dense_proof_poll_wall_total_us": 400,
        })
        relative, absolute, failures = VERIFIER._segment_relative_counters(
            end, baseline, keys, asynchronous_atlas=True,
        )
        self.assertEqual(failures, [])
        self.assertEqual(relative["proof"], 30)
        self.assertEqual(relative["dense_proof_atlas_enqueued"], 30)
        self.assertEqual(relative["dense_proof_atlas_completed"], 30)
        self.assertEqual(relative["dense_proof_enqueue_wall_samples"], 30)
        self.assertEqual(absolute["dense_proof_atlas_enqueued"], 40)
        self.assertEqual(absolute["dense_proof_enqueue_wall_samples"], 40)

    def test_segment_async_atlas_rejects_incomplete_pending_and_regression(self):
        keys = ("proof", "dense_proof_atlas_enqueued",
                "dense_proof_atlas_completed")
        baseline = {
            "proof": 10, "dense_proof_atlas_enqueued": 10,
            "dense_proof_atlas_completed": 10,
            "dense_proof_atlas_pending": 0,
        }
        incomplete = {
            "proof": 40, "dense_proof_atlas_enqueued": 40,
            "dense_proof_atlas_completed": 39,
            "dense_proof_atlas_pending": 0,
        }
        _relative, _absolute, failures = VERIFIER._segment_relative_counters(
            incomplete, baseline, keys, asynchronous_atlas=True,
        )
        self.assertIn(
            "segment-relative proof-atlas conservation is impossible", failures
        )

        pending = dict(baseline, dense_proof_atlas_pending=1)
        _relative, _absolute, failures = VERIFIER._segment_relative_counters(
            incomplete, pending, keys, asynchronous_atlas=True,
        )
        self.assertIn(
            "proof baseline has pending asynchronous proof-atlas work", failures
        )

        regressed = dict(incomplete, dense_proof_atlas_completed=9)
        _relative, _absolute, failures = VERIFIER._segment_relative_counters(
            regressed, baseline, keys, asynchronous_atlas=True,
        )
        self.assertIn(
            "segment-relative counter is negative: dense_proof_atlas_completed",
            failures,
        )

    def test_segment_async_atlas_allows_only_conserved_next_sample_pending(self):
        valid = {
            "proof": 31,
            "dense_proof_atlas_enqueued": 32,
            "dense_proof_atlas_completed": 31,
            "dense_proof_atlas_pending": 1,
        }
        self.assertTrue(
            VERIFIER._segment_async_atlas_completion_valid(valid)
        )
        for mutation in (
                {"dense_proof_atlas_completed": 30},
                {"dense_proof_atlas_enqueued": 33},
                {"dense_proof_atlas_pending": 5}):
            with self.subTest(mutation=mutation):
                self.assertFalse(
                    VERIFIER._segment_async_atlas_completion_valid(
                        dict(valid, **mutation)
                    )
                )

    def test_v27_reduced_workload_identity_is_exact_and_fail_closed(self):
        exact = {
            "dense_variant": "fragment-192x108-v27",
            "dense_analysis_width": 192,
            "dense_analysis_height": 108,
            "dense_solve_texels": 228096,
            "dense_total_texels": 282528,
        }
        self.assertTrue(VERIFIER._v27_workload_identity_valid(exact, 1920, 1080))
        # A 4:3 source must preserve aspect rather than be stretched to 16:9.
        four_three = dict(exact, dense_analysis_width=144,
                          dense_solve_texels=171072,
                          dense_total_texels=211896)
        self.assertTrue(VERIFIER._v27_workload_identity_valid(four_three, 320, 240))
        for field, invalid in (
                ("dense_variant", "fragment-256x144-v26"),
                ("dense_analysis_width", 193),
                ("dense_analysis_height", 109),
                ("dense_solve_texels", 228095),
                ("dense_total_texels", 282527)):
            changed = dict(exact)
            changed[field] = invalid
            self.assertFalse(VERIFIER._v27_workload_identity_valid(
                changed, 1920, 1080), field)
        impossible_wide = dict(exact, dense_analysis_height=4,
                               dense_solve_texels=16320,
                               dense_total_texels=20160)
        impossible_tall = dict(exact, dense_analysis_width=4,
                               dense_solve_texels=11472,
                               dense_total_texels=14208)
        self.assertFalse(VERIFIER._v27_workload_identity_valid(
            impossible_wide, 1920, 1080))
        self.assertFalse(VERIFIER._v27_workload_identity_valid(
            impossible_tall, 1920, 1080))
        self.assertFalse(VERIFIER._v27_workload_identity_valid(exact, 320, 240))

    def test_v27_health_parser_binds_workload_fields_to_contract(self):
        values = health_values(2_000_000_000, 1)
        line = health_line(values).replace(
            "proofContract=native-pixel-refined-regional-flow-v22-x2-presented "
            "proofSchemaVersion=22",
            "proofContract=dense-fragment-192x108-v27-qualification-x2-presented "
            "proofSchemaVersion=27",
        )
        workload = (
            "denseEnabled=1 densePromotions=1 densePasses=38 "
            "denseCpuSubmitTotalUs=100 denseCpuSubmitMaxUs=100 "
            "denseCpuSubmitLastUs=100 denseGpuCompleteTotalUs=4000 "
            "denseGpuCompleteMaxUs=4000 denseGpuCompleteLastUs=4000 "
            "denseGpuBudgetUs=7333 denseTimedPairs=1 denseWarpSequence=1 "
            "denseWarpMaxCompletedSequence=1 denseTimerPending=0 "
            "denseTimerDisjoint=0 denseTimerUnavailable=0 denseTimerStale=0 "
            "denseTimerMaxQueueAge=2 densePerformanceRejected=0 "
            "denseCalibrationRuns=1 denseCalibrationUs=100 "
            "denseRuntimeCadenceSource=app-present-window "
            "denseOfflineCadenceSource=surfaceflinger-layer-timestamps "
            "denseVariant=fragment-192x108-v27 denseAnalysisWidth=192 "
            "denseAnalysisHeight=108 denseSolveTexelsPerPromotion=228096 "
            "denseTotalTexelsPerPromotion=282528 "
            "denseCopySamples=1 denseCopyTotalUs=1 denseCopyP95Us=1 denseCopyMaxUs=1 "
            "densePyramidSamples=1 densePyramidTotalUs=60 densePyramidP95Us=60 densePyramidMaxUs=60 "
            "denseForwardSamples=1 denseForwardTotalUs=1900 denseForwardP95Us=1900 denseForwardMaxUs=1900 "
            "denseReverseSamples=1 denseReverseTotalUs=1900 denseReverseP95Us=1900 denseReverseMaxUs=1900 "
            "denseValidationSamples=1 denseValidationTotalUs=139 denseValidationP95Us=139 denseValidationMaxUs=139 "
            "denseWarpSamples=1 denseWarpTotalUs=100 denseWarpP95Us=100 denseWarpMaxUs=100 "
            "denseMaxFlowPixels=47 denseProofCells=1296 "
            "denseBackwardValidCells=1000 denseForwardValidCells=1000 "
        )
        line = line.replace("windowElapsedMs=", workload + "windowElapsedMs=")
        match = VERIFIER.HEALTH.search(line)
        self.assertIsNotNone(match)
        decoded = {key: (value if key in ("role", "proof_contract", "dense_variant")
                         else (0 if value is None else int(value)))
                   for key, value in match.groupdict().items()}
        self.assertEqual(decoded["proof_contract"], VERIFIER.DENSE_V27_PROOF_CONTRACT)
        self.assertTrue(VERIFIER._v27_workload_identity_valid(decoded, 1920, 1080))

    def test_v28_workload_uses_exact_integer_pyramid_and_rejects_v27_counts(self):
        exact = {
            "dense_variant": "fragment-160x90-v28",
            "dense_analysis_width": 160,
            "dense_analysis_height": 90,
            # 160x90 -> 80x45 -> 40x22; there is no fractional 22.5 row.
            "dense_solve_texels": 158080,
            "dense_total_texels": 195840,
        }
        self.assertTrue(VERIFIER._v28_workload_identity_valid(exact, 1920, 1080))
        four_three = dict(exact, dense_analysis_width=120,
                          dense_solve_texels=118560,
                          dense_total_texels=146880)
        self.assertTrue(VERIFIER._v28_workload_identity_valid(four_three, 320, 240))
        self.assertFalse(VERIFIER._v28_workload_identity_valid(
            dict(exact, dense_solve_texels=158400), 1920, 1080))
        self.assertFalse(VERIFIER._v28_workload_identity_valid(
            dict(exact, dense_variant="fragment-192x108-v27"), 1920, 1080))
        self.assertFalse(VERIFIER._v28_workload_identity_valid(
            dict(exact, dense_analysis_height=4), 1920, 1080))

    def test_v51_workload_counts_two_full_resolution_refinement_draws(self):
        exact = {
            "proof_schema_version": 51,
            "dense_variant": (
                "fragment-128x72-v51-cost-tested-bidirectional-refinement-"
                "stamped-pts-loss-bound-spatial-consensus-rational-clock-"
                "strict-flow"),
            "dense_analysis_width": 128,
            "dense_analysis_height": 72,
            # Historical solve: 101,376. Two 128x72 refinements add 18,432.
            "dense_solve_texels": 119808,
            "dense_total_texels": 144000,
        }
        self.assertTrue(VERIFIER._v28_workload_identity_valid(
            exact, 1920, 1080))
        self.assertFalse(VERIFIER._v28_workload_identity_valid(
            dict(exact, dense_solve_texels=101376,
                 dense_total_texels=125568), 1920, 1080))

    def test_v54_cycle_objective_keeps_v51_workload(self):
        exact = {
            "proof_schema_version": 54,
            "dense_variant": (
                "fragment-128x72-v54-cycle-aware-cost-tested-"
                "bidirectional-refinement-stamped-pts-loss-bound-spatial-"
                "consensus-rational-clock-strict-flow"),
            "dense_analysis_width": 128,
            "dense_analysis_height": 72,
            # The consistency term executes inside the two existing
            # full-resolution refinement draws.
            "dense_solve_texels": 119808,
            "dense_total_texels": 144000,
        }
        self.assertTrue(VERIFIER._v28_workload_identity_valid(
            exact, 1920, 1080))
        self.assertFalse(VERIFIER._v28_workload_identity_valid(
            dict(exact, dense_variant=(
                "fragment-128x72-v51-cost-tested-bidirectional-refinement-"
                "stamped-pts-loss-bound-spatial-consensus-rational-clock-"
                "strict-flow")), 1920, 1080))

    def test_v55_cycle_regularization_keeps_v51_workload(self):
        exact = {
            "proof_schema_version": 55,
            "dense_variant": (
                "fragment-128x72-v55-cycle-regularized-cost-tested-"
                "bidirectional-refinement-stamped-pts-loss-bound-spatial-"
                "consensus-rational-clock-strict-flow"),
            "dense_analysis_width": 128,
            "dense_analysis_height": 72,
            "dense_solve_texels": 119808,
            "dense_total_texels": 144000,
        }
        self.assertTrue(VERIFIER._v28_workload_identity_valid(
            exact, 1920, 1080))
        self.assertFalse(VERIFIER._v28_workload_identity_valid(
            dict(exact, dense_variant=(
                "fragment-128x72-v54-cycle-aware-cost-tested-"
                "bidirectional-refinement-stamped-pts-loss-bound-spatial-"
                "consensus-rational-clock-strict-flow")), 1920, 1080))

    def test_v56_strong_cycle_regularization_keeps_v51_workload(self):
        exact = {
            "proof_schema_version": 56,
            "dense_variant": (
                "fragment-128x72-v56-strong-cycle-regularized-cost-tested-"
                "bidirectional-refinement-stamped-pts-loss-bound-spatial-"
                "consensus-rational-clock-strict-flow"),
            "dense_analysis_width": 128,
            "dense_analysis_height": 72,
            "dense_solve_texels": 119808,
            "dense_total_texels": 144000,
        }
        self.assertTrue(VERIFIER._v28_workload_identity_valid(
            exact, 1920, 1080))
        self.assertFalse(VERIFIER._v28_workload_identity_valid(
            dict(exact, dense_variant=(
                "fragment-128x72-v55-cycle-regularized-cost-tested-"
                "bidirectional-refinement-stamped-pts-loss-bound-spatial-"
                "consensus-rational-clock-strict-flow")), 1920, 1080))

    def test_v57_compact_transport_keeps_v56_workload(self):
        exact = {
            "proof_schema_version": 57,
            "dense_variant": "fragment-v57-joint-cycle",
            "dense_analysis_width": 128,
            "dense_analysis_height": 72,
            "dense_solve_texels": 119808,
            "dense_total_texels": 144000,
        }
        self.assertTrue(VERIFIER._v28_workload_identity_valid(
            exact, 1920, 1080))
        self.assertFalse(VERIFIER._v28_workload_identity_valid(
            dict(exact, dense_variant=(
                "fragment-128x72-v56-strong-cycle-regularized-cost-tested-"
                "bidirectional-refinement-stamped-pts-loss-bound-spatial-"
                "consensus-rational-clock-strict-flow")), 1920, 1080))

    def test_v58_stronger_joint_cycle_keeps_v57_workload(self):
        exact = {
            "proof_schema_version": 58,
            "dense_variant": "fragment-v58-joint-cycle",
            "dense_analysis_width": 128,
            "dense_analysis_height": 72,
            "dense_solve_texels": 119808,
            "dense_total_texels": 144000,
        }
        self.assertTrue(VERIFIER._v28_workload_identity_valid(
            exact, 1920, 1080))
        self.assertFalse(VERIFIER._v28_workload_identity_valid(
            dict(exact, dense_variant="fragment-v57-joint-cycle"),
            1920, 1080))

    def test_v59_edge_aware_neighbor_keeps_v58_workload(self):
        exact = {
            "proof_schema_version": 59,
            "dense_variant": "fragment-v59-edge-aware-neighbor",
            "dense_analysis_width": 128,
            "dense_analysis_height": 72,
            "dense_solve_texels": 119808,
            "dense_total_texels": 144000,
        }
        self.assertTrue(VERIFIER._v28_workload_identity_valid(
            exact, 1920, 1080))
        self.assertFalse(VERIFIER._v28_workload_identity_valid(
            dict(exact, dense_variant="fragment-v58-joint-cycle"),
            1920, 1080))

    def test_v60_independent_global_seed_adds_exactly_two_one_pixel_draws(self):
        exact = {
            "proof_schema_version": 60,
            "dense_variant": "fragment-v60-independent-global-seed",
            "dense_analysis_width": 128,
            "dense_analysis_height": 72,
            "dense_solve_texels": 119808,
            "dense_total_texels": 144002,
        }
        self.assertTrue(VERIFIER._v28_workload_identity_valid(
            exact, 1920, 1080))
        self.assertFalse(VERIFIER._v28_workload_identity_valid(
            dict(exact, dense_total_texels=144000), 1920, 1080))
        self.assertFalse(VERIFIER._v28_workload_identity_valid(
            dict(exact, dense_variant="fragment-v59-edge-aware-neighbor"),
            1920, 1080))

    def test_v61_parallel_global_seed_accounts_for_candidate_and_reduce_draws(self):
        exact = {
            "proof_schema_version": 61,
            "dense_variant": "fragment-v61-parallel-global-seed",
            "dense_analysis_width": 128,
            "dense_analysis_height": 72,
            "dense_solve_texels": 119808,
            "dense_total_texels": 144216,
        }
        self.assertTrue(VERIFIER._v28_workload_identity_valid(
            exact, 1920, 1080))
        self.assertFalse(VERIFIER._v28_workload_identity_valid(
            dict(exact, dense_total_texels=144002), 1920, 1080))
        self.assertFalse(VERIFIER._v28_workload_identity_valid(
            dict(exact, dense_variant="fragment-v60-independent-global-seed"),
            1920, 1080))

    def test_v28_health_parser_requires_distinct_contract_and_wall_telemetry(self):
        values = health_values(2_000_000_000, 1)
        line = health_line(values).replace(
            "proofContract=native-pixel-refined-regional-flow-v22-x2-presented "
            "proofSchemaVersion=22",
            "proofContract=dense-fragment-160x90-v32-async-proof-atlas-qualification-x2-presented "
            "proofSchemaVersion=32",
        )
        workload = (
            "denseEnabled=1 densePromotions=120 densePasses=4560 "
            "denseCpuSubmitTotalUs=12000 denseCpuSubmitMaxUs=100 "
            "denseCpuSubmitLastUs=100 denseGpuCompleteTotalUs=600000 "
            "denseGpuCompleteMaxUs=6000 denseGpuCompleteLastUs=5000 "
            "denseGpuBudgetUs=7333 denseTimedPairs=120 denseWarpSequence=120 "
            "denseWarpMaxCompletedSequence=120 denseTimerPending=0 "
            "denseTimerDisjoint=0 denseTimerUnavailable=0 denseTimerStale=0 "
            "denseTimerMaxQueueAge=2 densePerformanceRejected=0 "
            "denseCalibrationRuns=1 denseCalibrationUs=100 "
            "denseCombinedPairMaxWarpP95Us=6600 "
            "densePromotionWallSamples=120 densePromotionWallTotalUs=720000 "
            "densePromotionWallP95Us=6500 densePromotionWallMaxUs=7000 "
            "denseSignatureWallSamples=120 denseSignatureWallTotalUs=12000 "
            "denseSignatureWallP95Us=110 denseSignatureWallMaxUs=120 "
            "denseProofWallSamples=0 denseProofWallTotalUs=0 "
            "denseProofWallP95Us=0 denseProofWallMaxUs=0 "
            "denseSignatureSequence=122 denseSignatureReady=120 "
            "denseSignatureUnavailable=0 denseSignatureMaxQueueAge=3 "
            "denseSignaturePending=2 denseSignatureCapability=63 "
            "denseSignatureRequestedGles=3 denseSignatureActualGlesMajor=3 "
            "denseSignatureActualGlesMinor=2 denseSignatureSelfTests=1 "
            "denseRuntimeCadenceSource=app-present-window "
            "denseOfflineCadenceSource=surfaceflinger-layer-timestamps "
            "denseVariant=fragment-160x90-v28 denseAnalysisWidth=160 "
            "denseAnalysisHeight=90 denseSolveTexelsPerPromotion=158080 "
            "denseTotalTexelsPerPromotion=195840 "
            "denseCopySamples=120 denseCopyTotalUs=120 denseCopyP95Us=1 denseCopyMaxUs=1 "
            "densePyramidSamples=120 densePyramidTotalUs=3600 densePyramidP95Us=30 densePyramidMaxUs=30 "
            "denseForwardSamples=120 denseForwardTotalUs=300000 denseForwardP95Us=2500 denseForwardMaxUs=2500 "
            "denseReverseSamples=120 denseReverseTotalUs=300000 denseReverseP95Us=2500 denseReverseMaxUs=2500 "
            "denseValidationSamples=120 denseValidationTotalUs=12000 denseValidationP95Us=100 denseValidationMaxUs=100 "
            "denseWarpSamples=120 denseWarpTotalUs=72000 denseWarpP95Us=600 denseWarpMaxUs=600 "
            "denseMaxFlowPixels=47 denseProofCells=1296 "
            "denseBackwardValidCells=1000 denseForwardValidCells=1000 "
        )
        match = VERIFIER.HEALTH.search(line.replace(
            "windowElapsedMs=", workload + "windowElapsedMs="))
        self.assertIsNotNone(match)
        decoded = {key: (value if key in ("role", "proof_contract", "dense_variant")
                         else (0 if value is None else int(value)))
                   for key, value in match.groupdict().items()}
        self.assertEqual(decoded["proof_contract"],
                         VERIFIER.DENSE_V28_V32_PROOF_CONTRACT)
        self.assertEqual(decoded["dense_combined_pair_warp_us"], 6600)
        self.assertEqual(decoded["dense_promotion_wall_samples"], 120)
        self.assertTrue(VERIFIER._v28_workload_identity_valid(decoded, 1920, 1080))
        self.assertTrue(VERIFIER._v31_signature_identity_valid(decoded))

        for corrupted in (
                dict(decoded, dense_signature_capability=31),
                dict(decoded, dense_signature_requested_gles=2),
                dict(decoded, dense_signature_actual_gles_major=2),
                dict(decoded, dense_signature_self_tests=0)):
            self.assertFalse(VERIFIER._v31_signature_identity_valid(corrupted))

        absent_capability = workload.replace(
            "denseSignaturePending=2 denseSignatureCapability=63 "
            "denseSignatureRequestedGles=3 denseSignatureActualGlesMajor=3 "
            "denseSignatureActualGlesMinor=2 denseSignatureSelfTests=1 ",
            "denseSignaturePending=2 ")
        parsed = VERIFIER.HEALTH.search(line.replace(
            "windowElapsedMs=", absent_capability + "windowElapsedMs="))
        self.assertIsNotNone(parsed)
        absent = {key: (value if key in ("role", "proof_contract", "dense_variant")
                        else (0 if value is None else int(value)))
                  for key, value in parsed.groupdict().items()}
        self.assertEqual(absent["dense_signature_capability"], 0)

    def test_v32_split_health_transport_joins_and_fails_closed(self):
        def materialize(pattern, overrides):
            def replace(match):
                name = match.group(1)
                if name in overrides:
                    return str(overrides[name])
                return "primary" if name == "role" else (
                    VERIFIER.DENSE_V28_PROOF_CONTRACT
                    if name == "proof_contract" else (
                    "fragment-160x90-v28" if name == "dense_variant" else "1"))
            text = __import__("re").sub(
                r"\(\?P<([a-z0-9_]+)>[^)]*\)", replace, pattern)
            return text.replace(".*?", "producerHz=60.00 ")

        common = {
            "generator": 7, "display_id": 0, "health_sequence": 9,
            "proof_schema_version": 32,
            "presents": 120, "window_start_ns": 1_000_000_000,
            "window_end_ns": 2_000_000_000,
            "dense_performance_rejected": 0,
        }
        base = materialize(VERIFIER.HEALTH_BASE.pattern, common)
        extension = materialize(VERIFIER.HEALTH_DENSE_EXTENSION.pattern, common)
        prefix = "08-13 12:00:00.000  4321  4322 I EmuFusionFrameGen: "
        records = VERIFIER._parse_health_records(
            prefix + base + "\n" + prefix + extension)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0][0].group("health_sequence"), "9")
        self.assertEqual(records[0][0].group("dense_proof_atlas_layout"), "1")
        # A cadence-rejected v32 window remains valid transport evidence. Its
        # rejection flag must survive the join so qualification rejects the
        # measured implementation instead of losing the record to v22 teardown.
        negative_extension = extension.replace(
            "densePerformanceRejected=0", "densePerformanceRejected=1", 1)
        self.assertNotEqual(negative_extension, extension)
        negative = VERIFIER._parse_health_records(
            prefix + base + "\n" + prefix + negative_extension)
        self.assertEqual(
            negative[0][0].group("dense_performance_rejected"), "1")
        decoded_negative = {
            key: (value if key in ("role", "proof_contract", "dense_variant")
                  else (0 if value is None else int(value)))
            for key, value in negative[0][0].groupdict().items()
        }
        self.assertEqual(decoded_negative["dense_enabled"], 1)
        self.assertNotEqual(decoded_negative["dense_performance_rejected"], 0)
        # This is complete, parseable negative evidence. The verifier's dense
        # qualification predicate must reject it explicitly rather than a
        # transport parser discarding it during teardown.
        self.assertFalse(
            decoded_negative["dense_performance_rejected"] == 0,
            "rejected dense window cannot satisfy qualification",
        )
        with self.assertRaisesRegex(ValueError, "missing its extension"):
            VERIFIER._parse_health_records(prefix + base)
        with self.assertRaisesRegex(ValueError, "orphan"):
            VERIFIER._parse_health_records(prefix + extension)
        with self.assertRaisesRegex(ValueError, "common key mismatch"):
            VERIFIER._parse_health_records(prefix + base + "\n" + prefix +
                    extension.replace("healthSequence=9", "healthSequence=10", 1))
        with self.assertRaisesRegex(ValueError, "orphan"):
            VERIFIER._parse_health_records(prefix + base + "\n" + prefix +
                    extension + "\n" + prefix + extension)
        with self.assertRaisesRegex(ValueError, "malformed or truncated"):
            VERIFIER._parse_health_records(prefix + base[:-40])

    def test_attach_parser_binds_immutable_input_dimensions(self):
        line = (
            "I/EmuFusionFrameGen( 123): Frame generator attached generator=1 "
            "role=primary displayId=0 "
            "proofContract=native-pixel-refined-regional-flow-v22-x2-presented "
            "proofSchemaVersion=22 output=1920x1080 input=640x480 displayHz=120")
        match = VERIFIER.ATTACHED.search(line)
        self.assertIsNotNone(match)
        self.assertEqual((int(match.group(6)), int(match.group(7))), (640, 480))

    def test_v33_scheduler_fields_are_atomic_and_required(self):
        def materialize(pattern, overrides):
            def replace(match):
                name = match.group(1)
                if name in overrides:
                    return str(overrides[name])
                return "primary" if name == "role" else (
                    VERIFIER.DENSE_V28_PROOF_CONTRACT
                    if name == "proof_contract" else (
                    "fragment-160x90-v28" if name == "dense_variant" else "1"))
            return __import__("re").sub(
                r"\(\?P<([a-z0-9_]+)>[^)]*\)", replace, pattern
            ).replace(".*?", "producerHz=50.00 ")

        common = {
            "generator": 7, "display_id": 0, "health_sequence": 10,
            "proof_schema_version": 33, "presents": 120,
            "window_start_ns": 1_000_000_000,
            "window_end_ns": 2_200_000_000,
            "window_presents": 120, "window_generated": 60,
            "window_promoted": 60, "window_due_selected": 120,
            "window_due_no_endpoint": 0, "window_due_phase_clamped": 0,
            "window_real_priority": 10,
            "window_synthetic_quota_skipped": 0,
            "window_presentation_epoch": 4,
            "window_synthetic_quota_opening": 0,
            "synthetic_quota_pending": 0,
            "window_synthetic_selected": 60,
            "window_synthetic_pair_created": 60,
            "window_synthetic_not_ready": 0,
            "window_duplicate_pair_selection": 0,
            "last_selected_synthetic_pair": 60,
        }
        base = materialize(VERIFIER.HEALTH_BASE_V33.pattern, common)
        extension = materialize(VERIFIER.HEALTH_DENSE_EXTENSION.pattern, common)
        prefix = "08-13 12:00:00.000  4321  4322 I EmuFusionFrameGen: "
        records = VERIFIER._parse_health_records(
            prefix + base + "\n" + prefix + extension)
        values = records[0][0].groupdict()
        self.assertEqual(values["window_due_selected"], "120")
        self.assertEqual(values["window_presentation_epoch"], "4")
        with self.assertRaisesRegex(ValueError, "malformed or truncated"):
            VERIFIER._parse_health_records(prefix + base.replace(
                " windowDueSelected=120", "", 1) + "\n" + prefix + extension)
        inflated = base.replace("windowDueSelected=120", "windowDueSelected=121", 1)
        parsed = VERIFIER._parse_health_records(
            prefix + inflated + "\n" + prefix + extension)[0][0]
        decoded = {key: (value if key in ("role", "proof_contract", "dense_variant")
                         else (None if value is None else int(value)))
                   for key, value in parsed.groupdict().items()}
        self.assertNotEqual(decoded["window_due_selected"],
                            decoded["window_presents"])

    def test_v34_diagnostic_transport_hierarchy_and_rebasing_fail_closed(self):
        def materialize(pattern, overrides):
            def replace(match):
                name = match.group(1)
                if name in overrides:
                    return str(overrides[name])
                return "primary" if name == "role" else (
                    VERIFIER.DENSE_V34_PROOF_CONTRACT
                    if name == "proof_contract" else (
                    "fragment-160x90-v34-diagnostic"
                    if name == "dense_variant" else "1"))
            return __import__("re").sub(
                r"\(\?P<([a-z0-9_]+)>[^)]*\)", replace, pattern
            ).replace(".*?", "producerHz=60.00 ")

        common = {
            "generator": 7, "display_id": 0, "health_sequence": 11,
            "proof_schema_version": 34, "presents": 120,
            "promoted": 10, "real": 10, "submitted": 10,
            "proof": 2, "window_start_ns": 1_000_000_000,
            "window_end_ns": 2_000_000_000,
            "window_presents": 120, "window_presentation_callbacks": 121,
            "window_generated": 60, "window_promoted": 60,
            "window_due_selected": 120, "window_due_no_endpoint": 0,
            "window_due_phase_clamped": 0, "window_real_priority": 10,
            "window_synthetic_quota_skipped": 0,
            "window_presentation_epoch": 4,
            "window_synthetic_quota_opening": 0,
            "synthetic_quota_pending": 0,
            "window_synthetic_selected": 60,
            "window_synthetic_pair_created": 60,
            "window_synthetic_not_ready": 0,
            "window_duplicate_pair_selection": 0,
            "last_selected_synthetic_pair": 60,
            "dense_promotions": 2, "dense_passes": 76,
            "dense_proof_cells": 2592,
            "dense_backward_valid": 1000, "dense_forward_valid": 1000,
            "dense_diagnostic_cells": 2592,
            "dense_diagnostic_tiles": 36,
            "dense_diagnostic_mask_errors": 0,
            "dense_diagnostic_last_atlas_sequence": 2,
            "dense_diagnostic_last_pair_sequence": 2,
            "dense_diagnostic_last_previous_endpoint": 9,
            "dense_diagnostic_last_current_endpoint": 10,
            "dense_proof_atlas_enqueued": 2,
            "dense_proof_atlas_completed": 2,
            "dense_proof_atlas_pending": 0,
            "dense_proof_atlas_layout": 2,
        }
        for direction in ("backward", "forward"):
            common.update({
                f"dense_{direction}_active": 2000,
                f"dense_{direction}_in_bounds": 2400,
                f"dense_{direction}_cycle_valid": 1900,
                f"dense_{direction}_photometric_valid": 1800,
                f"dense_{direction}_texture_valid": 1700,
                f"dense_{direction}_saturated": 20,
                f"dense_{direction}_out_of_bounds": 192,
                f"dense_{direction}_covered_tiles": 20,
                f"dense_{direction}_covered_tile_mask": 0x3ffff,
            })
        base = materialize(VERIFIER.HEALTH_BASE_V34.pattern, common)
        extension = materialize(
            VERIFIER.HEALTH_DENSE_EXTENSION_V34.pattern, common)
        prefix = "08-13 12:00:00.000  4321  4322 I EmuFusionFrameGen: "
        records = VERIFIER._parse_health_records(
            prefix + base + "\n" + prefix + extension)
        decoded = {
            key: (value if key in ("role", "proof_contract", "dense_variant")
                  else (None if value is None else int(value)))
            for key, value in records[0][0].groupdict().items()
        }
        self.assertEqual(decoded["proof_schema_version"], 34)
        self.assertEqual(decoded["dense_proof_atlas_layout"], 2)
        self.assertEqual([], VERIFIER._v34_diagnostic_hierarchy(decoded))
        self.assertTrue(VERIFIER._v28_workload_identity_valid(dict(
            decoded, dense_analysis_width=160, dense_analysis_height=90,
            dense_solve_texels=158080, dense_total_texels=195840),
            1920, 1080))

        adversaries = (
            ("dense_proof_atlas_layout", 1, "layout"),
            ("window_presentation_callbacks", 119, "callback window"),
            ("dense_backward_valid", 2001, "prerequisite funnel"),
            ("dense_backward_out_of_bounds", 191, "partition"),
            ("dense_diagnostic_cells", 2591, "do not cover"),
            ("dense_diagnostic_tiles", 35, "tiles do not cover"),
            ("dense_backward_covered_tile_mask", 1 << 18, "exceeds 18"),
            ("dense_backward_covered_tiles", 1, "mask exceeds its count"),
            ("dense_diagnostic_mask_errors", 1, "reserved bit"),
            ("dense_diagnostic_last_atlas_sequence", 1, "atlas binding"),
            ("dense_diagnostic_last_pair_sequence", 3, "pair binding"),
            ("dense_diagnostic_last_current_endpoint", 11, "endpoint binding"),
        )
        for field, value, expected in adversaries:
            with self.subTest(field=field):
                failures = VERIFIER._v34_diagnostic_hierarchy(
                    dict(decoded, **{field: value}))
                self.assertTrue(any(expected in item for item in failures), failures)

        # Schema-34 fields are atomic. Removing any one makes the record
        # malformed; a schema-33 extension cannot complete the pair.
        base_fields = ["windowPresentationCallbacks"]
        for direction in ("Backward", "Forward"):
            base_fields.extend("dense" + direction + suffix for suffix in (
                "ActiveCells", "InBoundsCells", "CycleValidCells",
                "PhotometricValidCells", "TextureValidCells",
                "SaturatedCells", "OutOfBoundsCells", "CoveredTiles",
                "CoveredTileMask"))
        extension_fields = (
            "denseDiagnosticCells", "denseDiagnosticTiles",
            "denseDiagnosticMaskErrors", "denseDiagnosticLastAtlasSequence",
            "denseDiagnosticLastPairSequence",
            "denseDiagnosticLastPreviousEndpoint",
            "denseDiagnosticLastCurrentEndpoint",
        )
        regex = __import__("re")
        for field in base_fields:
            with self.subTest(missing=field), self.assertRaisesRegex(
                    ValueError, "malformed or truncated"):
                truncated = regex.sub(rf" {field}=\d+", "", base, count=1)
                self.assertNotEqual(truncated, base)
                VERIFIER._parse_health_records(
                    prefix + truncated + "\n" + prefix + extension)
        for field in extension_fields:
            with self.subTest(missing=field), self.assertRaisesRegex(
                    ValueError, "malformed or truncated"):
                truncated = regex.sub(
                    rf" {field}=\d+", "", extension, count=1)
                self.assertNotEqual(truncated, extension)
                VERIFIER._parse_health_records(
                    prefix + base + "\n" + prefix + truncated)

        keys = ("proof", "dense_proof_cells", "dense_diagnostic_cells",
                "dense_diagnostic_tiles", "dense_backward_active",
                "dense_forward_active")
        baseline = {"proof": 10, "dense_proof_cells": 12960,
                    "dense_diagnostic_cells": 12960,
                    "dense_diagnostic_tiles": 180,
                    "dense_backward_active": 10000,
                    "dense_forward_active": 10000,
                    "dense_proof_atlas_pending": 0}
        end = {"proof": 40, "dense_proof_cells": 51840,
               "dense_diagnostic_cells": 51840,
               "dense_diagnostic_tiles": 720,
               "dense_backward_active": 40000,
               "dense_forward_active": 40000,
               "dense_proof_atlas_pending": 0}
        relative, absolute, failures = VERIFIER._segment_relative_counters(
            end, baseline, keys, asynchronous_atlas=False)
        self.assertEqual(failures, [])
        self.assertEqual(relative["dense_diagnostic_cells"], 30 * 1296)
        self.assertEqual(relative["dense_diagnostic_tiles"], 30 * 18)
        self.assertEqual(absolute["dense_diagnostic_cells"], 40 * 1296)

    def test_v34_explicit_reset_requires_zero_diagnostic_epoch(self):
        baseline = {key: 0 for key in
                    VERIFIER.RESET_COUNTER_FIELDS +
                    VERIFIER.V34_RESET_COUNTER_FIELDS}
        baseline.update({"window_end_ns": 2_000_000_000, "line_index": 20})
        end = {"line_index": 40}
        events = [
            {"pid": 123, "generator": 7, "lineIndex": 10,
             "enabled": False,
             "proofContract": VERIFIER.DENSE_V34_PROOF_CONTRACT,
             "proofSchemaVersion": 34},
            {"pid": 123, "generator": 7, "lineIndex": 11,
             "enabled": True,
             "proofContract": VERIFIER.DENSE_V34_PROOF_CONTRACT,
             "proofSchemaVersion": 34},
        ]
        reset = {"pid": 123, "generator": 7, "disabledLineIndex": 10,
                 "enabledLineIndex": 11,
                 "baselineWindowEndNs": 2_000_000_000}
        result = VERIFIER._validate_proof_reset(
            reset, events, [baseline], baseline, end, pid=123, generator=7,
            proof_contract=VERIFIER.DENSE_V34_PROOF_CONTRACT,
            proof_schema_version=34)
        self.assertEqual(result, reset)
        with self.assertRaisesRegex(ValueError, "v34 diagnostic counters"):
            VERIFIER._validate_proof_reset(
                reset, events, [dict(baseline, dense_backward_active=1)],
                dict(baseline, dense_backward_active=1), end,
                pid=123, generator=7,
                proof_contract=VERIFIER.DENSE_V34_PROOF_CONTRACT,
                proof_schema_version=34)

    def test_v35_packed_nearest_mask_is_atomic_and_not_cross_sampled(self):
        def materialize(pattern, overrides):
            def replace(match):
                name = match.group(1)
                if name in overrides:
                    return str(overrides[name])
                return "primary" if name == "role" else (
                    VERIFIER.DENSE_V35_PROOF_CONTRACT
                    if name == "proof_contract" else (
                    "fragment-160x90-v35-packed-mask"
                    if name == "dense_variant" else (
                    "packed-nearest-bf-v1"
                    if name == "dense_diagnostic_mask_layout" else "1")))
            return __import__("re").sub(
                r"\(\?P<([a-z0-9_]+)>[^)]*\)", replace, pattern
            ).replace(".*?", "producerHz=60.00 ")

        common = {
            "generator": 7, "display_id": 0, "health_sequence": 12,
            "proof_schema_version": 35, "presents": 120,
            "promoted": 10, "real": 10, "submitted": 10, "proof": 2,
            "window_start_ns": 1_000_000_000,
            "window_end_ns": 2_000_000_000,
            "window_presents": 120, "window_presentation_callbacks": 121,
            "window_generated": 60, "window_promoted": 60,
            "window_due_selected": 120, "window_due_no_endpoint": 0,
            "window_due_phase_clamped": 0, "window_real_priority": 10,
            "window_synthetic_quota_skipped": 0,
            "window_presentation_epoch": 4,
            "window_synthetic_quota_opening": 0,
            "synthetic_quota_pending": 0,
            "window_synthetic_selected": 60,
            "window_synthetic_pair_created": 60,
            "window_synthetic_not_ready": 0,
            "window_duplicate_pair_selection": 0,
            "last_selected_synthetic_pair": 60,
            "dense_promotions": 2, "dense_passes": 76,
            "dense_proof_cells": 2592,
            # LINEAR B is a separate population and may exceed any one
            # NEAREST factor count without making the transport impossible.
            "dense_backward_valid": 2000, "dense_forward_valid": 2000,
            "dense_diagnostic_cells": 2592,
            "dense_diagnostic_tiles": 36,
            "dense_diagnostic_packed_cells": 2592,
            "dense_diagnostic_mask_layout": "packed-nearest-bf-v1",
            "dense_diagnostic_partition_errors": 0,
            "dense_diagnostic_reserved_bit_errors": 0,
            "dense_diagnostic_mask_errors": 0,
            "dense_diagnostic_last_atlas_sequence": 2,
            "dense_diagnostic_last_pair_sequence": 2,
            "dense_diagnostic_last_previous_endpoint": 9,
            "dense_diagnostic_last_current_endpoint": 10,
            "dense_proof_atlas_enqueued": 2,
            "dense_proof_atlas_completed": 2,
            "dense_proof_atlas_pending": 0,
            "dense_proof_atlas_layout": 3,
        }
        for direction in ("backward", "forward"):
            common.update({
                f"dense_{direction}_active": 1900,
                f"dense_{direction}_in_bounds": 2400,
                f"dense_{direction}_cycle_valid": 1700,
                f"dense_{direction}_photometric_valid": 1600,
                f"dense_{direction}_texture_valid": 1500,
                f"dense_{direction}_saturated": 20,
                f"dense_{direction}_out_of_bounds": 192,
                f"dense_{direction}_covered_tiles": 20,
                f"dense_{direction}_covered_tile_mask": 0x3ffff,
            })
        base = materialize(VERIFIER.HEALTH_BASE_V35.pattern, common)
        extension = materialize(
            VERIFIER.HEALTH_DENSE_EXTENSION_V35.pattern, common)
        prefix = "08-13 12:00:00.000  4321  4322 I EmuFusionFrameGen: "
        joined = VERIFIER._parse_health_records(
            prefix + base + "\n" + prefix + extension)[0][0]
        decoded = {
            key: (value if key in (
                      "role", "proof_contract", "dense_variant",
                      "dense_diagnostic_mask_layout") else
                  (None if value is None else int(value)))
            for key, value in joined.groupdict().items()
        }
        self.assertEqual([], VERIFIER._v35_diagnostic_hierarchy(decoded))
        self.assertTrue(VERIFIER._v28_workload_identity_valid(dict(
            decoded, dense_analysis_width=160, dense_analysis_height=90,
            dense_solve_texels=158080, dense_total_texels=195840),
            1920, 1080))

        for field, value, expected in (
                ("dense_proof_atlas_layout", 2, "layout"),
                ("dense_diagnostic_packed_cells", 2591, "packed-mask"),
                ("dense_backward_out_of_bounds", 191, "partition"),
                ("dense_diagnostic_partition_errors", 1, "malformed"),
                ("dense_diagnostic_reserved_bit_errors", 1, "malformed"),
                ("dense_diagnostic_mask_errors", 1, "malformed")):
            with self.subTest(field=field):
                failures = VERIFIER._v35_diagnostic_hierarchy(
                    dict(decoded, **{field: value}))
                self.assertTrue(any(expected in item for item in failures), failures)

        # Every new field is required by schema35; it cannot fall through as
        # v34 or be silently fabricated by the parser.
        regex = __import__("re")
        for field in (
                "denseDiagnosticPackedCells", "denseDiagnosticMaskLayout",
                "denseDiagnosticPartitionErrors",
                "denseDiagnosticReservedBitErrors"):
            with self.subTest(missing=field), self.assertRaisesRegex(
                    ValueError, "malformed or truncated"):
                truncated = regex.sub(
                    rf" {field}=[a-z0-9-]+", "", extension, count=1)
                self.assertNotEqual(truncated, extension)
                VERIFIER._parse_health_records(
                    prefix + base + "\n" + prefix + truncated)

        keys = ("proof", "dense_diagnostic_cells",
                "dense_diagnostic_packed_cells",
                "dense_diagnostic_partition_errors",
                "dense_diagnostic_reserved_bit_errors")
        baseline = {"proof": 10, "dense_diagnostic_cells": 12960,
                    "dense_diagnostic_packed_cells": 12960,
                    "dense_diagnostic_partition_errors": 0,
                    "dense_diagnostic_reserved_bit_errors": 0,
                    "dense_proof_atlas_pending": 0}
        end = {"proof": 40, "dense_diagnostic_cells": 51840,
               "dense_diagnostic_packed_cells": 51840,
               "dense_diagnostic_partition_errors": 0,
               "dense_diagnostic_reserved_bit_errors": 0,
               "dense_proof_atlas_pending": 0}
        relative, _absolute, failures = VERIFIER._segment_relative_counters(
            end, baseline, keys, asynchronous_atlas=False)
        self.assertEqual([], failures)
        self.assertEqual(30 * 1296,
                         relative["dense_diagnostic_packed_cells"])

        # Schema36 preserves every packed-mask predicate but partitions the
        # bounded enqueue budget by presentation epoch. A late old-epoch PBO
        # completion is visible as excluded transport and cannot increment
        # proof/quality evidence.
        v36 = dict(common, proof_contract=VERIFIER.DENSE_V36_PROOF_CONTRACT,
                   proof_schema_version=36,
                   dense_variant="fragment-160x90-v36-epoch-bound-packed-mask",
                   dense_proof_atlas_layout=4,
                   dense_proof_atlas_enqueued=3,
                   dense_proof_atlas_completed=3,
                   proof_evidence_presentation_epoch=4,
                   proof_evidence_enqueued_in_epoch=2,
                   proof_evidence_accepted=2,
                   proof_evidence_excluded=1,
                   proof_evidence_last_accepted_atlas_sequence=2)
        base36 = materialize(VERIFIER.HEALTH_BASE_V36.pattern, v36)
        extension36 = materialize(
            VERIFIER.HEALTH_DENSE_EXTENSION_V36.pattern, v36)
        joined36 = VERIFIER._parse_health_records(
            prefix + base36 + "\n" + prefix + extension36)[0][0]
        decoded36 = {
            key: (value if key in (
                      "role", "proof_contract", "dense_variant",
                      "dense_diagnostic_mask_layout") else
                  (None if value is None else int(value)))
            for key, value in joined36.groupdict().items()
        }
        self.assertEqual([], VERIFIER._v36_diagnostic_hierarchy(decoded36))
        self.assertEqual(4, decoded36["proof_evidence_presentation_epoch"])

        # Schema37 keeps the proof transport but permits timestamp resampling
        # to select more than one distinct synthetic position from a source
        # interval. Aggregate output remains <=2x the consumed source and the
        # in-band target timestamp is positive/monotonic evidence.
        v37 = dict(
            v36, proof_contract=VERIFIER.DENSE_V37_PROOF_CONTRACT,
            proof_schema_version=37,
            dense_variant="fragment-128x72-v37-timestamp-resample",
            dense_proof_atlas_layout=5,
            locked=30, output=60, panel=120,
            window_presents=40, window_generated=30,
            window_real_priority=10, window_synthetic_selected=30,
            window_promoted=25, window_duplicate_pair_selection=0,
            endpoint_fifo_coalesced=0, endpoint_timestamp_corrections=0,
            dense_diagnostic_last_target_source_ns=1_500_000_000,
        )
        base37 = materialize(VERIFIER.HEALTH_BASE_V37.pattern, v37)
        extension37 = materialize(
            VERIFIER.HEALTH_DENSE_EXTENSION_V37.pattern, v37)
        joined37 = VERIFIER._parse_health_records(
            prefix + base37 + "\n" + prefix + extension37)[0][0]
        decoded37 = {
            key: (value if key in (
                      "role", "proof_contract", "dense_variant",
                      "dense_diagnostic_mask_layout") else
                  (None if value is None else int(value)))
            for key, value in joined37.groupdict().items()
        }
        self.assertEqual([], VERIFIER._v37_diagnostic_hierarchy(decoded37))
        self.assertEqual([], VERIFIER._v37_output_accounting_hierarchy(decoded37))
        classified, fallback, segment_classified = \
            VERIFIER._rational_visible_accounting(
                [decoded37, decoded37],
                dict(decoded37, presents=80))
        self.assertEqual(40, classified)
        self.assertEqual(0, fallback)
        self.assertEqual(80, segment_classified)
        _classified, fallback, _segment_classified = \
            VERIFIER._rational_visible_accounting(
                [dict(decoded37, window_presents=41)],
                dict(decoded37, presents=41))
        self.assertEqual(1, fallback)
        self.assertTrue(VERIFIER._v37_output_accounting_hierarchy(dict(
            decoded37, window_presents=53)))
        self.assertEqual([], VERIFIER._v37_output_accounting_hierarchy(dict(
            decoded37, window_due_no_endpoint=1)))
        self.assertTrue(VERIFIER._v37_diagnostic_hierarchy(dict(
            decoded37, dense_diagnostic_last_target_source_ns=0)))
        self.assertTrue(VERIFIER._v28_workload_identity_valid(dict(
            decoded37, dense_analysis_width=128, dense_analysis_height=72,
            dense_solve_texels=101376, dense_total_texels=125568),
            1920, 1080))

        # Schema38 keeps the exact v37 timestamp/FIFO/atlas transport while
        # making the vector-trajectory proof semantics incompatible. It must
        # parse only under its own contract/variant and retain every v37
        # accounting invariant.
        v38 = dict(
            v37, proof_contract=VERIFIER.DENSE_V38_PROOF_CONTRACT,
            proof_schema_version=38,
            dense_variant="fragment-128x72-v38-vector-trajectory",
        )
        self.assertTrue(VERIFIER._window_completed_output_meets_cadence(dict(
            v38, window_due_no_endpoint=1, window_presents=120,
            output=120, window_start_ns=1_000_000_000,
            window_end_ns=2_009_000_000)))
        self.assertFalse(VERIFIER._window_completed_output_meets_cadence(dict(
            v38, window_due_no_endpoint=5, window_presents=120,
            output=120, window_start_ns=1_000_000_000,
            window_end_ns=2_043_000_000)))
        base38 = materialize(VERIFIER.HEALTH_BASE_V38.pattern, v38)
        extension38 = materialize(
            VERIFIER.HEALTH_DENSE_EXTENSION_V38.pattern, v38)
        joined38 = VERIFIER._parse_health_records(
            prefix + base38 + "\n" + prefix + extension38)[0][0]
        decoded38 = {
            key: (value if key in (
                      "role", "proof_contract", "dense_variant",
                      "dense_diagnostic_mask_layout") else
                  (None if value is None else int(value)))
            for key, value in joined38.groupdict().items()
        }
        self.assertEqual([], VERIFIER._v37_diagnostic_hierarchy(decoded38))
        self.assertEqual([], VERIFIER._v37_output_accounting_hierarchy(decoded38))
        self.assertTrue(VERIFIER._v28_workload_identity_valid(dict(
            decoded38, dense_analysis_width=128, dense_analysis_height=72,
            dense_solve_texels=101376, dense_total_texels=125568),
            1920, 1080))

        # Schema39 is deliberately incompatible with v38 even though the
        # vector/image proof is unchanged: Android presentation timestamps and
        # the durable three-window cadence reject are now normative evidence.
        v39 = dict(
            v38, proof_contract=VERIFIER.DENSE_V39_PROOF_CONTRACT,
            proof_schema_version=39,
            dense_variant="fragment-128x72-v39-present-timed-vector-trajectory",
            presentation_timing_mode="egl-android-next-vsync",
            cadence_reject_consecutive_windows=3,
        )
        base39 = materialize(VERIFIER.HEALTH_BASE_V39.pattern, v39)
        extension39 = materialize(
            VERIFIER.HEALTH_DENSE_EXTENSION_V39.pattern, v39)
        joined39 = VERIFIER._parse_health_records(
            prefix + base39 + "\n" + prefix + extension39)[0][0]
        decoded39 = {
            key: (value if key in (
                      "role", "proof_contract", "dense_variant",
                      "dense_diagnostic_mask_layout",
                      "presentation_timing_mode") else
                  (None if value is None else int(value)))
            for key, value in joined39.groupdict().items()
        }
        self.assertEqual("egl-android-next-vsync",
                         decoded39["presentation_timing_mode"])
        self.assertEqual(3, decoded39["cadence_reject_consecutive_windows"])
        self.assertEqual([], VERIFIER._v37_diagnostic_hierarchy(decoded39))
        self.assertEqual([], VERIFIER._v37_output_accounting_hierarchy(decoded39))
        self.assertTrue(VERIFIER._v28_workload_identity_valid(dict(
            decoded39, dense_analysis_width=128, dense_analysis_height=72,
            dense_solve_texels=101376, dense_total_texels=125568),
            1920, 1080))
        with self.assertRaisesRegex(ValueError, "malformed or truncated"):
            VERIFIER._parse_health_records(
                prefix + base39.replace(
                    " presentationTimingMode=egl-android-next-vsync", "", 1) +
                "\n" + prefix + extension39)

        # Schema40 is transport-identical to v39 but has an incompatible
        # estimator identity: the preceding validated flow may only enter as
        # a confidence- and current-cost-checked proposal.
        v40 = dict(
            v39, proof_contract=VERIFIER.DENSE_V40_PROOF_CONTRACT,
            proof_schema_version=40,
            dense_variant=(
                "fragment-128x72-v40-temporal-flow-guidance-"
                "present-timed-vector-trajectory"),
        )
        base40 = materialize(VERIFIER.HEALTH_BASE_V40.pattern, v40)
        extension40 = materialize(
            VERIFIER.HEALTH_DENSE_EXTENSION_V40.pattern, v40)
        joined40 = VERIFIER._parse_health_records(
            prefix + base40 + "\n" + prefix + extension40)[0][0]
        decoded40 = {
            key: (value if key in (
                      "role", "proof_contract", "dense_variant",
                      "dense_diagnostic_mask_layout",
                      "presentation_timing_mode") else
                  (None if value is None else int(value)))
            for key, value in joined40.groupdict().items()
        }
        self.assertEqual(40, decoded40["proof_schema_version"])
        self.assertEqual([], VERIFIER._v37_diagnostic_hierarchy(decoded40))
        self.assertEqual([], VERIFIER._v37_output_accounting_hierarchy(decoded40))
        self.assertTrue(VERIFIER._v28_workload_identity_valid(dict(
            decoded40, dense_analysis_width=128, dense_analysis_height=72,
            dense_solve_texels=101376, dense_total_texels=125568),
            1920, 1080))
        with self.assertRaisesRegex(ValueError, "common key mismatch"):
            VERIFIER._parse_health_records(
                prefix + base40 + "\n" + prefix + extension39)

        # Schema41 rejects the stale-flow tie allowance used by v40.  It is
        # transport-compatible but carries an immutable strict-admission
        # identity, so a v40 extension cannot complete a v41 base.
        v41 = dict(
            v40, proof_contract=VERIFIER.DENSE_V41_PROOF_CONTRACT,
            proof_schema_version=41,
            dense_variant=(
                "fragment-128x72-v41-strict-temporal-flow-guidance-"
                "present-timed-vector-trajectory"),
        )
        base41 = materialize(VERIFIER.HEALTH_BASE_V41.pattern, v41)
        extension41 = materialize(
            VERIFIER.HEALTH_DENSE_EXTENSION_V41.pattern, v41)
        joined41 = VERIFIER._parse_health_records(
            prefix + base41 + "\n" + prefix + extension41)[0][0]
        decoded41 = {
            key: (value if key in (
                      "role", "proof_contract", "dense_variant",
                      "dense_diagnostic_mask_layout",
                      "presentation_timing_mode") else
                  (None if value is None else int(value)))
            for key, value in joined41.groupdict().items()
        }
        self.assertEqual(41, decoded41["proof_schema_version"])
        self.assertEqual([], VERIFIER._v37_diagnostic_hierarchy(decoded41))
        self.assertEqual([], VERIFIER._v37_output_accounting_hierarchy(decoded41))
        self.assertTrue(VERIFIER._v28_workload_identity_valid(dict(
            decoded41, dense_analysis_width=128, dense_analysis_height=72,
            dense_solve_texels=101376, dense_total_texels=125568),
            1920, 1080))
        with self.assertRaisesRegex(ValueError, "common key mismatch"):
            VERIFIER._parse_health_records(
                prefix + base41 + "\n" + prefix + extension40)
        coalesced36 = dict(
            decoded36, promoted=13, real=14, submitted=14,
            dense_diagnostic_last_previous_endpoint=13,
            dense_diagnostic_last_current_endpoint=14)
        self.assertEqual(
            [], VERIFIER._v36_diagnostic_hierarchy(coalesced36))
        nonadjacent36 = dict(
            coalesced36, dense_diagnostic_last_current_endpoint=15)
        self.assertTrue(any(
            "endpoint binding" in failure for failure in
            VERIFIER._v36_diagnostic_hierarchy(nonadjacent36)))
        self.assertTrue(VERIFIER._v28_workload_identity_valid(dict(
            decoded36, dense_analysis_width=160, dense_analysis_height=90,
            dense_solve_texels=158080, dense_total_texels=195840),
            1920, 1080))
        with self.assertRaisesRegex(ValueError, "common key mismatch"):
            VERIFIER._parse_health_records(
                prefix + base36 + "\n" + prefix + extension36.replace(
                    "proofEvidencePresentationEpoch=4",
                    "proofEvidencePresentationEpoch=5", 1))
        for field, value, expected in (
                ("proof_evidence_presentation_epoch", 5, "epoch"),
                ("proof_evidence_enqueued_in_epoch", 121, "budget"),
                ("proof_evidence_accepted", 1, "conservation"),
                ("proof_evidence_excluded", 0, "conservation"),
                ("proof_evidence_last_accepted_atlas_sequence", 3,
                 "binding")):
            with self.subTest(v36_field=field):
                failures = VERIFIER._v36_diagnostic_hierarchy(
                    dict(decoded36, **{field: value}))
                self.assertTrue(
                    any(expected in item for item in failures), failures)

        relative, _absolute, failures = VERIFIER._segment_relative_counters(
            {
                "proof": 77, "proof_evidence_accepted": 77,
                "proof_evidence_excluded": 1,
                "dense_proof_atlas_enqueued": 78,
                "dense_proof_atlas_completed": 78,
                "dense_proof_atlas_pending": 0,
            },
            {
                "proof": 47, "proof_evidence_accepted": 47,
                "proof_evidence_excluded": 1,
                "dense_proof_atlas_enqueued": 48,
                "dense_proof_atlas_completed": 48,
                "dense_proof_atlas_pending": 0,
            },
            ("proof", "proof_evidence_accepted", "proof_evidence_excluded",
             "dense_proof_atlas_enqueued", "dense_proof_atlas_completed"),
            asynchronous_atlas=True)
        self.assertEqual([], failures)
        self.assertEqual(30, relative["proof"])
        self.assertEqual(30, relative["proof_evidence_accepted"])
        self.assertEqual(0, relative["proof_evidence_excluded"])

    def test_v35_explicit_reset_requires_zero_packed_mask_epoch(self):
        baseline = {key: 0 for key in
                    VERIFIER.RESET_COUNTER_FIELDS +
                    VERIFIER.V35_RESET_COUNTER_FIELDS}
        baseline.update({"window_end_ns": 2_000_000_000, "line_index": 20})
        end = {"line_index": 40}
        events = [
            {"pid": 123, "generator": 7, "lineIndex": 10,
             "enabled": False,
             "proofContract": VERIFIER.DENSE_V35_PROOF_CONTRACT,
             "proofSchemaVersion": 35},
            {"pid": 123, "generator": 7, "lineIndex": 11,
             "enabled": True,
             "proofContract": VERIFIER.DENSE_V35_PROOF_CONTRACT,
             "proofSchemaVersion": 35},
        ]
        reset = {"pid": 123, "generator": 7, "disabledLineIndex": 10,
                 "enabledLineIndex": 11,
                 "baselineWindowEndNs": 2_000_000_000}
        self.assertEqual(reset, VERIFIER._validate_proof_reset(
            reset, events, [baseline], baseline, end, pid=123, generator=7,
            proof_contract=VERIFIER.DENSE_V35_PROOF_CONTRACT,
            proof_schema_version=35))
        dirty = dict(baseline, dense_diagnostic_packed_cells=1)
        with self.assertRaisesRegex(ValueError, "v35 diagnostic counters"):
            VERIFIER._validate_proof_reset(
                reset, events, [dirty], dirty, end, pid=123, generator=7,
                proof_contract=VERIFIER.DENSE_V35_PROOF_CONTRACT,
                proof_schema_version=35)

    def test_v36_explicit_reset_requires_zero_epoch_evidence_counters(self):
        baseline = {key: 0 for key in
                    VERIFIER.RESET_COUNTER_FIELDS +
                    VERIFIER.V36_RESET_COUNTER_FIELDS}
        baseline.update({"window_end_ns": 2_000_000_000, "line_index": 20})
        end = {"line_index": 40}
        events = [
            {"pid": 123, "generator": 7, "lineIndex": 10,
             "enabled": False,
             "proofContract": VERIFIER.DENSE_V36_PROOF_CONTRACT,
             "proofSchemaVersion": 36},
            {"pid": 123, "generator": 7, "lineIndex": 11,
             "enabled": True,
             "proofContract": VERIFIER.DENSE_V36_PROOF_CONTRACT,
             "proofSchemaVersion": 36},
        ]
        reset = {"pid": 123, "generator": 7, "disabledLineIndex": 10,
                 "enabledLineIndex": 11,
                 "baselineWindowEndNs": 2_000_000_000}
        self.assertEqual(reset, VERIFIER._validate_proof_reset(
            reset, events, [baseline], baseline, end, pid=123, generator=7,
            proof_contract=VERIFIER.DENSE_V36_PROOF_CONTRACT,
            proof_schema_version=36))
        dirty = dict(baseline, proof_evidence_excluded=1)
        with self.assertRaisesRegex(ValueError, "v36 evidence counters"):
            VERIFIER._validate_proof_reset(
                reset, events, [dirty], dirty, end, pid=123, generator=7,
                proof_contract=VERIFIER.DENSE_V36_PROOF_CONTRACT,
                proof_schema_version=36)

    def test_diagnostic_zero_callback_is_exact_empty_reset_only(self):
        empty = {
            "window_presentation_callbacks": 0, "window_presents": 0,
            "proof": 0, "dense_proof_cells": 0,
            "dense_diagnostic_cells": 0, "dense_diagnostic_tiles": 0,
            "dense_diagnostic_packed_cells": 0,
            "dense_diagnostic_mask_layout": "packed-nearest-bf-v1",
            "dense_diagnostic_partition_errors": 0,
            "dense_diagnostic_reserved_bit_errors": 0,
            "dense_diagnostic_mask_errors": 0,
            "dense_proof_atlas_layout": 3,
            "dense_proof_atlas_enqueued": 0,
            "dense_proof_atlas_completed": 0,
            "dense_proof_atlas_pending": 0,
            "dense_promotions": 0, "promoted": 393,
            "dense_diagnostic_last_atlas_sequence": 0,
            "dense_diagnostic_last_pair_sequence": 0,
            "dense_diagnostic_last_previous_endpoint": 0,
            "dense_diagnostic_last_current_endpoint": 0,
        }
        for direction in ("backward", "forward"):
            for suffix in (
                    "valid", "active", "in_bounds", "cycle_valid",
                    "photometric_valid", "texture_valid", "saturated",
                    "out_of_bounds", "covered_tiles", "covered_tile_mask"):
                empty[f"dense_{direction}_{suffix}"] = 0
        self.assertTrue(VERIFIER._diagnostic_empty_reset_snapshot(
            empty, v35=True))
        self.assertEqual([], VERIFIER._v35_diagnostic_hierarchy(empty))

        adversaries = [
            "window_presents", "proof", "dense_proof_cells",
            "dense_diagnostic_cells", "dense_diagnostic_tiles",
            "dense_diagnostic_packed_cells", "dense_proof_atlas_enqueued",
            "dense_proof_atlas_completed", "dense_proof_atlas_pending",
            "dense_promotions", "dense_diagnostic_mask_errors",
            "dense_diagnostic_partition_errors",
            "dense_diagnostic_reserved_bit_errors",
            "dense_diagnostic_last_atlas_sequence",
            "dense_diagnostic_last_pair_sequence",
            "dense_diagnostic_last_previous_endpoint",
            "dense_diagnostic_last_current_endpoint",
        ]
        for direction in ("backward", "forward"):
            adversaries.extend(f"dense_{direction}_{suffix}" for suffix in (
                "valid", "active", "in_bounds", "cycle_valid",
                "photometric_valid", "texture_valid", "saturated",
                "out_of_bounds", "covered_tiles", "covered_tile_mask"))
        for field in adversaries:
            with self.subTest(v35_nonzero=field):
                record = dict(empty, **{field: 1})
                self.assertFalse(VERIFIER._diagnostic_empty_reset_snapshot(
                    record, v35=True))
                failures = VERIFIER._v35_diagnostic_hierarchy(record)
                self.assertTrue(any("callback window" in item
                                    for item in failures), failures)

        # Schema34 has the same reset transport and must not retain the latent
        # unconditional-positive-callback defect.
        v34 = {key: value for key, value in empty.items() if key not in (
            "dense_diagnostic_packed_cells",
            "dense_diagnostic_mask_layout",
            "dense_diagnostic_partition_errors",
            "dense_diagnostic_reserved_bit_errors")}
        v34["dense_proof_atlas_layout"] = 2
        self.assertTrue(VERIFIER._diagnostic_empty_reset_snapshot(
            v34, v35=False))
        self.assertEqual([], VERIFIER._v34_diagnostic_hierarchy(v34))
        for field in ("dense_proof_atlas_enqueued",
                      "dense_backward_in_bounds",
                      "dense_diagnostic_last_pair_sequence"):
            with self.subTest(v34_nonzero=field):
                failures = VERIFIER._v34_diagnostic_hierarchy(
                    dict(v34, **{field: 1}))
                self.assertTrue(any("callback window" in item
                                    for item in failures), failures)

    def test_v22_health_without_v27_workload_block_remains_parseable(self):
        line = health_line(health_values(2_000_000_000, 1))
        match = VERIFIER.HEALTH.search(line)
        self.assertIsNotNone(match)
        self.assertIsNone(match.group("dense_variant"))
        for field in ("dense_analysis_width", "dense_analysis_height",
                      "dense_solve_texels", "dense_total_texels"):
            self.assertIsNone(match.group(field))

    def test_fractional_100_on_120_is_balanced_panel_quantized_cadence(self):
        result = VERIFIER._panel_quantized_latch_cadence(
            quantized_timestamps(120, 100, 3), 120, 100)
        self.assertTrue(result["valid"], result)
        self.assertEqual({1, 2}, set(result["intervalTicks"]))

    def test_fractional_80_on_120_is_balanced_panel_quantized_cadence(self):
        result = VERIFIER._panel_quantized_latch_cadence(
            quantized_timestamps(120, 80, 3), 120, 80)
        self.assertTrue(result["valid"], result)
        self.assertEqual({1, 2}, set(result["intervalTicks"]))

    def test_fractional_cadence_rejects_a_missing_vsync(self):
        timestamps = quantized_timestamps(120, 100, 3)
        timestamps[20] += round(1_000_000_000 / 120)
        result = VERIFIER._panel_quantized_latch_cadence(
            timestamps, 120, 100)
        self.assertFalse(result["valid"], result)

    def test_fractional_cadence_rejects_clustered_compensating_gaps(self):
        tick = round(1_000_000_000 / 120)
        # The average is exactly 100 Hz and every interval is individually an
        # allowed one/two-vsync interval, but clustering all long gaps creates
        # a visible pacing excursion that a mean-rate check would miss.
        intervals = [2] * 12 + [1] * 48
        timestamps = [1_000_000_000]
        for interval in intervals:
            timestamps.append(timestamps[-1] + interval * tick)
        result = VERIFIER._panel_quantized_latch_cadence(
            timestamps, 120, 100)
        self.assertFalse(result["valid"], result)
        self.assertEqual(1.0, result["quantizedFraction"])
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.fixture = EvidenceFixture(Path(self.temporary.name))

    def tearDown(self):
        self.temporary.cleanup()

    def test_steady_tier_passes_with_segment_relative_proof(self):
        report = self.fixture.verify()
        self.assertTrue(report["passed"], report["failures"])
        self.assertEqual(60, report["generator"]["proof"])
        self.assertEqual(0, report["presentAccounting"]["segmentFallback"])

    def test_missing_manifest_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "manifest is required"):
            VERIFIER.verify(self.fixture.log, self.fixture.latency)

    def test_v20_contract_cannot_qualify_v21(self):
        source = self.fixture.log.read_text(encoding="utf-8").replace(
            "native-pixel-refined-regional-flow-v22-x2-presented",
            "affine-neighbor-regional-flow-v20-content-unique",
        ).replace("proofSchemaVersion=22", "proofSchemaVersion=20")
        source = source.replace(
            "v21DirectionallyEligibleSyntheticPixels=",
            "v20DirectionallyEligibleSyntheticPixels=",
        ).replace(
            "v21CorrectVectorPredictedSyntheticPixels=",
            "v20CorrectVectorPredictedSyntheticPixels=",
        )
        self.fixture.log.write_text(source, encoding="utf-8")
        self.fixture.rebind_evidence()
        with self.assertRaisesRegex(ValueError, "no complete primary/display-0"):
            self.fixture.verify()

    def test_identity_mismatch_fails_closed(self):
        self.fixture.document["identity"]["romSha256"] = "not-a-sha"
        self.fixture.write_manifest()
        with self.assertRaisesRegex(ValueError, "romSha256"):
            self.fixture.verify()

    def test_schema43_rational_clock_identity_is_exact(self):
        record = {
            "source_millihz": 59_940,
            "target_millihz": 60_000,
            "panel_millihz": 120_000,
            "panel_scans_per_output": 2,
            "uniform_output_qualified": 1,
            "output": 60,
            "panel": 120,
            "window_ms": 2_000,
            "window_presents": 120,
            "window_swap_millihz": 60_000,
            "source_clock_kind": "pts",
        }
        self.assertEqual([], VERIFIER._v43_rational_clock_hierarchy(record))
        rational = dict(record,
                        source_millihz=59_940,
                        target_millihz=119_880,
                        panel_millihz=119_880,
                        panel_scans_per_output=1,
                        output=120,
                        window_ms=1_000,
                        window_presents=120,
                        window_swap_millihz=120_000,
                        source_clock_kind="auth")
        self.assertEqual([], VERIFIER._v43_rational_clock_hierarchy(rational))

    def test_schema43_unqualified_direct_clock_is_parseable_but_exact(self):
        record = {
            "source_millihz": 59_700,
            "target_millihz": 59_700,
            "panel_millihz": 120_000,
            "panel_scans_per_output": 0,
            "uniform_output_qualified": 0,
            "output": 60,
            "panel": 120,
            "window_ms": 1_000,
            "window_presents": 60,
            "window_swap_millihz": 60_000,
            "source_clock_kind": "pts",
        }
        self.assertEqual([], VERIFIER._v43_rational_clock_hierarchy(record))
        for mutation in (
                {"panel_scans_per_output": 2},
                {"target_millihz": 60_000},
                {"uniform_output_qualified": 1},
                {"window_swap_millihz": 59_000}):
            with self.subTest(mutation=mutation):
                candidate = dict(record)
                candidate.update(mutation)
                self.assertTrue(
                    VERIFIER._v43_rational_clock_hierarchy(candidate))

    def test_schema43_rational_clock_adversaries_fail_closed(self):
        record = {
            "source_millihz": 59_940,
            "target_millihz": 60_000,
            "panel_millihz": 120_000,
            "panel_scans_per_output": 2,
            "uniform_output_qualified": 1,
            "output": 60,
            "panel": 120,
            "window_ms": 2_000,
            "window_presents": 120,
            "window_swap_millihz": 60_000,
            "source_clock_kind": "producer-pts",
        }
        adversaries = (
            dict(target_millihz=120_000, panel_scans_per_output=1,
                 output=120),
            dict(target_millihz=100_000, panel_scans_per_output=1,
                 output=100),
            dict(uniform_output_qualified=0),
            dict(window_swap_millihz=59_999),
            dict(source_clock_kind="callback-count"),
            dict(panel_millihz=119_880),
        )
        for mutation in adversaries:
            with self.subTest(mutation=mutation):
                candidate = dict(record)
                candidate.update(mutation)
                self.assertTrue(
                    VERIFIER._v43_rational_clock_hierarchy(candidate))

    def test_schema43_segment_rejects_unstable_or_mixed_clocks(self):
        base = {
            "source_millihz": 59_940,
            "target_millihz": 60_000,
            "panel_millihz": 120_000,
            "panel_scans_per_output": 2,
            "source_clock_kind": "pts",
        }
        stable = [dict(base, source_millihz=value)
                  for value in (59_900, 59_940, 60_000)]
        self.assertEqual([], VERIFIER._v43_segment_clock_hierarchy(stable))
        unstable = [dict(base, source_millihz=value)
                    for value in (57_000, 58_200, 59_000)]
        self.assertTrue(VERIFIER._v43_segment_clock_hierarchy(unstable))
        mixed = stable + [dict(base, target_millihz=120_000,
                               panel_scans_per_output=1)]
        self.assertTrue(VERIFIER._v43_segment_clock_hierarchy(mixed))

    def test_schema43_through_51_transport_require_bound_rational_clock_record(self):
        cases = (
            (43, VERIFIER.DENSE_V43_PROOF_CONTRACT,
             "fragment-128x72-v43-rational-source-panel-clock-strict-flow",
             VERIFIER.HEALTH_BASE_V43,
             VERIFIER.HEALTH_DENSE_EXTENSION_V43,
             VERIFIER.HEALTH_RATIONAL_CLOCK_V43),
            (44, VERIFIER.DENSE_V44_PROOF_CONTRACT,
             "fragment-128x72-v44-unique-endpoint-rational-clock-strict-flow",
             VERIFIER.HEALTH_BASE_V44,
             VERIFIER.HEALTH_DENSE_EXTENSION_V44,
             VERIFIER.HEALTH_RATIONAL_CLOCK_V44),
            (45, VERIFIER.DENSE_V45_PROOF_CONTRACT,
             "fragment-128x72-v45-spatial-consensus-rational-clock-strict-flow",
             VERIFIER.HEALTH_BASE_V45,
             VERIFIER.HEALTH_DENSE_EXTENSION_V45,
             VERIFIER.HEALTH_RATIONAL_CLOCK_V45),
            (46, VERIFIER.DENSE_V46_PROOF_CONTRACT,
             "fragment-128x72-v46-independent-bidirectional-spatial-consensus-rational-clock-strict-flow",
             VERIFIER.HEALTH_BASE_V46,
             VERIFIER.HEALTH_DENSE_EXTENSION_V46,
             VERIFIER.HEALTH_RATIONAL_CLOCK_V46),
            (47, VERIFIER.DENSE_V47_PROOF_CONTRACT,
             "fragment-128x72-v47-stamped-pts-loss-bound-independent-bidirectional-spatial-consensus-rational-clock-strict-flow",
             VERIFIER.HEALTH_BASE_V47,
             VERIFIER.HEALTH_DENSE_EXTENSION_V47,
             VERIFIER.HEALTH_RATIONAL_CLOCK_V47),
            (48, VERIFIER.DENSE_V48_PROOF_CONTRACT,
             "fragment-128x72-v48-reciprocal-proposal-stamped-pts-loss-bound-bidirectional-spatial-consensus-rational-clock-strict-flow",
             VERIFIER.HEALTH_BASE_V48,
             VERIFIER.HEALTH_DENSE_EXTENSION_V48,
             VERIFIER.HEALTH_RATIONAL_CLOCK_V48),
            (49, VERIFIER.DENSE_V49_PROOF_CONTRACT,
             "fragment-128x72-v49-multilevel-reciprocal-proposal-stamped-pts-loss-bound-bidirectional-spatial-consensus-rational-clock-strict-flow",
             VERIFIER.HEALTH_BASE_V49,
             VERIFIER.HEALTH_DENSE_EXTENSION_V49,
             VERIFIER.HEALTH_RATIONAL_CLOCK_V49),
            (50, VERIFIER.DENSE_V50_PROOF_CONTRACT,
             "fragment-128x72-v50-iterated-multilevel-reciprocal-proposal-stamped-pts-loss-bound-bidirectional-spatial-consensus-rational-clock-strict-flow",
             VERIFIER.HEALTH_BASE_V50,
             VERIFIER.HEALTH_DENSE_EXTENSION_V50,
             VERIFIER.HEALTH_RATIONAL_CLOCK_V50),
            (51, VERIFIER.DENSE_V51_PROOF_CONTRACT,
             "fragment-128x72-v51-cost-tested-bidirectional-refinement-stamped-pts-loss-bound-spatial-consensus-rational-clock-strict-flow",
             VERIFIER.HEALTH_BASE_V51,
             VERIFIER.HEALTH_DENSE_EXTENSION_V51,
             VERIFIER.HEALTH_RATIONAL_CLOCK_V51),
            (54, VERIFIER.DENSE_V54_PROOF_CONTRACT,
             "fragment-128x72-v54-cycle-aware-cost-tested-bidirectional-refinement-stamped-pts-loss-bound-spatial-consensus-rational-clock-strict-flow",
             VERIFIER.HEALTH_BASE_V54,
             VERIFIER.HEALTH_DENSE_EXTENSION_V54,
             VERIFIER.HEALTH_RATIONAL_CLOCK_V54),
            (55, VERIFIER.DENSE_V55_PROOF_CONTRACT,
             "fragment-128x72-v55-cycle-regularized-cost-tested-bidirectional-refinement-stamped-pts-loss-bound-spatial-consensus-rational-clock-strict-flow",
             VERIFIER.HEALTH_BASE_V55,
             VERIFIER.HEALTH_DENSE_EXTENSION_V55,
             VERIFIER.HEALTH_RATIONAL_CLOCK_V55),
            (56, VERIFIER.DENSE_V56_PROOF_CONTRACT,
             "fragment-128x72-v56-strong-cycle-regularized-cost-tested-bidirectional-refinement-stamped-pts-loss-bound-spatial-consensus-rational-clock-strict-flow",
             VERIFIER.HEALTH_BASE_V56,
             VERIFIER.HEALTH_DENSE_EXTENSION_V56,
             VERIFIER.HEALTH_RATIONAL_CLOCK_V56),
            (57, VERIFIER.DENSE_V57_PROOF_CONTRACT,
             "fragment-v57-joint-cycle",
             VERIFIER.HEALTH_BASE_V57,
             VERIFIER.HEALTH_DENSE_EXTENSION_V57,
             VERIFIER.HEALTH_RATIONAL_CLOCK_V57),
            (58, VERIFIER.DENSE_V58_PROOF_CONTRACT,
             "fragment-v58-joint-cycle",
             VERIFIER.HEALTH_BASE_V58,
             VERIFIER.HEALTH_DENSE_EXTENSION_V58,
             VERIFIER.HEALTH_RATIONAL_CLOCK_V58),
            (59, VERIFIER.DENSE_V59_PROOF_CONTRACT,
             "fragment-v59-edge-aware-neighbor",
             VERIFIER.HEALTH_BASE_V59,
             VERIFIER.HEALTH_DENSE_EXTENSION_V59,
             VERIFIER.HEALTH_RATIONAL_CLOCK_V59),
            (60, VERIFIER.DENSE_V60_PROOF_CONTRACT,
             "fragment-v60-independent-global-seed",
             VERIFIER.HEALTH_BASE_V60,
             VERIFIER.HEALTH_DENSE_EXTENSION_V60,
             VERIFIER.HEALTH_RATIONAL_CLOCK_V60),
            (61, VERIFIER.DENSE_V61_PROOF_CONTRACT,
             "fragment-v61-parallel-global-seed",
             VERIFIER.HEALTH_BASE_V61,
             VERIFIER.HEALTH_DENSE_EXTENSION_V61,
             VERIFIER.HEALTH_RATIONAL_CLOCK_V61),
        )
        prefix = "08-14 12:00:00.000  4321  4322 I EmuFusionFrameGen: "
        for schema, contract, variant, base_pattern, extension_pattern, clock_pattern in cases:
            common = {
                "generator": 7, "role": "primary", "display_id": 0,
                "proof_contract": contract,
                "proof_schema_version": schema, "health_sequence": 9,
                "presents": 120, "window_start_ns": 1_000_000_000,
                "window_end_ns": 2_000_000_000,
                "proof_evidence_presentation_epoch": 4,
                "cadence_reject_consecutive_windows": 3,
                "source_millihz": 59_940, "target_millihz": 60_000,
                "panel_millihz": 120_000, "panel_scans_per_output": 2,
                "uniform_output_qualified": 1,
                "window_swap_millihz": 60_000,
                "source_clock_kind": "pts",
            }

            def materialize(pattern):
                def replace(match):
                    name = match.group(1)
                    if name in common:
                        return str(common[name])
                    if name == "dense_variant":
                        return variant
                    if name == "dense_diagnostic_mask_layout":
                        return "packed-nearest-bf-v1"
                    if name == "presentation_timing_mode":
                        return "egl-android-next-vsync"
                    return "1"
                return re.sub(r"\(\?P<([a-z0-9_]+)>[^)]*\)", replace,
                              pattern).replace(
                                  ".*?", "producerHz=59.94 ").removesuffix("$")

            base = materialize(base_pattern.pattern)
            extension = materialize(extension_pattern.pattern)
            clock = materialize(clock_pattern.pattern)
            with self.subTest(schema=schema):
                records = VERIFIER._parse_health_records(
                    prefix + base + "\n" + prefix + extension + "\n" +
                    prefix + clock)
                self.assertEqual(1, len(records))
                self.assertEqual("59940",
                                 records[0][0].group("source_millihz"))
                with self.assertRaisesRegex(ValueError, "completion"):
                    VERIFIER._parse_health_records(
                        prefix + base + "\n" + prefix + extension)
                with self.assertRaisesRegex(ValueError,
                                            "common key mismatch"):
                    VERIFIER._parse_health_records(
                        prefix + base + "\n" + prefix + extension + "\n" +
                        prefix + clock.replace(
                            "healthSequence=9", "healthSequence=10", 1))

    def test_manifest_cannot_be_reused_with_different_evidence(self):
        self.fixture.log.write_text(
            self.fixture.log.read_text() + "I/Unrelated( 999): mutation\n",
            encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "exact evidence files"):
            self.fixture.verify()

    def test_route_must_bind_core_and_system_to_selected_process(self):
        self.fixture.log.write_text(
            self.fixture.log.read_text().replace(
                "InWindowGameHost( 123)", "InWindowGameHost( 999)"),
            encoding="utf-8")
        self.fixture.rebind_evidence()
        with self.assertRaisesRegex(ValueError, "matching game route"):
            self.fixture.verify()

    def test_session_bounds_must_contain_health_and_surface_evidence(self):
        self.fixture.document["identity"]["sessionEndNs"] = 14_500_000_000
        self.fixture.write_manifest()
        with self.assertRaisesRegex(ValueError, "outside its bound session"):
            self.fixture.verify()

    def test_prior_tier_cumulative_proof_does_not_qualify(self):
        directory = Path(self.temporary.name) / "prior"
        directory.mkdir()
        fixture = EvidenceFixture(directory, prior_proof=60, proof_increment=0)
        report = fixture.verify()
        self.assertFalse(report["passed"])
        self.assertIn("too few framebuffer proof samples", report["failures"])

    def test_unclassified_window_present_is_rejected(self):
        self.fixture.log.write_text(
            self.fixture.log.read_text().replace(
                "windowPresents=120 windowGenerated=60 windowPromoted=60",
                "windowPresents=120 windowGenerated=59 windowPromoted=60"),
            encoding="utf-8")
        self.fixture.rebind_evidence()
        report = self.fixture.verify()
        self.assertFalse(report["passed"])
        self.assertIn("cadence window contains undeclared fallback presents",
                      report["failures"])

    def test_explicit_bounded_fallback_is_reported_not_misclassified(self):
        self.fixture.log.write_text(
            self.fixture.log.read_text().replace(
                "windowPresents=120 windowGenerated=60 windowPromoted=60",
                "windowPresents=120 windowGenerated=59 windowPromoted=60"),
            encoding="utf-8")
        self.fixture.document["segments"][0]["maxFallbackPresents"] = 1
        self.fixture.rebind_evidence()
        report = self.fixture.verify()
        self.assertTrue(report["passed"], report["failures"])
        self.assertEqual(1, report["presentAccounting"]["windowFallback"])

    def test_steady_segment_rejects_mixed_tiers(self):
        self.fixture.log.write_text(
            self.fixture.log.read_text().replace(
                "lockedFps=60 outputFps=120 panelFps=120", "lockedFps=50 outputFps=120 panelFps=120", 1),
            encoding="utf-8")
        self.fixture.rebind_evidence()
        with self.assertRaisesRegex(ValueError, "mixes source tiers"):
            self.fixture.verify()

    def test_transition_passes_only_after_settled_target_baseline(self):
        directory = Path(self.temporary.name) / "transition"
        directory.mkdir()
        fixture = EvidenceFixture(directory, transition=True)
        report = fixture.verify()
        self.assertTrue(report["passed"], report["failures"])
        self.assertEqual(50, report["qualification"]["transition"]["expectedToFps"])

    def test_transition_rejects_post_settle_tier_oscillation(self):
        directory = Path(self.temporary.name) / "oscillation"
        directory.mkdir()
        fixture = EvidenceFixture(directory, transition=True)
        lines = fixture.log.read_text().splitlines()
        lines[-2] = lines[-2].replace("lockedFps=50", "lockedFps=60")
        fixture.log.write_text("\n".join(lines) + "\n", encoding="utf-8")
        fixture.rebind_evidence()
        with self.assertRaisesRegex(ValueError, "remain settled"):
            fixture.verify()


if __name__ == "__main__":
    unittest.main()
