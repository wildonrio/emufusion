"""Synthetic contract fixtures only; these files are NOT empirical evidence."""

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools import verify_frame_generation_evidence_v2 as verifier


class EvidenceContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="emufusion-evidence-fixture-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "manifest.json"
        self.artifacts = []
        self.add_artifact("apk", "apk", b"SYNTHETIC FIXTURE, NOT AN APK")
        for name, pixel in (("left", 0), ("generated", 64), ("right", 128), ("reference", 65)):
            self.add_artifact(name, "lossless_image", b"P6\n1 1\n255\n" + bytes([pixel] * 3))
        self.add_artifact("provenance", "capture_provenance",
                          b'{"kind":"synthetic_fixture","not_empirical":true}')
        self.add_artifact("trace", "presentation_trace", b"initial synthetic fixture")
        self.rows = [
            {"event": "run_start", "recorded_ns": 900_000_000, "session_id": "fixture-session"},
            {"event": "epoch_start", "recorded_ns": 950_000_000, "epoch_id": "epoch-1",
             "reset_reason": "startup", "panel_hz": 120, "source_hz": 30,
             "output_hz": 60, "mode": "x2"},
            {"event": "endpoint", "recorded_ns": 1_000_000_000, "epoch_id": "epoch-1",
             "endpoint_id": "a", "source_sequence": 1, "producer_timestamp_ns": 1_000_000_000},
            {"event": "endpoint", "recorded_ns": 1_033_333_334, "epoch_id": "epoch-1",
             "endpoint_id": "b", "source_sequence": 2, "producer_timestamp_ns": 1_033_333_334},
            self.present(1, "real", 1_050_000_000, 1_000_000_000, endpoint_id="a"),
            self.present(2, "generated", 1_066_666_667, 1_016_666_667,
                         left_endpoint_id="a", right_endpoint_id="b",
                         phase_numerator=1, phase_denominator=2),
            self.present(3, "real", 1_083_333_334, 1_033_333_334, endpoint_id="b"),
            {"event": "run_end", "recorded_ns": 1_100_000_000, "session_id": "fixture-session"},
        ]
        run = {"run_id": "fixture-run", "system": "fixture-system", "title": "SYNTHETIC FIXTURE",
               "backend": "fixture-backend", "mode": "x2", "apk_artifact_id": "apk", "trace_artifact_id": "trace",
               "identity": {key: "fixture-" + key for key in verifier.IDENTITY_FIELDS},
               "capture_samples": [{"kind": "generated", "present_id": 2, "left_endpoint_id": "a", "right_endpoint_id": "b",
                    "left_artifact_id": "left", "generated_artifact_id": "generated",
                    "right_artifact_id": "right", "reference_artifact_id": "reference",
                    "reference_kind": "held_out_real_middle", "provenance_artifact_id": "provenance"}]}
        run["identity"].update(pid=1, display_id=0, session_id="fixture-session",
                               clock_domains=dict.fromkeys(verifier.TIMESTAMP_FIELDS, "android_monotonic"),
                               apk_sha256=self.artifacts[0]["sha256"])
        self.manifest = {"schema_version": 1, "evidence_kind": "synthetic_fixture",
                         "campaign_id": "fixture-campaign", "artifacts": self.artifacts,
                         "runs": [run], "expected_runs": [{k: run[k] for k in
                             ("run_id", "system", "title", "backend", "mode")}]}
        self.persist()

    @staticmethod
    def present(pid, role, stamp, content, **extra):
        return {"event": "present", "recorded_ns": stamp + 10, "epoch_id": "epoch-1",
                "present_id": pid, "role": role, "role_source": "producer_identity",
                "outcome": "presented", "desired_present_ns": stamp,
                "actual_present_ns": stamp, "content_timestamp_ns": content,
                "deadline_missed": False, "fallback_reason": "", **extra}

    def add_artifact(self, name, kind, data):
        (self.root / name).write_bytes(data)
        self.artifacts.append({"artifact_id": name, "path": name, "kind": kind,
                               "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})

    def persist(self, recount=True, reindex=True):
        if reindex:
            for index, row in enumerate(self.rows, 1):
                row.update(event_index=index, run_id="fixture-run")
        if recount:
            counts = dict.fromkeys(verifier.COUNTERS, 0)
            for row in self.rows:
                if row["event"] == "epoch_start":
                    counts["epochs"] += 1
                elif row["event"] == "endpoint":
                    counts["endpoints"] += 1
                elif row["event"] == "present":
                    counts["present_attempts"] += 1
                    counts[row["outcome"]] += 1
                    counts["generated_presented"] += row["outcome"] == "presented" and row["role"] == "generated"
                    counts["deadline_misses"] += row["deadline_missed"]
                    counts["fallback_presents"] += bool(row["fallback_reason"])
            counts["resets"] = max(0, counts["epochs"] - 1)
            self.rows[-1]["counters"] = counts.copy()
            self.manifest["runs"][0]["counters"] = counts.copy()
        data = ("\n".join(json.dumps(row) for row in self.rows) + "\n").encode()
        (self.root / "trace").write_bytes(data)
        trace = next(a for a in self.artifacts if a["artifact_id"] == "trace")
        trace.update(sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data))
        self.path.write_text(json.dumps(self.manifest), encoding="utf-8")

    def result(self):
        return verifier.validate(self.path)

    def invalid(self, text):
        result = self.result()
        self.assertEqual(result["status"], "INVALID", result)
        self.assertFalse(result["passed"])
        self.assertIn(text, " ".join(result["errors"]))
        return result

    def test_structurally_complete_fixture_remains_unverified(self):
        result = self.result()
        self.assertEqual(result["status"], "UNVERIFIED", result)
        self.assertTrue(result["structural_checks_passed"])
        self.assertFalse(result["passed"])
        self.assertEqual(result["evidence_kind"], "synthetic_fixture")
        self.assertGreaterEqual(len(result["unimplemented_required_checks"]), 4)
        self.assertEqual(result["runs"][0]["observed_counters"]["generated_presented"], 1)

    def test_odd_span_midpoint_uses_floor_nanosecond(self):
        self.rows[3]["producer_timestamp_ns"] -= 1
        self.rows[6]["content_timestamp_ns"] -= 1
        self.rows[5]["content_timestamp_ns"] -= 1
        self.persist()
        self.assertTrue(self.result()["structural_checks_passed"])
        self.rows[5]["content_timestamp_ns"] += 1
        self.persist()
        self.invalid("timestamp is not midpoint")

    def test_author_claimed_pass_cannot_promote_result(self):
        self.manifest.update(passed=True, status="PASS", pixel_quality=1.0)
        self.persist()
        self.assertEqual(self.result()["status"], "UNVERIFIED")

    def test_missing_expected_system_run(self):
        other = dict(self.manifest["expected_runs"][0], run_id="missing-switch")
        self.manifest["expected_runs"].append(other)
        self.persist()
        self.invalid("missing or unexpected runs")

    def test_title_substitution(self):
        self.manifest["runs"][0]["title"] = "unreviewed title menu"
        self.persist()
        self.invalid("substituted")

    def test_artifact_tampering(self):
        (self.root / "generated").write_bytes(b"changed bytes")
        self.invalid("size mismatch")

    def test_artifact_same_size_hash_tampering(self):
        path = self.root / "generated"
        path.write_bytes(path.read_bytes()[:-1] + b"x")
        self.invalid("SHA-256 mismatch")

    def test_path_escape(self):
        self.artifacts[0]["path"] = "../outside-apk"
        self.persist()
        self.invalid("path escapes")

    def test_missing_run_boundaries(self):
        self.rows = self.rows[1:]
        self.persist()
        self.invalid("run boundaries")

    def test_missing_event_is_detected(self):
        self.rows[4]["event_index"] += 1
        self.persist(reindex=False)
        self.invalid("event_index gap")

    def test_guessed_generated_role(self):
        self.rows[5]["role_source"] = "alternating_video_frames"
        self.persist()
        self.invalid("guessed or missing frame role")

    def test_missing_physical_timestamp(self):
        del self.rows[5]["actual_present_ns"]
        self.persist()
        self.invalid("actual physical timestamp")

    def test_generated_present_before_right_endpoint_produced(self):
        self.rows[4]["actual_present_ns"] = 1_005_000_000
        self.rows[5]["actual_present_ns"] = 1_020_000_000
        self.persist()
        self.invalid("precedes production")

    def test_real_present_before_its_endpoint_produced(self):
        self.rows[4]["actual_present_ns"] = 999_999_999
        self.persist()
        self.invalid("precedes production")

    def test_content_cannot_return_to_left_endpoint_after_midpoint(self):
        self.rows[6].update(endpoint_id="a", content_timestamp_ns=1_000_000_000)
        self.persist()
        self.invalid("content chronology moved backwards")

    def test_duplicate_real_endpoint_cannot_masquerade_as_progress(self):
        self.rows[5].update(role="real", endpoint_id="a", content_timestamp_ns=1_000_000_000)
        self.persist()
        self.invalid("repeated without a hold")

    def test_missing_monotonic_clock_declaration(self):
        del self.manifest["runs"][0]["identity"]["clock_domains"]
        self.persist()
        self.invalid("clock domains")

    def test_incompatible_monotonic_clock_domains(self):
        self.manifest["runs"][0]["identity"]["clock_domains"]["producer_timestamp_ns"] = "guest_ticks"
        self.persist()
        self.invalid("clock domains")

    def test_missing_present_id(self):
        del self.rows[5]["present_id"]
        self.persist()
        self.invalid("present_id")

    def test_missing_endpoint_source_sequence(self):
        self.rows[3]["source_sequence"] = 3
        self.persist()
        self.invalid("source_sequence")

    def test_non_midpoint_phase(self):
        self.rows[5]["phase_denominator"] = 3
        self.persist()
        self.invalid("exact 1/2")

    def test_non_midpoint_timestamp(self):
        self.rows[5]["content_timestamp_ns"] += 1_000_000
        self.persist()
        self.invalid("timestamp is not midpoint")

    def test_x3_schedule(self):
        self.rows[1].update(source_hz=40, output_hz=120)
        self.persist()
        self.invalid("generation ceiling")

    def test_40_to_80_on_120_rejected(self):
        self.rows[1].update(source_hz=40, output_hz=80)
        self.persist()
        self.invalid("uniform integer panel divisor")

    def test_exact_fractional_panel_divisor(self):
        self.rows[1].update(source_hz=29.997, output_hz=59.994, panel_hz=119.988)
        self.persist()
        self.assertEqual(self.result()["status"], "UNVERIFIED")

    def test_explicit_rational_panel_divisor(self):
        self.rows[1].update(source_hz={"numerator": 29997, "denominator": 1000},
                            output_hz="29997/500", panel_hz="119.988")
        self.persist()
        self.assertEqual(self.result()["status"], "UNVERIFIED")

    def test_near_fractional_panel_divisor_is_not_rounded(self):
        self.rows[1].update(source_hz=29.997, output_hz=59.994, panel_hz=119.988001)
        self.persist()
        self.invalid("uniform integer panel divisor")

    def test_near_x2_source_rate_is_not_rounded(self):
        self.rows[1].update(source_hz=29.997001, output_hz=59.994, panel_hz=119.988)
        self.persist()
        self.invalid("generation ceiling")

    def test_invalid_rational_rates(self):
        for value in (True, 0, -1, "NaN", "Infinity", "1/0", [],
                      {"numerator": 1, "denominator": 0}):
            with self.subTest(value=value):
                self.rows[1]["source_hz"] = value
                self.persist()
                self.invalid("rate")

    def test_duplicate_generated_pair(self):
        duplicate = copy.deepcopy(self.rows[5])
        duplicate.update(present_id=3, recorded_ns=1_070_000_010,
                         desired_present_ns=1_070_000_000, actual_present_ns=1_070_000_000)
        self.rows[6]["present_id"] = 4
        self.rows.insert(6, duplicate)
        self.persist()
        self.invalid("more than one generated attempt")

    def test_missing_ground_truth(self):
        del self.manifest["runs"][0]["capture_samples"][0]["reference_artifact_id"]
        self.persist()
        self.invalid("capture images")

    def test_missing_capture_provenance(self):
        del self.manifest["runs"][0]["capture_samples"][0]["provenance_artifact_id"]
        self.persist()
        self.invalid("capture_provenance artifact identity")

    def test_capture_bound_to_wrong_present(self):
        self.manifest["runs"][0]["capture_samples"][0]["present_id"] = 1
        self.persist()
        self.invalid("physically presented generated row")

    def test_missing_capture_samples(self):
        self.manifest["runs"][0]["capture_samples"] = []
        self.persist()
        self.invalid("missing exact generated-frame captures")

    def make_direct(self):
        self.manifest["runs"][0]["mode"] = "direct"
        self.manifest["expected_runs"][0]["mode"] = "direct"
        self.rows[1].update(mode="direct", output_hz=30)
        del self.rows[5]
        self.rows[5]["present_id"] = 2
        self.manifest["runs"][0]["capture_samples"] = [{
            "kind": "direct", "present_id": 1, "endpoint_id": "a",
            "endpoint_artifact_id": "left", "presented_artifact_id": "generated",
            "provenance_artifact_id": "provenance"}]

    def test_direct_run_needs_no_generated_frames_or_middle_reference(self):
        self.make_direct()
        self.manifest["artifacts"][:] = [a for a in self.artifacts if a["artifact_id"] != "reference"]
        self.persist()
        result = self.result()
        self.assertEqual(result["status"], "UNVERIFIED", result)
        self.assertFalse(result["passed"])
        report = result["runs"][0]
        self.assertEqual(report["observed_counters"]["generated_presented"], 0)
        self.assertEqual(report["captured_direct_presents"], 1)

    def test_direct_capture_must_bind_exact_endpoint(self):
        self.make_direct()
        self.manifest["runs"][0]["capture_samples"][0]["endpoint_id"] = "b"
        self.persist()
        self.invalid("Direct capture endpoint mismatch")

    def test_direct_requires_capture(self):
        self.make_direct()
        self.manifest["runs"][0]["capture_samples"] = []
        self.persist()
        self.invalid("Direct captures")

    def test_direct_cannot_contain_generated_epoch(self):
        self.make_direct()
        self.rows[1].update(mode="x2", output_hz=60)
        self.persist()
        self.invalid("Direct run contains a generation epoch")

    def test_direct_cannot_contain_generated_attempt(self):
        self.manifest["runs"][0]["mode"] = "direct"
        self.manifest["expected_runs"][0]["mode"] = "direct"
        self.rows[1].update(mode="direct", output_hz=30)
        self.persist()
        self.invalid("generated present while direct")

    def test_requested_x2_cannot_be_substituted_by_direct(self):
        self.make_direct()
        self.manifest["expected_runs"][0]["mode"] = "x2"
        self.persist()
        self.invalid("substituted")

    def test_direct_fractional_panel_divisor(self):
        self.make_direct()
        self.rows[1].update(source_hz="59.994", output_hz="59.994", panel_hz="119.988")
        self.persist()
        self.assertEqual(self.result()["status"], "UNVERIFIED")

    def test_counter_mismatch(self):
        self.manifest["runs"][0]["counters"]["generated_presented"] = 100
        self.persist(recount=False)
        self.invalid("entire trace")

    def append_epoch(self):
        second = copy.deepcopy(self.rows[1:-1])
        for row in second:
            row["epoch_id"] = "epoch-2"
            for key in ("recorded_ns", "producer_timestamp_ns", "desired_present_ns",
                        "actual_present_ns", "content_timestamp_ns"):
                if key in row:
                    row[key] += 1_000_000_000
            if row["event"] == "epoch_start":
                row["reset_reason"] = "cooldown_recovery"
            if "source_sequence" in row:
                row["source_sequence"] += 2
            if "present_id" in row:
                row["present_id"] += 3
            for key in ("endpoint_id", "left_endpoint_id", "right_endpoint_id"):
                if key in row:
                    row[key] += "2"
        self.rows[-1]["recorded_ns"] += 1_000_000_000
        self.rows[-1:-1] = second

    def test_recovery_does_not_erase_prior_deadline_failure(self):
        self.append_epoch()
        self.rows[5]["deadline_missed"] = True
        self.persist()
        result = self.invalid("later recovery cannot erase")
        counts = result["runs"][0]["observed_counters"]
        self.assertEqual(counts["epochs"], 2)
        self.assertEqual(counts["resets"], 1)
        self.assertEqual(counts["deadline_misses"], 1)
        self.assertEqual(counts["generated_presented"], 2)

    def test_declaring_clean_epoch_counters_cannot_hide_session_failure(self):
        self.append_epoch()
        self.rows[5]["deadline_missed"] = True
        self.persist()
        self.rows[-1]["counters"]["deadline_misses"] = 0
        self.manifest["runs"][0]["counters"]["deadline_misses"] = 0
        self.persist(recount=False)
        result = self.invalid("entire trace")
        self.assertEqual(result["runs"][0]["observed_counters"]["deadline_misses"], 1)

    def test_cross_epoch_endpoints_rejected(self):
        self.append_epoch()
        self.rows[11]["left_endpoint_id"] = "a"
        self.rows[11]["right_endpoint_id"] = "b"
        self.persist()
        self.invalid("stale endpoints crossed epoch")

    def test_failed_present_count_retained(self):
        self.rows[6].update(outcome="dropped", outcome_reason="compositor_rejected")
        del self.rows[6]["actual_present_ns"]
        self.persist()
        result = self.invalid("later recovery cannot erase")
        self.assertEqual(result["runs"][0]["observed_counters"]["dropped"], 1)

    def test_duplicate_json_keys_rejected(self):
        self.path.write_text('{"schema_version":1,"schema_version":1}')
        self.invalid("duplicate JSON key")

    def test_invalid_json_not_a_crash(self):
        self.path.write_text("{")
        self.assertEqual(self.result()["status"], "INVALID")

    def test_cli_never_exits_success_for_fixture(self):
        run = subprocess.run([sys.executable, str(Path(verifier.__file__)), str(self.path)],
                             capture_output=True, text=True)
        self.assertEqual(run.returncode, 3, run.stderr)
        self.assertEqual(json.loads(run.stdout)["status"], "UNVERIFIED")


if __name__ == "__main__":
    unittest.main()
