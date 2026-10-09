#!/usr/bin/env python3
"""Known-middle image comparator; NOT runtime/campaign qualification.

Read-only standard-library analysis of exact packed RGBA8 A/G/B/M files. M must
be a withheld real middle or independent deterministic reference. A hash binds
the predeclared ROI plan; it does not independently attest when it was frozen.
Output status is INVALID, INSUFFICIENT, REGRESSION or IMPROVEMENT_OBSERVED. Every
result has qualification_status=UNVERIFIED and passed=false. No input pixels are
resized, warped, aligned for scoring, color-converted, overwritten or exported.
Integer alignment is a diagnostic, not dense/subpixel optical-flow ground truth.
See docs/qa/frame-generation-quality-comparator-v2.md for schema and limitations.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path


POLICY = {
    "revision": "known-middle-code-values-v2",
    "blend_roundings": ["floor", "ceil", "nearest_even"],
    "dynamic_blend_error_bound": "per-channel-nearest-floor-or-ceil-to-reference",
    "max_pixels": 4194304,
    "min_roi_pixels": 64,
    "endpoint_mae_min": 2.0,
    "changed_pixel_delta": 8,
    "changed_fraction_min": 0.02,
    "baseline_dynamic_mae_min": 0.5,
    "improvement_fraction_min": 0.10,
    "improvement_absolute_min": 0.5,
    "mae_max": 8.0,
    "mae_regression_allowance": 0.5,
    "edge_mae_max": 8.0,
    "edge_regression_allowance": 0.5,
    "tile_side": 8,
    "worst_tile_mae_max": 12.0,
    "tile_regression_allowance": 1.0,
    "large_error_delta": 16,
    "large_error_fraction_max": 0.05,
    "large_error_fraction_allowance": 0.005,
    "hud_mae_max": 0.5,
    "hud_edge_mae_max": 0.5,
    "hud_worst_tile_mae_max": 1.0,
    "hud_max_channel_error": 8,
    "edge_threshold": 16,
    "edge_low_threshold": 8,
    "alignment_radius": 4,
    "alignment_max_samples": 512,
    "alignment_tie_margin": 0.05,
    "translation_residual_max_pixels": 0.75,
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


POLICY_SHA256 = sha(json.dumps(POLICY, sort_keys=True, separators=(",", ":")).encode())
LIMITATIONS = [
    "Provenance and pre-capture ROI freeze require independent attestation; JSON assertions are not proof.",
    "No timing, physical scanout, guest-speed, audio, latency, thermal or sustained-run qualification.",
    "Code-value metrics are not perceptual/human review; no dense or subpixel flow ground truth.",
    "One triplet cannot qualify multi-frame flicker or temporal stability across an entire sequence.",
]


class Invalid(ValueError):
    pass


class Insufficient(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise Invalid(message)


def load_json(raw):
    def pairs(entries):
        result = {}
        for key, value in entries:
            require(key not in result, "duplicate JSON key: " + key)
            result[key] = value
        return result
    def bad_constant(value):
        raise Invalid("nonfinite JSON constant: " + value)
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=bad_constant)


def positive(value):
    return type(value) is int and value > 0


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def artifact(entry, root, identities, max_bytes=64 * 1024 * 1024):
    require(isinstance(entry, dict), "missing artifact identity")
    relative = entry.get("path")
    require(nonempty(relative) and not Path(relative).is_absolute(), "artifact path must be relative")
    path = (root / relative).resolve()
    require(path.is_relative_to(root) and path.is_file(), "artifact missing or escapes evidence root")
    file_stat = path.stat()
    keys = {("path", path), ("inode", file_stat.st_dev, file_stat.st_ino)}
    require(not identities.intersection(keys), "aliased artifact path/inode")
    identities.update(keys)
    size = entry.get("size_bytes")
    require(positive(size) and size <= max_bytes and size == file_stat.st_size, "artifact size mismatch")
    raw = path.read_bytes()
    require(entry.get("sha256") == sha(raw), "artifact SHA-256 mismatch: " + relative)
    return raw


def luma(raw, offset):
    # Fixed encoded-code-value gradient, deliberately NOT gamma conversion.
    return (54 * raw[offset] + 183 * raw[offset + 1] + 19 * raw[offset + 2]) / 256


def delta(left, right, offset):
    return max(abs(left[offset + c] - right[offset + c]) for c in range(3))


def metrics(candidate, reference, left, right, width, rect):
    x0, y0, rw, rh = rect
    total = dynamic_total = dynamic_count = edge_total = edge_count = 0
    false_edges = missed_edges = reference_edges = candidate_edges = 0
    histogram = [0] * 256
    tiles = {}
    for y in range(y0, y0 + rh):
        for x in range(x0, x0 + rw):
            offset = (y * width + x) * 4
            errors = [abs(candidate[offset + c] - reference[offset + c]) for c in range(3)]
            error = sum(errors)
            total += error
            histogram[max(errors)] += 1
            if max(delta(left, right, offset), delta(left, reference, offset),
                   delta(right, reference, offset)) >= POLICY["changed_pixel_delta"]:
                dynamic_total += error
                dynamic_count += 1
            tile = ((x - x0) // POLICY["tile_side"], (y - y0) // POLICY["tile_side"])
            values = tiles.setdefault(tile, [0, 0])
            values[0] += error
            values[1] += 3
            for neighbor in ((offset + 4 if x + 1 < x0 + rw else None),
                             (offset + 4 * width if y + 1 < y0 + rh else None)):
                if neighbor is None:
                    continue
                g = luma(candidate, neighbor) - luma(candidate, offset)
                m = luma(reference, neighbor) - luma(reference, offset)
                edge_total += abs(g - m)
                edge_count += 1
                ge, me = abs(g) >= POLICY["edge_threshold"], abs(m) >= POLICY["edge_threshold"]
                candidate_edges += ge
                reference_edges += me
                false_edges += ge and abs(m) < POLICY["edge_low_threshold"]
                missed_edges += me and abs(g) < POLICY["edge_low_threshold"]
    pixels = rw * rh
    cumulative, p95 = 0, 0
    for error, count in enumerate(histogram):
        cumulative += count
        if cumulative >= math.ceil(pixels * 0.95):
            p95 = error
            break
    return {
        "rgb_mae": total / (3 * pixels),
        "dynamic_rgb_mae": dynamic_total / (3 * dynamic_count) if dynamic_count else None,
        "dynamic_pixels": dynamic_count,
        "edge_gradient_mae": edge_total / edge_count if edge_count else None,
        "worst_tile_mae": max(v[0] / v[1] for v in tiles.values()),
        "p95_max_channel_error": p95,
        "max_channel_error": max(i for i, count in enumerate(histogram) if count),
        "large_error_fraction": sum(histogram[POLICY["large_error_delta"] + 1:]) / pixels,
        "false_edge_fraction": false_edges / max(1, candidate_edges),
        "missed_edge_fraction": missed_edges / max(1, reference_edges),
        "reference_edge_count": reference_edges,
    }


def alignment(candidate, target, width, rect):
    """Diagnostic only: never transform pixels or use aligned scores in gates."""
    x0, y0, rw, rh = rect
    radius = POLICY["alignment_radius"]
    if rw <= 2 * radius or rh <= 2 * radius:
        return {"observable": False, "reason": "ROI too small for fixed search support"}
    stride = max(1, math.ceil(math.sqrt((rw - 2 * radius) * (rh - 2 * radius) /
                                      POLICY["alignment_max_samples"])))
    # Ceiling at both axes can exceed the area estimate for a very thin ROI.
    # Keep the declared sample/memory/work bound exact, including that case.
    while (math.ceil((rw - 2 * radius) / stride) * math.ceil((rh - 2 * radius) / stride)
           > POLICY["alignment_max_samples"]):
        stride += 1
    points = [(x, y) for y in range(y0 + radius, y0 + rh - radius, stride)
              for x in range(x0 + radius, x0 + rw - radius, stride)]
    costs = []
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            error = 0
            for x, y in points:
                a, b = ((y + dy) * width + x + dx) * 4, (y * width + x) * 4
                error += sum(abs(candidate[a + c] - target[b + c]) for c in range(3))
            costs.append((error / (3 * len(points)), dx, dy))
    costs.sort(key=lambda c: (c[0], c[1] * c[1] + c[2] * c[2], c[2], c[1]))
    best, second = costs[:2]
    return {"observable": second[0] - best[0] > POLICY["alignment_tie_margin"],
            "dx": best[1], "dy": best[2], "residual_pixels": math.hypot(best[1], best[2]),
            "best_rgb_mae": best[0], "runner_up_margin": second[0] - best[0],
            "samples": len(points), "stride": stride, "search_radius": radius,
            "at_search_boundary": max(abs(best[1]), abs(best[2])) == radius}


def compare_pixels(images, width, height, rois):
    left, generated, right, middle = (images[k] for k in ("A", "G", "B", "M"))
    # Explicit common roundings plus the numeric envelope below prevent a
    # rounding convention from masquerading as inferred midpoint motion.
    baselines = {"copy_left": left, "copy_right": right,
                 "blend_floor": bytes((a + b) // 2 for a, b in zip(left, right)),
                 "blend_ceil": bytes((a + b + 1) // 2 for a, b in zip(left, right)),
                 "blend_nearest_even": bytes(round((a + b) / 2) for a, b in zip(left, right))}
    reports, failures, insufficient = [], [], []
    scopes = [{"roi_id": "__full_frame__", "kind": "full_frame", "rect": [0, 0, width, height]}] + rois
    for roi in scopes:
        rect, kind, name = roi["rect"], roi["kind"], roi["roi_id"]
        observed = metrics(generated, middle, left, right, width, rect)
        controls = {key: metrics(raw, middle, left, right, width, rect) for key, raw in baselines.items()}
        report = {**roi, "generated": observed, "baselines": controls, "failures": [], "insufficient": []}
        reports.append(report)
        def fail(reason):
            report["failures"].append(reason)
            failures.append(name + ": " + reason)
        def unavailable(reason):
            report["insufficient"].append(reason)
            insufficient.append(name + ": " + reason)
        for key, maximum, allowance in (
                ("rgb_mae", POLICY["mae_max"], POLICY["mae_regression_allowance"]),
                ("edge_gradient_mae", POLICY["edge_mae_max"], POLICY["edge_regression_allowance"]),
                ("worst_tile_mae", POLICY["worst_tile_mae_max"], POLICY["tile_regression_allowance"]),
                ("large_error_fraction", POLICY["large_error_fraction_max"], POLICY["large_error_fraction_allowance"])):
            best = min(m[key] for m in controls.values())
            if observed[key] > maximum or observed[key] > best + allowance:
                fail(key + " exceeds frozen absolute/strongest-baseline damage bound")
        if kind == "hud":
            for key, limit in (("rgb_mae", POLICY["hud_mae_max"]),
                               ("edge_gradient_mae", POLICY["hud_edge_mae_max"]),
                               ("worst_tile_mae", POLICY["hud_worst_tile_mae_max"]),
                               ("max_channel_error", POLICY["hud_max_channel_error"])):
                if observed[key] > limit:
                    fail(key + " exceeds frozen HUD damage bound")
        if kind in ("moving", "occlusion"):
            x0, y0, rw, rh = rect
            endpoint_error = changed = blend_envelope_error = 0
            for y in range(y0, y0 + rh):
                for x in range(x0, x0 + rw):
                    offset = (y * width + x) * 4
                    endpoint_error += sum(abs(left[offset + c] - right[offset + c]) for c in range(3))
                    changed += delta(left, right, offset) >= POLICY["changed_pixel_delta"]
                    if max(delta(left, right, offset), delta(left, middle, offset),
                           delta(right, middle, offset)) >= POLICY["changed_pixel_delta"]:
                        for channel in range(3):
                            total = left[offset + channel] + right[offset + channel]
                            reference = middle[offset + channel]
                            blend_envelope_error += min(abs(total // 2 - reference),
                                                        abs((total + 1) // 2 - reference))
            report["endpoint_rgb_mae"] = endpoint_error / (rw * rh * 3)
            report["endpoint_changed_fraction"] = changed / (rw * rh)
            best = min(m["dynamic_rgb_mae"] for m in controls.values()) if observed["dynamic_pixels"] else 0
            report["strongest_dynamic_baseline_mae"] = best
            envelope = (blend_envelope_error / (3 * observed["dynamic_pixels"])
                        if observed["dynamic_pixels"] else 0)
            report["blend_quantization_envelope"] = {
                "dynamic_rgb_mae_lower_bound": envelope,
                "reference_dependent_numeric_control": True,
                "is_generated_image_or_quality_evidence": False,
            }
            # This reference-dependent LOWER BOUND is deliberately stronger
            # than any one spatial/per-channel floor/ceil rounding choice. No
            # resulting image is synthesized, saved, or used as evidence.
            best = min(best, envelope)
            report["strongest_dynamic_comparison_bound_mae"] = best
            if (report["endpoint_rgb_mae"] < POLICY["endpoint_mae_min"] or
                    report["endpoint_changed_fraction"] < POLICY["changed_fraction_min"] or
                    best < POLICY["baseline_dynamic_mae_min"]):
                unavailable("static/unobservable midpoint or no measurable advantage possible over baseline")
            elif (observed["dynamic_rgb_mae"] > best * (1 - POLICY["improvement_fraction_min"]) or
                  best - observed["dynamic_rgb_mae"] < POLICY["improvement_absolute_min"]):
                fail("dynamic-region error does not improve strongest baseline by both frozen margins")
            report["alignment_to_middle"] = alignment(generated, middle, width, rect)
            if roi.get("motion_model") == "translation":
                fits = {key: alignment(candidate, target, width, rect) for key, candidate, target in (
                    ("A_to_G", left, generated), ("A_to_M", left, middle),
                    ("B_to_G", right, generated), ("B_to_M", right, middle))}
                report["temporal_alignment_diagnostics"] = fits
                all_fits = list(fits.values()) + [report["alignment_to_middle"]]
                if not all(fit["observable"] and not fit.get("at_search_boundary", True) for fit in all_fits):
                    unavailable("translation diagnostic ambiguous or outside bounded search; no motion claim")
                else:
                    error = max(math.hypot(fits[a]["dx"] - fits[b]["dx"], fits[a]["dy"] - fits[b]["dy"])
                                for a, b in (("A_to_G", "A_to_M"), ("B_to_G", "B_to_M")))
                    report["temporal_displacement_error_pixels"] = error
                    if max(error, report["alignment_to_middle"]["residual_pixels"]) > POLICY["translation_residual_max_pixels"]:
                        fail("integer midpoint/temporal displacement differs from true middle")
    status = "REGRESSION" if failures else "INSUFFICIENT" if insufficient else "IMPROVEMENT_OBSERVED"
    return {"status": status, "regions": reports, "failures": failures, "insufficient": insufficient}


def compare(manifest_path, expected_plan_sha256):
    result = {"comparator_schema_version": 1, "qualification_status": "UNVERIFIED", "passed": False,
              "status": "INVALID", "policy": POLICY, "policy_sha256": POLICY_SHA256,
              "comparator_sha256": sha(Path(__file__).read_bytes()),
              "limitations": LIMITATIONS, "errors": []}
    try:
        path = Path(manifest_path).resolve()
        raw = path.read_bytes()
        manifest = load_json(raw)
        require(isinstance(manifest, dict) and type(manifest.get("schema_version")) is int
                and manifest["schema_version"] == 1, "unsupported schema")
        result["manifest_sha256"] = sha(raw)
        require(manifest.get("evidence_kind") in ("synthetic_fixture", "empirical"), "missing evidence kind")
        result["evidence_kind"] = manifest["evidence_kind"]
        for key in ("sample_id", "run_id", "backend", "epoch_id", "left_endpoint_id", "right_endpoint_id"):
            require(nonempty(manifest.get(key)), "missing identity: " + key)
            result[key] = manifest[key]
        require(manifest["left_endpoint_id"] != manifest["right_endpoint_id"], "same endpoint IDs")
        require(positive(manifest.get("present_id")), "missing present identity")
        result["present_id"] = manifest["present_id"]
        times = [manifest.get(key) for key in ("left_timestamp_ns", "middle_timestamp_ns", "right_timestamp_ns")]
        require(all(positive(t) for t in times) and times[0] < times[1] < times[2]
                and times[1] - times[0] == (times[2] - times[0]) // 2, "not exact floor-nanosecond midpoint")
        require(type(manifest.get("phase_numerator")) is int and manifest["phase_numerator"] == 1
                and type(manifest.get("phase_denominator")) is int and manifest["phase_denominator"] == 2, "not one midpoint")
        require(manifest.get("pixel_format") == "RGBA8_UNORM" and manifest.get("row_origin") == "native_row_0",
                "unsupported pixel format/orientation; no implicit conversion")
        width, height = manifest.get("width"), manifest.get("height")
        require(positive(width) and positive(height) and width * height <= POLICY["max_pixels"], "invalid image dimensions")
        require(manifest.get("row_stride_bytes") == width * 4, "not packed full-resolution RGBA")
        identities = set()
        plan_raw = artifact(manifest.get("roi_plan"), path.parent, identities, 1024 * 1024)
        require(nonempty(expected_plan_sha256) and sha(plan_raw) == expected_plan_sha256, "ROI plan commitment mismatch")
        plan = load_json(plan_raw)
        require(type(plan.get("schema_version")) is int and plan["schema_version"] == 1
                and plan.get("policy_sha256") == POLICY_SHA256, "unfrozen/different metric policy")
        require(plan.get("sample_id") == manifest["sample_id"], "ROI plan sample mismatch")
        result["roi_plan_sha256"] = sha(plan_raw)
        result["roi_freeze_independently_attested"] = False
        rois = plan.get("rois")
        require(isinstance(rois, list) and 1 <= len(rois) <= 16, "missing or unbounded fixed ROIs")
        names, kinds = set(), set()
        for roi in rois:
            require(isinstance(roi, dict) and nonempty(roi.get("roi_id")) and roi["roi_id"] not in names
                    and roi["roi_id"] != "__full_frame__", "duplicate/missing ROI identity")
            names.add(roi["roi_id"])
            kind, rect = roi.get("kind"), roi.get("rect")
            require(kind in ("moving", "hud", "occlusion"), "unknown ROI category")
            kinds.add(kind)
            require(isinstance(rect, list) and len(rect) == 4 and all(type(v) is int for v in rect), "invalid ROI rectangle")
            x, y, w, h = rect
            require(x >= 0 and y >= 0 and w > 1 and h > 1 and w * h >= POLICY["min_roi_pixels"]
                    and x + w <= width and y + h <= height, "ROI outside exact frame/too small")
            require(roi.get("motion_model") in ("translation", "general", "static"), "missing fixed motion model")
        require("moving" in kinds, "at least one intended moving ROI required")
        absent = plan.get("not_present", {})
        require(isinstance(absent, dict) and set(absent) == {"hud", "occlusion"} - kinds
                and all(nonempty(v) for v in absent.values()), "undeclared missing HUD/occlusion coverage")
        result["not_present_in_sample"] = absent
        image_entries = manifest.get("images")
        if not isinstance(image_entries, dict) or "M" not in image_entries or not manifest.get("reference"):
            raise Insufficient("missing withheld true middle/reference provenance")
        require(set(image_entries) == {"A", "G", "B", "M"}, "missing/unknown image roles")
        reference = manifest["reference"]
        if (reference.get("kind") not in ("held_out_real_middle", "deterministic_reference_renderer") or
                reference.get("withheld_from_backend") is not True):
            raise Insufficient("reference is not declared independent and withheld from backend inputs")
        require(reference.get("timestamp_ns") == times[1] and nonempty(reference.get("capture_id")), "reference identity mismatch")
        artifact(reference.get("provenance"), path.parent, identities, 1024 * 1024)
        artifact(manifest.get("capture_provenance"), path.parent, identities, 1024 * 1024)
        images = {role: artifact(image_entries[role], path.parent, identities, width * height * 4)
                  for role in ("A", "G", "B", "M")}
        require(all(len(data) == width * height * 4 for data in images.values()), "image dimensions/byte length mismatch")
        result["image_sha256"] = {role: sha(data) for role, data in images.items()}
        if any(any(alpha != 255 for alpha in data[3::4]) for data in images.values()):
            raise Insufficient("nonopaque alpha requires a separately frozen compositing metric; RGB must not silently ignore it")
        result.update(compare_pixels(images, width, height, rois))
    except Insufficient as exc:
        result["status"] = "INSUFFICIENT"
        result["errors"].append(str(exc))
    except (Invalid, OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        result["errors"].append(str(exc))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--expected-plan-sha256", required=True)
    args = parser.parse_args()
    result = compare(args.manifest, args.expected_plan_sha256)
    print(json.dumps(result, sort_keys=True, indent=2))
    return {"INVALID": 2, "INSUFFICIENT": 3, "REGRESSION": 4, "IMPROVEMENT_OBSERVED": 0}[result["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
