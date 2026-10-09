#!/usr/bin/env python3
"""First-stage frame-generation evidence contract; never returns PASS.

Usage: python3 tools/verify_frame_generation_evidence_v2.py manifest.json
Exit 2 = INVALID; exit 3 = structurally consistent but UNVERIFIED.

The version-1 manifest contains campaign_id, evidence_kind (empirical or
synthetic_fixture), expected_runs [{run_id, system, title, backend, mode}], artifacts
[{artifact_id, path, sha256, size_bytes, kind}], and runs. Artifact paths are
relative to the manifest, confined to its directory, and must identify files.

Each run repeats its expected identity, adds identity fields listed below,
apk_artifact_id, trace_artifact_id, capture_samples, and counters. Run mode is
direct or x2. identity.clock_domains must declare every TIMESTAMP_FIELDS entry
as android_monotonic; producer/content timestamps must already be mapped to
that domain. Declaration is checked for consistency, not independently attested.
A JSONL trace
has contiguous event_index values, monotonic recorded_ns, and matching run_id:
run_start, epoch_start, endpoint/present events, further epochs, then run_end.
The final event repeats session-wide counters. Every epoch declares its panel,
source/output Hz, mode (direct/x2), unique epoch_id and reset_reason. Rates accept
exact integers, decimal numbers/strings, fraction strings, or positive integer
{numerator, denominator} objects; divisibility uses exact rational arithmetic.
Endpoints
retain unique endpoint_id, contiguous source_sequence, and producer_timestamp_ns.
Every present has a contiguous present_id, current epoch_id, explicit role,
role_source=producer_identity, outcome, desired_present_ns, content_timestamp_ns,
deadline_missed boolean and fallback_reason. Successful presents also have
actual_present_ns. Real/hold rows bind endpoint_id; generated rows bind adjacent
left_endpoint_id/right_endpoint_id and phase_numerator=1/phase_denominator=2.
Dropped/unavailable rows carry outcome_reason and no actual timestamp. Successful
content time must advance (only an explicit hold may equal its predecessor),
and physical presentation cannot precede production of any dependency.

Capture samples of kind=generated bind one successfully presented generated present_id to three
lossless image artifacts, the exact endpoint IDs, a held-out or rendered true
middle reference image, and a provenance artifact. Direct runs have no generated
attempts and require kind=direct samples binding a real present_id/endpoint_id to
distinct endpoint_artifact_id and presented_artifact_id lossless files plus
provenance_artifact_id. Direct samples do not need a middle-frame reference.
This validates files and
identity joins, NOT the truth of producer labels, screenshot pixels, reference
provenance, clocks, completeness outside the declared run, or visual quality.
No numeric metric or caller-authored `passed` field can promote this result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from fractions import Fraction
from pathlib import Path
from typing import Any


IDENTITY_FIELDS = ("source_revision", "package_name", "core", "device_model",
                   "device_fingerprint", "gpu", "driver", "session_id")
TIMESTAMP_FIELDS = ("recorded_ns", "producer_timestamp_ns", "content_timestamp_ns",
                    "desired_present_ns", "actual_present_ns")
COUNTERS = ("epochs", "resets", "endpoints", "present_attempts", "presented",
            "generated_presented", "dropped", "unavailable", "deadline_misses",
            "fallback_presents")
UNIMPLEMENTED = [
    "Independent attestation of capture provenance and trace completeness",
    "Measured physical scan intervals and source clock agreement across every epoch",
    "Decoded image identity, exact passthrough, midpoint motion and reference-image comparison",
    "Artifact severity, occlusion/HUD/cut behavior and human visual review",
    "Sustained GPU/thermal headroom and capture-overhead comparison",
]


class InvalidEvidence(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise InvalidEvidence(message)


def positive(value: Any) -> bool:
    return type(value) is int and value > 0


def nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def exact_rate(value: Any) -> Fraction:
    """Parse positive finite rates without rounding near-divisors into matches."""
    try:
        if isinstance(value, dict):
            require(set(value) == {"numerator", "denominator"}
                    and all(positive(value[k]) for k in value), "invalid rational rate")
            result = Fraction(value["numerator"], value["denominator"])
        else:
            require(type(value) in (int, float, str), "invalid rational rate type")
            text = str(value)
            require(len(text) <= 128, "rate representation too long")
            result = Fraction(text)
        require(result > 0, "rate must be positive")
        return result
    except (ValueError, ZeroDivisionError, OverflowError) as exc:
        raise InvalidEvidence(f"invalid finite rational rate: {value!r}") from exc


def object_pairs(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(text: str) -> Any:
    def bad_constant(value: str) -> None:
        raise InvalidEvidence(f"non-finite JSON number: {value}")
    return json.loads(text, object_pairs_hook=object_pairs,
                      parse_constant=bad_constant)


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def check_artifacts(manifest: dict, root: Path) -> dict:
    entries = manifest.get("artifacts")
    require(isinstance(entries, list) and bool(entries), "artifacts must be nonempty")
    artifacts, used_paths = {}, set()
    for entry in entries:
        require(isinstance(entry, dict), "artifact must be an object")
        name = entry.get("artifact_id")
        require(nonempty(name) and name not in artifacts, "duplicate/missing artifact_id")
        relative = entry.get("path")
        require(nonempty(relative) and not Path(relative).is_absolute(),
                f"artifact {name}: path must be relative")
        path = (root / relative).resolve()
        require(path.is_relative_to(root) and path.is_file(),
                f"artifact {name}: missing file or path escapes evidence directory")
        require(path not in used_paths, f"artifact {name}: aliased artifact file")
        require(type(entry.get("size_bytes")) is int and entry["size_bytes"] > 0
                and path.stat().st_size == entry["size_bytes"],
                f"artifact {name}: empty file or size mismatch")
        require(entry.get("sha256") == digest(path), f"artifact {name}: SHA-256 mismatch")
        require(nonempty(entry.get("kind")), f"artifact {name}: missing kind")
        artifacts[name] = {**entry, "resolved_path": path}
        used_paths.add(path)
    return artifacts


def artifact(artifacts: dict, name: Any, kind: str) -> dict:
    require(nonempty(name) and name in artifacts, f"missing {kind} artifact identity")
    result = artifacts[name]
    require(result["kind"] == kind, f"artifact {name}: expected {kind}")
    return result


def check_counters(value: Any, observed: dict, location: str) -> None:
    require(isinstance(value, dict) and set(value) == set(COUNTERS),
            f"{location}: missing/unknown lifetime counters")
    require(all(type(value[k]) is int and value[k] >= 0 for k in COUNTERS),
            f"{location}: invalid lifetime counter")
    require(value == observed, f"{location}: counters do not equal entire trace: {observed}")


def check_run(run: dict, artifacts: dict, report: dict) -> None:
    identity = run.get("identity")
    require(isinstance(identity, dict) and all(nonempty(identity.get(k))
            for k in IDENTITY_FIELDS), "missing persisted build/device/session identity")
    require(positive(identity.get("pid")) and type(identity.get("display_id")) is int
            and identity["display_id"] >= 0, "missing process/display identity")
    require(identity.get("clock_domains") == dict.fromkeys(TIMESTAMP_FIELDS, "android_monotonic"),
            "missing or incoherent monotonic timestamp clock domains")
    require(run.get("mode") in ("direct", "x2"), "missing run mode")
    apk = artifact(artifacts, run.get("apk_artifact_id"), "apk")
    require(identity.get("apk_sha256") == apk["sha256"], "APK identity mismatch")
    trace = artifact(artifacts, run.get("trace_artifact_id"), "presentation_trace")
    rows = []
    with trace["resolved_path"].open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            require(bool(line.strip()), f"trace line {number}: empty row")
            row = read_json(line)
            require(isinstance(row, dict), f"trace line {number}: not an object")
            rows.append(row)
    require(len(rows) >= 5, "trace too short")
    require(rows[0].get("event") == "run_start" and rows[-1].get("event") == "run_end",
            "trace missing complete run boundaries")
    require(rows[0].get("session_id") == identity["session_id"] ==
            rows[-1].get("session_id"), "trace session identity mismatch")

    counters = dict.fromkeys(COUNTERS, 0)
    report["observed_counters"] = counters
    endpoints, presents, epochs, generated_pairs = {}, {}, set(), set()
    epoch, recorded_ns, producer_ns, actual_ns, desired_ns = None, 0, 0, 0, 0
    last_presented_content_ns = 0
    for index, row in enumerate(rows, 1):
        require(row.get("event_index") == index and type(row.get("event_index")) is int,
                "trace event_index gap, duplicate or reorder")
        require(row.get("run_id") == run["run_id"], "trace crossed run identity")
        stamp = row.get("recorded_ns")
        require(positive(stamp) and stamp >= recorded_ns, "trace recorded_ns not monotonic")
        recorded_ns = stamp
        event = row.get("event")
        if event in ("run_start", "run_end"):
            require((event == "run_start" and index == 1) or
                    (event == "run_end" and index == len(rows)), "interior run boundary")
            continue
        if event == "epoch_start":
            eid = row.get("epoch_id")
            require(nonempty(eid) and eid not in epochs, "missing/reused epoch_id")
            require(nonempty(row.get("reset_reason")), "missing epoch reset reason")
            if epochs:
                counters["resets"] += 1
                require(row["reset_reason"] != "startup", "reset relabeled startup")
            else:
                require(row["reset_reason"] == "startup", "first epoch not startup")
            source, output, panel = (exact_rate(row.get(k)) for k in
                                     ("source_hz", "output_hz", "panel_hz"))
            require((panel / output).denominator == 1,
                    "epoch rates do not occupy a uniform integer panel divisor")
            require(row.get("mode") in ("direct", "x2"), "unknown epoch generation mode")
            require(run["mode"] != "direct" or row["mode"] == "direct",
                    "Direct run contains a generation epoch")
            require(output == source * (2 if row["mode"] == "x2" else 1),
                    "epoch violates direct/x2 generation ceiling")
            epoch = row
            epochs.add(eid)
            counters["epochs"] += 1
            continue
        require(epoch is not None and row.get("epoch_id") == epoch["epoch_id"],
                "event missing/current epoch identity")
        if event == "endpoint":
            eid, sequence, produced = (row.get(k) for k in
                                      ("endpoint_id", "source_sequence", "producer_timestamp_ns"))
            require(nonempty(eid) and eid not in endpoints, "missing/reused endpoint_id")
            require(type(sequence) is int and sequence == len(endpoints) + 1,
                    "source_sequence missing endpoint, reset or reorder")
            require(positive(produced) and producer_ns < produced <= stamp,
                    "endpoint producer timestamp not monotonic or observed before produced")
            producer_ns = produced
            endpoints[eid] = row
            counters["endpoints"] += 1
            continue
        require(event == "present", "unknown trace event")
        pid = row.get("present_id")
        require(type(pid) is int and pid == len(presents) + 1,
                "present_id missing, duplicate, reset or reorder")
        require(row.get("role_source") == "producer_identity", "guessed or missing frame role")
        role, outcome = row.get("role"), row.get("outcome")
        require(role in ("real", "generated", "hold"), "missing/unknown frame role")
        require(outcome in ("presented", "dropped", "unavailable"), "missing present outcome")
        require(type(row.get("deadline_missed")) is bool, "missing deadline outcome")
        require(isinstance(row.get("fallback_reason"), str), "missing fallback accounting")
        desired, content = row.get("desired_present_ns"), row.get("content_timestamp_ns")
        require(positive(desired) and desired > desired_ns and positive(content),
                "missing or nonmonotonic desired/content timestamp")
        desired_ns = desired
        if role == "generated":
            require(epoch["mode"] == "x2", "generated present while direct")
            left, right = row.get("left_endpoint_id"), row.get("right_endpoint_id")
            require(left in endpoints and right in endpoints, "generated row missing exact endpoints")
            a, b = endpoints[left], endpoints[right]
            require(a["epoch_id"] == b["epoch_id"] == epoch["epoch_id"], "stale endpoints crossed epoch")
            require(b["source_sequence"] == a["source_sequence"] + 1, "generated endpoints not adjacent")
            require(type(row.get("phase_numerator")) is int and row["phase_numerator"] == 1
                    and type(row.get("phase_denominator")) is int and row["phase_denominator"] == 2,
                    "generated phase is not exact 1/2")
            require(content == a["producer_timestamp_ns"] +
                    (b["producer_timestamp_ns"] - a["producer_timestamp_ns"]) // 2,
                    "generated content timestamp is not midpoint")
            pair = (left, right)
            require(pair not in generated_pairs, "more than one generated attempt per endpoint pair")
            generated_pairs.add(pair)
            dependency_timestamp_ns = b["producer_timestamp_ns"]
        else:
            eid = row.get("endpoint_id")
            require(eid in endpoints and endpoints[eid]["epoch_id"] == epoch["epoch_id"],
                    "real/hold present missing current exact endpoint")
            require(content == endpoints[eid]["producer_timestamp_ns"], "endpoint timestamp mismatch")
            dependency_timestamp_ns = endpoints[eid]["producer_timestamp_ns"]
        if role == "hold":
            require(nonempty(row["fallback_reason"]), "hold missing fallback reason")
        if outcome == "presented":
            actual = row.get("actual_present_ns")
            require(positive(actual) and actual_ns < actual <= stamp,
                    "missing/nonmonotonic actual physical timestamp")
            require(actual >= dependency_timestamp_ns,
                    "physical present precedes production of its endpoint dependencies")
            require(content > last_presented_content_ns or
                    (role == "hold" and content == last_presented_content_ns),
                    "successful content chronology moved backwards or repeated without a hold")
            actual_ns = actual
            last_presented_content_ns = content
            counters["presented"] += 1
            counters["generated_presented"] += role == "generated"
        else:
            require(row.get("actual_present_ns") is None and nonempty(row.get("outcome_reason")),
                    "failed present fabricated actual timestamp or omitted reason")
            counters[outcome] += 1
        counters["deadline_misses"] += row["deadline_missed"]
        counters["fallback_presents"] += bool(row["fallback_reason"])
        counters["present_attempts"] += 1
        presents[pid] = row
    require(counters["endpoints"] >= 2 and counters["presented"] > 0,
            "no real presentation evidence")
    if run["mode"] == "x2":
        require(counters["generated_presented"] > 0, "no generated presentation evidence")
    else:
        require(not generated_pairs, "Direct run contains generated attempts")
    check_counters(rows[-1].get("counters"), counters, "run_end")
    check_counters(run.get("counters"), counters, "manifest run")
    samples = run.get("capture_samples")
    require(isinstance(samples, list) and bool(samples), "missing exact generated-frame captures or Direct captures")
    sampled, sampled_generated, sampled_direct = set(), set(), set()
    for sample in samples:
        require(isinstance(sample, dict), "capture sample is not an object")
        pid = sample.get("present_id")
        require(type(pid) is int and pid in presents and pid not in sampled,
                "capture missing/duplicate present_id")
        row = presents[pid]
        kind = sample.get("kind")
        require(kind in ("generated", "direct"), "missing capture kind")
        artifact(artifacts, sample.get("provenance_artifact_id"), "capture_provenance")
        if kind == "direct":
            require(row["role"] == "real" and row["outcome"] == "presented",
                    "Direct capture not bound to a physically presented real row")
            require(sample.get("endpoint_id") == row["endpoint_id"], "Direct capture endpoint mismatch")
            image_ids = [sample.get("endpoint_artifact_id"), sample.get("presented_artifact_id")]
            require(all(nonempty(i) for i in image_ids) and len(set(image_ids)) == 2,
                    "Direct capture needs separate endpoint/output artifact identities")
            for aid in image_ids:
                artifact(artifacts, aid, "lossless_image")
            sampled.add(pid)
            sampled_direct.add(pid)
            continue
        require(row["role"] == "generated" and row["outcome"] == "presented",
                "capture not bound to a physically presented generated row")
        require(sample.get("left_endpoint_id") == row["left_endpoint_id"] and
                sample.get("right_endpoint_id") == row["right_endpoint_id"], "capture endpoint mismatch")
        image_ids = [sample.get(k) for k in ("left_artifact_id", "generated_artifact_id",
                                           "right_artifact_id", "reference_artifact_id")]
        require(all(nonempty(i) for i in image_ids) and len(set(image_ids)) == 4,
                "capture images must have separate exact artifact identities")
        for aid in image_ids:
            artifact(artifacts, aid, "lossless_image")
        require(sample.get("reference_kind") in
                ("held_out_real_middle", "deterministic_reference_renderer"),
                "missing independent middle-frame reference kind")
        sampled.add(pid)
        sampled_generated.add(pid)
    require(bool(sampled_generated if run["mode"] == "x2" else sampled_direct),
            "missing capture samples for requested run mode")
    report["captured_generated_presents"] = len(sampled_generated)
    report["captured_direct_presents"] = len(sampled_direct)
    report["unsampled_generated_presents"] = counters["generated_presented"] - len(sampled_generated)
    report["observed_failures"] = {k: counters[k] for k in
                                   ("deadline_misses", "dropped", "unavailable", "fallback_presents")}
    require(not any(report["observed_failures"].values()),
            "run contains presentation failures/fallbacks; later recovery cannot erase them")


def validate(path: Path) -> dict:
    result = {"validator_schema_version": 1, "status": "INVALID", "passed": False,
              "structural_checks_passed": False, "errors": [], "runs": [],
              "unimplemented_required_checks": UNIMPLEMENTED.copy()}
    try:
        path = path.resolve()
        manifest = read_json(path.read_text(encoding="utf-8"))
        require(isinstance(manifest, dict) and type(manifest.get("schema_version")) is int
                and manifest["schema_version"] == 1, "unsupported manifest schema")
        require(nonempty(manifest.get("campaign_id")), "missing campaign_id")
        require(manifest.get("evidence_kind") in ("empirical", "synthetic_fixture"),
                "missing evidence_kind")
        result["evidence_kind"] = manifest["evidence_kind"]
        result["manifest_sha256"] = digest(path)
        artifacts = check_artifacts(manifest, path.parent)
        expected, runs = manifest.get("expected_runs"), manifest.get("runs")
        require(isinstance(expected, list) and bool(expected) and isinstance(runs, list),
                "missing expected run matrix")
        def keys(items: list) -> dict:
            out = {}
            for item in items:
                require(isinstance(item, dict) and all(nonempty(item.get(k)) for k in
                        ("run_id", "system", "title", "backend", "mode")), "missing run identity")
                require(item["run_id"] not in out, "duplicate run_id")
                out[item["run_id"]] = item
            return out
        wanted, actual = keys(expected), keys(runs)
        require(set(wanted) == set(actual), "missing or unexpected runs against declared matrix")
        for run_id, run in actual.items():
            require(all(wanted[run_id][k] == run[k] for k in ("system", "title", "backend", "mode")),
                    "run substituted system/title/backend/mode")
            report = {"run_id": run_id, "errors": []}
            result["runs"].append(report)
            try:
                check_run(run, artifacts, report)
            except (InvalidEvidence, ValueError, OSError, KeyError, TypeError) as exc:
                report["errors"].append(str(exc))
                result["errors"].append(f"{run_id}: {exc}")
        if not result["errors"]:
            result["status"] = "UNVERIFIED"
            result["structural_checks_passed"] = True
    except (InvalidEvidence, ValueError, OSError, KeyError, TypeError) as exc:
        result["errors"].append(str(exc))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    result = validate(args.manifest)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 2 if result["status"] == "INVALID" else 3


if __name__ == "__main__":
    raise SystemExit(main())
