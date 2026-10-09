import importlib.util
import hashlib
import json
import math
import re
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "unified-android" / "tools" / "verify_frame_generation_evidence.py"


def load_module():
    spec = importlib.util.spec_from_file_location("frame_evidence", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FrameGenerationEvidenceTest(unittest.TestCase):
    def test_schema42_uses_only_uniform_panel_divisors(self):
        module = load_module()
        self.assertEqual(
            [40, 60, 60, 60, 120],
            [module._schema42_output_fps(120, source)
             for source in (20, 30, 40, 50, 60)],
        )
        self.assertEqual(
            [30, 60, 60, 60, 60],
            [module._schema42_output_fps(60, source)
             for source in (20, 30, 40, 50, 60)],
        )
        valid = {
            "proof_schema_version": 42,
            "panel": 120, "locked": 50, "output": 60,
            "window_presents": 60, "window_real_priority": 10,
            "window_generated": 50, "window_synthetic_selected": 50,
            "window_promoted": 50,
            "window_duplicate_pair_selection": 0,
        }
        self.assertEqual([], module._v37_output_accounting_hierarchy(valid))
        invalid = dict(valid, output=100, window_presents=100,
                       window_real_priority=50)
        self.assertTrue(module._v37_output_accounting_hierarchy(invalid))
        for panel, source, output, exact_real, generated in (
                (120, 20, 40, 20, 20),
                (120, 30, 60, 30, 30),
                (120, 40, 60, 20, 40),
                (120, 50, 60, 10, 50),
                (120, 60, 120, 60, 60),
                (60, 20, 30, 10, 20),
                (60, 30, 60, 30, 30),
                (60, 40, 60, 20, 40),
                (60, 50, 60, 10, 50),
                (60, 60, 60, 60, 0)):
            with self.subTest(panel=panel, source=source):
                record = dict(
                    valid, panel=panel, locked=source, output=output,
                    window_presents=output,
                    window_real_priority=exact_real,
                    window_generated=generated,
                    window_synthetic_selected=generated,
                    window_promoted=source,
                )
                self.assertEqual(
                    [], module._v37_output_accounting_hierarchy(record))
                self.assertEqual(
                    (exact_real, generated),
                    module._schema36_rational_rates(source, output),
                )

    def verify(self, log, latency, **kwargs):
        """Bind legacy adversarial fixtures to the v1 qualification envelope."""
        module = load_module()
        proof_reset = kwargs.pop("proof_reset", None)
        segment_override = kwargs.pop("segment_override", None)
        source = log.read_text(encoding="utf-8")
        role = kwargs.get("role", "primary")
        display_id = kwargs.get("display_id", 0)
        selected = [match for match in module.HEALTH.finditer(source)
                    if match.group("role") == role and
                    int(match.group("display_id")) == display_id]
        first = selected[0] if selected else None
        last = selected[-1] if selected else None
        generator = int(first.group("generator")) if first else 7
        pid = 1234
        manifest = log.with_name("qualification.json")
        digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        segment = {
            "segmentId": "fixture-tier",
            "kind": "steady",
            "startWindowEndNs": int(first.group("window_end_ns")) if first else 1,
            "proofBaselineWindowEndNs": int(first.group("window_end_ns")) if first else 1,
            "endWindowEndNs": int(last.group("window_end_ns")) if last else 2,
            "expectedLockedFps": int(last.group("locked")) if last else 60,
            "maxFallbackPresents": 0,
        }
        if proof_reset is not None:
            segment["proofReset"] = proof_reset
        if segment_override is not None:
            segment = dict(segment_override)
        document = {
            "schemaVersion": 1,
            "evidence": {
                "logSha256": digest(log),
                "latencySha256": digest(latency),
            },
            "identity": {
                "sessionId": "fixture-session",
                "systemId": "nes",
                "gameId": "fixture-game",
                "coreId": "mesen",
                "packageName": "com.thorium.preview",
                "romSha256": "1" * 64,
                "coreSha256": "2" * 64,
                "apkSha256": "3" * 64,
                "pid": pid,
                "generator": generator,
                "role": role,
                "displayId": display_id,
                "sessionStartNs": 1,
                "sessionEndNs": 20_000_000_000,
            },
            "segments": [segment],
        }
        manifest.write_text(json.dumps(document), encoding="utf-8")
        return module.verify(log, latency, qualification_path=manifest,
                             segment_id="fixture-tier", **kwargs)

    @staticmethod
    def classify_pixels(previous, current, output, phase=0.5):
        """Exact CPU mirror of DisplayFrameGenerator's proof-pixel rules."""
        eligible = substantive = non_crossfade = 0
        for before, after, candidate in zip(previous, current, output):
            endpoint_span = sum(abs(a - b) for a, b in zip(before, after))
            if endpoint_span < 36:
                continue
            eligible += 1
            from_previous = sum(abs(value - a)
                                for value, a in zip(candidate, before))
            from_current = sum(abs(value - b)
                               for value, b in zip(candidate, after))
            fixed = tuple(round(a * (1.0 - phase) + b * phase)
                          for a, b in zip(before, after))
            from_crossfade = sum(abs(value - blended)
                                 for value, blended in zip(candidate, fixed))
            if (from_previous >= max(9, endpoint_span * 8 // 100) and
                    from_current >= max(9, endpoint_span * 8 // 100)):
                substantive += 1
            if from_crossfade >= max(9, endpoint_span * 6 // 100):
                non_crossfade += 1
        return eligible, substantive, non_crossfade

    @staticmethod
    def classify_vector_prediction(previous, current, output, predicted,
                                   inverse, phase=0.5):
        """CPU mirror of the directional prediction gate in frame proof."""
        eligible = synthesized = 0
        for before, after, candidate, reference, negative in zip(
                previous, current, output, predicted, inverse):
            endpoint_span = sum(abs(a - b) for a, b in zip(before, after))
            if endpoint_span < 36:
                continue
            fixed = tuple(round(a * (1.0 - phase) + b * phase)
                          for a, b in zip(before, after))
            from_previous = sum(abs(value - a)
                                for value, a in zip(candidate, before))
            from_current = sum(abs(value - b)
                               for value, b in zip(candidate, after))
            from_crossfade = sum(abs(value - blended)
                                 for value, blended in zip(candidate, fixed))
            prediction_error = sum(abs(value - expected)
                                   for value, expected in zip(candidate, reference))
            inverse_error = sum(abs(value - wrong)
                                for value, wrong in zip(candidate, negative))
            separation = sum(abs(expected - wrong)
                             for expected, wrong in zip(reference, negative))
            if separation < 9:
                continue
            eligible += 1
            # Production's v6 directional counter intentionally/actually has
            # no substantive or non-crossfade predicate here. Keep this mirror
            # exact: those independent counters are what prevent a coincident
            # fixed crossfade from turning a 100% directional fraction into a
            # false pass.
            if (prediction_error <= 12 and
                    prediction_error * 4 <= from_crossfade * 3 and
                    prediction_error * 4 <= inverse_error):
                synthesized += 1
        return eligible, synthesized

    def evidence(self, bad=False):
        directory = tempfile.TemporaryDirectory()
        root = Path(directory.name)
        log = root / "log.txt"
        latency = root / "latency.txt"
        final_record = (
            "I/EmuFusionFrameGen(1234): Presentation health generator=7 "
            "role=primary displayId=0 proofContract=native-pixel-refined-regional-flow-v22-x2-presented "
            "proofSchemaVersion=22 "
            "presents=2400 generated=1400 real=1200 promoted=1000 submitted=1600 "
            "producerHz=59.9 lockedFps=60 outputFps=120 panelFps=120 "
            "latticeRegionSamples=11520 latticeBackwardCoherentRegions=2300 "
            "latticeForwardCoherentRegions=2250 "
            "latticeBackwardBoundaryRegions=100 latticeForwardBoundaryRegions=90 "
            "latticeBackwardCoherentBoundaryRegions=40 "
            "latticeForwardCoherentBoundaryRegions=35 "
            "latticeBackwardCoherentRegionCount=20 "
            "latticeForwardCoherentRegionCount=19 "
            "latticeBackwardBoundaryRegionCount=1 "
            "latticeForwardBoundaryRegionCount=2 "
            "latticeBackwardCoherentBoundaryRegionCount=1 "
            "latticeForwardCoherentBoundaryRegionCount=1 "
            "latticeBackwardPeakSupport=180 latticeForwardPeakSupport=175 "
            "regionalFlowRegionSamples=11520 regionalBackwardSupportedRegions=2500 "
            "regionalForwardSupportedRegions=2480 "
            "regionalBackwardNeighborRegions=2400 regionalForwardNeighborRegions=2300 "
            "regionalBackwardConstantNeighborRegions=2200 "
            "regionalForwardConstantNeighborRegions=2100 "
            "regionalBackwardGradientNeighborRegions=500 "
            "regionalForwardGradientNeighborRegions=450 "
            "regionalBackwardAcceptedRegions=2100 regionalForwardAcceptedRegions=2040 "
            "regionalBackwardAcceptedBoundaryRegions=30 "
            "regionalForwardAcceptedBoundaryRegions=28 "
            "regionalBackwardCycleAcceptedRegions=1800 "
            "regionalForwardCycleAcceptedRegions=1750 "
            "regionalBackwardAcceptedRegionCount=18 regionalForwardAcceptedRegionCount=17 "
            "regionalBackwardAcceptedBoundaryRegionCount=1 "
            "regionalForwardAcceptedBoundaryRegionCount=1 "
            "regionalBackwardCycleAcceptedRegionCount=15 "
            "regionalForwardCycleAcceptedRegionCount=14 "
            "regionalBackwardSupportedRegionCount=22 "
            "regionalForwardSupportedRegionCount=21 "
            "regionalBackwardNeighborRegionCount=20 "
            "regionalForwardNeighborRegionCount=19 "
            "regionalBackwardConstantNeighborRegionCount=18 "
            "regionalForwardConstantNeighborRegionCount=17 "
            "regionalBackwardGradientNeighborRegionCount=5 "
            "regionalForwardGradientNeighborRegionCount=4 "
            "regionalBackwardPeakSupport=210 regionalForwardPeakSupport=205 "
            "regionalBackwardPeakConfidence=180 regionalForwardPeakConfidence=176 "
            f"activeMotionVectors={0 if bad else 12000} "
            "confidentMotionVectors=8000 motionVectorCells=32400 proofSamples=120 "
            "syntheticProofSamples=100 syntheticDistinctFromEndpoints=94 "
            "changingProofOutputs=100 eligibleSyntheticPixels=12000 "
            "substantiveSyntheticPixels=9000 nonCrossfadeSyntheticPixels=8000 "
            "motionEligibleProofSamples=100 motionCorrelatedProofSamples=90 "
            "v21DirectionallyEligibleSyntheticPixels=5000 "
            "v21CorrectVectorPredictedSyntheticPixels=4200 windowElapsedMs=2000 "
            "windowStartNs=11000000000 windowEndNs=13000000000 "
            "windowPresents=240 windowGenerated=120 windowPromoted=120\n"
        )
        baseline = final_record
        for field in ("proofSamples", "syntheticProofSamples",
                      "syntheticDistinctFromEndpoints", "changingProofOutputs",
                      "eligibleSyntheticPixels", "substantiveSyntheticPixels",
                      "nonCrossfadeSyntheticPixels", "motionEligibleProofSamples",
                      "motionCorrelatedProofSamples",
                      "v21DirectionallyEligibleSyntheticPixels",
                      "v21CorrectVectorPredictedSyntheticPixels",
                      "latticeRegionSamples", "latticeBackwardCoherentRegions",
                      "latticeForwardCoherentRegions",
                      "latticeBackwardBoundaryRegions",
                      "latticeForwardBoundaryRegions",
                      "latticeBackwardCoherentBoundaryRegions",
                      "latticeForwardCoherentBoundaryRegions",
                      "latticeBackwardCoherentRegionCount",
                      "latticeForwardCoherentRegionCount",
                      "latticeBackwardBoundaryRegionCount",
                      "latticeForwardBoundaryRegionCount",
                      "latticeBackwardCoherentBoundaryRegionCount",
                      "latticeForwardCoherentBoundaryRegionCount",
                      "latticeBackwardPeakSupport", "latticeForwardPeakSupport",
                      "regionalFlowRegionSamples", "regionalBackwardSupportedRegions",
                      "regionalForwardSupportedRegions",
                      "regionalBackwardNeighborRegions",
                      "regionalForwardNeighborRegions",
                      "regionalBackwardConstantNeighborRegions",
                      "regionalForwardConstantNeighborRegions",
                      "regionalBackwardGradientNeighborRegions",
                      "regionalForwardGradientNeighborRegions",
                      "regionalBackwardAcceptedRegions",
                      "regionalForwardAcceptedRegions",
                      "regionalBackwardAcceptedBoundaryRegions",
                      "regionalForwardAcceptedBoundaryRegions",
                      "regionalBackwardCycleAcceptedRegions",
                      "regionalForwardCycleAcceptedRegions",
                      "regionalBackwardAcceptedRegionCount",
                      "regionalForwardAcceptedRegionCount",
                      "regionalBackwardAcceptedBoundaryRegionCount",
                      "regionalForwardAcceptedBoundaryRegionCount",
                      "regionalBackwardCycleAcceptedRegionCount",
                      "regionalForwardCycleAcceptedRegionCount",
                      "regionalBackwardSupportedRegionCount",
                      "regionalForwardSupportedRegionCount",
                      "regionalBackwardNeighborRegionCount",
                      "regionalForwardNeighborRegionCount",
                      "regionalBackwardConstantNeighborRegionCount",
                      "regionalForwardConstantNeighborRegionCount",
                      "regionalBackwardGradientNeighborRegionCount",
                      "regionalForwardGradientNeighborRegionCount",
                      "regionalBackwardPeakSupport", "regionalForwardPeakSupport",
                      "regionalBackwardPeakConfidence",
                      "regionalForwardPeakConfidence"):
            baseline = re.sub(rf"{field}=\d+", f"{field}=0", baseline)
        baseline = re.sub(
            r"presents=2400 generated=1400 real=1200 promoted=1000 submitted=1600",
            "presents=0 generated=0 real=0 promoted=0 submitted=0", baseline)
        baseline = baseline.replace("windowStartNs=11000000000",
                                    "windowStartNs=1")
        baseline = baseline.replace("windowEndNs=13000000000",
                                    "windowEndNs=1000000000")
        first_proof = baseline.replace("proofSamples=0", "proofSamples=1")
        first_proof = first_proof.replace(
            "latticeRegionSamples=0", "latticeRegionSamples=96")
        first_proof = first_proof.replace(
            "regionalFlowRegionSamples=0", "regionalFlowRegionSamples=96")
        first_proof = first_proof.replace(
            "presents=0 generated=0 real=0 promoted=0 submitted=0",
            "presents=120 generated=60 real=60 promoted=60 submitted=60")
        first_proof = first_proof.replace("windowStartNs=1",
                                          "windowStartNs=1000000000")
        first_proof = first_proof.replace("windowEndNs=1000000000",
                                          "windowEndNs=2000000000")
        log.write_text(
            "I/EmuFusionFrameGen(1234): Frame generator attached generator=7 "
            "role=primary displayId=0 proofContract=native-pixel-refined-regional-flow-v22-x2-presented "
            "proofSchemaVersion=22 "
            "output=1920x1080 input=1920x1080\n"
            "I/InWindowGameHost(1234): In-window route accepted engine=mesen system=nes\n"
            "I/EmuFusionFrameGen(1234): Qualification proof generator=7 enabled=true "
            "proofContract=native-pixel-refined-regional-flow-v22-x2-presented "
            "proofSchemaVersion=22\n"
            + baseline + first_proof + final_record,
            encoding="utf-8",
        )
        values = [8_333_333]
        stamp = 12_000_000_000
        for _ in range(128):
            values.append(f"{stamp} {stamp + 1000} {stamp + 2000}")
            stamp += 8_333_333
        latency.write_text("\n".join(map(str, values)) + "\n", encoding="utf-8")
        return directory, log, latency

    def test_motion_hash_and_surface_latch_evidence_passes(self):
        directory, log, latency = self.evidence()
        with directory:
            report = self.verify(log, latency)
        self.assertTrue(report["passed"], report)
        self.assertEqual(
            report["proofContract"],
            "native-pixel-refined-regional-flow-v22-x2-presented",
        )
        self.assertEqual(report["proofSchemaVersion"], 22)
        self.assertEqual(report["candidateLattice"]["regionSamples"], 11520)
        self.assertEqual(
            report["candidateLattice"]["backwardCoherentRegions"], 2300)
        self.assertEqual(report["regionalFlow"]["regionSamples"], 11520)
        self.assertEqual(
            report["regionalFlow"]["backwardCycleAcceptedRegions"], 1800)
        self.assertGreater(report["syntheticDistinctFraction"], 0.9)

    def test_r23_pid_bound_threadtime_log_passes_without_derivation(self):
        directory, log, latency = self.evidence()
        with directory:
            text = log.read_text(encoding="utf-8")
            text = text.replace(
                "I/EmuFusionFrameGen(1234):",
                "08-11 10:09:37.258 1234 22885 I EmuFusionFrameGen:",
            ).replace(
                "I/InWindowGameHost(1234):",
                "08-11 10:09:36.221 1234 1234 I LucentInWindow:",
            )
            log.write_text(text, encoding="utf-8")
            report = self.verify(log, latency)
        self.assertTrue(report["passed"], report)
        self.assertEqual(report["qualification"]["identity"]["pid"], 1234)

    def test_threadtime_pid_parser_rejects_malformed_and_foreign_identity(self):
        module = load_module()
        exact = (
            "08-11 10:09:37.258 14302 22885 I EmuFusionFrameGen: "
            "Presentation health generator=1"
        )
        self.assertEqual(module.framegen_line_pid(exact), 14302)
        for malformed in (
            "08-11 10:09:37.258 nope 22885 I EmuFusionFrameGen: Presentation health",
            "08-11 10:09:37.258 0 22885 I EmuFusionFrameGen: Presentation health",
            "08-11 10:09:37.258 14302 22885 I OtherTag: "
            "I/EmuFusionFrameGen(9999): Presentation health",
            "noise I/EmuFusionFrameGen(14302): Presentation health",
        ):
            self.assertIsNone(module.framegen_line_pid(malformed), malformed)

        directory, log, latency = self.evidence()
        with directory:
            text = log.read_text(encoding="utf-8").replace(
                "I/EmuFusionFrameGen(1234):",
                "08-11 10:09:37.258 9999 22885 I EmuFusionFrameGen:",
            ).replace(
                "I/InWindowGameHost(1234):",
                "08-11 10:09:36.221 9999 9999 I LucentInWindow:",
            )
            log.write_text(text, encoding="utf-8")
            with self.assertRaisesRegex(ValueError,
                                        "identity does not match"):
                self.verify(log, latency)

    def test_threadtime_health_with_malformed_pid_fails_closed(self):
        directory, log, latency = self.evidence()
        with directory:
            text = log.read_text(encoding="utf-8").replace(
                "I/EmuFusionFrameGen(1234):",
                "08-11 10:09:37.258 malformed 22885 I EmuFusionFrameGen:",
            )
            log.write_text(text, encoding="utf-8")
            with self.assertRaisesRegex(ValueError,
                                        "(?:proof marker|health record) has no process identity"):
                self.verify(log, latency)

    def _proof_reset_evidence(self):
        directory, log, latency = self.evidence()
        lines = log.read_text(encoding="utf-8").splitlines()
        disabled = (
            "I/EmuFusionFrameGen(1234): Qualification proof generator=7 "
            "enabled=false proofContract="
            "native-pixel-refined-regional-flow-v22-x2-presented "
            "proofSchemaVersion=22"
        )
        lines.insert(2, disabled)
        # The false→true transition resets exactly the proof-owned counters;
        # lifetime cadence/lattice counters need not reset.
        lines[4] = lines[4].replace(
            "activeMotionVectors=12000", "activeMotionVectors=0"
        ).replace("confidentMotionVectors=8000", "confidentMotionVectors=0")
        log.write_text("\n".join(lines) + "\n", encoding="utf-8")
        reset = {"pid": 1234, "generator": 7,
                 "disabledLineIndex": 2, "enabledLineIndex": 3,
                 "baselineWindowEndNs": 1_000_000_000}
        return directory, log, latency, reset

    def test_segment_bound_false_true_proof_reset_passes(self):
        directory, log, latency, reset = self._proof_reset_evidence()
        with directory:
            report = self.verify(log, latency, proof_reset=reset)
        self.assertTrue(report["passed"], report)
        self.assertEqual(report["qualification"]["proofReset"], reset)

    def test_transition_reset_rebases_proof_without_rebasing_lifetime_counters(self):
        directory, log, latency, _reset = self._proof_reset_evidence()
        with directory:
            lines = log.read_text(encoding="utf-8").splitlines()
            source = lines[4].replace("lockedFps=60", "lockedFps=50")
            source = source.replace("windowEndNs=1000000000",
                                    "windowEndNs=500000000")
            source = source.replace(
                "presents=0 generated=0 real=0 promoted=0 submitted=0",
                "presents=120 generated=60 real=60 promoted=60 submitted=60",
            ).replace("proofSamples=0", "proofSamples=60")
            lines.insert(2, source)
            lines[5] = lines[5].replace(
                "presents=0 generated=0 real=0 promoted=0 submitted=0",
                "presents=120 generated=60 real=60 promoted=60 submitted=60",
            )
            log.write_text("\n".join(lines) + "\n", encoding="utf-8")
            reset = {"pid": 1234, "generator": 7,
                     "disabledLineIndex": 3, "enabledLineIndex": 4,
                     "baselineWindowEndNs": 1_000_000_000}
            segment = {"segmentId": "fixture-tier", "kind": "transition",
                       "startWindowEndNs": 500_000_000,
                       "proofBaselineWindowEndNs": 1_000_000_000,
                       "endWindowEndNs": 13_000_000_000,
                       "expectedFromFps": 50, "expectedToFps": 60,
                       "maxTransitionMs": 10_000, "maxFallbackPresents": 0,
                       "proofReset": reset}
            report = self.verify(
                log, latency, proof_reset=reset, segment_override=segment
            )
        self.assertTrue(report["passed"], report)
        self.assertEqual(report["qualification"]["transition"]["settlingMs"],
                         500.0)

    def test_proof_reset_rejects_missing_reordered_cross_identity_and_nonzero(self):
        mutations = (
            (lambda lines, reset: reset.update(enabledLineIndex=2),
             "chronology"),
            (lambda lines, reset: lines.insert(4, lines[3]),
             "missing, reordered, duplicated, or reused"),
            (lambda lines, reset: lines.__setitem__(
                2, lines[2].replace("(1234)", "(9999)")),
             "missing, reordered, duplicated, or reused"),
            (lambda lines, reset: lines.__setitem__(
                4, lines[4].replace("activeMotionVectors=0",
                                    "activeMotionVectors=1")),
             "baseline counters are nonzero"),
        )
        for mutate, error in mutations:
            directory, log, latency, reset = self._proof_reset_evidence()
            with directory:
                lines = log.read_text(encoding="utf-8").splitlines()
                mutate(lines, reset)
                log.write_text("\n".join(lines) + "\n", encoding="utf-8")
                with self.subTest(error=error), self.assertRaisesRegex(
                        ValueError, error):
                    self.verify(log, latency, proof_reset=reset)

    def test_secondary_display_is_verified_as_an_independent_generator(self):
        directory, log, latency = self.evidence()
        with directory:
            source = log.read_text(encoding="utf-8")
            source = source.replace("generator=7", "generator=9")
            source = source.replace("role=primary displayId=0",
                                    "role=secondary displayId=4")
            log.write_text(source, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "primary/display-0"):
                self.verify(log, latency)
            report = self.verify(
                log, latency, role="secondary", display_id=4
            )
        self.assertTrue(report["passed"], report)
        self.assertEqual(report["role"], "secondary")
        self.assertEqual(report["displayId"], 4)

    def test_secondary_evidence_cannot_be_joined_to_primary_generator(self):
        directory, log, latency = self.evidence()
        with directory:
            with self.assertRaisesRegex(ValueError, "secondary/display-4"):
                self.verify(
                    log, latency, role="secondary", display_id=4
                )

    def test_production_logger_and_verifier_share_exact_v22_schema(self):
        generator = (ROOT / "unified-android" / "src" / "com" / "thorium" /
                     "preview" / "game" / "DisplayFrameGenerator.java").read_text(
                         encoding="utf-8")
        verifier = load_module()
        self.assertEqual(
            verifier.PROOF_CONTRACT,
            "native-pixel-refined-regional-flow-v22-x2-presented",
        )
        self.assertEqual(verifier.PROOF_SCHEMA_VERSION, 22)
        self.assertIn('"native-pixel-refined-regional-flow-v22-x2-presented"', generator)
        self.assertIn("PROOF_SCHEMA_VERSION = 22", generator)
        self.assertIn('" v21DirectionallyEligibleSyntheticPixels="', generator)
        self.assertIn('" v21CorrectVectorPredictedSyntheticPixels="', generator)

    def test_dense_v25_contract_is_explicit_and_fails_closed_on_coverage(self):
        generator = (ROOT / "unified-android" / "src" / "com" / "thorium" /
                     "preview" / "game" / "DisplayFrameGenerator.java").read_text(
                         encoding="utf-8")
        verifier = load_module()
        self.assertEqual(verifier.DENSE_PROOF_CONTRACT,
                         "dense-pyramid-timer-v26-raw-ns-qualification-x2-presented")
        self.assertEqual(verifier.DENSE_PROOF_SCHEMA_VERSION, 26)
        self.assertIn("densePasses=", generator)
        self.assertIn("denseBackwardValidCells=", generator)
        self.assertIn("denseForwardValidCells=", generator)
        self.assertIn("densePyramidSwitch.enabled()", generator)
        # 2026-09-01: the dense generator is the product path; it is no
        # longer gated on the QA proof request.
        self.assertIn("denseRequested = densePyramidSwitch.enabled()", generator)
        self.assertNotIn("requested && densePyramidSwitch.enabled()", generator)

    def test_dense_v25_impossible_pass_accounting_is_rejected(self):
        directory, log, latency = self.evidence()
        with directory:
            source = log.read_text(encoding="utf-8")
            source = source.replace(
                "proofContract=native-pixel-refined-regional-flow-v22-x2-presented "
                "proofSchemaVersion=22",
                "proofContract=dense-pyramid-timer-v26-raw-ns-qualification-x2-presented "
                "proofSchemaVersion=26",
            )
            source = source.replace(
                " v21CorrectVectorPredictedSyntheticPixels=4200 ",
                " v21CorrectVectorPredictedSyntheticPixels=4200 denseEnabled=1 "
                "densePromotions=120 densePasses=1 denseCpuSubmitTotalUs=12000 "
                "denseCpuSubmitMaxUs=200 denseCpuSubmitLastUs=100 "
                "denseGpuCompleteTotalUs=24000 denseGpuCompleteMaxUs=400 "
                "denseGpuCompleteLastUs=200 denseGpuBudgetUs=7333 "
                "denseTimedPairs=120 denseWarpSequence=60 "
                "denseWarpMaxCompletedSequence=60 denseTimerPending=0 denseTimerDisjoint=0 "
                "denseTimerUnavailable=0 denseTimerStale=0 denseTimerMaxQueueAge=2 "
                "densePerformanceRejected=0 "
                "denseCalibrationRuns=1 denseCalibrationUs=100 "
                "denseRuntimeCadenceSource=app-present-window "
                "denseOfflineCadenceSource=surfaceflinger-layer-timestamps "
                "denseCopySamples=120 denseCopyTotalUs=1200 denseCopyP95Us=10 denseCopyMaxUs=10 "
                "densePyramidSamples=120 densePyramidTotalUs=2400 densePyramidP95Us=20 densePyramidMaxUs=20 "
                "denseForwardSamples=120 denseForwardTotalUs=3600 denseForwardP95Us=30 denseForwardMaxUs=30 "
                "denseReverseSamples=120 denseReverseTotalUs=3600 denseReverseP95Us=30 denseReverseMaxUs=30 "
                "denseValidationSamples=120 denseValidationTotalUs=1200 denseValidationP95Us=10 denseValidationMaxUs=10 "
                "denseWarpSamples=60 denseWarpTotalUs=600 denseWarpP95Us=10 denseWarpMaxUs=10 "
                "denseMaxFlowPixels=47 "
                "denseProofCells=155520 denseBackwardValidCells=120000 "
                "denseForwardValidCells=120000 ",
            )
            # Attach remains the immutable v22 generator identity; proof state
            # and health select the qualification arm after attachment.
            source = source.replace(
                "Frame generator attached generator=7 role=primary displayId=0 "
                "proofContract=dense-pyramid-timer-v26-raw-ns-qualification-x2-presented "
                "proofSchemaVersion=26",
                "Frame generator attached generator=7 role=primary displayId=0 "
                "proofContract=native-pixel-refined-regional-flow-v22-x2-presented "
                "proofSchemaVersion=22",
            )
            log.write_text(source, encoding="utf-8")
            report = self.verify(log, latency)
        self.assertFalse(report["passed"])
        self.assertIn("dense pyramid telemetry is impossible", report["failures"])

    def test_dense_v25_timer_failures_cannot_qualify(self):
        mutations = {
            "denseTimerDisjoint=0": "denseTimerDisjoint=1",
            "denseTimerUnavailable=0": "denseTimerUnavailable=1",
            "denseTimerStale=0": "denseTimerStale=1",
            "denseTimerPending=0": "denseTimerPending=96",
            "denseTimedPairs=120": "denseTimedPairs=119",
            "densePerformanceRejected=0": "densePerformanceRejected=1",
            "denseTimerMaxQueueAge=2": "denseTimerMaxQueueAge=65",
            "denseForwardSamples=120": "denseForwardSamples=119",
        }
        for original, invalid in mutations.items():
            directory, log, latency = self.evidence()
            with directory:
                source = log.read_text(encoding="utf-8")
                source = source.replace(
                    "Qualification proof generator=7 enabled=true "
                    "proofContract=native-pixel-refined-regional-flow-v22-x2-presented "
                    "proofSchemaVersion=22",
                    "Qualification proof generator=7 enabled=true "
                    "proofContract=dense-pyramid-timer-v26-raw-ns-qualification-x2-presented "
                    "proofSchemaVersion=26",
                )

                def dense_record(match):
                    line = match.group(0)
                    line = line.replace(
                        "proofContract=native-pixel-refined-regional-flow-v22-x2-presented "
                        "proofSchemaVersion=22",
                        "proofContract=dense-pyramid-timer-v26-raw-ns-qualification-x2-presented "
                        "proofSchemaVersion=26",
                    )
                    proof = int(re.search(r"proofSamples=(\d+)", line).group(1))
                    promotions = 0 if proof == 0 else (1 if proof == 1 else 120)
                    warp = 0 if proof == 0 else (1 if proof == 1 else 60)
                    telemetry = (
                        f"denseEnabled=1 densePromotions={promotions} "
                        f"densePasses={promotions * 38} "
                        f"denseCpuSubmitTotalUs={promotions * 100} "
                        f"denseCpuSubmitMaxUs={100 if promotions else 0} "
                        f"denseCpuSubmitLastUs={100 if promotions else 0} "
                        f"denseGpuCompleteTotalUs={promotions * 400} "
                        f"denseGpuCompleteMaxUs={400 if promotions else 0} "
                        f"denseGpuCompleteLastUs={400 if promotions else 0} "
                        "denseGpuBudgetUs=7333 "
                        f"denseTimedPairs={promotions} denseWarpSequence={warp} "
                        f"denseWarpMaxCompletedSequence={warp} denseTimerPending=0 "
                        "denseTimerDisjoint=0 denseTimerUnavailable=0 "
                        "denseTimerStale=0 denseTimerMaxQueueAge=2 "
                        "densePerformanceRejected=0 denseCalibrationRuns=1 "
                        "denseCalibrationUs=100 "
                        "denseRuntimeCadenceSource=app-present-window "
                        "denseOfflineCadenceSource=surfaceflinger-layer-timestamps "
                    )
                    for name, scale in (("Copy", 10), ("Pyramid", 20),
                                        ("Forward", 30), ("Reverse", 30),
                                        ("Validation", 10)):
                        maximum = scale if promotions else 0
                        telemetry += (f"dense{name}Samples={promotions} "
                            f"dense{name}TotalUs={promotions * scale} "
                            f"dense{name}P95Us={maximum} dense{name}MaxUs={maximum} ")
                    telemetry += (f"denseWarpSamples={warp} denseWarpTotalUs={warp * 10} "
                        f"denseWarpP95Us={10 if warp else 0} denseWarpMaxUs={10 if warp else 0} "
                        "denseMaxFlowPixels=47 "
                        f"denseProofCells={proof * 1296} "
                        f"denseBackwardValidCells={proof * 1000} "
                        f"denseForwardValidCells={proof * 1000} ")
                    return line.replace("windowElapsedMs=", telemetry + "windowElapsedMs=")

                source = re.sub(r"^I/EmuFusionFrameGen\(1234\): Presentation health.*$",
                                dense_record, source, flags=re.MULTILINE)
                source = source.replace(original, invalid)
                log.write_text(source, encoding="utf-8")
                report = self.verify(log, latency)
            self.assertFalse(report["passed"], (original, report))

    def test_dense_v25_timer_counters_are_monotonic_and_pair_bound(self):
        verifier_source = (ROOT / "unified-android" / "tools" /
                           "verify_frame_generation_evidence.py").read_text(
                               encoding="utf-8")
        for field in (
                '"dense_timed_pairs"', '"dense_copy_samples"',
                '"dense_pyramid_samples"', '"dense_forward_samples"',
                '"dense_reverse_samples"', '"dense_validation_samples"',
                '"dense_warp_samples"'):
            self.assertIn(field, verifier_source)
        self.assertIn('_segment_dense_timer_pairs_valid(', verifier_source)
        self.assertIn('values[f"dense_{stage}_samples"] >= 120', verifier_source)

    def test_segment_dense_timer_pairs_conserve_opening_and_closing_work(self):
        module = load_module()
        baseline = {
            "dense_promotions": 448,
            "dense_timed_pairs": 447,
            "dense_timer_pending": 6,
        }
        end = {
            "dense_promotions": 1348,
            "dense_timed_pairs": 1348,
            "dense_timer_pending": 1,
        }
        segment = {"dense_promotions": 900, "dense_timed_pairs": 901}
        self.assertTrue(module._segment_dense_timer_pairs_valid(
            baseline, end, segment
        ))

        # A fabricated extra completion has no opening query ownership.
        no_opening = dict(baseline, dense_timed_pairs=448,
                          dense_timer_pending=0)
        self.assertFalse(module._segment_dense_timer_pairs_valid(
            no_opening, end, segment
        ))
        # An end snapshot cannot claim more incomplete pairs than native rows.
        impossible_closing = dict(end, dense_timed_pairs=1346,
                                  dense_timer_pending=1)
        self.assertFalse(module._segment_dense_timer_pairs_valid(
            baseline, impossible_closing, segment
        ))

    def test_v20_artifact_cannot_qualify_native_pixel_refinement_v21(self):
        directory, log, latency = self.evidence()
        with directory:
            source = log.read_text(encoding="utf-8")
            source = source.replace(
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
            log.write_text(source, encoding="utf-8")
            with self.assertRaisesRegex(
                    ValueError, "no complete primary/display-0"):
                self.verify(log, latency)

    def test_old_unversioned_pixel_counters_cannot_masquerade_as_vector_proof(self):
        directory, log, latency = self.evidence()
        with directory:
            source = log.read_text(encoding="utf-8")
            source = source.replace(
                " proofContract=native-pixel-refined-regional-flow-v22-x2-presented", "")
            source = source.replace(" proofSchemaVersion=22", "")
            source = source.replace(
                "v21DirectionallyEligibleSyntheticPixels=",
                "motionEligibleSyntheticPixels=",
            )
            source = source.replace(
                "v21CorrectVectorPredictedSyntheticPixels=",
                "motionSynthesizedSyntheticPixels=",
            )
            log.write_text(source, encoding="utf-8")
            with self.assertRaisesRegex(
                    ValueError, "no complete primary/display-0"):
                self.verify(log, latency)

    def test_one_way_v5_artifact_cannot_qualify_coherent_dilation_v10(self):
        directory, log, latency = self.evidence()
        with directory:
            source = log.read_text(encoding="utf-8")
            source = source.replace(
                "native-pixel-refined-regional-flow-v22-x2-presented",
                "vector-prediction-v5-content-unique",
            ).replace("proofSchemaVersion=22", "proofSchemaVersion=5")
            source = source.replace(
                "v21DirectionallyEligibleSyntheticPixels=",
                "v5DirectionallyEligibleSyntheticPixels=",
            ).replace(
                "v21CorrectVectorPredictedSyntheticPixels=",
                "v5CorrectVectorPredictedSyntheticPixels=",
            )
            log.write_text(source, encoding="utf-8")
            with self.assertRaisesRegex(
                    ValueError, "no complete primary/display-0"):
                self.verify(log, latency)

    def test_fragmenting_v6_artifact_cannot_qualify_coherent_dilation_v10(self):
        directory, log, latency = self.evidence()
        with directory:
            source = log.read_text(encoding="utf-8")
            source = source.replace(
                "native-pixel-refined-regional-flow-v22-x2-presented",
                "bidirectional-occlusion-v6-content-unique",
            ).replace("proofSchemaVersion=22", "proofSchemaVersion=6")
            source = source.replace(
                "v21DirectionallyEligibleSyntheticPixels=",
                "v6DirectionallyEligibleSyntheticPixels=",
            ).replace(
                "v21CorrectVectorPredictedSyntheticPixels=",
                "v6CorrectVectorPredictedSyntheticPixels=",
            )
            log.write_text(source, encoding="utf-8")
            with self.assertRaisesRegex(
                    ValueError, "no complete primary/display-0"):
                self.verify(log, latency)

    def test_slow_v7_artifact_cannot_qualify_coherent_dilation_v10(self):
        directory, log, latency = self.evidence()
        with directory:
            source = log.read_text(encoding="utf-8")
            source = source.replace(
                "native-pixel-refined-regional-flow-v22-x2-presented",
                "robust-blockmatch-v7-content-unique",
            ).replace("proofSchemaVersion=22", "proofSchemaVersion=7")
            source = source.replace(
                "v21DirectionallyEligibleSyntheticPixels=",
                "v7DirectionallyEligibleSyntheticPixels=",
            ).replace(
                "v21CorrectVectorPredictedSyntheticPixels=",
                "v7CorrectVectorPredictedSyntheticPixels=",
            )
            log.write_text(source, encoding="utf-8")
            with self.assertRaisesRegex(
                    ValueError, "no complete primary/display-0"):
                self.verify(log, latency)

    def test_motion_disabled_v8_artifact_cannot_qualify_coherent_dilation_v10(self):
        directory, log, latency = self.evidence()
        with directory:
            source = log.read_text(encoding="utf-8")
            source = source.replace(
                "native-pixel-refined-regional-flow-v22-x2-presented",
                "efficient-robust-blockmatch-v8-content-unique",
            ).replace("proofSchemaVersion=22", "proofSchemaVersion=8")
            source = source.replace(
                "v21DirectionallyEligibleSyntheticPixels=",
                "v8DirectionallyEligibleSyntheticPixels=",
            ).replace(
                "v21CorrectVectorPredictedSyntheticPixels=",
                "v8CorrectVectorPredictedSyntheticPixels=",
            )
            log.write_text(source, encoding="utf-8")
            with self.assertRaisesRegex(
                    ValueError, "no complete primary/display-0"):
                self.verify(log, latency)

    def test_sparse_v9_artifact_cannot_qualify_coherent_dilation_v10(self):
        directory, log, latency = self.evidence()
        with directory:
            source = log.read_text(encoding="utf-8")
            source = source.replace(
                "native-pixel-refined-regional-flow-v22-x2-presented",
                "coherent-fine-v9-content-unique",
            ).replace("proofSchemaVersion=22", "proofSchemaVersion=9")
            source = source.replace(
                "v21DirectionallyEligibleSyntheticPixels=",
                "v9DirectionallyEligibleSyntheticPixels=",
            ).replace(
                "v21CorrectVectorPredictedSyntheticPixels=",
                "v9CorrectVectorPredictedSyntheticPixels=",
            )
            log.write_text(source, encoding="utf-8")
            with self.assertRaisesRegex(
                    ValueError, "no complete primary/display-0"):
                self.verify(log, latency)

    def test_local_dilation_v10_artifact_cannot_qualify_global_camera_v11(self):
        directory, log, latency = self.evidence()
        with directory:
            source = log.read_text(encoding="utf-8")
            source = source.replace(
                "native-pixel-refined-regional-flow-v22-x2-presented",
                "coherent-dilation-v10-content-unique",
            ).replace("proofSchemaVersion=22", "proofSchemaVersion=10")
            source = source.replace(
                "v21DirectionallyEligibleSyntheticPixels=",
                "v10DirectionallyEligibleSyntheticPixels=",
            ).replace(
                "v21CorrectVectorPredictedSyntheticPixels=",
                "v10CorrectVectorPredictedSyntheticPixels=",
            )
            log.write_text(source, encoding="utf-8")
            with self.assertRaisesRegex(
                    ValueError, "no complete primary/display-0"):
                self.verify(log, latency)

    def test_global_camera_v11_artifact_cannot_qualify_exact_copy_v12(self):
        directory, log, latency = self.evidence()
        with directory:
            source = log.read_text(encoding="utf-8")
            source = source.replace(
                "native-pixel-refined-regional-flow-v22-x2-presented",
                "global-camera-v11-content-unique",
            ).replace("proofSchemaVersion=22", "proofSchemaVersion=11")
            source = source.replace(
                "v21DirectionallyEligibleSyntheticPixels=",
                "v11DirectionallyEligibleSyntheticPixels=",
            ).replace(
                "v21CorrectVectorPredictedSyntheticPixels=",
                "v11CorrectVectorPredictedSyntheticPixels=",
            )
            log.write_text(source, encoding="utf-8")
            with self.assertRaisesRegex(
                    ValueError, "no complete primary/display-0"):
                self.verify(log, latency)

    def test_exact_copy_v12_artifact_cannot_qualify_optional_attribute_v13(self):
        directory, log, latency = self.evidence()
        with directory:
            source = log.read_text(encoding="utf-8")
            source = source.replace(
                "native-pixel-refined-regional-flow-v22-x2-presented",
                "exact-copy-global-camera-v12-content-unique",
            ).replace("proofSchemaVersion=22", "proofSchemaVersion=12")
            source = source.replace(
                "v21DirectionallyEligibleSyntheticPixels=",
                "v12DirectionallyEligibleSyntheticPixels=",
            ).replace(
                "v21CorrectVectorPredictedSyntheticPixels=",
                "v12CorrectVectorPredictedSyntheticPixels=",
            )
            log.write_text(source, encoding="utf-8")
            with self.assertRaisesRegex(
                    ValueError, "no complete primary/display-0"):
                self.verify(log, latency)

    def test_optional_attribute_v13_artifact_cannot_qualify_regional_v16(self):
        directory, log, latency = self.evidence()
        with directory:
            source = log.read_text(encoding="utf-8")
            source = source.replace(
                "native-pixel-refined-regional-flow-v22-x2-presented",
                "optional-attribute-global-camera-v13-content-unique",
            ).replace("proofSchemaVersion=22", "proofSchemaVersion=13")
            source = source.replace(
                "v21DirectionallyEligibleSyntheticPixels=",
                "v13DirectionallyEligibleSyntheticPixels=",
            ).replace(
                "v21CorrectVectorPredictedSyntheticPixels=",
                "v13CorrectVectorPredictedSyntheticPixels=",
            )
            log.write_text(source, encoding="utf-8")
            with self.assertRaisesRegex(
                    ValueError, "no complete primary/display-0"):
                self.verify(log, latency)

    def test_photometric_global_v14_artifact_cannot_qualify_regional_v16(self):
        directory, log, latency = self.evidence()
        with directory:
            source = log.read_text(encoding="utf-8")
            source = source.replace(
                "native-pixel-refined-regional-flow-v22-x2-presented",
                "photometric-global-camera-v14-content-unique",
            ).replace("proofSchemaVersion=22", "proofSchemaVersion=14")
            source = source.replace(
                "v21DirectionallyEligibleSyntheticPixels=",
                "v14DirectionallyEligibleSyntheticPixels=",
            ).replace(
                "v21CorrectVectorPredictedSyntheticPixels=",
                "v14CorrectVectorPredictedSyntheticPixels=",
            )
            log.write_text(source, encoding="utf-8")
            with self.assertRaisesRegex(
                    ValueError, "no complete primary/display-0"):
                self.verify(log, latency)

    def test_raw_seeded_regional_v15_artifact_cannot_qualify_granular_v17(self):
        directory, log, latency = self.evidence()
        with directory:
            source = log.read_text(encoding="utf-8")
            source = source.replace(
                "native-pixel-refined-regional-flow-v22-x2-presented",
                "photometric-regional-flow-v15-content-unique",
            ).replace("proofSchemaVersion=22", "proofSchemaVersion=15")
            source = source.replace(
                "v21DirectionallyEligibleSyntheticPixels=",
                "v15DirectionallyEligibleSyntheticPixels=",
            ).replace(
                "v21CorrectVectorPredictedSyntheticPixels=",
                "v15CorrectVectorPredictedSyntheticPixels=",
            )
            log.write_text(source, encoding="utf-8")
            with self.assertRaisesRegex(
                    ValueError, "no complete primary/display-0"):
                self.verify(log, latency)

    def test_candidate_lattice_telemetry_hierarchy_is_fail_closed(self):
        directory, log, latency = self.evidence()
        with directory:
            source = log.read_text(encoding="utf-8").replace(
                "latticeRegionSamples=11520", "latticeRegionSamples=2879")
            log.write_text(source, encoding="utf-8")
            report = self.verify(log, latency)
        self.assertFalse(report["passed"])
        self.assertTrue(any("candidate lattice telemetry" in failure
                            for failure in report["failures"]))

    def test_coherent_candidate_count_is_bounded_by_region_samples(self):
        directory, log, latency = self.evidence()
        with directory:
            source = log.read_text(encoding="utf-8").replace(
                "latticeBackwardCoherentRegions=2300",
                "latticeBackwardCoherentRegions=11521",
            )
            log.write_text(source, encoding="utf-8")
            report = self.verify(log, latency)
        self.assertFalse(report["passed"])
        self.assertTrue(any("coherent candidate cumulative" in failure
                            for failure in report["failures"]))

    def test_instantaneous_coherent_candidate_count_is_bounded_by_grid(self):
        directory, log, latency = self.evidence()
        with directory:
            source = log.read_text(encoding="utf-8").replace(
                "latticeBackwardCoherentRegionCount=20",
                "latticeBackwardCoherentRegionCount=97",
            )
            log.write_text(source, encoding="utf-8")
            report = self.verify(log, latency)
        self.assertFalse(report["passed"])
        self.assertTrue(any("candidate lattice instantaneous" in failure
                            for failure in report["failures"]))

    def test_coherent_boundary_intersection_is_bounded_by_each_parent(self):
        directory, log, latency = self.evidence()
        with directory:
            source = log.read_text(encoding="utf-8").replace(
                "latticeBackwardCoherentBoundaryRegions=40",
                "latticeBackwardCoherentBoundaryRegions=101",
            )
            log.write_text(source, encoding="utf-8")
            report = self.verify(log, latency)
        self.assertFalse(report["passed"])
        self.assertTrue(any("coherent-boundary intersection" in failure
                            for failure in report["failures"]))

    def test_accepted_boundary_intersection_is_bounded_by_each_parent(self):
        directory, log, latency = self.evidence()
        with directory:
            source = log.read_text(encoding="utf-8").replace(
                "regionalBackwardAcceptedBoundaryRegions=30",
                "regionalBackwardAcceptedBoundaryRegions=101",
            )
            log.write_text(source, encoding="utf-8")
            report = self.verify(log, latency)
        self.assertFalse(report["passed"])
        self.assertTrue(any("accepted-boundary intersection" in failure
                            for failure in report["failures"]))

    def test_regional_flow_telemetry_hierarchy_is_fail_closed(self):
        directory, log, latency = self.evidence()
        with directory:
            source = log.read_text(encoding="utf-8").replace(
                "regionalFlowRegionSamples=11520",
                "regionalFlowRegionSamples=2879")
            log.write_text(source, encoding="utf-8")
            report = self.verify(log, latency)
        self.assertFalse(report["passed"])
        self.assertTrue(any("regional flow telemetry" in failure
                            for failure in report["failures"]))

    def test_each_directional_regional_acceptance_is_bounded_by_samples(self):
        directory, log, latency = self.evidence()
        with directory:
            source = log.read_text(encoding="utf-8").replace(
                "regionalBackwardAcceptedRegions=2100",
                "regionalBackwardAcceptedRegions=2881",
            )
            log.write_text(source, encoding="utf-8")
            report = self.verify(log, latency)
        self.assertFalse(report["passed"])
        self.assertTrue(any("regional cumulative acceptance counters" in failure
                            for failure in report["failures"]))

    def test_directional_acceptance_cannot_exceed_neighbor_consensus(self):
        directory, log, latency = self.evidence()
        with directory:
            source = log.read_text(encoding="utf-8").replace(
                "regionalBackwardNeighborRegions=2400",
                "regionalBackwardNeighborRegions=2099",
            )
            log.write_text(source, encoding="utf-8")
            report = self.verify(log, latency)
        self.assertFalse(report["passed"])
        self.assertTrue(any("regional cumulative acceptance counters" in failure
                            for failure in report["failures"]))

    def test_neighbor_model_subsets_cannot_exceed_union(self):
        directory, log, latency = self.evidence()
        with directory:
            source = log.read_text(encoding="utf-8").replace(
                "regionalBackwardGradientNeighborRegions=500",
                "regionalBackwardGradientNeighborRegions=2401",
            )
            log.write_text(source, encoding="utf-8")
            report = self.verify(log, latency)
        self.assertFalse(report["passed"])
        self.assertTrue(any("neighbor-model subset" in failure
                            for failure in report["failures"]))

    def test_neighbor_union_cannot_exceed_sum_of_model_subsets(self):
        directory, log, latency = self.evidence()
        with directory:
            source = log.read_text(encoding="utf-8").replace(
                "regionalBackwardNeighborRegions=2400",
                "regionalBackwardNeighborRegions=2701",
            )
            log.write_text(source, encoding="utf-8")
            report = self.verify(log, latency)
        self.assertFalse(report["passed"])
        self.assertTrue(any("neighbor-model subset" in failure
                            for failure in report["failures"]))

    def test_instantaneous_neighbor_union_cannot_exceed_subset_sum(self):
        directory, log, latency = self.evidence()
        with directory:
            source = log.read_text(encoding="utf-8").replace(
                "regionalBackwardNeighborRegionCount=20",
                "regionalBackwardNeighborRegionCount=24",
            )
            log.write_text(source, encoding="utf-8")
            report = self.verify(log, latency)
        self.assertFalse(report["passed"])
        self.assertTrue(any("instantaneous neighbor-model subsets" in failure
                            for failure in report["failures"]))

    def test_each_cycle_direction_is_bounded_by_directional_acceptance(self):
        directory, log, latency = self.evidence()
        with directory:
            source = log.read_text(encoding="utf-8").replace(
                "regionalForwardCycleAcceptedRegions=1750",
                "regionalForwardCycleAcceptedRegions=2041",
            )
            log.write_text(source, encoding="utf-8")
            report = self.verify(log, latency)
        self.assertFalse(report["passed"])
        self.assertTrue(any("regional cumulative acceptance" in failure
                            for failure in report["failures"]))

    def test_cycle_acceptance_requires_same_directional_confidence(self):
        directory, log, latency = self.evidence()
        with directory:
            source = log.read_text(encoding="utf-8")
            # A cycle-qualified region is measured from a direction whose
            # center confidence is above the exact directional acceptance
            # byte. It must therefore remain a subset of that direction.
            source = source.replace(
                "regionalBackwardAcceptedRegions=2100",
                "regionalBackwardAcceptedRegions=0",
            ).replace(
                "regionalBackwardAcceptedBoundaryRegions=30",
                "regionalBackwardAcceptedBoundaryRegions=0",
            ).replace(
                "regionalBackwardAcceptedRegionCount=18",
                "regionalBackwardAcceptedRegionCount=0",
            ).replace(
                "regionalBackwardAcceptedBoundaryRegionCount=1",
                "regionalBackwardAcceptedBoundaryRegionCount=0",
            ).replace(
                "regionalBackwardPeakConfidence=180",
                "regionalBackwardPeakConfidence=25",
            ).replace(
                "regionalForwardPeakConfidence=176",
                "regionalForwardPeakConfidence=255",
            )
            log.write_text(source, encoding="utf-8")
            report = self.verify(log, latency)
        self.assertFalse(report["passed"])
        self.assertTrue(any("regional cumulative acceptance" in failure
                            for failure in report["failures"]))

    def test_bidirectional_regional_acceptance_is_bounded_by_samples(self):
        directory, log, latency = self.evidence()
        with directory:
            source = log.read_text(encoding="utf-8").replace(
                "regionalBackwardCycleAcceptedRegions=1800",
                "regionalBackwardCycleAcceptedRegions=11521",
            )
            log.write_text(source, encoding="utf-8")
            report = self.verify(log, latency)
        self.assertFalse(report["passed"])
        self.assertTrue(any("regional cumulative acceptance counters" in failure
                            for failure in report["failures"]))

    def test_instantaneous_regional_acceptance_is_bounded_by_cell_count(self):
        directory, log, latency = self.evidence()
        with directory:
            source = log.read_text(encoding="utf-8").replace(
                "regionalBackwardAcceptedRegionCount=18",
                "regionalBackwardAcceptedRegionCount=25",
            )
            log.write_text(source, encoding="utf-8")
            report = self.verify(log, latency)
        self.assertFalse(report["passed"])
        self.assertTrue(any("regional instantaneous acceptance" in failure
                            for failure in report["failures"]))

    def test_instantaneous_bidirectional_acceptance_is_bounded_by_cell_count(self):
        directory, log, latency = self.evidence()
        with directory:
            source = log.read_text(encoding="utf-8").replace(
                "regionalBackwardCycleAcceptedRegionCount=15",
                "regionalBackwardCycleAcceptedRegionCount=97",
            )
            log.write_text(source, encoding="utf-8")
            report = self.verify(log, latency)
        self.assertFalse(report["passed"])
        self.assertTrue(any("regional instantaneous acceptance" in failure
                            for failure in report["failures"]))

    def test_instantaneous_acceptance_cannot_exceed_neighbor_consensus(self):
        directory, log, latency = self.evidence()
        with directory:
            source = log.read_text(encoding="utf-8").replace(
                "regionalBackwardNeighborRegionCount=20",
                "regionalBackwardNeighborRegionCount=17",
            )
            log.write_text(source, encoding="utf-8")
            report = self.verify(log, latency)
        self.assertFalse(report["passed"])
        self.assertTrue(any("regional instantaneous acceptance" in failure
                            for failure in report["failures"]))

    def test_c81_counters_fail_even_with_current_contract_tokens_pasted_on(self):
        directory, log, latency = self.evidence()
        with directory:
            source = log.read_text(encoding="utf-8")
            # c81 emitted these aggregate names. Give the forged record every
            # current contract/version token but retain the old vocabulary: it
            # must remain structurally unparseable as v10 proof.
            source = source.replace(
                "v21DirectionallyEligibleSyntheticPixels=",
                "motionEligibleSyntheticPixels=",
            )
            source = source.replace(
                "v21CorrectVectorPredictedSyntheticPixels=",
                "motionSynthesizedSyntheticPixels=",
            )
            log.write_text(source, encoding="utf-8")
            with self.assertRaisesRegex(
                    ValueError, "no complete primary/display-0"):
                self.verify(log, latency)

    def test_callback_numbers_cannot_hide_zero_motion(self):
        directory, log, latency = self.evidence(bad=True)
        with directory:
            report = self.verify(log, latency)
        self.assertFalse(report["passed"])
        self.assertTrue(any("motion field" in item for item in report["failures"]))

    def test_impossible_counter_hierarchy_is_rejected(self):
        directory, log, latency = self.evidence()
        with directory:
            source = log.read_text(encoding="utf-8").replace(
                "syntheticProofSamples=100",
                "syntheticProofSamples=121",
            ).replace(
                "v21CorrectVectorPredictedSyntheticPixels=4200",
                "v21CorrectVectorPredictedSyntheticPixels=13000",
            )
            log.write_text(source, encoding="utf-8")
            report = self.verify(log, latency)
        self.assertFalse(report["passed"])
        self.assertTrue(any("synthetic proof samples exceed proof" in item
                            for item in report["failures"]))
        self.assertTrue(any("synthesized/motion-eligible/eligible" in item
                            for item in report["failures"]))

    def test_cumulative_proof_counter_regression_is_rejected(self):
        directory, log, latency = self.evidence()
        with directory:
            lines = log.read_text(encoding="utf-8").splitlines()
            # Final overlapping record follows a one-sample record, so zero is
            # an impossible reset within the same attached generator session.
            lines[-1] = lines[-1].replace("proofSamples=120", "proofSamples=0")
            log.write_text("\n".join(lines) + "\n", encoding="utf-8")
            report = self.verify(log, latency)
        self.assertFalse(report["passed"])
        self.assertTrue(any("cumulative counter regressed: proof" in item
                            for item in report["failures"]))

    def test_promoted_unique_submitted_hierarchy_is_rejected(self):
        directory, log, latency = self.evidence()
        with directory:
            source = log.read_text(encoding="utf-8").replace(
                "real=1200 promoted=1000", "real=900 promoted=1000")
            log.write_text(source, encoding="utf-8")
            report = self.verify(log, latency)
        self.assertFalse(report["passed"])
        self.assertTrue(any("promoted/real/submitted counters are impossible" in item
                            for item in report["failures"]))

    def test_static_tail_does_not_erase_motion_proven_during_window(self):
        directory, log, latency = self.evidence()
        with directory:
            lines = log.read_text(encoding="utf-8").splitlines()
            final = lines[-1]
            # The bounded proof records are motion-rich, but the final cadence
            # health interval's current frame is static. The cumulative spatial
            # proof remains attached to the same PID/generator.
            final = final.replace("activeMotionVectors=12000",
                                  "activeMotionVectors=0")
            final = final.replace("confidentMotionVectors=8000",
                                  "confidentMotionVectors=0")
            lines[-1] = final
            log.write_text("\n".join(lines) + "\n", encoding="utf-8")
            report = self.verify(log, latency)
        self.assertTrue(report["passed"], report)
        self.assertEqual(report["generator"]["active"], 0)
        self.assertGreater(report["proofWindowPeakMotion"]["activeVectors"], 0)

    def test_crash_marker_fails_otherwise_valid_evidence(self):
        directory, log, latency = self.evidence()
        with directory:
            log.write_text(log.read_text() + "Fatal signal 11\n", encoding="utf-8")
            report = self.verify(log, latency)
        self.assertFalse(report["passed"])

    def test_fixed_pixel_crossfade_cannot_pass_on_hash_inequality(self):
        directory, log, latency = self.evidence()
        with directory:
            source = log.read_text(encoding="utf-8")
            source = source.replace("nonCrossfadeSyntheticPixels=8000",
                                    "nonCrossfadeSyntheticPixels=0")
            source = source.replace("motionCorrelatedProofSamples=90",
                                    "motionCorrelatedProofSamples=0")
            log.write_text(source, encoding="utf-8")
            report = self.verify(log, latency)
        self.assertFalse(report["passed"])
        self.assertTrue(any("crossfade" in item for item in report["failures"]))

    def test_pixel_metrics_separate_duplicate_crossfade_and_translated_motion(self):
        # A nonlinear wrapped signal makes a two-pixel ground-truth translation
        # materially different from the fixed-coordinate average of endpoints
        # four pixels apart. This directly tests the production metric, not just
        # pre-filled log counters.
        values = [round(127.5 + 110 * math.sin(index * 0.41) +
                        15 * math.sin(index * 1.7)) for index in range(128)]
        previous = [(value, value, value) for value in values]

        def shifted(distance):
            return [previous[(index - distance) % len(previous)]
                    for index in range(len(previous))]

        current = shifted(4)
        motion_midpoint = shifted(2)
        fixed_crossfade = [
            tuple(round((a + b) / 2) for a, b in zip(before, after))
            for before, after in zip(previous, current)
        ]
        duplicate = self.classify_pixels(previous, current, previous)
        crossfade = self.classify_pixels(previous, current, fixed_crossfade)
        motion = self.classify_pixels(previous, current, motion_midpoint)
        self.assertEqual(duplicate[1], 0, "endpoint repeat must not be substantive")
        self.assertEqual(crossfade[2], 0, "fixed crossfade must have no warp evidence")
        self.assertGreater(motion[1] / motion[0], 0.80)
        self.assertGreater(motion[2] / motion[0], 0.75)

    def test_vector_prediction_rejects_inverse_crossfade_and_random_output(self):
        # A nonlinear signal and known four-pixel translation make the correct
        # midpoint distinguishable from both fixed-coordinate blending and the
        # opposite-vector negative control. This mirrors the production integer
        # thresholds rather than trusting pre-filled health counters.
        values = [max(0, min(255, round(
            127.5 + 90 * math.sin(index * 0.41) +
            25 * math.sin(index * 1.7)))) for index in range(128)]
        previous = [(value, value, value) for value in values]

        def shifted(distance):
            return [previous[(index - distance) % len(previous)]
                    for index in range(len(previous))]

        current = shifted(4)
        predicted = shifted(2)
        inverse_left = shifted(-2)
        inverse_right = shifted(6)
        inverse = [tuple(round((a + b) / 2) for a, b in zip(left, right))
                   for left, right in zip(inverse_left, inverse_right)]
        crossfade = [tuple(round((a + b) / 2) for a, b in zip(before, after))
                     for before, after in zip(previous, current)]
        # Deterministic high-amplitude output unrelated to either reference.
        random_output = [
            ((index * 73 + 19) % 256,
             (index * 151 + 47) % 256,
             (index * 211 + 89) % 256)
            for index in range(len(previous))
        ]

        correct = self.classify_vector_prediction(
            previous, current, predicted, predicted, inverse)
        wrong_direction = self.classify_vector_prediction(
            previous, current, inverse, predicted, inverse)
        fixed = self.classify_vector_prediction(
            previous, current, crossfade, predicted, inverse)
        noise = self.classify_vector_prediction(
            previous, current, random_output, predicted, inverse)
        self.assertGreater(correct[0], 100)
        self.assertGreater(correct[1] / correct[0], 0.75)
        self.assertEqual(wrong_direction[1], 0)
        self.assertEqual(fixed[1], 0)
        self.assertEqual(noise[1], 0)

    def test_perfect_v6_directional_fraction_does_not_supersede_crossfade_gate(self):
        # The correct-vector reference can coincide exactly with a fixed
        # crossfade for a locally linear/symmetric sample while the inverted
        # reference differs. Production then counts the pixel as v10 synthesized
        # (zero prediction error wins every ratio), even though it contains no
        # visible departure from crossfade. This is why a 100% v6 fraction is
        # not evidence that the independent non-crossfade failure is stale.
        previous = [(0, 0, 0)] * 64
        current = [(200, 100, 50)] * 64
        fixed = [(100, 50, 25)] * 64
        inverse = [(120, 50, 25)] * 64
        eligible, synthesized = self.classify_vector_prediction(
            previous, current, fixed, fixed, inverse)
        pixel_counts = self.classify_pixels(previous, current, fixed)
        self.assertEqual((eligible, synthesized), (64, 64))
        self.assertEqual(pixel_counts[2], 0)

        directory, log, latency = self.evidence()
        with directory:
            source = log.read_text(encoding="utf-8")
            source = source.replace("nonCrossfadeSyntheticPixels=8000",
                                    "nonCrossfadeSyntheticPixels=3000")
            source = source.replace("motionCorrelatedProofSamples=90",
                                    "motionCorrelatedProofSamples=0")
            source = source.replace(
                "v21CorrectVectorPredictedSyntheticPixels=4200",
                "v21CorrectVectorPredictedSyntheticPixels=5000",
            )
            log.write_text(source, encoding="utf-8")
            report = self.verify(log, latency)
        self.assertEqual(report["spatialMotionSynthesisFraction"], 1.0)
        self.assertFalse(report["passed"])
        self.assertTrue(any("crossfade" in failure
                            for failure in report["failures"]))

    def test_repeated_endpoints_cannot_pass_as_generated_frames(self):
        directory, log, latency = self.evidence()
        with directory:
            source = log.read_text(encoding="utf-8")
            replacements = {
                "syntheticDistinctFromEndpoints=94":
                    "syntheticDistinctFromEndpoints=0",
                "substantiveSyntheticPixels=9000":
                    "substantiveSyntheticPixels=0",
                "nonCrossfadeSyntheticPixels=8000":
                    "nonCrossfadeSyntheticPixels=0",
                "motionCorrelatedProofSamples=90":
                    "motionCorrelatedProofSamples=0",
            }
            for before, after in replacements.items():
                source = source.replace(before, after)
            log.write_text(source, encoding="utf-8")
            report = self.verify(log, latency)
        self.assertFalse(report["passed"])
        self.assertTrue(any("repeat a real endpoint" in item
                            for item in report["failures"]))

    def test_five_percent_perturbation_cannot_disguise_crossfade(self):
        directory, log, latency = self.evidence()
        with directory:
            # 95% of eligible pixels are still fixed-coordinate crossfade. The
            # old 5% gate accepted this exact boundary as "motion correlated".
            source = log.read_text(encoding="utf-8")
            source = source.replace("nonCrossfadeSyntheticPixels=8000",
                                    "nonCrossfadeSyntheticPixels=600")
            source = source.replace("motionCorrelatedProofSamples=90",
                                    "motionCorrelatedProofSamples=20")
            log.write_text(source, encoding="utf-8")
            report = self.verify(log, latency)
        self.assertFalse(report["passed"])
        self.assertTrue(any("most synthetic output" in item
                            for item in report["failures"]))

    def test_rejected_gamecube_fragmentation_cannot_pass_on_directional_counter(self):
        directory, log, latency = self.evidence()
        with directory:
            source = log.read_text(encoding="utf-8")
            replacements = {
                "eligibleSyntheticPixels=12000":
                    "eligibleSyntheticPixels=11443",
                "substantiveSyntheticPixels=9000":
                    "substantiveSyntheticPixels=10551",
                "nonCrossfadeSyntheticPixels=8000":
                    "nonCrossfadeSyntheticPixels=3444",
                "motionCorrelatedProofSamples=90":
                    "motionCorrelatedProofSamples=0",
                "v21DirectionallyEligibleSyntheticPixels=5000":
                    "v21DirectionallyEligibleSyntheticPixels=4948",
                "v21CorrectVectorPredictedSyntheticPixels=4200":
                    "v21CorrectVectorPredictedSyntheticPixels=4948",
            }
            for before, after in replacements.items():
                source = source.replace(before, after)
            log.write_text(source, encoding="utf-8")
            report = self.verify(log, latency)
        self.assertFalse(report["passed"])
        self.assertEqual(report["spatialMotionSynthesisFraction"], 1.0)
        self.assertAlmostEqual(report["nonCrossfadePixelFraction"],
                               3444 / 11443)
        self.assertTrue(any("most synthetic output" in item
                            for item in report["failures"]))
        self.assertTrue(any("not correlated" in item
                            for item in report["failures"]))

    def test_motion_disabled_gamecube_cadence_cannot_pass_as_interpolation(self):
        directory, log, latency = self.evidence()
        with directory:
            source = log.read_text(encoding="utf-8")
            replacements = {
                "eligibleSyntheticPixels=12000":
                    "eligibleSyntheticPixels=11639",
                "substantiveSyntheticPixels=9000":
                    "substantiveSyntheticPixels=11561",
                "nonCrossfadeSyntheticPixels=8000":
                    "nonCrossfadeSyntheticPixels=839",
                "motionEligibleProofSamples=100":
                    "motionEligibleProofSamples=5",
                "motionCorrelatedProofSamples=90":
                    "motionCorrelatedProofSamples=0",
                "v21DirectionallyEligibleSyntheticPixels=5000":
                    "v21DirectionallyEligibleSyntheticPixels=227",
                "v21CorrectVectorPredictedSyntheticPixels=4200":
                    "v21CorrectVectorPredictedSyntheticPixels=227",
            }
            for before, after in replacements.items():
                source = source.replace(before, after)
            log.write_text(source, encoding="utf-8")
            report = self.verify(log, latency)
        self.assertFalse(report["passed"])
        self.assertAlmostEqual(report["nonCrossfadePixelFraction"],
                               839 / 11639)
        self.assertTrue(any("most synthetic output" in item
                            for item in report["failures"]))
        self.assertTrue(any("too few synthesized samples" in item
                            for item in report["failures"]))

    def test_sparse_v9_gamecube_motion_cannot_pass_on_clean_cadence(self):
        directory, log, latency = self.evidence()
        with directory:
            source = log.read_text(encoding="utf-8")
            replacements = {
                "eligibleSyntheticPixels=12000":
                    "eligibleSyntheticPixels=12593",
                "substantiveSyntheticPixels=9000":
                    "substantiveSyntheticPixels=12244",
                "nonCrossfadeSyntheticPixels=8000":
                    "nonCrossfadeSyntheticPixels=1927",
                "motionEligibleProofSamples=100":
                    "motionEligibleProofSamples=44",
                "motionCorrelatedProofSamples=90":
                    "motionCorrelatedProofSamples=0",
                "v21DirectionallyEligibleSyntheticPixels=5000":
                    "v21DirectionallyEligibleSyntheticPixels=1077",
                "v21CorrectVectorPredictedSyntheticPixels=4200":
                    "v21CorrectVectorPredictedSyntheticPixels=1077",
            }
            for before, after in replacements.items():
                source = source.replace(before, after)
            log.write_text(source, encoding="utf-8")
            report = self.verify(log, latency)
        self.assertFalse(report["passed"])
        self.assertAlmostEqual(report["nonCrossfadePixelFraction"],
                               1927 / 12593)
        self.assertEqual(report["spatialMotionSynthesisFraction"], 1.0)
        self.assertTrue(any("most synthetic output" in item
                            for item in report["failures"]))

    def test_exact_bc3_v10_gamecube_counters_remain_rejected_by_v11_gates(self):
        directory, log, latency = self.evidence()
        with directory:
            source = log.read_text(encoding="utf-8")
            replacements = {
                "eligibleSyntheticPixels=12000":
                    "eligibleSyntheticPixels=11664",
                "substantiveSyntheticPixels=9000":
                    "substantiveSyntheticPixels=11471",
                "nonCrossfadeSyntheticPixels=8000":
                    "nonCrossfadeSyntheticPixels=1604",
                "motionEligibleProofSamples=100":
                    "motionEligibleProofSamples=38",
                "motionCorrelatedProofSamples=90":
                    "motionCorrelatedProofSamples=1",
                "v21DirectionallyEligibleSyntheticPixels=5000":
                    "v21DirectionallyEligibleSyntheticPixels=842",
                "v21CorrectVectorPredictedSyntheticPixels=4200":
                    "v21CorrectVectorPredictedSyntheticPixels=842",
                "windowElapsedMs=2000": "windowElapsedMs=1013",
                "windowPresents=240": "windowPresents=120",
                "windowGenerated=120": "windowGenerated=59",
                "windowPromoted=120": "windowPromoted=61",
            }
            for before, after in replacements.items():
                source = source.replace(before, after)
            log.write_text(source, encoding="utf-8")
            report = self.verify(log, latency)
        self.assertFalse(report["passed"])
        self.assertAlmostEqual(report["nonCrossfadePixelFraction"],
                               1604 / 11664)
        self.assertTrue(any("most synthetic output" in item
                            for item in report["failures"]))

    def test_exact_a094_v13_gamecube_content_failure_remains_rejected_by_v17(self):
        directory, log, latency = self.evidence()
        with directory:
            source = log.read_text(encoding="utf-8")
            replacements = {
                "proofSamples=120": "proofSamples=60",
                "syntheticProofSamples=100": "syntheticProofSamples=60",
                "syntheticDistinctFromEndpoints=94":
                    "syntheticDistinctFromEndpoints=60",
                "changingProofOutputs=100": "changingProofOutputs=59",
                "eligibleSyntheticPixels=12000":
                    "eligibleSyntheticPixels=10742",
                "substantiveSyntheticPixels=9000":
                    "substantiveSyntheticPixels=10478",
                "nonCrossfadeSyntheticPixels=8000":
                    "nonCrossfadeSyntheticPixels=1403",
                "motionEligibleProofSamples=100":
                    "motionEligibleProofSamples=8",
                "motionCorrelatedProofSamples=90":
                    "motionCorrelatedProofSamples=2",
                "v21DirectionallyEligibleSyntheticPixels=5000":
                    "v21DirectionallyEligibleSyntheticPixels=399",
                "v21CorrectVectorPredictedSyntheticPixels=4200":
                    "v21CorrectVectorPredictedSyntheticPixels=399",
                "latticeRegionSamples=11520": "latticeRegionSamples=5760",
                "latticeBackwardCoherentRegions=2300":
                    "latticeBackwardCoherentRegions=0",
                "latticeForwardCoherentRegions=2250":
                    "latticeForwardCoherentRegions=0",
                "latticeBackwardCoherentRegionCount=20":
                    "latticeBackwardCoherentRegionCount=0",
                "latticeForwardCoherentRegionCount=19":
                    "latticeForwardCoherentRegionCount=0",
                "latticeBackwardPeakSupport=180": "latticeBackwardPeakSupport=0",
                "latticeForwardPeakSupport=175": "latticeForwardPeakSupport=0",
                "regionalFlowRegionSamples=11520":
                    "regionalFlowRegionSamples=5760",
                "regionalBackwardSupportedRegions=2500":
                    "regionalBackwardSupportedRegions=0",
                "regionalForwardSupportedRegions=2480":
                    "regionalForwardSupportedRegions=0",
                "regionalBackwardAcceptedRegions=2100":
                    "regionalBackwardAcceptedRegions=0",
                "regionalForwardAcceptedRegions=2040":
                    "regionalForwardAcceptedRegions=0",
                "regionalBackwardCycleAcceptedRegions=1800":
                    "regionalBackwardCycleAcceptedRegions=0",
                "regionalBackwardAcceptedRegionCount=18":
                    "regionalBackwardAcceptedRegionCount=0",
                "regionalForwardAcceptedRegionCount=17":
                    "regionalForwardAcceptedRegionCount=0",
                "regionalBackwardCycleAcceptedRegionCount=15":
                    "regionalBackwardCycleAcceptedRegionCount=0",
                "regionalBackwardSupportedRegionCount=22":
                    "regionalBackwardSupportedRegionCount=0",
                "regionalForwardSupportedRegionCount=21":
                    "regionalForwardSupportedRegionCount=0",
                "windowElapsedMs=2000": "windowElapsedMs=1015",
                "windowPresents=240": "windowPresents=120",
                "windowGenerated=120": "windowGenerated=60",
                "windowPromoted=120": "windowPromoted=60",
            }
            for before, after in replacements.items():
                source = source.replace(before, after)
            log.write_text(source, encoding="utf-8")
            report = self.verify(log, latency)
        self.assertFalse(report["passed"])
        self.assertAlmostEqual(report["nonCrossfadePixelFraction"],
                               1403 / 10742)
        self.assertEqual(report["spatialMotionSynthesisFraction"], 1.0)
        self.assertTrue(any("most synthetic output" in item
                            for item in report["failures"]))
        self.assertTrue(any("too few synthesized samples" in item
                            for item in report["failures"]))

    def test_exact_9aa2_v14_gamecube_content_failure_remains_rejected_by_v17(self):
        directory, log, latency = self.evidence()
        with directory:
            source = log.read_text(encoding="utf-8")
            replacements = {
                "proofSamples=120": "proofSamples=60",
                "syntheticProofSamples=100": "syntheticProofSamples=60",
                "syntheticDistinctFromEndpoints=94":
                    "syntheticDistinctFromEndpoints=60",
                "changingProofOutputs=100": "changingProofOutputs=59",
                "eligibleSyntheticPixels=12000":
                    "eligibleSyntheticPixels=12536",
                "substantiveSyntheticPixels=9000":
                    "substantiveSyntheticPixels=12285",
                "nonCrossfadeSyntheticPixels=8000":
                    "nonCrossfadeSyntheticPixels=1430",
                "motionEligibleProofSamples=100":
                    "motionEligibleProofSamples=4",
                "motionCorrelatedProofSamples=90":
                    "motionCorrelatedProofSamples=0",
                "v21DirectionallyEligibleSyntheticPixels=5000":
                    "v21DirectionallyEligibleSyntheticPixels=319",
                "v21CorrectVectorPredictedSyntheticPixels=4200":
                    "v21CorrectVectorPredictedSyntheticPixels=319",
                "latticeRegionSamples=11520": "latticeRegionSamples=5760",
                "latticeBackwardCoherentRegions=2300":
                    "latticeBackwardCoherentRegions=0",
                "latticeForwardCoherentRegions=2250":
                    "latticeForwardCoherentRegions=0",
                "latticeBackwardCoherentRegionCount=20":
                    "latticeBackwardCoherentRegionCount=0",
                "latticeForwardCoherentRegionCount=19":
                    "latticeForwardCoherentRegionCount=0",
                "latticeBackwardPeakSupport=180": "latticeBackwardPeakSupport=0",
                "latticeForwardPeakSupport=175": "latticeForwardPeakSupport=0",
                "regionalFlowRegionSamples=11520":
                    "regionalFlowRegionSamples=5760",
                "regionalBackwardSupportedRegions=2500":
                    "regionalBackwardSupportedRegions=0",
                "regionalForwardSupportedRegions=2480":
                    "regionalForwardSupportedRegions=0",
                "regionalBackwardAcceptedRegions=2100":
                    "regionalBackwardAcceptedRegions=0",
                "regionalForwardAcceptedRegions=2040":
                    "regionalForwardAcceptedRegions=0",
                "regionalBackwardCycleAcceptedRegions=1800":
                    "regionalBackwardCycleAcceptedRegions=0",
                "regionalBackwardAcceptedRegionCount=18":
                    "regionalBackwardAcceptedRegionCount=0",
                "regionalForwardAcceptedRegionCount=17":
                    "regionalForwardAcceptedRegionCount=0",
                "regionalBackwardCycleAcceptedRegionCount=15":
                    "regionalBackwardCycleAcceptedRegionCount=0",
                "regionalBackwardSupportedRegionCount=22":
                    "regionalBackwardSupportedRegionCount=0",
                "regionalForwardSupportedRegionCount=21":
                    "regionalForwardSupportedRegionCount=0",
                "regionalBackwardPeakSupport=210":
                    "regionalBackwardPeakSupport=69",
                "regionalForwardPeakSupport=205":
                    "regionalForwardPeakSupport=64",
                "regionalBackwardPeakConfidence=180":
                    "regionalBackwardPeakConfidence=0",
                "regionalForwardPeakConfidence=176":
                    "regionalForwardPeakConfidence=0",
                "windowElapsedMs=2000": "windowElapsedMs=1015",
                "windowPresents=240": "windowPresents=120",
                "windowGenerated=120": "windowGenerated=60",
                "windowPromoted=120": "windowPromoted=60",
            }
            for before, after in replacements.items():
                source = source.replace(before, after)
            log.write_text(source, encoding="utf-8")
            report = self.verify(log, latency)
        self.assertFalse(report["passed"])
        self.assertAlmostEqual(report["nonCrossfadePixelFraction"],
                               1430 / 12536)
        self.assertEqual(report["regionalFlow"]["backwardAcceptedRegions"], 0)
        self.assertTrue(any("most synthetic output" in item
                            for item in report["failures"]))
        self.assertTrue(any("too few synthesized samples" in item
                            for item in report["failures"]))

    def test_exact_1d15_v15_gamecube_content_failure_remains_rejected_by_v17(self):
        directory, log, latency = self.evidence()
        with directory:
            source = log.read_text(encoding="utf-8")
            replacements = {
                "proofSamples=120": "proofSamples=60",
                "syntheticProofSamples=100": "syntheticProofSamples=60",
                "syntheticDistinctFromEndpoints=94":
                    "syntheticDistinctFromEndpoints=60",
                "changingProofOutputs=100": "changingProofOutputs=59",
                "eligibleSyntheticPixels=12000":
                    "eligibleSyntheticPixels=11487",
                "substantiveSyntheticPixels=9000":
                    "substantiveSyntheticPixels=11000",
                "nonCrossfadeSyntheticPixels=8000":
                    "nonCrossfadeSyntheticPixels=1698",
                "motionEligibleProofSamples=100":
                    "motionEligibleProofSamples=8",
                "motionCorrelatedProofSamples=90":
                    "motionCorrelatedProofSamples=0",
                "v21DirectionallyEligibleSyntheticPixels=5000":
                    "v21DirectionallyEligibleSyntheticPixels=391",
                "v21CorrectVectorPredictedSyntheticPixels=4200":
                    "v21CorrectVectorPredictedSyntheticPixels=391",
                "latticeRegionSamples=11520": "latticeRegionSamples=5760",
                "latticeBackwardCoherentRegions=2300":
                    "latticeBackwardCoherentRegions=0",
                "latticeForwardCoherentRegions=2250":
                    "latticeForwardCoherentRegions=0",
                "latticeBackwardCoherentRegionCount=20":
                    "latticeBackwardCoherentRegionCount=0",
                "latticeForwardCoherentRegionCount=19":
                    "latticeForwardCoherentRegionCount=0",
                "latticeBackwardPeakSupport=180": "latticeBackwardPeakSupport=0",
                "latticeForwardPeakSupport=175": "latticeForwardPeakSupport=0",
                "regionalFlowRegionSamples=11520":
                    "regionalFlowRegionSamples=5760",
                "regionalBackwardSupportedRegions=2500":
                    "regionalBackwardSupportedRegions=23",
                "regionalForwardSupportedRegions=2480":
                    "regionalForwardSupportedRegions=11",
                "regionalBackwardAcceptedRegions=2100":
                    "regionalBackwardAcceptedRegions=11",
                "regionalForwardAcceptedRegions=2040":
                    "regionalForwardAcceptedRegions=3",
                "regionalBackwardCycleAcceptedRegions=1800":
                    "regionalBackwardCycleAcceptedRegions=2",
                "regionalBackwardAcceptedRegionCount=18":
                    "regionalBackwardAcceptedRegionCount=0",
                "regionalForwardAcceptedRegionCount=17":
                    "regionalForwardAcceptedRegionCount=0",
                "regionalBackwardCycleAcceptedRegionCount=15":
                    "regionalBackwardCycleAcceptedRegionCount=0",
                "regionalBackwardSupportedRegionCount=22":
                    "regionalBackwardSupportedRegionCount=0",
                "regionalForwardSupportedRegionCount=21":
                    "regionalForwardSupportedRegionCount=0",
                "windowElapsedMs=2000": "windowElapsedMs=1013",
                "windowPresents=240": "windowPresents=120",
                "windowGenerated=120": "windowGenerated=60",
                "windowPromoted=120": "windowPromoted=60",
            }
            for before, after in replacements.items():
                source = source.replace(before, after)
            log.write_text(source, encoding="utf-8")
            report = self.verify(log, latency)
        self.assertFalse(report["passed"])
        self.assertAlmostEqual(report["nonCrossfadePixelFraction"],
                               1698 / 11487)
        self.assertEqual(report["regionalFlow"]["backwardSupportedRegions"], 23)
        self.assertEqual(report["regionalFlow"]["backwardCycleAcceptedRegions"], 2)
        self.assertTrue(any("most synthetic output" in item
                            for item in report["failures"]))
        self.assertTrue(any("too few changing pixels" in item or
                            "too few synthesized samples" in item
                            for item in report["failures"]))

    def test_exact_d254_v16_gamecube_content_failure_remains_rejected_by_v17(self):
        directory, log, latency = self.evidence()
        with directory:
            source = log.read_text(encoding="utf-8")
            replacements = {
                "proofSamples=120": "proofSamples=60",
                "syntheticProofSamples=100": "syntheticProofSamples=60",
                "syntheticDistinctFromEndpoints=94":
                    "syntheticDistinctFromEndpoints=60",
                "changingProofOutputs=100": "changingProofOutputs=59",
                "eligibleSyntheticPixels=12000":
                    "eligibleSyntheticPixels=11960",
                "substantiveSyntheticPixels=9000":
                    "substantiveSyntheticPixels=11680",
                "nonCrossfadeSyntheticPixels=8000":
                    "nonCrossfadeSyntheticPixels=1543",
                "motionEligibleProofSamples=100":
                    "motionEligibleProofSamples=6",
                "motionCorrelatedProofSamples=90":
                    "motionCorrelatedProofSamples=0",
                "v21DirectionallyEligibleSyntheticPixels=5000":
                    "v21DirectionallyEligibleSyntheticPixels=311",
                "v21CorrectVectorPredictedSyntheticPixels=4200":
                    "v21CorrectVectorPredictedSyntheticPixels=311",
                "latticeRegionSamples=11520": "latticeRegionSamples=5760",
                "latticeBackwardCoherentRegions=2300":
                    "latticeBackwardCoherentRegions=1274",
                "latticeForwardCoherentRegions=2250":
                    "latticeForwardCoherentRegions=1268",
                "latticeBackwardBoundaryRegions=100":
                    "latticeBackwardBoundaryRegions=0",
                "latticeForwardBoundaryRegions=90":
                    "latticeForwardBoundaryRegions=0",
                "latticeBackwardCoherentRegionCount=20":
                    "latticeBackwardCoherentRegionCount=22",
                "latticeForwardCoherentRegionCount=19":
                    "latticeForwardCoherentRegionCount=22",
                "latticeBackwardBoundaryRegionCount=1":
                    "latticeBackwardBoundaryRegionCount=0",
                "latticeForwardBoundaryRegionCount=2":
                    "latticeForwardBoundaryRegionCount=0",
                "regionalFlowRegionSamples=11520":
                    "regionalFlowRegionSamples=5760",
                "regionalBackwardSupportedRegions=2500":
                    "regionalBackwardSupportedRegions=7",
                "regionalForwardSupportedRegions=2480":
                    "regionalForwardSupportedRegions=5",
                "regionalBackwardNeighborRegions=2400":
                    "regionalBackwardNeighborRegions=1",
                "regionalForwardNeighborRegions=2300":
                    "regionalForwardNeighborRegions=4",
                "regionalBackwardAcceptedRegions=2100":
                    "regionalBackwardAcceptedRegions=1",
                "regionalForwardAcceptedRegions=2040":
                    "regionalForwardAcceptedRegions=4",
                "regionalBackwardCycleAcceptedRegions=1800":
                    "regionalBackwardCycleAcceptedRegions=0",
                "regionalBackwardAcceptedRegionCount=18":
                    "regionalBackwardAcceptedRegionCount=0",
                "regionalForwardAcceptedRegionCount=17":
                    "regionalForwardAcceptedRegionCount=0",
                "regionalBackwardCycleAcceptedRegionCount=15":
                    "regionalBackwardCycleAcceptedRegionCount=0",
                "regionalBackwardSupportedRegionCount=22":
                    "regionalBackwardSupportedRegionCount=0",
                "regionalForwardSupportedRegionCount=21":
                    "regionalForwardSupportedRegionCount=0",
                "regionalBackwardNeighborRegionCount=20":
                    "regionalBackwardNeighborRegionCount=0",
                "regionalForwardNeighborRegionCount=19":
                    "regionalForwardNeighborRegionCount=0",
                "windowElapsedMs=2000": "windowElapsedMs=1013",
                "windowPresents=240": "windowPresents=120",
                "windowGenerated=120": "windowGenerated=60",
                "windowPromoted=120": "windowPromoted=60",
            }
            for before, after in replacements.items():
                source = source.replace(before, after)
            log.write_text(source, encoding="utf-8")
            report = self.verify(log, latency)
        self.assertFalse(report["passed"])
        self.assertAlmostEqual(report["nonCrossfadePixelFraction"],
                               1543 / 11960)
        self.assertEqual(
            report["candidateLattice"]["backwardCoherentRegions"], 1274)
        self.assertEqual(report["regionalFlow"]["backwardSupportedRegions"], 7)
        self.assertTrue(any("most synthetic output" in item
                            for item in report["failures"]))
        self.assertTrue(any("too few changing pixels" in item or
                            "too few synthesized samples" in item
                            for item in report["failures"]))

    def test_exact_3979_v18_gamecube_content_failure_remains_rejected_by_v19(self):
        directory, log, latency = self.evidence()
        with directory:
            source = log.read_text(encoding="utf-8")
            replacements = {
                "proofSamples=120": "proofSamples=60",
                "syntheticProofSamples=100": "syntheticProofSamples=60",
                "syntheticDistinctFromEndpoints=94":
                    "syntheticDistinctFromEndpoints=60",
                "changingProofOutputs=100": "changingProofOutputs=59",
                "eligibleSyntheticPixels=12000":
                    "eligibleSyntheticPixels=11344",
                "substantiveSyntheticPixels=9000":
                    "substantiveSyntheticPixels=11000",
                "nonCrossfadeSyntheticPixels=8000":
                    "nonCrossfadeSyntheticPixels=2030",
                "motionEligibleProofSamples=100":
                    "motionEligibleProofSamples=23",
                "motionCorrelatedProofSamples=90":
                    "motionCorrelatedProofSamples=0",
                "v21DirectionallyEligibleSyntheticPixels=5000":
                    "v21DirectionallyEligibleSyntheticPixels=831",
                "v21CorrectVectorPredictedSyntheticPixels=4200":
                    "v21CorrectVectorPredictedSyntheticPixels=831",
                "latticeRegionSamples=11520": "latticeRegionSamples=5760",
                "latticeBackwardCoherentRegions=2300":
                    "latticeBackwardCoherentRegions=841",
                "latticeForwardCoherentRegions=2250":
                    "latticeForwardCoherentRegions=824",
                "latticeBackwardBoundaryRegions=100":
                    "latticeBackwardBoundaryRegions=1414",
                "latticeForwardBoundaryRegions=90":
                    "latticeForwardBoundaryRegions=1414",
                "latticeBackwardCoherentRegionCount=20":
                    "latticeBackwardCoherentRegionCount=0",
                "latticeForwardCoherentRegionCount=19":
                    "latticeForwardCoherentRegionCount=0",
                "latticeBackwardBoundaryRegionCount=1":
                    "latticeBackwardBoundaryRegionCount=0",
                "latticeForwardBoundaryRegionCount=2":
                    "latticeForwardBoundaryRegionCount=0",
                "regionalFlowRegionSamples=11520":
                    "regionalFlowRegionSamples=5760",
                "regionalBackwardSupportedRegions=2500":
                    "regionalBackwardSupportedRegions=771",
                "regionalForwardSupportedRegions=2480":
                    "regionalForwardSupportedRegions=758",
                "regionalBackwardNeighborRegions=2400":
                    "regionalBackwardNeighborRegions=415",
                "regionalForwardNeighborRegions=2300":
                    "regionalForwardNeighborRegions=416",
                "regionalBackwardConstantNeighborRegions=2200":
                    "regionalBackwardConstantNeighborRegions=415",
                "regionalForwardConstantNeighborRegions=2100":
                    "regionalForwardConstantNeighborRegions=416",
                "regionalBackwardGradientNeighborRegions=500":
                    "regionalBackwardGradientNeighborRegions=0",
                "regionalForwardGradientNeighborRegions=450":
                    "regionalForwardGradientNeighborRegions=0",
                "regionalBackwardAcceptedRegions=2100":
                    "regionalBackwardAcceptedRegions=161",
                "regionalForwardAcceptedRegions=2040":
                    "regionalForwardAcceptedRegions=161",
                "regionalBackwardCycleAcceptedRegions=1800":
                    "regionalBackwardCycleAcceptedRegions=77",
                "regionalForwardCycleAcceptedRegions=1750":
                    "regionalForwardCycleAcceptedRegions=77",
                "regionalBackwardAcceptedRegionCount=18":
                    "regionalBackwardAcceptedRegionCount=0",
                "regionalForwardAcceptedRegionCount=17":
                    "regionalForwardAcceptedRegionCount=0",
                "regionalBackwardCycleAcceptedRegionCount=15":
                    "regionalBackwardCycleAcceptedRegionCount=0",
                "regionalForwardCycleAcceptedRegionCount=14":
                    "regionalForwardCycleAcceptedRegionCount=0",
                "regionalBackwardSupportedRegionCount=22":
                    "regionalBackwardSupportedRegionCount=0",
                "regionalForwardSupportedRegionCount=21":
                    "regionalForwardSupportedRegionCount=0",
                "regionalBackwardNeighborRegionCount=20":
                    "regionalBackwardNeighborRegionCount=0",
                "regionalForwardNeighborRegionCount=19":
                    "regionalForwardNeighborRegionCount=0",
                "regionalBackwardConstantNeighborRegionCount=18":
                    "regionalBackwardConstantNeighborRegionCount=0",
                "regionalForwardConstantNeighborRegionCount=17":
                    "regionalForwardConstantNeighborRegionCount=0",
                "regionalBackwardGradientNeighborRegionCount=5":
                    "regionalBackwardGradientNeighborRegionCount=0",
                "regionalForwardGradientNeighborRegionCount=4":
                    "regionalForwardGradientNeighborRegionCount=0",
                "windowElapsedMs=2000": "windowElapsedMs=1013",
                "windowPresents=240": "windowPresents=120",
                "windowGenerated=120": "windowGenerated=60",
                "windowPromoted=120": "windowPromoted=60",
            }
            for before, after in replacements.items():
                source = source.replace(before, after)
            log.write_text(source, encoding="utf-8")
            report = self.verify(log, latency)
        self.assertFalse(report["passed"])
        self.assertAlmostEqual(report["nonCrossfadePixelFraction"],
                               2030 / 11344)
        self.assertEqual(report["regionalFlow"]["backwardSupportedRegions"], 771)
        self.assertEqual(report["regionalFlow"]["backwardCycleAcceptedRegions"], 77)
        self.assertEqual(report["spatialMotionSynthesisFraction"], 1.0)
        self.assertTrue(any("most synthetic output" in item
                            for item in report["failures"]))
        self.assertTrue(any("not correlated" in item
                            for item in report["failures"]))

    def test_bad_generated_cadence_cannot_fake_120_badge(self):
        directory, log, latency = self.evidence()
        with directory:
            source = log.read_text(encoding="utf-8").replace(
                "windowGenerated=120", "windowGenerated=20")
            log.write_text(source, encoding="utf-8")
            report = self.verify(log, latency)
        self.assertFalse(report["passed"])
        self.assertTrue(any("exact source-to-panel gap" in item
                            for item in report["failures"]))

    def test_unrelated_global_flow_cannot_fake_spatial_motion_synthesis(self):
        directory, log, latency = self.evidence()
        with directory:
            source = log.read_text(encoding="utf-8").replace(
                "v21CorrectVectorPredictedSyntheticPixels=4200",
                "v21CorrectVectorPredictedSyntheticPixels=200",
            )
            log.write_text(source, encoding="utf-8")
            report = self.verify(log, latency)
        self.assertFalse(report["passed"])
        self.assertTrue(any("spatially follow" in item
                            for item in report["failures"]))

    def test_exact_generated_gap_for_every_locked_tier(self):
        expected = {20: 20, 30: 30, 40: 40, 50: 50, 60: 60}
        for locked, generated_fps in expected.items():
            with self.subTest(locked=locked):
                directory, log, latency = self.evidence()
                with directory:
                    source = log.read_text(encoding="utf-8")
                    source = source.replace("lockedFps=60", f"lockedFps={locked}")
                    source = source.replace(
                        "outputFps=120 panelFps=120",
                        f"outputFps={locked * 2} panelFps=120")
                    source = source.replace(
                        "windowGenerated=120 windowPromoted=120",
                        f"windowGenerated={generated_fps * 2} "
                        f"windowPromoted={locked * 2}",
                    )
                    source = source.replace(
                        "windowPresents=240",
                        f"windowPresents={locked * 4}",
                    )
                    panel_period = round(1_000_000_000 / 120)
                    output_period = round(1_000_000_000 / (locked * 2))
                    stamp = 12_000_000_000
                    rows = ["8333333"]
                    deadline = 0
                    tolerance = panel_period // 4
                    for _ in range(240):
                        selected = stamp + tolerance
                        if deadline == 0 or selected >= deadline:
                            rows.append(f"{stamp} {stamp} {stamp}")
                            if deadline == 0:
                                deadline = stamp + output_period
                            else:
                                while deadline <= selected:
                                    deadline += output_period
                        stamp += panel_period
                    latency.write_text("\n".join(rows) + "\n", encoding="utf-8")
                    log.write_text(source, encoding="utf-8")
                    report = self.verify(log, latency)
                self.assertTrue(report["passed"], report)
                self.assertAlmostEqual(report["cadence"]["realFps"], locked)
                self.assertAlmostEqual(
                    report["cadence"]["generatedFps"], generated_fps)
                self.assertAlmostEqual(report["cadence"]["outputFps"], locked * 2)

    def test_wrong_gap_fails_at_every_locked_tier(self):
        expected = {20: 20, 30: 30, 40: 40, 50: 50, 60: 60}
        for locked, generated_fps in expected.items():
            with self.subTest(locked=locked):
                directory, log, latency = self.evidence()
                with directory:
                    source = log.read_text(encoding="utf-8")
                    source = source.replace("lockedFps=60", f"lockedFps={locked}")
                    source = source.replace(
                        "outputFps=120 panelFps=120",
                        f"outputFps={locked * 2} panelFps=120")
                    source = source.replace(
                        "windowGenerated=120 windowPromoted=120",
                        f"windowGenerated={(generated_fps - 10) * 2} "
                        f"windowPromoted={locked * 2}",
                    )
                    log.write_text(source, encoding="utf-8")
                    report = self.verify(log, latency)
                self.assertFalse(report["passed"])
                self.assertTrue(any("exact source-to-panel gap" in item
                                    for item in report["failures"]))

    def test_surface_target_must_match_generator_output(self):
        directory, log, latency = self.evidence()
        with directory:
            # Internally consistent 90-Hz SurfaceFlinger data must not be joined
            # to the generator's 120-FPS health record.
            period = 11_111_111
            stamp = 1_000_000_000
            rows = [str(period)]
            for _ in range(128):
                rows.append(f"{stamp} {stamp + 1000} {stamp + 2000}")
                stamp += period
            latency.write_text("\n".join(rows) + "\n", encoding="utf-8")
            report = self.verify(log, latency)
        self.assertFalse(report["passed"])
        self.assertTrue(any("physical refresh" in item for item in report["failures"]))

    def test_twice_panel_rate_is_not_accepted_as_on_target(self):
        directory, log, latency = self.evidence()
        with directory:
            period = 8_333_333
            stamp = 1_000_000_000
            rows = [str(period)]
            for _ in range(128):
                rows.append(f"{stamp} {stamp + 1000} {stamp + 2000}")
                stamp += period // 2
            latency.write_text("\n".join(rows) + "\n", encoding="utf-8")
            report = self.verify(log, latency)
        self.assertFalse(report["passed"])
        self.assertTrue(any("reported output cadence" in item
                            for item in report["failures"]))

    def test_desired_timestamps_cannot_hide_slow_actual_presentation(self):
        directory, log, latency = self.evidence()
        with directory:
            desired = 1_000_000_000
            actual = 1_000_000_000
            rows = ["8333333"]
            for _ in range(128):
                rows.append(f"{desired} {actual} {desired + 1_000_000}")
                desired += 8_333_333       # requested at 120 Hz
                actual += 33_333_333        # visible at only 30 Hz
            latency.write_text("\n".join(rows) + "\n", encoding="utf-8")
            report = self.verify(log, latency)
        self.assertFalse(report["passed"])
        self.assertTrue(any("reported output cadence" in item
                            for item in report["failures"]))

    def test_timestamp_shift_cannot_force_unrelated_trace_to_overlap(self):
        directory, log, latency = self.evidence()
        with directory:
            rows = latency.read_text(encoding="utf-8").splitlines()
            shifted = [rows[0]]
            for row in rows[1:]:
                columns = row.split()
                shifted.append(" ".join(str(int(value) + 20_000_000_000)
                                        for value in columns))
            latency.write_text("\n".join(shifted) + "\n", encoding="utf-8")
            report = self.verify(log, latency)
        self.assertFalse(report["passed"])
        self.assertEqual(report["surfaceFlingerRawOverlapFrames"], 0)
        self.assertTrue(any("does not overlap" in item
                            for item in report["failures"]))

    def test_mixed_process_records_cannot_join_one_generator_number(self):
        directory, log, latency = self.evidence()
        with directory:
            lines = log.read_text(encoding="utf-8").splitlines()
            lines[-1] = lines[-1].replace(
                "I/EmuFusionFrameGen(1234)", "I/EmuFusionFrameGen(9876)")
            log.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "multiple primary generator processes"):
                self.verify(log, latency)

    def test_duplicate_proof_enable_cannot_join_multiple_sessions(self):
        directory, log, latency = self.evidence()
        with directory:
            with log.open("a", encoding="utf-8") as stream:
                stream.write(
                    "I/EmuFusionFrameGen(1234): Qualification proof "
                    "generator=7 enabled=true "
                    "proofContract=native-pixel-refined-regional-flow-v22-x2-presented "
                    "proofSchemaVersion=22\n"
                )
            with self.assertRaisesRegex(ValueError, "enabled exactly once"):
                self.verify(log, latency)

    def test_pending_actual_present_fence_is_not_counted(self):
        directory, log, latency = self.evidence()
        with directory:
            maximum = (1 << 63) - 1
            latency.write_text(
                "8333333\n" +
                "\n".join(f"{1_000_000_000 + index * 8_333_333} {maximum} 1"
                          for index in range(128)) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "fewer than 31 valid"):
                self.verify(log, latency)


if __name__ == "__main__":
    unittest.main()
