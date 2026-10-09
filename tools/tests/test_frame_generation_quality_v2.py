"""Deterministic synthetic calibration fixtures, never empirical game evidence."""
import copy
import json
import os
import pathlib
import random
import subprocess
import sys
import tempfile
import unittest

from tools import compare_frame_generation_quality_v2 as quality


def rgba_image(width, height, pixel):
    return bytes(channel for y in range(height) for x in range(width)
                 for channel in (*pixel(x, y), 255))


def fixture_images():
    width, height = 64, 64
    rng = random.Random(9017)
    texture = [[tuple(rng.randrange(16, 240) for _ in range(3)) for _ in range(80)] for _ in range(64)]
    def scene(t):
        def pixel(x, y):
            if y < 16:  # Fixed HUD/text-like geometry, not part of the moving pan.
                return (240, 240, 240) if (x // 2 + y // 3) % 5 == 0 else (12, 12, 12)
            if y >= 48:  # Moving foreground reveals a different stationary background.
                return (220, 36, 44) if 18 + t * 2 <= x < 34 + t * 2 else texture[y][x]
            return texture[y][x + 6 + t * 2]
        return rgba_image(width, height, pixel)
    a, m, b = scene(-1), scene(0), scene(1)
    return width, height, {"A": a, "G": m, "B": b, "M": m}


class QualityComparatorTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fg-quality-synthetic-fixture-")
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.width, self.height, self.images = fixture_images()
        self.plan = {
            "schema_version": 1, "sample_id": "synthetic-calibration-1",
            "policy_sha256": quality.POLICY_SHA256,
            "rois": [
                {"roi_id": "pan", "kind": "moving", "rect": [0, 16, 64, 32], "motion_model": "translation"},
                {"roi_id": "hud", "kind": "hud", "rect": [0, 0, 64, 16], "motion_model": "static"},
                {"roi_id": "reveal", "kind": "occlusion", "rect": [0, 48, 64, 16], "motion_model": "general"},
            ], "not_present": {},
        }

    def artifact(self, name, raw):
        (self.root / name).write_bytes(raw)
        return {"path": name, "size_bytes": len(raw), "sha256": quality.sha(raw)}

    def manifest(self, images=None):
        images = images or self.images
        plan_raw = json.dumps(self.plan, sort_keys=True).encode()
        manifest = {
            "schema_version": 1, "evidence_kind": "synthetic_fixture", "sample_id": self.plan["sample_id"],
            "run_id": "calibration-not-a-game", "backend": "synthetic-control", "epoch_id": "fixture-epoch",
            "present_id": 2, "left_endpoint_id": "fixture-A", "right_endpoint_id": "fixture-B",
            "left_timestamp_ns": 1000, "middle_timestamp_ns": 1010, "right_timestamp_ns": 1021,
            "phase_numerator": 1, "phase_denominator": 2,
            "pixel_format": "RGBA8_UNORM", "row_origin": "native_row_0",
            "width": self.width, "height": self.height, "row_stride_bytes": self.width * 4,
            "roi_plan": self.artifact("fixed-rois.json", plan_raw),
            "capture_provenance": self.artifact("capture-provenance.json", b'{"synthetic_fixture":true}'),
            "reference": {"kind": "deterministic_reference_renderer", "withheld_from_backend": True,
                          "timestamp_ns": 1010, "capture_id": "synthetic-M",
                          "provenance": self.artifact("reference-provenance.json", b'{"fixture_seed":9017}')},
            "images": {role: self.artifact(role + ".rgba", raw) for role, raw in images.items()},
        }
        return manifest

    def evaluate(self, manifest=None, expected=None):
        manifest = manifest if manifest is not None else self.manifest()
        path = self.root / "sample.json"
        path.write_text(json.dumps(manifest))
        result = quality.compare(path, expected or manifest["roi_plan"]["sha256"])
        self.assertFalse(result["passed"])
        self.assertEqual(result["qualification_status"], "UNVERIFIED")
        self.assertNotEqual(result["status"], "PASS")
        return result

    def test_exact_middle_positive_calibration_is_not_runtime_pass(self):
        result = self.evaluate()
        self.assertEqual(result["status"], "IMPROVEMENT_OBSERVED", result)
        self.assertEqual(result["evidence_kind"], "synthetic_fixture")
        pan = next(r for r in result["regions"] if r["roi_id"] == "pan")
        self.assertEqual(pan["generated"]["rgb_mae"], 0)
        self.assertEqual(pan["temporal_displacement_error_pixels"], 0)
        self.assertGreater(pan["strongest_dynamic_baseline_mae"], 1)

    def test_bad_copies_and_blends_never_earn_improvement(self):
        a, b = self.images["A"], self.images["B"]
        candidates = {"copy-A": a, "copy-B": b,
                      "blend-floor": bytes((x + y) // 2 for x, y in zip(a, b)),
                      "blend-ceil": bytes((x + y + 1) // 2 for x, y in zip(a, b)),
                      "blend-nearest-even": bytes(round((x + y) / 2) for x, y in zip(a, b))}
        for name, generated in candidates.items():
            with self.subTest(control=name):
                result = self.evaluate(self.manifest({**self.images, "G": generated}))
                self.assertEqual(result["status"], "REGRESSION", result)
                self.assertTrue(result["failures"])

    def test_noise_negative_calibration(self):
        rng = random.Random(92841)
        generated = bytes(value if i % 4 == 3 else rng.randrange(256)
                          for i, value in enumerate(self.images["M"]))
        result = self.evaluate(self.manifest({**self.images, "G": generated}))
        self.assertEqual(result["status"], "REGRESSION")
        self.assertGreater(result["regions"][0]["generated"]["large_error_fraction"], 0.8)

    def test_nearest_even_half_blend_quantization_is_not_motion(self):
        self.width = self.height = 16
        self.plan["rois"] = [{"roi_id": "fade", "kind": "moving", "rect": [0, 0, 16, 16], "motion_model": "general"}]
        self.plan["not_present"] = {"hud": "synthetic additive fade", "occlusion": "synthetic additive fade"}
        a = rgba_image(16, 16, lambda x, y: (50 + (x + y) % 2,) * 3)
        b = rgba_image(16, 16, lambda x, y: (61 + (x + y) % 2,) * 3)
        middle = bytes(round((x + y) / 2) for x, y in zip(a, b))
        result = self.evaluate(self.manifest({"A": a, "G": middle, "B": b, "M": middle}))
        self.assertEqual(result["status"], "INSUFFICIENT", result)
        region = next(r for r in result["regions"] if r["roi_id"] == "fade")
        self.assertEqual(region["baselines"]["blend_floor"]["dynamic_rgb_mae"], 0.5)
        self.assertEqual(region["baselines"]["blend_ceil"]["dynamic_rgb_mae"], 0.5)
        self.assertEqual(region["baselines"]["blend_nearest_even"]["dynamic_rgb_mae"], 0)
        self.assertEqual(region["strongest_dynamic_comparison_bound_mae"], 0)

    def test_spatial_per_channel_half_blend_rounding_envelope(self):
        self.width = self.height = 16
        self.plan["rois"] = [{"roi_id": "dither", "kind": "moving", "rect": [0, 0, 16, 16], "motion_model": "general"}]
        self.plan["not_present"] = {"hud": "synthetic quantization control", "occlusion": "synthetic quantization control"}
        a = rgba_image(16, 16, lambda x, y: (50, 50, 50))
        b = rgba_image(16, 16, lambda x, y: (61, 61, 61))
        # Every channel independently chooses a valid adjacent quantization;
        # no single global floor/ceil/nearest-even image matches this control.
        middle = rgba_image(16, 16, lambda x, y: tuple(55 + ((x + y + c) % 2) for c in range(3)))
        result = self.evaluate(self.manifest({"A": a, "G": middle, "B": b, "M": middle}))
        self.assertEqual(result["status"], "INSUFFICIENT", result)
        region = next(r for r in result["regions"] if r["roi_id"] == "dither")
        self.assertEqual(region["strongest_dynamic_baseline_mae"], 0.5)
        self.assertEqual(region["strongest_dynamic_comparison_bound_mae"], 0)
        self.assertTrue(region["blend_quantization_envelope"]["reference_dependent_numeric_control"])

    def test_v1_policy_commitment_is_rejected_not_reinterpreted(self):
        self.plan["policy_sha256"] = "d6add7e391e3836c00aa5543c2a2ddccd2af47a3992816e520fcf6729df935b7"
        result = self.evaluate()
        self.assertEqual(result["status"], "INVALID")
        self.assertTrue(any("policy" in error for error in result["errors"]))

    def test_tiny_blend_improvement_cannot_clear_frozen_margins(self):
        a, b, m = (self.images[k] for k in ("A", "B", "M"))
        generated = bytes(round(0.95 * ((x + y) / 2) + 0.05 * z) for x, y, z in zip(a, b, m))
        result = self.evaluate(self.manifest({**self.images, "G": generated}))
        self.assertEqual(result["status"], "REGRESSION")
        self.assertTrue(any("both frozen margins" in reason for reason in result["failures"]))

    def test_analytic_subpixel_thin_geometry_reference_fixture(self):
        # A controlled continuous scene sampled at -1,0,+1; no runtime capture
        # is being replaced. Integer alignment is deliberately not claimed.
        self.width = self.height = 32
        def scene(t):
            return rgba_image(32, 32, lambda x, y: tuple(
                round(15 + 220 * max(0, 1 - abs(((x + y * 0.2 + t * 1.5) % 16) - 8) / 2))
                for _ in range(3)))
        a, m, b = scene(-1), scene(0), scene(1)
        self.plan["rois"] = [{"roi_id": "subpixel-diagonal", "kind": "moving",
                              "rect": [0, 0, 32, 32], "motion_model": "general"}]
        self.plan["not_present"] = {"hud": "synthetic analytic scene has no HUD",
                                    "occlusion": "single synthetic layer"}
        result = self.evaluate(self.manifest({"A": a, "G": m, "B": b, "M": m}))
        self.assertEqual(result["status"], "IMPROVEMENT_OBSERVED", result)
        result = self.evaluate(self.manifest({"A": a, "G": bytes((x + y) // 2 for x, y in zip(a, b)), "B": b, "M": m}))
        self.assertEqual(result["status"], "REGRESSION")

    def test_thin_roi_alignment_grid_respects_sample_bound(self):
        raw = bytes((12, 12, 12, 255)) * (1300 * 9)
        result = quality.alignment(raw, raw, 1300, [0, 0, 1300, 9])
        self.assertLessEqual(result["samples"], quality.POLICY["alignment_max_samples"])
        self.assertFalse(result["observable"])

    def test_wrong_one_pixel_warp_negative_calibration(self):
        middle = self.images["M"]
        generated = bytearray(middle)
        for y in range(16, 48):
            for x in range(63):
                offset = (y * 64 + x) * 4
                generated[offset:offset + 4] = middle[offset + 4:offset + 8]
        result = self.evaluate(self.manifest({**self.images, "G": bytes(generated)}))
        self.assertEqual(result["status"], "REGRESSION")
        pan = next(r for r in result["regions"] if r["roi_id"] == "pan")
        self.assertEqual(pan["alignment_to_middle"]["residual_pixels"], 1)
        self.assertTrue(any("displacement" in reason for reason in pan["failures"]))

    def test_one_bad_hud_pixel_not_hidden_by_frame_average(self):
        generated = bytearray(self.images["M"])
        generated[0:3] = b"\0\0\0"
        result = self.evaluate(self.manifest({**self.images, "G": bytes(generated)}))
        self.assertEqual(result["status"], "REGRESSION")
        self.assertLess(result["regions"][0]["generated"]["rgb_mae"], 0.1)
        hud = next(r for r in result["regions"] if r["roi_id"] == "hud")
        self.assertTrue(any("HUD" in reason for reason in hud["failures"]))

    def test_local_damage_tile_not_hidden_by_average(self):
        generated = bytearray(self.images["M"])
        for y in range(24, 32):
            for x in range(8, 16):
                offset = (y * 64 + x) * 4
                generated[offset:offset + 3] = b"\xff\xff\xff"
        result = self.evaluate(self.manifest({**self.images, "G": bytes(generated)}))
        self.assertEqual(result["status"], "REGRESSION")
        self.assertLess(result["regions"][0]["generated"]["rgb_mae"], quality.POLICY["mae_max"])
        self.assertGreater(result["regions"][0]["generated"]["worst_tile_mae"], quality.POLICY["worst_tile_mae_max"])

    def test_static_even_identical_output_is_insufficient(self):
        result = self.evaluate(self.manifest(dict.fromkeys(("A", "G", "B", "M"), self.images["M"])))
        self.assertEqual(result["status"], "INSUFFICIENT")

    def test_static_insufficiency_does_not_hide_hud_regression(self):
        images = dict.fromkeys(("A", "G", "B", "M"), self.images["M"])
        generated = bytearray(images["G"])
        generated[0:3] = b"\0\0\0"
        images["G"] = bytes(generated)
        result = self.evaluate(self.manifest(images))
        self.assertEqual(result["status"], "REGRESSION")
        self.assertTrue(result["insufficient"])
        self.assertTrue(result["failures"])

    def test_midpoint_equal_to_endpoint_has_no_provable_baseline_advantage(self):
        result = self.evaluate(self.manifest({**self.images, "G": self.images["A"], "M": self.images["A"]}))
        self.assertEqual(result["status"], "INSUFFICIENT")

    def test_missing_middle_and_not_withheld_are_insufficient(self):
        manifest = self.manifest()
        del manifest["images"]["M"]
        self.assertEqual(self.evaluate(manifest)["status"], "INSUFFICIENT")
        manifest = self.manifest()
        manifest["reference"]["withheld_from_backend"] = False
        self.assertEqual(self.evaluate(manifest)["status"], "INSUFFICIENT")

    def test_no_silent_alpha_or_format_conversion(self):
        generated = bytearray(self.images["G"])
        generated[3] = 0
        self.assertEqual(self.evaluate(self.manifest({**self.images, "G": bytes(generated)}))["status"], "INSUFFICIENT")
        manifest = self.manifest()
        manifest["pixel_format"] = "BGRA8"
        self.assertEqual(self.evaluate(manifest)["status"], "INVALID")

    def test_plan_and_policy_fingerprints_are_enforced(self):
        self.assertEqual(quality.POLICY_SHA256, "5f5eb367cd2d596a43cfa428e8c939e8d74564890a80722584bd6196d4be6560")
        self.assertEqual(self.evaluate(expected="0" * 64)["status"], "INVALID")
        self.plan["policy_sha256"] = "1" * 64
        self.assertEqual(self.evaluate()["status"], "INVALID")

    def test_fixed_roi_missing_coverage_bounds_and_duplicate_id(self):
        for mutate in (lambda: self.plan["rois"].pop(),
                       lambda: self.plan["rois"][0].update(rect=[-1, 0, 64, 64]),
                       lambda: self.plan["rois"][0].update(roi_id="hud")):
            original = copy.deepcopy(self.plan)
            mutate()
            self.assertEqual(self.evaluate()["status"], "INVALID")
            self.plan = original

    def test_files_untouched_and_corruption_or_alias_rejected(self):
        manifest = self.manifest()
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        self.evaluate(manifest)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir() if p.name != "sample.json"})
        (self.root / "G.rgba").write_bytes(b"broken")
        self.assertEqual(self.evaluate(manifest)["status"], "INVALID")

    def test_hardlinked_groundtruth_cannot_masquerade_as_separate_capture(self):
        manifest = self.manifest()
        (self.root / "G.rgba").unlink()
        os.link(self.root / "M.rgba", self.root / "G.rgba")
        result = self.evaluate(manifest)
        self.assertEqual(result["status"], "INVALID")
        self.assertIn("inode", result["errors"][0])
        manifest = self.manifest()
        manifest["images"]["G"] = manifest["images"]["M"]
        self.assertEqual(self.evaluate(manifest)["status"], "INVALID")

    def test_metadata_midpoint_and_reference_mismatch_invalid(self):
        for key, value in (("middle_timestamp_ns", 1011), ("left_endpoint_id", "fixture-B"),
                           ("row_stride_bytes", 260), ("phase_numerator", True), ("schema_version", True)):
            manifest = self.manifest()
            manifest[key] = value
            self.assertEqual(self.evaluate(manifest)["status"], "INVALID")
        manifest = self.manifest()
        manifest["reference"]["timestamp_ns"] = 1011
        self.assertEqual(self.evaluate(manifest)["status"], "INVALID")

    def test_cli_reports_comparator_only(self):
        manifest = self.manifest()
        self.evaluate(manifest)
        output = subprocess.run([sys.executable, str(pathlib.Path(quality.__file__)),
                                 str(self.root / "sample.json"), "--expected-plan-sha256",
                                 manifest["roi_plan"]["sha256"]], capture_output=True, text=True, timeout=30)
        self.assertEqual(output.returncode, 0, output.stderr)
        self.assertFalse(json.loads(output.stdout)["passed"])


if __name__ == "__main__":
    unittest.main()
