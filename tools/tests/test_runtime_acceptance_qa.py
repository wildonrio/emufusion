import importlib.util
import inspect
import io
import hashlib
import json
import re
import shlex
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "unified-android" / "tools"
sys.path.insert(0, str(TOOLS))
SPEC = importlib.util.spec_from_file_location(
    "runtime_acceptance", TOOLS / "run_runtime_acceptance_qa.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class RuntimeAcceptanceQaTest(unittest.TestCase):
    @staticmethod
    def _framegen_health_match(*, contract, schema, workload=None,
                               missing_required=None, malformed=None):
        groups = {key: "1" for key in MODULE.frame_gen.HEALTH.groupindex}
        groups.update({
            "role": "primary",
            "proof_contract": contract,
            "proof_schema_version": str(schema),
        })
        for key in MODULE._FRAMEGEN_OPTIONAL_FIELDS:
            groups[key] = None
        if workload is not None:
            groups.update(workload)
        if missing_required is not None:
            groups[missing_required] = None
        if malformed is not None:
            groups[malformed] = "not-a-number"

        class Match:
            def groupdict(self):
                return dict(groups)

            def group(self, name):
                return groups[name]

        return Match()

    @classmethod
    def _split_v32_health_transport(cls, *, mismatch=None, schema=32):
        optional = {
            key: "1" for key in MODULE._FRAMEGEN_OPTIONAL_FIELDS
            if (key not in MODULE._FRAMEGEN_OPTIONAL_V33_SCHEDULER_FIELDS and
                key not in MODULE._FRAMEGEN_OPTIONAL_V34_DIAGNOSTIC_FIELDS and
                key not in MODULE._FRAMEGEN_OPTIONAL_V35_PACKED_MASK_FIELDS)
        }
        optional.update({
            "dense_variant": "fragment-160x90-v28",
            "dense_analysis_width": "160",
            "dense_analysis_height": "90",
            "dense_solve_texels": "158080",
            "dense_total_texels": "195840",
            "dense_signature_capability": "63",
            "dense_signature_requested_gles": "3",
            "dense_signature_actual_gles_major": "3",
            "dense_signature_actual_gles_minor": "2",
            "dense_signature_self_tests": "1",
        })
        contract = (MODULE._FRAMEGEN_V33_CONTRACT if schema == 33
                    else "dense-fragment-v32")
        complete = cls._framegen_health_match(
            contract=contract, schema=schema,
            workload=optional,
        ).groupdict()
        common = {
            "generator": "7", "role": "primary", "display_id": "0",
            "proof_contract": contract,
            "proof_schema_version": str(schema), "health_sequence": "41",
            "presents": "1200", "window_start_ns": "1000000000",
            "window_end_ns": "2000000000",
        }
        base = {key: value for key, value in complete.items()
                if not key.startswith("dense_")}
        base.update(common)
        base["dense_extension_required"] = "1"
        if schema == 33:
            base.update({
                "window_due_selected": "120",
                "window_due_no_endpoint": "0",
                "window_due_phase_clamped": "0",
                "window_real_priority": "60",
                "window_synthetic_quota_skipped": "0",
                "window_presentation_epoch": "9",
                "window_synthetic_quota_opening": "0",
                "synthetic_quota_pending": "0",
                "window_synthetic_selected": "60",
                "window_synthetic_pair_created": "60",
                "window_synthetic_not_ready": "0",
                "window_duplicate_pair_selection": "0",
                "last_selected_synthetic_pair": "60",
            })
        extension = {key: value for key, value in complete.items()
                     if key.startswith("dense_")}
        extension.update(common)
        if mismatch is not None:
            extension[mismatch] = str(int(extension[mismatch]) + 1)

        class Match:
            def __init__(self, groups):
                self.groups = groups

            def groupdict(self):
                return dict(self.groups)

            def group(self, name):
                return self.groups[name]

        class Pattern:
            def __init__(self, marker, groups):
                self.marker = marker
                self.groups = groups
                self.groupindex = {key: index + 1
                                   for index, key in enumerate(groups)}

            def search(self, line):
                return Match(self.groups) if self.marker in line else None

        return (
            Pattern("Presentation health base", base),
            Pattern("Presentation health dense-extension", extension),
        )

    @staticmethod
    def _real_v32_health_line(pattern, marker):
        """Materialize one line from the verifier's frozen transport regex."""
        schema = ("35" if
                  "proofSchemaVersion=(?P<proof_schema_version>35)" in
                  pattern.pattern else ("34" if
                  "proofSchemaVersion=(?P<proof_schema_version>34)" in
                  pattern.pattern else ("33" if
                  "proofSchemaVersion=(?P<proof_schema_version>33)" in
                  pattern.pattern else "32")))
        pairs = re.findall(
            r"([A-Za-z][A-Za-z0-9]*)=\(\?P<([a-z0-9_]+)>",
            pattern.pattern,
        )
        values = {
            "generator": "7", "role": "primary", "display_id": "0",
            "proof_contract": (MODULE._FRAMEGEN_V35_CONTRACT if schema == "35"
                               else (MODULE._FRAMEGEN_V34_CONTRACT if schema == "34"
                               else (MODULE._FRAMEGEN_V33_CONTRACT
                                     if schema == "33"
                                     else "dense-fragment-v32"))),
            "proof_schema_version": schema, "health_sequence": "41",
            "presents": "1200", "window_start_ns": "1000000000",
            "window_end_ns": "2000000000", "window_ms": "1000",
            "window_presents": "120", "window_generated": "60",
            "window_promoted": "60", "dense_extension_required": "1",
            "window_presentation_callbacks": "121",
            "window_due_selected": "120", "window_due_no_endpoint": "0",
            "window_due_phase_clamped": "0", "window_real_priority": "60",
            "window_synthetic_quota_skipped": "0",
            "window_presentation_epoch": "9",
            "window_synthetic_quota_opening": "0",
            "synthetic_quota_pending": "0",
            "window_synthetic_selected": "60",
            "window_synthetic_pair_created": "60",
            "window_synthetic_not_ready": "0",
            "window_duplicate_pair_selection": "0",
            "last_selected_synthetic_pair": "60",
            "locked": "60", "output": "120", "panel": "120",
            "dense_variant": ("fragment-160x90-v35-packed-mask"
                              if schema == "35" else
                              ("fragment-160x90-v34-diagnostic"
                               if schema == "34" else
                               "fragment-160x90-v28")),
        }
        if schema in ("34", "35"):
            values.update({
                "proof": "2", "dense_proof_cells": "2592",
                "dense_backward_valid": "1000",
                "dense_forward_valid": "1000",
                "dense_diagnostic_cells": "2592",
                "dense_diagnostic_tiles": "36",
                "dense_diagnostic_mask_errors": "0",
                "dense_diagnostic_last_atlas_sequence": "2",
                "dense_diagnostic_last_pair_sequence": "2",
                "dense_diagnostic_last_previous_endpoint": "9",
                "dense_diagnostic_last_current_endpoint": "10",
                "dense_proof_atlas_layout": ("3" if schema == "35" else "2"),
                "dense_proof_atlas_enqueued": "2",
                "dense_proof_atlas_completed": "2",
                "dense_proof_atlas_pending": "0",
                "dense_promotions": "2", "promoted": "10", "real": "10",
                "submitted": "10",
            })
        if schema == "35":
            values.update({
                "dense_diagnostic_packed_cells": "2592",
                "dense_diagnostic_mask_layout": "packed-nearest-bf-v1",
                "dense_diagnostic_partition_errors": "0",
                "dense_diagnostic_reserved_bit_errors": "0",
            })
        for direction in (("backward", "forward")
                          if schema in ("34", "35") else ()):
            values.update({
                f"dense_{direction}_active": "2000",
                f"dense_{direction}_in_bounds": "2400",
                f"dense_{direction}_cycle_valid": "1900",
                f"dense_{direction}_photometric_valid": "1800",
                f"dense_{direction}_texture_valid": "1700",
                f"dense_{direction}_saturated": "20",
                f"dense_{direction}_out_of_bounds": "192",
                f"dense_{direction}_covered_tiles": "20",
                f"dense_{direction}_covered_tile_mask": str(0x3ffff),
            })
        tokens = []
        for label, group in pairs:
            if group == "dense_variant":
                tokens.extend((
                    "denseRuntimeCadenceSource=app-present-window",
                    "denseOfflineCadenceSource=surfaceflinger-layer-timestamps",
                ))
            tokens.append(f"{label}={values.get(group, '1')}")
        return (f"I/EmuFusionFrameGen( 321): {marker} " +
                " ".join(tokens))

    @staticmethod
    def _controller_identity_adb(readable, contents):
        device_block = """I: Bus=0003 Vendor=2020 Product=0111 Version=0111
N: Name="Odin Controller"
H: Handlers=event9 js0
"""

        def adb_result(_adb, _serial, *args, **_kwargs):
            if args == ("shell", "cat", "/proc/bus/input/devices"):
                return mock.Mock(returncode=0, stdout=device_block)
            if args == ("shell", "getevent", "-lp", "/dev/input/event9"):
                return mock.Mock(returncode=0, stdout="add device 1: /dev/input/event9\n")
            if args[:4] == ("shell", "settings", "get", "system"):
                return mock.Mock(returncode=0, stdout="0\n")
            if args[:3] == ("shell", "test", "-r"):
                path = args[3]
                if path in readable:
                    return mock.Mock(returncode=0, stdout="")
                # Exact r29 adb behavior: the command status is authoritative;
                # diagnostic stdout must never make a missing file readable.
                return mock.Mock(
                    returncode=1,
                    stdout=f"cat: {path}: No such file or directory\n",
                )
            if args[:2] == ("exec-out", "cat"):
                path = args[2]
                value = contents[path]
                if isinstance(value, tuple):
                    return mock.Mock(returncode=value[0], stdout=value[1])
                return mock.Mock(returncode=0, stdout=value)
            raise AssertionError(f"unexpected adb call: {args}")

        return adb_result

    @staticmethod
    def _reload_activity_dump(main_token="mainnew", preview_token="previewnew"):
        return f"""
topResumedActivity=ActivityRecord{{{main_token} u0 com.thorium.preview/org.pegasus_frontend.android.MainActivity}}
    * Hist  #0: ActivityRecord{{{main_token} u0 com.thorium.preview/org.pegasus_frontend.android.MainActivity}}
      state=RESUMED stopped=false
      mVisibleRequested=true reportedDrawn=true
      firstWindowDrawn=true nowVisible=true
    * Hist  #0: ActivityRecord{{{preview_token} u0 com.thorium.preview/.PreviewActivity}}
      state=RESUMED stopped=false
      mVisibleRequested=true reportedDrawn=true
      firstWindowDrawn=true nowVisible=true
ResumedActivity: ActivityRecord{{{main_token} u0 com.thorium.preview/org.pegasus_frontend.android.MainActivity}}
mCurrentFocus=Window{{123 u0 com.thorium.preview/org.pegasus_frontend.android.MainActivity}}
"""

    @staticmethod
    def _reload_window_dump():
        return """
mTopFocusedDisplayId=0
mCurrentFocus=Window{123 u0 com.thorium.preview/org.pegasus_frontend.android.MainActivity}
  Window #1 Window{123 u0 com.thorium.preview/org.pegasus_frontend.android.MainActivity}:
    mDisplayId=0
    mHasSurface=true isReadyForDisplay()=true
    Surface: shown=true
    mDrawState=HAS_DRAWN
    isOnScreen=true isVisible=true
  Window #2 Window{456 u0 com.thorium.preview/com.thorium.preview.PreviewActivity}:
    mDisplayId=4
    mHasSurface=true isReadyForDisplay()=true
    Surface: shown=true
    mDrawState=HAS_DRAWN
    isOnScreen=true isVisible=true
"""

    def test_matrix_contains_every_current_user_gate(self):
        matrix = MODULE.load_matrix(TOOLS / "runtime-acceptance-matrix.json")
        folders = {case.folder for case in matrix}
        self.assertTrue({
            "nes", "megadrive", "gb", "gamegear", "snes", "psx", "n64",
            "dreamcast", "gbc", "ps2", "gba", "gc", "nds", "wii", "n3ds",
            "ps3", "wiiu", "windows", "switch",
        }.issubset(folders))
        dual = {case.folder for case in matrix if case.dual_screen}
        self.assertEqual(dual, {"nds", "n3ds", "wiiu"})
        self.assertTrue(next(case for case in matrix if case.folder == "wii").flicker_burst)
        named = {case.folder: case.required_titles for case in matrix
                 if case.required_titles}
        self.assertEqual(named["gc"], ("Metroid Prime",))
        # SMG2 is preferred: SMG1's qualification save drifted into deep
        # menu states across repeated runs (2026-08-15) while SMG2's fresh
        # chooser matches the measured empty-slot flow.
        self.assertEqual(named["wii"],
                         ("Super Mario Galaxy 2", "Super Mario Galaxy"))
        self.assertEqual(named["nds"], ("Metroid Prime: Hunters",))
        self.assertEqual(named["n3ds"],
                         ("The Legend of Zelda: A Link Between Worlds",))
        touched = {case.folder for case in matrix if case.lower_touch}
        self.assertEqual(touched, {"nds", "n3ds"})

    def test_framegen_health_decoder_preserves_legacy_v22_optional_absence(self):
        match = self._framegen_health_match(
            contract=MODULE.frame_gen.PROOF_CONTRACT,
            schema=MODULE.frame_gen.PROOF_SCHEMA_VERSION,
        )
        decoded = MODULE._decode_framegen_health_match(match)
        self.assertEqual(decoded["role"], "primary")
        self.assertEqual(decoded["proof_contract"],
                         MODULE.frame_gen.PROOF_CONTRACT)
        self.assertIsInstance(decoded["generator"], int)
        for key in MODULE._FRAMEGEN_OPTIONAL_FIELDS:
            self.assertIsNone(decoded[key], key)

        health_pattern = mock.Mock()
        health_pattern.search.return_value = match
        with mock.patch.object(MODULE.frame_gen, "HEALTH", health_pattern), \
                mock.patch.object(MODULE.frame_gen, "framegen_line_pid",
                                  return_value=321):
            generic = MODULE._framegen_health_records(
                "legacy-v22", "primary", 1)
            nes = MODULE._nes_framegen_records_with_lines("legacy-v22")
        self.assertEqual(generic[0]["pid"], 321)
        self.assertEqual(nes[0]["pid"], 321)
        self.assertEqual(nes[0]["line_index"], 0)

    def test_framegen_health_decoder_preserves_full_v27_workload_types(self):
        workload = {
            "dense_variant": "fragment-192x108-v27",
            "dense_analysis_width": "192",
            "dense_analysis_height": "108",
            "dense_solve_texels": "228096",
            "dense_total_texels": "282528",
        }
        decoded = MODULE._decode_framegen_health_match(
            self._framegen_health_match(
                contract=MODULE.frame_gen.DENSE_V27_PROOF_CONTRACT,
                schema=MODULE.frame_gen.DENSE_V27_PROOF_SCHEMA_VERSION,
                workload=workload,
            )
        )
        self.assertEqual(decoded["dense_variant"],
                         "fragment-192x108-v27")
        self.assertEqual(decoded["dense_analysis_width"], 192)
        self.assertEqual(decoded["dense_analysis_height"], 108)
        self.assertEqual(decoded["dense_solve_texels"], 228096)
        self.assertEqual(decoded["dense_total_texels"], 282528)

    def test_framegen_health_decoder_preserves_full_v31_signature_context(self):
        workload = {
            "dense_variant": "fragment-160x90-v28",
            "dense_analysis_width": "160",
            "dense_analysis_height": "90",
            "dense_solve_texels": "158080",
            "dense_total_texels": "195840",
        }
        wall = {key: "1" for key in
                MODULE._FRAMEGEN_OPTIONAL_WALL_TIMING_FIELDS}
        queue = {
            "dense_signature_sequence": "122",
            "dense_signature_ready": "120",
            "dense_signature_unavailable": "0",
            "dense_signature_max_queue_age": "3",
            "dense_signature_pending": "2",
        }
        context = {
            "dense_signature_capability": "63",
            "dense_signature_requested_gles": "3",
            "dense_signature_actual_gles_major": "3",
            "dense_signature_actual_gles_minor": "2",
            "dense_signature_self_tests": "1",
        }
        decoded = MODULE._decode_framegen_health_match(
            self._framegen_health_match(
                contract=MODULE.frame_gen.DENSE_V28_PROOF_CONTRACT,
                schema=MODULE.frame_gen.DENSE_V28_PROOF_SCHEMA_VERSION,
                workload={**workload, **wall, **queue, **context},
            )
        )
        for key, value in context.items():
            self.assertEqual(decoded[key], int(value), key)
        self.assertEqual(decoded["dense_variant"],
                         "fragment-160x90-v28")

    def test_framegen_health_decoder_rejects_partial_or_malformed_groups(self):
        partial = {
            "dense_variant": "fragment-192x108-v27",
            "dense_analysis_width": "192",
        }
        with self.assertRaisesRegex(RuntimeError,
                                    "partial dense workload identity"):
            MODULE._decode_framegen_health_match(
                self._framegen_health_match(
                    contract=MODULE.frame_gen.DENSE_V27_PROOF_CONTRACT,
                    schema=MODULE.frame_gen.DENSE_V27_PROOF_SCHEMA_VERSION,
                    workload=partial,
                )
            )
        workload = {
            "dense_variant": "fragment-192x108-v27",
            "dense_analysis_width": "192",
            "dense_analysis_height": "108",
            "dense_solve_texels": "228096",
            "dense_total_texels": "282528",
        }
        with self.assertRaisesRegex(RuntimeError, "malformed numeric telemetry"):
            MODULE._decode_framegen_health_match(
                self._framegen_health_match(
                    contract=MODULE.frame_gen.DENSE_V27_PROOF_CONTRACT,
                    schema=MODULE.frame_gen.DENSE_V27_PROOF_SCHEMA_VERSION,
                    workload=workload,
                    malformed="dense_analysis_width",
                )
            )
        with self.assertRaisesRegex(RuntimeError, "missing required fields"):
            MODULE._decode_framegen_health_match(
                self._framegen_health_match(
                    contract=MODULE.frame_gen.PROOF_CONTRACT,
                    schema=MODULE.frame_gen.PROOF_SCHEMA_VERSION,
                    missing_required="window_end_ns",
                )
            )

    def test_framegen_health_decoder_rejects_partial_or_malformed_v31_context(self):
        partial_context = {
            "dense_signature_capability": "63",
            "dense_signature_requested_gles": "3",
            "dense_signature_actual_gles_major": "3",
            "dense_signature_actual_gles_minor": "2",
        }
        with self.assertRaisesRegex(RuntimeError,
                                    "partial dense signature context"):
            MODULE._decode_framegen_health_match(
                self._framegen_health_match(
                    contract=MODULE.frame_gen.DENSE_V28_PROOF_CONTRACT,
                    schema=MODULE.frame_gen.DENSE_V28_PROOF_SCHEMA_VERSION,
                    workload=partial_context,
                )
            )
        full_context = dict(
            partial_context, dense_signature_self_tests="1")
        with self.assertRaisesRegex(RuntimeError, "malformed numeric telemetry"):
            MODULE._decode_framegen_health_match(
                self._framegen_health_match(
                    contract=MODULE.frame_gen.DENSE_V28_PROOF_CONTRACT,
                    schema=MODULE.frame_gen.DENSE_V28_PROOF_SCHEMA_VERSION,
                    workload=full_context,
                    malformed="dense_signature_actual_gles_minor",
                )
            )

    def test_framegen_v32_split_health_joins_one_immediate_keyed_extension(self):
        base, extension = self._split_v32_health_transport()
        log = (
            "I/EmuFusionFrameGen( 321): Presentation health base ...\n"
            "I/OtherTag( 999): unrelated interleaved diagnostic\n"
            "I/EmuFusionFrameGen( 321): Presentation health dense-extension ...\n"
        )
        with mock.patch.object(MODULE.frame_gen, "HEALTH_BASE", base,
                               create=True), mock.patch.object(
                                   MODULE.frame_gen, "HEALTH_DENSE_EXTENSION",
                                   extension, create=True):
            records = MODULE._framegen_health_transport_records(log)
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["pid"], 321)
        self.assertEqual(record["health_sequence"], 41)
        self.assertEqual(record["presents"], 1200)
        self.assertEqual(record["dense_signature_requested_gles"], 3)
        # A complete split record becomes observable only at its extension.
        self.assertEqual(record["line_index"], 2)

    def test_framegen_v32_split_health_joins_the_real_frozen_regex(self):
        base_line = self._real_v32_health_line(
            MODULE.frame_gen.HEALTH_BASE, "Presentation health base")
        extension_line = self._real_v32_health_line(
            MODULE.frame_gen.HEALTH_DENSE_EXTENSION,
            "Presentation health dense-extension")
        self.assertIsNotNone(MODULE.frame_gen.HEALTH_BASE.search(base_line))
        self.assertIsNotNone(
            MODULE.frame_gen.HEALTH_DENSE_EXTENSION.search(extension_line))
        records = MODULE._framegen_health_transport_records(
            base_line + "\n" + extension_line + "\n")
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["pid"], 321)
        self.assertEqual(record["health_sequence"], 41)
        self.assertEqual(record["window_end_ns"], 2_000_000_000)
        self.assertEqual(record["dense_proof_atlas_enqueued"], 1)
        self.assertEqual(record["dense_callback_delta_samples"], 1)
        self.assertEqual(record["dense_proof_poll_wall_samples"], 1)

    def test_framegen_v33_split_health_requires_scheduler_and_real_regex(self):
        base_line = self._real_v32_health_line(
            MODULE.frame_gen.HEALTH_BASE_V33, "Presentation health base")
        extension_line = self._real_v32_health_line(
            MODULE.frame_gen.HEALTH_DENSE_EXTENSION,
            "Presentation health dense-extension")
        # The extension accepts both schemas; bind this one to the v33 base.
        extension_line = extension_line.replace(
            "proofContract=dense-fragment-v32 proofSchemaVersion=32",
            f"proofContract={MODULE._FRAMEGEN_V33_CONTRACT} "
            "proofSchemaVersion=33",
        )
        self.assertIsNotNone(
            MODULE.frame_gen.HEALTH_BASE_V33.search(base_line))
        self.assertIsNotNone(
            MODULE.frame_gen.HEALTH_DENSE_EXTENSION.search(extension_line))
        records = MODULE._framegen_health_transport_records(
            base_line + "\n" + extension_line + "\n")
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["proof_schema_version"], 33)
        self.assertEqual(record["proof_contract"],
                         MODULE._FRAMEGEN_V33_CONTRACT)
        self.assertEqual(record["window_due_selected"], 120)
        self.assertEqual(record["window_real_priority"], 60)
        self.assertEqual(record["window_presentation_epoch"], 9)
        self.assertEqual(record["window_synthetic_quota_opening"], 0)
        self.assertEqual(record["synthetic_quota_pending"], 0)
        self.assertEqual(record["window_synthetic_selected"], 60)
        self.assertEqual(record["window_synthetic_pair_created"], 60)
        self.assertEqual(record["window_synthetic_not_ready"], 0)
        self.assertEqual(record["window_duplicate_pair_selection"], 0)
        self.assertEqual(record["last_selected_synthetic_pair"], 60)

    def test_framegen_v34_split_health_requires_atomic_diagnostics_and_hierarchy(self):
        base_line = self._real_v32_health_line(
            MODULE.frame_gen.HEALTH_BASE_V34, "Presentation health base")
        extension_line = self._real_v32_health_line(
            MODULE.frame_gen.HEALTH_DENSE_EXTENSION_V34,
            "Presentation health dense-extension")
        self.assertIsNotNone(MODULE.frame_gen.HEALTH_BASE_V34.search(base_line))
        self.assertIsNotNone(
            MODULE.frame_gen.HEALTH_DENSE_EXTENSION_V34.search(extension_line))
        records = MODULE._framegen_health_transport_records(
            base_line + "\n" + extension_line + "\n")
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["proof_schema_version"], 34)
        self.assertEqual(record["proof_contract"], MODULE._FRAMEGEN_V34_CONTRACT)
        self.assertEqual(record["window_presentation_callbacks"], 121)
        self.assertEqual(record["dense_diagnostic_cells"], 2592)
        self.assertEqual(record["dense_backward_covered_tile_mask"], 0x3ffff)
        self.assertEqual(record["dense_diagnostic_last_current_endpoint"], 10)

        for label in ("windowPresentationCallbacks",
                      "denseBackwardActiveCells",
                      "denseDiagnosticCells"):
            with self.subTest(missing=label), self.assertRaisesRegex(
                    RuntimeError, "malformed or truncated"):
                target = base_line if label != "denseDiagnosticCells" else extension_line
                truncated = re.sub(rf" {label}=\d+", "", target, count=1)
                self.assertNotEqual(truncated, target)
                MODULE._framegen_health_transport_records(
                    (truncated if target is base_line else base_line) + "\n" +
                    (truncated if target is extension_line else extension_line) + "\n")

        for field, value in (("denseDiagnosticMaskErrors", "1"),
                             ("denseBackwardValidCells", "2001"),
                             ("denseDiagnosticLastPairSequence", "3"),
                             ("windowPresentationCallbacks", "119")):
            with self.subTest(impossible=field), self.assertRaisesRegex(
                    RuntimeError, "impossible diagnostic"):
                target = (extension_line if
                          field.startswith("denseDiagnostic") or
                          field == "denseBackwardValidCells" else base_line)
                malformed = re.sub(rf" {field}=\d+", f" {field}={value}",
                                   target, count=1)
                self.assertNotEqual(malformed, target)
                MODULE._framegen_health_transport_records(
                    (malformed if target is base_line else base_line) + "\n" +
                    (malformed if target is extension_line else extension_line) + "\n")

    def test_framegen_v34_split_health_rejects_mixed_schema_pairs(self):
        v34_base = self._real_v32_health_line(
            MODULE.frame_gen.HEALTH_BASE_V34, "Presentation health base")
        v34_extension = self._real_v32_health_line(
            MODULE.frame_gen.HEALTH_DENSE_EXTENSION_V34,
            "Presentation health dense-extension")
        v33_base = self._real_v32_health_line(
            MODULE.frame_gen.HEALTH_BASE_V33, "Presentation health base")
        v33_extension = self._real_v32_health_line(
            MODULE.frame_gen.HEALTH_DENSE_EXTENSION,
            "Presentation health dense-extension").replace(
                "proofContract=dense-fragment-v32 proofSchemaVersion=32",
                f"proofContract={MODULE._FRAMEGEN_V33_CONTRACT} "
                "proofSchemaVersion=33")
        for base, extension in ((v34_base, v33_extension),
                                (v33_base, v34_extension)):
            with self.subTest(schema=base), self.assertRaisesRegex(
                    RuntimeError, "identity mismatch"):
                MODULE._framegen_health_transport_records(
                    base + "\n" + extension + "\n")

    def test_framegen_v35_split_health_requires_packed_nearest_mask(self):
        base_line = self._real_v32_health_line(
            MODULE.frame_gen.HEALTH_BASE_V35, "Presentation health base")
        extension_line = self._real_v32_health_line(
            MODULE.frame_gen.HEALTH_DENSE_EXTENSION_V35,
            "Presentation health dense-extension")
        self.assertIsNotNone(MODULE.frame_gen.HEALTH_BASE_V35.search(base_line))
        self.assertIsNotNone(
            MODULE.frame_gen.HEALTH_DENSE_EXTENSION_V35.search(extension_line))
        records = MODULE._framegen_health_transport_records(
            base_line + "\n" + extension_line + "\n")
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["proof_schema_version"], 35)
        self.assertEqual(record["proof_contract"], MODULE._FRAMEGEN_V35_CONTRACT)
        self.assertEqual(record["dense_variant"],
                         "fragment-160x90-v35-packed-mask")
        self.assertEqual(record["dense_proof_atlas_layout"], 3)
        self.assertEqual(record["dense_diagnostic_packed_cells"], 2592)
        self.assertEqual(record["dense_diagnostic_mask_layout"],
                         "packed-nearest-bf-v1")
        self.assertEqual(record["dense_diagnostic_partition_errors"], 0)
        self.assertEqual(record["dense_diagnostic_reserved_bit_errors"], 0)

        for label in ("denseDiagnosticPackedCells",
                      "denseDiagnosticMaskLayout",
                      "denseDiagnosticPartitionErrors",
                      "denseDiagnosticReservedBitErrors"):
            with self.subTest(missing=label), self.assertRaisesRegex(
                    RuntimeError, "malformed or truncated"):
                truncated = re.sub(
                    rf" {label}=(?:\d+|packed-nearest-bf-v1)", "",
                    extension_line, count=1)
                self.assertNotEqual(truncated, extension_line)
                MODULE._framegen_health_transport_records(
                    base_line + "\n" + truncated + "\n")

    def test_framegen_v35_split_health_rejects_impossible_mask_hierarchy(self):
        base_line = self._real_v32_health_line(
            MODULE.frame_gen.HEALTH_BASE_V35, "Presentation health base")
        extension_line = self._real_v32_health_line(
            MODULE.frame_gen.HEALTH_DENSE_EXTENSION_V35,
            "Presentation health dense-extension")
        for field, value in (
                ("denseDiagnosticPackedCells", "2591"),
                ("denseDiagnosticPartitionErrors", "1"),
                ("denseDiagnosticReservedBitErrors", "1"),
                ("denseDiagnosticMaskErrors", "1"),
                ("denseProofAtlasLayout", "2"),
                ("denseBackwardOutOfBoundsCells", "191")):
            with self.subTest(field=field), self.assertRaisesRegex(
                    RuntimeError, "impossible packed-mask hierarchy"):
                target = (base_line if field.startswith("denseBackward")
                          else extension_line)
                malformed = re.sub(
                    rf" {field}=\d+", f" {field}={value}", target, count=1)
                self.assertNotEqual(malformed, target)
                MODULE._framegen_health_transport_records(
                    (malformed if target is base_line else base_line) + "\n" +
                    (malformed if target is extension_line else extension_line) +
                    "\n")

        wrong_layout = extension_line.replace(
            "denseDiagnosticMaskLayout=packed-nearest-bf-v1",
            "denseDiagnosticMaskLayout=linear-rgba-v2")
        with self.assertRaisesRegex(RuntimeError, "malformed or truncated"):
            MODULE._framegen_health_transport_records(
                base_line + "\n" + wrong_layout + "\n")

        wrong_variant = extension_line.replace(
            "denseVariant=fragment-160x90-v35-packed-mask",
            "denseVariant=fragment-160x90-v34-diagnostic")
        with self.assertRaisesRegex(RuntimeError,
                                    "impossible packed-mask hierarchy"):
            MODULE._framegen_health_transport_records(
                base_line + "\n" + wrong_variant + "\n")

    def test_framegen_v35_does_not_compare_linear_valid_to_nearest_factor_bits(self):
        base_line = self._real_v32_health_line(
            MODULE.frame_gen.HEALTH_BASE_V35, "Presentation health base")
        extension_line = self._real_v32_health_line(
            MODULE.frame_gen.HEALTH_DENSE_EXTENSION_V35,
            "Presentation health dense-extension")
        extension_line = re.sub(
            r" denseBackwardValidCells=\d+",
            " denseBackwardValidCells=2500", extension_line, count=1)
        base_line = re.sub(
            r" denseBackwardActiveCells=\d+",
            " denseBackwardActiveCells=100", base_line, count=1)
        records = MODULE._framegen_health_transport_records(
            base_line + "\n" + extension_line + "\n")
        self.assertEqual(records[0]["dense_backward_valid"], 2500)
        self.assertEqual(records[0]["dense_backward_active"], 100)

    def test_framegen_v35_split_health_rejects_mixed_v34_pair(self):
        v35_base = self._real_v32_health_line(
            MODULE.frame_gen.HEALTH_BASE_V35, "Presentation health base")
        v35_extension = self._real_v32_health_line(
            MODULE.frame_gen.HEALTH_DENSE_EXTENSION_V35,
            "Presentation health dense-extension")
        v34_base = self._real_v32_health_line(
            MODULE.frame_gen.HEALTH_BASE_V34, "Presentation health base")
        v34_extension = self._real_v32_health_line(
            MODULE.frame_gen.HEALTH_DENSE_EXTENSION_V34,
            "Presentation health dense-extension")
        for base, extension in ((v35_base, v34_extension),
                                (v34_base, v35_extension)):
            with self.subTest(base=base), self.assertRaisesRegex(
                    RuntimeError, "identity mismatch"):
                MODULE._framegen_health_transport_records(
                    base + "\n" + extension + "\n")

    def test_framegen_v34_v35_exact_empty_callback_window_is_fail_closed(self):
        def set_group(line, pattern, group, value):
            labels = dict((capture, label) for label, capture in re.findall(
                r"([A-Za-z][A-Za-z0-9]*)=\(\?P<([a-z0-9_]+)>",
                pattern.pattern,
            ))
            label = labels.get(group)
            if label is None:
                return line, False
            token = re.compile(rf" {label}=\d+")
            self.assertIsNotNone(token.search(line), group)
            replaced = re.sub(
                rf" {label}=\d+", f" {label}={value}", line, count=1)
            return replaced, True

        for schema, base_pattern, extension_pattern in (
                (34, MODULE.frame_gen.HEALTH_BASE_V34,
                 MODULE.frame_gen.HEALTH_DENSE_EXTENSION_V34),
                (35, MODULE.frame_gen.HEALTH_BASE_V35,
                 MODULE.frame_gen.HEALTH_DENSE_EXTENSION_V35)):
            with self.subTest(schema=schema):
                base = self._real_v32_health_line(
                    base_pattern, "Presentation health base")
                extension = self._real_v32_health_line(
                    extension_pattern,
                    "Presentation health dense-extension")
                empty_fields = (
                    MODULE._FRAMEGEN_EMPTY_DIAGNOSTIC_COMMON_FIELDS +
                    (MODULE._FRAMEGEN_EMPTY_DIAGNOSTIC_V35_FIELDS
                     if schema == 35 else ())
                )
                for field in ("window_presentation_callbacks",) + empty_fields:
                    base, in_base = set_group(base, base_pattern, field, 0)
                    extension, in_extension = set_group(
                        extension, extension_pattern, field, 0)
                    self.assertNotEqual(in_base, in_extension, field)

                records = MODULE._framegen_health_transport_records(
                    base + "\n" + extension + "\n")
                self.assertEqual(len(records), 1)
                self.assertEqual(records[0]["window_presentation_callbacks"], 0)

                for field in empty_fields:
                    bad_base, in_base = set_group(
                        base, base_pattern, field, 1)
                    bad_extension, in_extension = set_group(
                        extension, extension_pattern, field, 1)
                    self.assertNotEqual(in_base, in_extension, field)
                    with self.subTest(schema=schema, nonzero=field), \
                            self.assertRaisesRegex(
                                RuntimeError,
                                "impossible diagnostic callback window"):
                        MODULE._framegen_health_transport_records(
                            bad_base + "\n" + bad_extension + "\n")

                nonempty_base, found = set_group(
                    base, base_pattern, "window_presents", 2)
                self.assertTrue(found)
                nonempty_base, found = set_group(
                    nonempty_base, base_pattern,
                    "window_presentation_callbacks", 1)
                self.assertTrue(found)
                with self.assertRaisesRegex(
                        RuntimeError, "impossible diagnostic callback window"):
                    MODULE._framegen_health_transport_records(
                        nonempty_base + "\n" + extension + "\n")

    def test_framegen_v33_split_health_rejects_missing_or_mixed_scheduler_schema(self):
        base, extension = self._split_v32_health_transport(schema=33)
        base_line = "I/EmuFusionFrameGen( 321): Presentation health base ...\n"
        extension_line = (
            "I/EmuFusionFrameGen( 321): Presentation health dense-extension ...\n"
        )
        del base.groups["window_due_phase_clamped"]
        with mock.patch.object(MODULE.frame_gen, "HEALTH_BASE", base), \
                mock.patch.object(MODULE.frame_gen, "HEALTH_BASE_V33",
                                  mock.Mock(search=mock.Mock(return_value=None),
                                            groupindex={})), \
                mock.patch.object(MODULE.frame_gen, "HEALTH_DENSE_EXTENSION",
                                  extension), self.assertRaisesRegex(
                                      RuntimeError, "scheduler contract"):
            MODULE._framegen_health_transport_records(
                base_line + extension_line)

        for field in ("window_synthetic_quota_opening",
                      "window_synthetic_selected",
                      "window_synthetic_pair_created",
                      "window_synthetic_not_ready",
                      "window_duplicate_pair_selection",
                      "last_selected_synthetic_pair"):
            base, extension = self._split_v32_health_transport(schema=33)
            del base.groups[field]
            with mock.patch.object(MODULE.frame_gen, "HEALTH_BASE", base), \
                    mock.patch.object(MODULE.frame_gen, "HEALTH_BASE_V33",
                                      mock.Mock(search=mock.Mock(return_value=None),
                                                groupindex={})), \
                    mock.patch.object(MODULE.frame_gen, "HEALTH_DENSE_EXTENSION",
                                      extension), self.subTest(field=field), \
                    self.assertRaisesRegex(RuntimeError, "scheduler contract"):
                MODULE._framegen_health_transport_records(
                    base_line + extension_line)

        for selected, created, duplicates in ((61, 60, 0), (60, 60, 1)):
            base, extension = self._split_v32_health_transport(schema=33)
            base.groups["window_synthetic_selected"] = str(selected)
            base.groups["window_synthetic_pair_created"] = str(created)
            base.groups["window_duplicate_pair_selection"] = str(duplicates)
            with mock.patch.object(MODULE.frame_gen, "HEALTH_BASE", base), \
                    mock.patch.object(MODULE.frame_gen, "HEALTH_BASE_V33",
                                      mock.Mock(search=mock.Mock(return_value=None),
                                                groupindex={})), \
                    mock.patch.object(MODULE.frame_gen, "HEALTH_DENSE_EXTENSION",
                                      extension), self.subTest(
                                          selected=selected, created=created,
                                          duplicates=duplicates), \
                    self.assertRaisesRegex(RuntimeError,
                                           "impossible pair telemetry"):
                MODULE._framegen_health_transport_records(
                    base_line + extension_line)

        base, extension = self._split_v32_health_transport(schema=33)
        extension.groups["proof_schema_version"] = "32"
        with mock.patch.object(MODULE.frame_gen, "HEALTH_BASE", base), \
                mock.patch.object(MODULE.frame_gen, "HEALTH_BASE_V33",
                                  mock.Mock(search=mock.Mock(return_value=None),
                                            groupindex={})), \
                mock.patch.object(MODULE.frame_gen, "HEALTH_DENSE_EXTENSION",
                                  extension), self.assertRaisesRegex(
                                      RuntimeError, "identity mismatch"):
            MODULE._framegen_health_transport_records(
                base_line + extension_line)

    def test_framegen_v32_split_health_rejects_missing_duplicate_or_reordered(self):
        base, extension = self._split_v32_health_transport()
        base_line = "I/EmuFusionFrameGen( 321): Presentation health base ...\n"
        extension_line = (
            "I/EmuFusionFrameGen( 321): Presentation health dense-extension ...\n"
        )
        with mock.patch.object(MODULE.frame_gen, "HEALTH_BASE", base,
                               create=True), mock.patch.object(
                                   MODULE.frame_gen, "HEALTH_DENSE_EXTENSION",
                                   extension, create=True):
            for log, expected in (
                    (base_line, "lacks its immediate dense extension"),
                    (base_line + extension_line + extension_line,
                     "orphan dense extension"),
                    (extension_line + base_line, "orphan dense extension"),
                    (base_line + base_line, "before another base")):
                with self.subTest(expected=expected), self.assertRaisesRegex(
                        RuntimeError, expected):
                    MODULE._framegen_health_transport_records(log)

    def test_framegen_v32_split_health_rejects_mixed_identity_and_truncation(self):
        base_line = "I/EmuFusionFrameGen( 321): Presentation health base ...\n"
        # Pairing is keyed by strict pid + generator id, so a mismatch in
        # either is an orphan extension by construction (there is no pending
        # base on that stream to merge with); only a same-stream extension
        # whose shared fields disagree reaches the field-level identity check.
        foreign_pid_line = (
            "I/EmuFusionFrameGen( 654): Presentation health dense-extension ...\n"
        )
        same_pid_line = (
            "I/EmuFusionFrameGen( 321): Presentation health dense-extension ...\n"
        )
        for mismatch in (None, "generator", "presents", "health_sequence",
                         "window_start_ns", "window_end_ns"):
            orphan_stream = mismatch in (None, "generator")
            extension_line = (foreign_pid_line if mismatch is None
                              else same_pid_line)
            expected = ("orphan dense extension" if orphan_stream
                        else "identity mismatch")
            base, extension = self._split_v32_health_transport(
                mismatch=mismatch)
            with mock.patch.object(MODULE.frame_gen, "HEALTH_BASE", base,
                                   create=True), mock.patch.object(
                                       MODULE.frame_gen,
                                       "HEALTH_DENSE_EXTENSION", extension,
                                       create=True), self.subTest(
                                           mismatch=mismatch), \
                    self.assertRaisesRegex(RuntimeError, expected):
                MODULE._framegen_health_transport_records(
                    base_line + extension_line)

        no_match = mock.Mock()
        no_match.search.return_value = None
        no_match.groupindex = {}
        with mock.patch.object(MODULE.frame_gen, "HEALTH_BASE", no_match,
                               create=True), mock.patch.object(
                                   MODULE.frame_gen, "HEALTH_DENSE_EXTENSION",
                                   no_match, create=True):
            for marker in ("base", "dense-extension"):
                with self.subTest(marker=marker), self.assertRaisesRegex(
                        RuntimeError, "malformed or truncated"):
                    MODULE._framegen_health_transport_records(
                        "I/EmuFusionFrameGen( 321): Presentation health " +
                        marker + " truncated\n")

    def test_framegen_split_health_tolerates_cross_stream_interleaving(self):
        # Two live generators (the dual-screen GamePad pair) publish base and
        # extension lines from independent handler threads into one logcat.
        # Another stream's base between one stream's base and extension is
        # physical concurrency, not splicing, and must decode both records —
        # while a same-stream base before its extension stays an error.
        base, extension = self._split_v32_health_transport()
        base_a = "I/EmuFusionFrameGen( 321): Presentation health base ...\n"
        base_b = "I/EmuFusionFrameGen( 654): Presentation health base ...\n"
        ext_a = (
            "I/EmuFusionFrameGen( 321): Presentation health dense-extension ...\n"
        )
        ext_b = (
            "I/EmuFusionFrameGen( 654): Presentation health dense-extension ...\n"
        )
        with mock.patch.object(MODULE.frame_gen, "HEALTH_BASE", base,
                               create=True), mock.patch.object(
                                   MODULE.frame_gen, "HEALTH_DENSE_EXTENSION",
                                   extension, create=True):
            records = MODULE._framegen_health_transport_records(
                base_a + base_b + ext_a + ext_b)
            self.assertEqual([record["pid"] for record in records], [321, 654])
            with self.assertRaisesRegex(
                    RuntimeError, "another base for this generator"):
                MODULE._framegen_health_transport_records(
                    base_a + base_a + ext_a)
    def test_r29_controller_identity_ignores_missing_path_diagnostic_stdout(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        output = Path(temporary.name)
        system = "/system/usr/keylayout/Vendor_2020_Product_0111.kl"
        vendor = "/vendor/usr/keylayout/Vendor_2020_Product_0111.kl"
        valid = (
            "# Thor Odin-style layout\n"
            "key 304 BUTTON_A\nkey 305 BUTTON_B\n"
            "key 314 BUTTON_SELECT\nkey 315 BUTTON_START\n"
            "axis 0x00 X\n"
        )
        with mock.patch.object(
                MODULE.qa, "adb",
                side_effect=self._controller_identity_adb(
                    {system}, {system: valid, vendor: "cat: missing\n"}
                )) as adb_call:
            result = MODULE.nes_controller_identity(
                Path("/adb"), "serial", mock.Mock(node="/dev/input/event9"),
                output, "nes-title-01",
            )
        self.assertEqual(result["keylayoutPath"], system)
        self.assertEqual(Path(result["paths"]["keylayout"]).read_text(), valid)
        cat_paths = [call.args[4] for call in adb_call.call_args_list
                     if call.args[2:4] == ("exec-out", "cat")]
        self.assertEqual(cat_paths, [system])

    def test_controller_identity_rejects_two_or_zero_readable_keylayouts(self):
        system = "/system/usr/keylayout/Vendor_2020_Product_0111.kl"
        vendor = "/vendor/usr/keylayout/Vendor_2020_Product_0111.kl"
        valid = "key 304 BUTTON_A\n"
        for readable, message in (({system, vendor}, "ambiguous"),
                                  (set(), "no readable candidate")):
            with self.subTest(readable=readable), tempfile.TemporaryDirectory() as root, \
                    mock.patch.object(
                        MODULE.qa, "adb",
                        side_effect=self._controller_identity_adb(
                            readable, {system: valid, vendor: valid}
                        )), \
                    self.assertRaisesRegex(RuntimeError, message):
                MODULE.nes_controller_identity(
                    Path("/adb"), "serial", mock.Mock(node="/dev/input/event9"),
                    Path(root), "nes-title-01",
                )

    def test_controller_identity_rejects_empty_malformed_or_failed_cat(self):
        system = "/system/usr/keylayout/Vendor_2020_Product_0111.kl"
        cases = (
            ("", "empty or malformed"),
            ("cat: /vendor/file: No such file or directory\n", "empty or malformed"),
            ("this is not a keylayout\n", "empty or malformed"),
            ((1, "read failed\n"), "became unreadable"),
        )
        for content, message in cases:
            with self.subTest(content=content), tempfile.TemporaryDirectory() as root, \
                    mock.patch.object(
                        MODULE.qa, "adb",
                        side_effect=self._controller_identity_adb(
                            {system}, {system: content}
                        )), \
                    self.assertRaisesRegex(RuntimeError, message):
                MODULE.nes_controller_identity(
                    Path("/adb"), "serial", mock.Mock(node="/dev/input/event9"),
                    Path(root), "nes-title-01",
                )

    def test_frontend_reload_snapshot_requires_both_drawn_resumed_displays(self):
        snapshot = MODULE.frontend_reload_snapshot(
            self._reload_activity_dump(), self._reload_window_dump()
        )
        self.assertTrue(snapshot["mainDrawnResumed"])
        self.assertTrue(snapshot["mainFocused"])
        self.assertTrue(snapshot["mainWindowReady"])
        self.assertTrue(snapshot["previewDrawnResumed"])
        self.assertTrue(snapshot["previewWindowReady"])
        self.assertEqual(snapshot["previewToken"], "previewnew")

        missing_lower = MODULE.frontend_reload_snapshot(
            self._reload_activity_dump(),
            self._reload_window_dump().replace("mDisplayId=4", "mDisplayId=0"),
        )
        self.assertFalse(missing_lower["previewWindowReady"])

    def test_frontend_reload_wait_proves_new_pid_service_and_recreated_lower(self):
        activities = self._reload_activity_dump()
        windows = self._reload_window_dump()

        def adb_result(_adb, _serial, *args, **_kwargs):
            if args[:2] == ("shell", "test -d /proc/111"):
                return mock.Mock(returncode=1, stdout="")
            if args[:2] == ("shell", "test -d /proc/333"):
                return mock.Mock(returncode=1, stdout="")
            if args[:2] == ("shell", "pidof com.thorium.preview"):
                return mock.Mock(returncode=0, stdout="222\n")
            if args[:2] == ("shell", "pidof com.thorium.preview:frontend_restart"):
                return mock.Mock(returncode=1, stdout="")
            if args[:4] == ("shell", "dumpsys", "activity", "activities"):
                return mock.Mock(returncode=0, stdout=activities)
            if args[:4] == ("shell", "dumpsys", "window", "windows"):
                return mock.Mock(returncode=0, stdout=windows)
            if args[:5] == ("shell", "dumpsys", "activity", "services",
                            "com.thorium.preview"):
                return mock.Mock(returncode=0, stdout="ACTIVITY MANAGER SERVICES\n")
            self.fail(f"unexpected adb call: {args}")

        reload_log = "\n".join((
            "baseline",
            "I/LucentImport( 333): Frontend restart bridge ready oldPid=111 "
            "bridgePid=333 resumed=true focused=true firstFrameDrawn=true",
            "I/LucentImport( 333): Frontend restart observed old process exit oldPid=111",
            "I/LucentImport( 333): Frontend restart bridge launching fresh Qt process attempt=1",
            "healthy",
            "",
        ))
        with mock.patch.object(MODULE.qa, "adb", side_effect=adb_result), \
                mock.patch.object(MODULE, "import_service_request",
                                  return_value={"systems": {"nes": {}}}), \
                mock.patch.object(MODULE.qa, "logs",
                                  return_value=reload_log), \
                mock.patch.object(MODULE, "timestamped_logs",
                                  return_value="baseline-timed\n"), \
                mock.patch.object(MODULE.time, "sleep"):
            proof = MODULE.wait_frontend_reload(
                Path("/adb"), "serial", 111, "previewold", "baseline\n",
                "baseline-timed\n",
                timeout=2.0,
            )
        self.assertTrue(proof["oldPidDead"])
        self.assertEqual(proof["newPid"], 222)
        self.assertTrue(proof["differentNewPid"])
        self.assertTrue(proof["previewRecreated"])
        self.assertTrue(proof["serviceReady"])
        self.assertEqual(proof["bridgePid"], 333)
        self.assertFalse(proof["bridgeProcessAlive"])
        self.assertEqual(proof["bridgeNamedPids"], [])
        self.assertTrue(proof["bridgeActivityGone"])
        self.assertTrue(proof["bridgeProcessAcceptable"])
        self.assertTrue(proof["mediaTeardownQuiet"])
        self.assertEqual(proof["stablePolls"], 2)
        self.assertTrue(MODULE.frontend_reload_is_ready(proof))
        for key, value in (
                ("bridgeProcessAcceptable", False),
                ("bridgeActivityGone", False),
                ("mediaTeardownQuiet", False),
                ("differentNewPid", False)):
            rejected = dict(proof)
            rejected[key] = value
            self.assertFalse(MODULE.frontend_reload_is_ready(rejected), key)

    def test_frontend_reload_rejects_owned_anr_bal_and_renderer_failures(self):
        anr = "E/ActivityManager: ANR in com.thorium.preview"
        self.assertEqual(MODULE.reload_log_failures(anr, 111, 222), [anr])
        renderer = "E/Qt( 222): Android EGL swap failed (0x300d)"
        self.assertEqual(MODULE.reload_log_failures(renderer, 111, 222), [renderer])
        old_renderer = "I/Adreno ( 111): DequeueBuffer: dequeueBuffer failed"
        foreign_renderer = "I/Adreno ( 999): DequeueBuffer: dequeueBuffer failed"
        self.assertEqual(MODULE.reload_log_failures(old_renderer, 111, 222), [])
        self.assertEqual(MODULE.reload_log_failures(foreign_renderer, 111, 222), [])
        app_queue = ("E/BufferQueueProducer( 222): [SurfaceView#4]"
                     "(id:x,api:1,p:222,c:222) queueBuffer: "
                     "BufferQueue has been abandoned")
        self.assertEqual(MODULE.reload_log_failures(app_queue, 111, 222),
                         [app_queue])
        denied = "W/ActivityTaskManager: Abort background activity starts"
        policy = "allowBackgroundActivityStart:false"
        self.assertEqual(MODULE.reload_log_failures(denied, 111, 222), [denied])
        self.assertEqual(MODULE.reload_log_failures(policy, 111, 222), [policy])
        failed_launch = "E/LucentImport: Frontend restart bridge launch attempt failed"
        self.assertEqual(
            MODULE.reload_log_failures(failed_launch, 111, 222), [failed_launch]
        )

    @staticmethod
    def _r9_media_teardown(pid=29739, count=18, span_ms=14, api=3,
                           producer=1743, operation="cancelBuffer",
                           include_context=True):
        lines = []
        if include_context:
            lines.extend((
                f"08-11 06:18:18.970 {pid} {pid} I ThorPreview: Preparing video path=/sdcard/ThorPreview/a.mp4",
                "08-11 06:18:18.971 1743 1800 I NuPlayerDriver: stop(0x1)",
                f"08-11 06:18:18.972 {pid} {pid} I MediaPlayer: resetDrmState: release",
                f"08-11 06:18:18.973 {pid} {pid} I MediaCodec: release codec",
                f"08-11 06:18:18.974 {pid} {pid} I SurfaceUtils: disconnecting from surface onShutdown",
            ))
        for index in range(count):
            offset = round(index * span_ms / max(1, count - 1))
            seconds = 18_984 + offset
            op = "connect" if index == count - 1 and operation == "cancelBuffer" else operation
            lines.append(
                f"08-11 06:18:{seconds // 1000:02d}.{seconds % 1000:03d} "
                f"{pid} {pid} E BufferQueueProducer: "
                f"[SurfaceTexture-0-{pid}-0](id:abc,api:{api},p:{producer},c:{pid}) "
                f"{op}: BufferQueue has been abandoned"
            )
        if include_context:
            lines.append(
                f"08-11 06:18:19.010 {pid} {pid} I ThorPreview: Prepared video path=/sdcard/ThorPreview/b.mp4"
            )
        return "\n".join(lines) + "\n"

    def test_r9_bounded_media_surface_teardown_is_narrowly_accepted(self):
        proof = MODULE.classify_reload_surface_teardown(
            self._r9_media_teardown(), 29739
        )
        self.assertEqual(proof["failures"], [])
        self.assertEqual(proof["totalAbandonments"], 18)
        self.assertEqual(proof["aggregateSpanMs"], 14)
        self.assertEqual(len(proof["allowedGroups"]), 1)
        group = proof["allowedGroups"][0]
        self.assertEqual(group["api"], 3)
        self.assertEqual(group["producerPid"], 1743)
        self.assertEqual(group["consumerPid"], 29739)
        self.assertEqual(group["operations"][-1], "connect")
        self.assertIn("ThorPreview", group["contextFamilies"])

    @staticmethod
    def _r27_media_teardown(pid=1153, producer=25585, api=3,
                            queue_first=True, second_queue=False,
                            include_nuplayer=True, include_codec=True,
                            include_player=True, include_surface=True,
                            include_terminal=True):
        surface = (f"[SurfaceTexture-0-{pid}-0]"
                   f"(id:48100000002,api:{api},p:{producer},c:{pid})")
        queue = (f"08-11 11:51:14.573 {pid} 1172 E BufferQueueProducer: "
                 f"{surface} queueBuffer: BufferQueue has been abandoned")
        cancel = (f"08-11 11:51:14.574 {pid} 1171 E BufferQueueProducer: "
                  f"{surface} cancelBuffer: BufferQueue has been abandoned")
        lines = [queue] if queue_first else [cancel, queue]
        if include_nuplayer:
            lines.append("08-11 11:51:14.573 25585 26952 D NuPlayerDriver: stop(0x1)")
        if include_codec:
            lines.extend((
                "08-11 11:51:14.573 25585 1267 I CCodecBufferChannel: queueBuffer failed: -19",
                "08-11 11:51:14.573 25585 1267 E MediaCodec: rendering to obsolete surface",
                "08-11 11:51:14.573 25585 1267 D MediaCodec: flushMediametrics",
            ))
        if include_player:
            lines.append("08-11 11:51:14.573 1153 1153 V MediaPlayer: resetDrmState")
        if include_surface:
            lines.append("08-11 11:51:14.573 25585 1266 D SurfaceUtils: disconnecting from surface")
        lines.extend([cancel] * 18)
        if second_queue:
            lines.append(queue.replace(".573", ".580"))
        lines.append(
            f"08-11 11:51:14.584 {pid} 1285 E BufferQueueProducer: "
            f"{surface} connect: BufferQueue has been abandoned"
        )
        if include_terminal:
            lines.append("08-11 11:51:14.588 25585 1260 D NuPlayerDriver: notifyResetComplete(0x1)")
        return "\n".join(lines) + "\n"

    def test_r27_one_leading_media_queue_teardown_is_narrowly_accepted(self):
        log = self._r27_media_teardown()
        proof = MODULE.classify_reload_surface_teardown(log, 1153)
        self.assertEqual(proof["failures"], [])
        self.assertEqual(proof["totalAbandonments"], 20)
        self.assertEqual(proof["aggregateSpanMs"], 11)
        group = proof["allowedGroups"][0]
        self.assertEqual(group["operations"][0], "queuebuffer")
        self.assertEqual(group["operations"][-1], "connect")
        self.assertIsNotNone(group["queueTeardownChronology"])
        self.assertEqual(MODULE.reload_log_failures(log, 29466, 1153), [])

    def test_r27_queue_allowance_rejects_order_owner_and_context_tampering(self):
        cases = (
            self._r27_media_teardown(queue_first=False),
            self._r27_media_teardown(second_queue=True),
            self._r27_media_teardown(include_nuplayer=False),
            self._r27_media_teardown(include_codec=False),
            self._r27_media_teardown(include_player=False),
            self._r27_media_teardown(include_surface=False),
            self._r27_media_teardown(include_terminal=False),
            self._r27_media_teardown(api=1),
            self._r27_media_teardown(producer=1153),
            self._r27_media_teardown().replace("cancelBuffer", "dequeueBuffer", 1),
        )
        for log in cases:
            with self.subTest(log=log[:160]):
                self.assertTrue(
                    MODULE.classify_reload_surface_teardown(log, 1153)["failures"]
                )

    def test_r27_queue_defer_is_exact_and_foreign_media_is_ignored(self):
        exact = self._r27_media_teardown().splitlines()[0]
        self.assertTrue(MODULE.deferred_remote_media_abandonment(exact, 1153))
        self.assertFalse(MODULE.deferred_remote_media_abandonment(
            exact.replace("api:3", "api:1"), 1153
        ))
        self.assertFalse(MODULE.deferred_remote_media_abandonment(
            exact.replace("p:25585", "p:1153"), 1153
        ))

    @staticmethod
    def _r33_media_dequeue_teardown(pid=6791, producer=25585, api=3,
                                    omit="", second_dequeue=False,
                                    dequeue_first=False):
        surface = (f"[SurfaceTexture-0-{pid}-0]"
                   f"(id:1a8700000002,api:{api},p:{producer},c:{pid})")
        cancel = (f"08-11 14:19:45.121 {pid} 6800 E BufferQueueProducer: "
                  f"{surface} cancelBuffer: BufferQueue has been abandoned")
        dequeue = (f"08-11 14:19:45.121 {pid} 6801 E BufferQueueProducer: "
                   f"{surface} dequeueBuffer: BufferQueue has been abandoned")
        lines = []
        context = {
            "stop": "08-11 14:19:45.120 25585 26000 D NuPlayerDriver: stop(0x1)",
            "player": (f"08-11 14:19:45.120 {pid} {pid} V MediaPlayer: "
                       "resetDrmState cleanDrmObj"),
        }
        lines.extend(value for key, value in context.items() if omit != key)
        if dequeue_first:
            lines.append(dequeue)
        lines.extend([cancel] * 5)
        if not dequeue_first:
            lines.append(dequeue)
        if second_dequeue:
            lines.append(dequeue.replace(".121", ".122"))
        lines.extend([cancel] * 2)
        post = {
            "dequeue-error": ("08-11 14:19:45.121 25585 26001 E C2BqBuffer: "
                              "cannot dequeue buffer: -19 allocation failed"),
            "flush": ("08-11 14:19:45.125 25585 26001 E MediaCodec: "
                      "UNKNOWN_ERROR while FLUSHING"),
            "surface": ("08-11 14:19:45.125 25585 26002 D SurfaceUtils: "
                        "disconnectFromSurface"),
            "shutdown": ("08-11 14:19:45.125 25585 26000 E NuPlayerDecoder: "
                         "flush failure; shutting down"),
            "release": "08-11 14:19:45.126 25585 26001 D Codec2Client: release OK",
            "null": "08-11 14:19:45.127 25585 26001 D C2BqBuffer: null producer",
            "shutdown-connect": ("08-11 14:19:45.128 25585 26002 D SurfaceUtils: "
                                 "onShutdown connect native window"),
        }
        lines.extend(value for key, value in post.items() if omit != key)
        # Seven final cancels makes the exact physical group 16 events total:
        # 5 cancel + dequeue + 2 cancel + 7 cancel + terminal connect.
        lines.extend([cancel.replace(".121", ".122")] * 7)
        lines.append(
            f"08-11 14:19:45.129 {pid} 6802 E BufferQueueProducer: "
            f"{surface} connect: BufferQueue has been abandoned"
        )
        tail = {
            "reset": ("08-11 14:19:45.130 25585 26000 D NuPlayerDriver: "
                      "notifyResetComplete"),
            "native": ("08-11 14:19:45.130 25585 26002 D SurfaceUtils: "
                       "disconnectNativeWindow"),
            "deallocate": ("08-11 14:19:45.134 25585 26001 D CodecDriver: "
                           "closed and deallocated"),
            "healthy": (f"08-11 14:19:46.220 {pid} {pid} I ThorPreview: "
                        "Prepared video path=/sdcard/ThorPreview/next.mp4"),
        }
        lines.extend(value for key, value in tail.items() if omit != key)
        return "\n".join(lines) + "\n"

    def test_r33_one_mid_group_remote_media_dequeue_is_narrowly_accepted(self):
        log = self._r33_media_dequeue_teardown()
        proof = MODULE.classify_reload_surface_teardown(log, 6791)
        self.assertEqual(proof["failures"], [])
        self.assertEqual(proof["totalAbandonments"], 16)
        self.assertEqual(proof["aggregateSpanMs"], 8)
        group = proof["allowedGroups"][0]
        self.assertEqual(group["operations"].count("dequeuebuffer"), 1)
        self.assertGreater(group["operations"].index("dequeuebuffer"), 0)
        self.assertEqual(group["operations"][-1], "connect")
        self.assertIsNotNone(group["dequeueTeardownChronology"])
        self.assertEqual(MODULE.reload_log_failures(log, 2968, 6791), [])

    def test_r33_dequeue_allowance_rejects_shape_context_and_owner_tampering(self):
        cases = [
            self._r33_media_dequeue_teardown(dequeue_first=True),
            self._r33_media_dequeue_teardown(second_dequeue=True),
            self._r33_media_dequeue_teardown(api=1),
            self._r33_media_dequeue_teardown(producer=6791),
        ]
        cases.extend(self._r33_media_dequeue_teardown(omit=name) for name in (
            "stop", "player", "dequeue-error", "flush", "surface",
            "shutdown", "release", "null", "shutdown-connect", "reset",
            "native", "deallocate",
        ))
        for log in cases:
            with self.subTest(log=log[:180]):
                self.assertTrue(
                    MODULE.classify_reload_surface_teardown(log, 6791)["failures"]
                )
        foreign = self._r27_media_teardown(pid=7777)
        proof = MODULE.classify_reload_surface_teardown(foreign, 1153)
        self.assertEqual(proof["failures"], [])
        self.assertEqual(proof["totalAbandonments"], 0)

    def test_reload_wait_requires_one_second_quiet_after_r9_teardown(self):
        activities = self._reload_activity_dump()
        windows = self._reload_window_dump()
        clock = {"now": 0.0}

        def adb_result(_adb, _serial, *args, **_kwargs):
            if args[:2] == ("shell", "test -d /proc/111"):
                return mock.Mock(returncode=1, stdout="")
            if args[:2] == ("shell", "test -d /proc/333"):
                return mock.Mock(returncode=1, stdout="")
            if args[:2] == ("shell", "pidof com.thorium.preview"):
                return mock.Mock(returncode=0, stdout="222\n")
            if args[:2] == ("shell", "pidof com.thorium.preview:frontend_restart"):
                return mock.Mock(returncode=1, stdout="")
            if args[:4] == ("shell", "dumpsys", "activity", "activities"):
                return mock.Mock(returncode=0, stdout=activities)
            if args[:4] == ("shell", "dumpsys", "window", "windows"):
                return mock.Mock(returncode=0, stdout=windows)
            if args[:5] == ("shell", "dumpsys", "activity", "services",
                            "com.thorium.preview"):
                return mock.Mock(returncode=0, stdout="ACTIVITY MANAGER SERVICES\n")
            self.fail(f"unexpected adb call: {args}")

        reload_log = "\n".join((
            "baseline",
            "I/LucentImport( 333): Frontend restart bridge ready oldPid=111 "
            "bridgePid=333 resumed=true focused=true firstFrameDrawn=true",
            "I/LucentImport( 333): Frontend restart observed old process exit oldPid=111",
            "I/LucentImport( 333): Frontend restart bridge launching fresh Qt process attempt=1",
            "",
        ))

        def advance(seconds):
            clock["now"] += seconds

        with mock.patch.object(MODULE.qa, "adb", side_effect=adb_result), \
                mock.patch.object(MODULE, "import_service_request",
                                  return_value={"systems": {"nes": {}}}), \
                mock.patch.object(MODULE.qa, "logs", return_value=reload_log), \
                mock.patch.object(MODULE, "timestamped_logs", return_value=(
                    "baseline-timed\n" + self._r9_media_teardown(pid=222)
                )), \
                mock.patch.object(MODULE.time, "monotonic",
                                  side_effect=lambda: clock["now"]), \
                mock.patch.object(MODULE.time, "sleep", side_effect=advance):
            proof = MODULE.wait_frontend_reload(
                Path("/adb"), "serial", 111, "previewold", "baseline\n",
                "baseline-timed\n", timeout=2.0,
            )
        self.assertGreaterEqual(clock["now"], 1.25)
        self.assertTrue(proof["mediaTeardownQuiet"])
        self.assertEqual(proof["mediaTeardown"]["totalAbandonments"], 18)

    def _run_reload_with_service_responses(self, responses, timeout=2.0):
        activities = self._reload_activity_dump()
        windows = self._reload_window_dump()
        clock = {"now": 0.0}

        def adb_result(_adb, _serial, *args, **_kwargs):
            if args[:2] == ("shell", "test -d /proc/111"):
                return mock.Mock(returncode=1, stdout="")
            if args[:2] == ("shell", "test -d /proc/333"):
                return mock.Mock(returncode=1, stdout="")
            if args[:2] == ("shell", "pidof com.thorium.preview"):
                return mock.Mock(returncode=0, stdout="222\n")
            if args[:2] == ("shell", "pidof com.thorium.preview:frontend_restart"):
                return mock.Mock(returncode=1, stdout="")
            if args[:4] == ("shell", "dumpsys", "activity", "activities"):
                return mock.Mock(returncode=0, stdout=activities)
            if args[:4] == ("shell", "dumpsys", "window", "windows"):
                return mock.Mock(returncode=0, stdout=windows)
            if args[:5] == ("shell", "dumpsys", "activity", "services",
                            "com.thorium.preview"):
                return mock.Mock(returncode=0, stdout="ACTIVITY MANAGER SERVICES\n")
            self.fail(f"unexpected adb call: {args}")

        reload_log = "\n".join((
            "baseline",
            "I/LucentImport( 333): Frontend restart bridge ready oldPid=111 "
            "bridgePid=333 resumed=true focused=true firstFrameDrawn=true",
            "I/LucentImport( 333): Frontend restart observed old process exit oldPid=111",
            "I/LucentImport( 333): Frontend restart bridge launching fresh Qt process attempt=1",
            "",
        ))
        iterator = iter(responses)
        final = responses[-1]

        def service_response(*_args, **_kwargs):
            try:
                value = next(iterator)
            except StopIteration:
                value = final
            if isinstance(value, BaseException):
                raise value
            return value

        def advance(seconds):
            clock["now"] += seconds

        patches = (
            mock.patch.object(MODULE.qa, "adb", side_effect=adb_result),
            mock.patch.object(MODULE, "import_service_request",
                              side_effect=service_response),
            mock.patch.object(MODULE.qa, "logs", return_value=reload_log),
            mock.patch.object(MODULE, "timestamped_logs",
                              return_value="baseline-timed\n"),
            mock.patch.object(MODULE.time, "monotonic",
                              side_effect=lambda: clock["now"]),
            mock.patch.object(MODULE.time, "sleep", side_effect=advance),
        )
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            return MODULE.wait_frontend_reload(
                Path("/adb"), "serial", 111, "previewold", "baseline\n",
                "baseline-timed\n", timeout=timeout,
            )

    def test_reload_transient_remote_disconnect_then_success_stays_bounded(self):
        proof = self._run_reload_with_service_responses((
            MODULE.http.client.RemoteDisconnected("fresh service not ready"),
            {"systems": {"nes": {}}},
            {"systems": {"nes": {}}},
        ))
        self.assertTrue(proof["serviceReady"])
        self.assertTrue(proof["servicePayloadValid"])
        self.assertEqual(proof["serviceError"], "")
        self.assertEqual(proof["stablePolls"], 2)

    def test_reload_persistent_transport_failure_times_out_fail_closed(self):
        with self.assertRaisesRegex(
                RuntimeError, "transient library index transport failure: RemoteDisconnected"):
            self._run_reload_with_service_responses((
                MODULE.http.client.RemoteDisconnected("still starting"),
            ), timeout=0.6)

    def test_reload_malformed_successful_index_never_becomes_ready(self):
        malformed = (
            ["not", "an", "object"],
            {"systems": ["nes"]},
            MODULE.json.JSONDecodeError("bad JSON", "{", 1),
        )
        for payload in malformed:
            with self.subTest(payload=repr(payload)), self.assertRaisesRegex(
                    RuntimeError, "malformed library index"):
                self._run_reload_with_service_responses((payload,), timeout=0.6)

    def test_r12_preinput_menu_uses_reference_title_and_list_structure(self):
        r12_ocr = (
            "Lucent Callback Test CRITICS N/A USERS N/A RELEASE N/A "
            "Low G Man CRITICS 6.9 USERS 6.8 RELEASE 1990"
        )
        with mock.patch.object(MODULE, "mean_absolute_difference",
                               return_value=23.001125), \
                mock.patch.object(MODULE, "ocr", return_value=r12_ocr):
            proof = MODULE.classify_nes_library_frame(
                Path("menu.png"), Path("pre-input.png"),
                "Lucent Callback Test",
            )
        self.assertTrue(proof["matched"])
        self.assertTrue(proof["titleMatched"])
        self.assertEqual(proof["ratingLabels"],
                         ["CRITICS", "USERS", "RELEASE"])
        self.assertEqual(proof["viewLabels"], [])
        self.assertTrue(proof["structureMatched"])

    def test_generic_return_menu_accepts_large_headings_without_tiny_footer(self):
        with mock.patch.object(MODULE, "mean_absolute_difference",
                               return_value=49.68), \
                mock.patch.object(
                    MODULE, "ocr",
                    return_value=(
                        "NINTENDO GAMECUBE METROID PRIME "
                        "CRITICS 9.6 USERS 9.0 RELEASE 2002"
                    )):
            proof = MODULE.classify_generic_library_frame(
                Path("menu.png"), Path("return.png")
            )
        self.assertTrue(proof["matched"])
        self.assertEqual(proof["viewLabels"], [])
        self.assertEqual(proof["ratingLabels"],
                         ["CRITICS", "USERS", "RELEASE"])

    def test_generic_return_menu_rejects_gameplay_and_loose_reference(self):
        cases = (
            (37.7, "PRESS AND HOLD TO LOCK ONTO TARGETS", False),
            (64.9, "CRITICS USERS", True),
            (65.0, "CRITICS USERS RELEASE", False),
        )
        for difference, text, expected in cases:
            with self.subTest(difference=difference, text=text), \
                    mock.patch.object(MODULE, "mean_absolute_difference",
                                      return_value=difference), \
                    mock.patch.object(MODULE, "ocr", return_value=text):
                proof = MODULE.classify_generic_library_frame(
                    Path("menu.png"), Path("frame.png")
                )
                self.assertEqual(proof["matched"], expected)

    @staticmethod
    def _immediate_launch_classifier(states):
        def classify(_reference, path, expected_title):
            state = states[path.name]
            selected = state == "menu" and expected_title == "Lucent Callback Test"
            any_menu = state in ("menu", "wrong-menu")
            text = {
                "menu": "LUCENT CALLBACK TEST CRITICS USERS RELEASE",
                "wrong-menu": "DIFFERENT GAME CRITICS USERS RELEASE",
                "guest": "",
                "foreign": "PREPARING GAME",
                "title-splash": "LUCENT CALLBACK TEST",
                "unknown": "",
            }[state]
            return {
                "matched": selected,
                "ocr": text,
                "referenceMeanAbsoluteDifference": 23.0 if any_menu else 90.0,
                "referenceThresholdExclusive": 65.0,
                "structureMatched": any_menu,
                "titleMatched": state in ("menu", "title-splash"),
            }
        return classify

    def test_r24_immediate_nes_frames_allow_selected_menu_then_guest(self):
        frames = [Path(f"nes-title-01-launch-{index:02d}.png")
                  for index in range(1, 5)]
        states = {frames[0].name: "menu",
                  **{path.name: "guest" for path in frames[1:]}}
        with mock.patch.object(
                MODULE, "classify_nes_library_frame",
                side_effect=self._immediate_launch_classifier(states)), \
                mock.patch.object(
                    MODULE, "_nes_immediate_guest_frame",
                    side_effect=lambda path: states[path.name] == "guest"):
            evidence = MODULE.classify_nes_immediate_launch_frames(
                frames, Path("nes-cover.png"), "Lucent Callback Test"
            )
        self.assertEqual([item["state"] for item in evidence],
                         ["selected-menu", "guest", "guest", "guest"])

    def test_immediate_nes_guest_classifier_requires_visible_four_three_with_pillars(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        valid = root / "guest.png"
        stretched = root / "stretched.png"
        black = root / "black.png"
        image = Image.new("RGB", (960, 540), "black")
        ImageDraw.Draw(image).rectangle((120, 0, 839, 539), fill=(20, 80, 170))
        image.save(valid)
        Image.new("RGB", (960, 540), (20, 80, 170)).save(stretched)
        Image.new("RGB", (960, 540), "black").save(black)
        self.assertTrue(MODULE._nes_immediate_guest_frame(valid))
        self.assertFalse(MODULE._nes_immediate_guest_frame(stretched))
        self.assertFalse(MODULE._nes_immediate_guest_frame(black))

    def test_immediate_nes_frames_reject_menu_regression(self):
        frames = [Path("launch-01.png"), Path("launch-02.png"),
                  Path("launch-03.png")]
        states = {frames[0].name: "menu", frames[1].name: "guest",
                  frames[2].name: "menu"}
        with mock.patch.object(
                MODULE, "classify_nes_library_frame",
                side_effect=self._immediate_launch_classifier(states)), \
                mock.patch.object(
                    MODULE, "_nes_immediate_guest_frame",
                    side_effect=lambda path: states[path.name] == "guest"), \
                self.assertRaisesRegex(RuntimeError, "reappeared after guest"):
            MODULE.classify_nes_immediate_launch_frames(
                frames, Path("menu.png"), "Lucent Callback Test"
            )

    def test_immediate_nes_frames_reject_wrong_menu_foreign_and_no_guest(self):
        cases = (
            (["wrong-menu"], "wrong selected menu"),
            (["foreign"], "launch interstitial"),
            (["menu", "menu"], "never reached guest"),
        )
        for sequence, message in cases:
            with self.subTest(sequence=sequence):
                frames = [Path(f"launch-{index:02d}.png")
                          for index in range(len(sequence))]
                states = dict(zip((path.name for path in frames), sequence))
                with mock.patch.object(
                        MODULE, "classify_nes_library_frame",
                        side_effect=self._immediate_launch_classifier(states)), \
                        mock.patch.object(
                            MODULE, "_nes_immediate_guest_frame",
                            side_effect=lambda path: states[path.name] == "guest"), \
                        self.assertRaisesRegex(RuntimeError, message):
                    MODULE.classify_nes_immediate_launch_frames(
                        frames, Path("menu.png"), "Lucent Callback Test"
                    )

    def test_r28_nes_return_allows_guest_then_exact_lucent_menu_persistently(self):
        frames = [Path(f"nes-title-01-moving-stop-return-video-{index:06d}.png")
                  for index in range(38, 43)]
        states = {path.name: ("guest" if index < 40 else "menu")
                  for index, path in zip(range(38, 43), frames)}
        with mock.patch.object(
                MODULE, "classify_nes_library_frame",
                side_effect=self._immediate_launch_classifier(states)), \
                mock.patch.object(
                    MODULE, "_nes_video_guest_frame",
                    side_effect=lambda path: states[path.name] == "guest"):
            evidence, menu_paths = MODULE.classify_nes_return_frames(
                frames, Path("nes-cover.png"), "Lucent Callback Test"
            )
        self.assertEqual([item["state"] for item in evidence],
                         ["guest", "guest", "selected-menu",
                          "selected-menu", "selected-menu"])
        self.assertEqual(menu_paths, set(frames[2:]))
        self.assertIn("LUCENT CALLBACK TEST", evidence[2]["ocr"])

    def test_nes_return_rejects_menu_to_guest_regression(self):
        frames = [Path("return-01.png"), Path("return-02.png"),
                  Path("return-03.png")]
        states = {frames[0].name: "guest", frames[1].name: "menu",
                  frames[2].name: "guest"}
        with mock.patch.object(
                MODULE, "classify_nes_library_frame",
                side_effect=self._immediate_launch_classifier(states)), \
                mock.patch.object(
                    MODULE, "_nes_video_guest_frame",
                    side_effect=lambda path: states[path.name] == "guest"), \
                self.assertRaisesRegex(RuntimeError,
                                       "reappeared after the library menu"):
            MODULE.classify_nes_return_frames(
                frames, Path("menu.png"), "Lucent Callback Test"
            )

    def test_nes_return_rejects_wrong_splash_foreign_and_missing_menu(self):
        cases = (
            (["guest", "wrong-menu"], "wrong selected menu"),
            (["guest", "title-splash"], "title splash"),
            (["guest", "foreign"], "return interstitial"),
            (["guest", "unknown"], "foreign/unclassified"),
            (["guest", "guest"], "never reached the exact selected"),
        )
        for sequence, message in cases:
            with self.subTest(sequence=sequence):
                frames = [Path(f"return-{index:02d}.png")
                          for index in range(len(sequence))]
                states = dict(zip((path.name for path in frames), sequence))
                with mock.patch.object(
                        MODULE, "classify_nes_library_frame",
                        side_effect=self._immediate_launch_classifier(states)), \
                        mock.patch.object(
                            MODULE, "_nes_video_guest_frame",
                            side_effect=lambda path: states[path.name] == "guest"), \
                        self.assertRaisesRegex(RuntimeError, message):
                    MODULE.classify_nes_return_frames(
                        frames, Path("menu.png"), "Lucent Callback Test"
                    )

    def test_stop_passes_exact_title_to_nes_return_only(self):
        source = inspect.getsource(MODULE.stop_and_return)
        self.assertIn(
            'expected_title if case.folder == "nes" else None', source
        )
        self.assertIn("finish_visible_return_recording", source)

    def test_runtime_checkpoint_requires_commit_without_quarantine(self):
        before = "engine booted normally"
        current = "Quick Resume committed engine=mesen system=nes"
        self.assertEqual(
            MODULE.runtime_checkpoint_outcome(
                before, current, "mesen", "nes", 0, 0
            ),
            "committed",
        )
        self.assertIsNone(
            MODULE.runtime_checkpoint_outcome(
                before,
                "Skipped unqualified runtime-state checkpoint engine=mesen "
                "marker=state-restore-quarantined",
                "mesen", "nes", 0, 0,
            )
        )

    def test_runtime_checkpoint_accepts_declared_quarantine_skip(self):
        before = (
            "Runtime state restore is quarantined; cold booting engine=armsx2 "
            "marker=state-restore-quarantined"
        )
        skipped = (
            "Skipped unqualified runtime-state checkpoint engine=armsx2 "
            "marker=state-restore-quarantined"
        )
        self.assertEqual(
            MODULE.runtime_checkpoint_outcome(
                before, skipped, "armsx2", "ps2", 0, 0
            ),
            "quarantined",
        )
        self.assertIsNone(
            MODULE.runtime_checkpoint_outcome(
                before, skipped, "armsx2", "ps2", 0, 1
            )
        )

    def test_runtime_checkpoint_accepts_only_paired_visible_save_failure(self):
        save = (
            "Quick Resume was not updated for dolphin marker=save-failure"
        )
        visible = (
            "Background exit checkpoint failure shown in library "
            "engine=dolphin system=wii marker=exit-save-failure-visible"
        )
        self.assertEqual(
            MODULE.runtime_checkpoint_outcome(
                "", save + "\n" + visible, "dolphin", "wii",
                0, 0, 0, 0,
            ),
            "failed-visible",
        )
        self.assertIsNone(MODULE.runtime_checkpoint_outcome(
            "", save, "dolphin", "wii", 0, 0, 0, 0,
        ))
        self.assertIsNone(MODULE.runtime_checkpoint_outcome(
            "", visible, "dolphin", "wii", 0, 0, 0, 0,
        ))
        self.assertIsNone(MODULE.runtime_checkpoint_outcome(
            save + "\n" + visible, save + "\n" + visible,
            "dolphin", "wii", 0, 0, 1, 1,
        ))

    def test_preinput_menu_classifier_rejects_title_splash_and_wrong_reference(self):
        cases = (
            (23.0, "Lucent Callback Test PRESENTS", False),
            (23.0, "Different Game CRITICS USERS RELEASE", False),
            (65.0, "Lucent Callback Test CRITICS USERS RELEASE", False),
            (64.9, "Lucent Callback Test LIST VIEW", True),
        )
        for difference, text, expected in cases:
            with self.subTest(difference=difference, text=text), \
                    mock.patch.object(MODULE, "mean_absolute_difference",
                                      return_value=difference), \
                    mock.patch.object(MODULE, "ocr", return_value=text):
                proof = MODULE.classify_nes_library_frame(
                    Path("menu.png"), Path("frame.png"),
                    "Lucent Callback Test",
                )
                self.assertEqual(proof["matched"], expected)

    def test_preinput_launch_error_distinguishes_timestamp_from_classifier(self):
        after_only = [MODULE.nes_qa.TimedImage(
            0, 1_000_000_001, Path("after.png")
        )]
        with self.assertRaisesRegex(
                RuntimeError, "no timestamped pre-input frame"):
            MODULE.require_nes_preinput_library_frame(
                after_only, 1_000_000_000, Path("menu.png"), "Expected"
            )

        before = [MODULE.nes_qa.TimedImage(
            0, 999_000_000, Path("before.png")
        )]
        with mock.patch.object(MODULE, "classify_nes_library_frame",
                               return_value={"matched": False,
                                             "titleMatched": False}), \
                self.assertRaisesRegex(
                    RuntimeError, "failed the library-menu classifier"
                ):
            MODULE.require_nes_preinput_library_frame(
                before, 1_000_000_000, Path("menu.png"), "Expected"
            )

    def test_nes_launch_recorder_is_warmed_before_physical_a(self):
        order = []
        recorder = mock.Mock()
        with mock.patch.object(
                MODULE, "begin_visible_return_recording",
                side_effect=lambda *_args: (
                    order.append("record-warmed") or recorder, "/remote.mp4"
                )), mock.patch.object(
                MODULE, "inject_nes_launch_device_clocked",
                side_effect=lambda *_args: (
                    order.append("physical-a") or
                    {"inputLowerBoundElapsedNs": 123}
                )):
            actual = MODULE.begin_nes_launch_capture(
                Path("/adb"), "serial", mock.Mock(), Path("/output"), "nes"
            )
        self.assertEqual(order, ["record-warmed", "physical-a"])
        self.assertEqual(actual, (
            recorder, "/remote.mp4", {"inputLowerBoundElapsedNs": 123}
        ))

    def test_nes_launch_recorder_failure_cleans_remote_before_propagating(self):
        recorder = mock.Mock()
        recorder.poll.return_value = None
        with mock.patch.object(
                MODULE, "begin_visible_return_recording",
                return_value=(recorder, "/remote launch.mp4")), \
                mock.patch.object(MODULE, "inject_nes_launch_device_clocked",
                                  side_effect=RuntimeError("input failed")), \
                mock.patch.object(MODULE.qa, "adb") as adb:
            with self.assertRaisesRegex(RuntimeError, "input failed"):
                MODULE.begin_nes_launch_capture(
                    Path("/adb"), "serial", mock.Mock(), Path("/output"), "nes"
                )
        recorder.kill.assert_called_once_with()
        recorder.communicate.assert_called_once_with(timeout=2.0)
        adb.assert_called_once_with(
            Path("/adb"), "serial", "shell", "rm", "-f",
            "/remote launch.mp4", check=False,
        )

    def test_nes_motion_normalization_leaves_already_moving_fixture_untouched(self):
        controller = mock.Mock()
        pair = (Path("initial-before.png"), Path("initial-after.png"))
        with mock.patch.object(MODULE, "_capture_nes_motion_pair",
                               return_value=pair), \
                mock.patch.object(MODULE.nes_qa, "analyze_motion",
                                  return_value={"changedPixels": 1200,
                                                "spanMs": 250}):
            proof = MODULE.normalize_nes_fixture_motion(
                Path("/adb"), "serial", controller, Path("/output"),
                "nes", "startup",
            )
        self.assertEqual(proof["initialState"], "moving")
        self.assertEqual(proof["action"], "none")
        self.assertEqual(proof["motionBefore"], "initial-before.png")
        controller.key.assert_not_called()

    def test_nes_motion_normalization_physically_unfreezes_then_reproves(self):
        controller = mock.Mock(START=315)
        pairs = (
            (Path("static-before.png"), Path("static-after.png")),
            (Path("moving-before.png"), Path("moving-after.png")),
        )
        with mock.patch.object(MODULE, "_capture_nes_motion_pair",
                               side_effect=pairs) as capture, \
                mock.patch.object(MODULE.nes_qa, "analyze_motion", side_effect=(
                    ValueError("NES fixture did not visibly advance: changedPixels=0"),
                    {"changedPixels": 2000, "spanMs": 250},
                )), mock.patch.object(MODULE.time, "sleep"):
            proof = MODULE.normalize_nes_fixture_motion(
                Path("/adb"), "serial", controller, Path("/output"),
                "nes", "startup",
            )
        self.assertEqual(capture.call_count, 2)
        controller.key.assert_called_once_with(
            315, "nes-qualification-startup-restore-moving", hold=0.08
        )
        self.assertEqual(proof["initialState"], "static")
        self.assertEqual(proof["initialChangedPixels"], 0)
        self.assertEqual(proof["action"], "physical-start")
        self.assertEqual(proof["motionBefore"], "moving-before.png")

    def test_nes_motion_normalization_fails_if_start_does_not_restore_motion(self):
        controller = mock.Mock(START=315)
        with mock.patch.object(MODULE, "_capture_nes_motion_pair", side_effect=(
                (Path("static-before.png"), Path("static-after.png")),
                (Path("still-before.png"), Path("still-after.png")),
        )), mock.patch.object(MODULE.nes_qa, "analyze_motion", side_effect=(
            ValueError("NES fixture did not visibly advance: changedPixels=0"),
            ValueError("NES fixture did not visibly advance: changedPixels=0"),
        )), mock.patch.object(MODULE.time, "sleep"):
            with self.assertRaisesRegex(
                    RuntimeError, "physical Start did not restore"):
                MODULE.normalize_nes_fixture_motion(
                    Path("/adb"), "serial", controller, Path("/output"),
                    "nes", "startup",
                )
        controller.key.assert_called_once()

    def test_nes_control_failure_still_normalizes_motion_in_finally(self):
        controller = mock.Mock(A=304, B=305, STOP=314, START=315,
                               UP=544, DOWN=545, LEFT=546, RIGHT=547)
        startup = {
            "initialState": "moving", "action": "none",
            "motion": {"changedPixels": 1200, "spanMs": 250},
            "initialBefore": "startup-before.png",
            "initialAfter": "startup-after.png",
            "motionBefore": "startup-before.png",
            "motionAfter": "startup-after.png",
        }
        cleanup = {
            "initialState": "static", "action": "physical-start",
            "motion": {"changedPixels": 1300, "spanMs": 250},
            "initialBefore": "cleanup-before.png",
            "initialAfter": "cleanup-after.png",
            "motionBefore": "cleanup-moving-before.png",
            "motionAfter": "cleanup-moving-after.png",
        }
        with mock.patch.object(MODULE.nes_qa, "analyze_geometry",
                               return_value={"fullHeight": True}), \
                mock.patch.object(MODULE, "normalize_nes_fixture_motion",
                                  side_effect=(startup, cleanup)) as normalize, \
                mock.patch.object(MODULE, "screenshot"), \
                mock.patch.object(MODULE, "_capture_nes_control",
                                  side_effect=lambda *_args: Path("control.png")), \
                mock.patch.object(MODULE.nes_qa, "analyze_controls",
                                  side_effect=ValueError("marker mismatch")), \
                mock.patch.object(MODULE.time, "sleep"):
            with self.assertRaisesRegex(ValueError, "marker mismatch"):
                MODULE.nes_fixture_evidence(
                    Path("/adb"), "serial", controller, Path("/output"),
                    "nes", Path("gameplay.png"),
                )
        self.assertEqual([call.args[-1] for call in normalize.call_args_list],
                         ["startup", "post-controls"])

    def test_r7_app_owned_qt_surface_abandonment_is_rejected(self):
        log = self._r9_media_teardown(
            api=1, producer=29739, operation="dequeueBuffer"
        ) + "\n".join((
            "08-11 06:18:19.020 29739 29739 E Adreno: DequeueBuffer failed",
            "08-11 06:18:19.021 29739 29739 E Qt: Renderer stopped",
            "08-11 06:18:19.022 29739 29739 E Qt: Android EGL swap failed (0x300d)",
            "08-11 06:18:19.023 29739 29739 E Lucent: Engine session error",
        ))
        proof = MODULE.classify_reload_surface_teardown(log, 29739)
        self.assertGreaterEqual(len(proof["failures"]), 5)

        qt_surface = (
            "08-11 06:18:19.030 29739 29739 E BufferQueueProducer: "
            "[SurfaceView[com.thorium.preview/MainActivity]#4]"
            "(id:def,api:1,p:29739,c:29739) dequeueBuffer: "
            "BufferQueue has been abandoned\n"
        )
        self.assertTrue(MODULE.classify_reload_surface_teardown(
            qt_surface, 29739
        )["failures"])

    def test_r11_old_pid_pre_ready_adreno_errors_do_not_taint_new_process(self):
        old_pid = 23936
        new_pid = 28519
        old_lines = "\n".join((
            "08-11 06:45:23.486 23936 24001 I Adreno: DequeueBuffer: dequeueBuffer failed",
            "08-11 06:45:23.486 23936 24001 I Adreno: DequeueBuffer: dequeueBuffer failed",
            "08-11 06:45:23.544 28472 28472 I LucentImport: Frontend restart bridge ready oldPid=23936 bridgePid=28472 resumed=true focused=true firstFrameDrawn=true",
        ))
        proof = MODULE.classify_reload_surface_teardown(old_lines, new_pid)
        self.assertEqual(proof["failures"], [])

        new_line = old_lines.replace(
            "23936 24001 I Adreno", "28519 28519 I Adreno", 1
        )
        self.assertTrue(MODULE.classify_reload_surface_teardown(
            new_line, new_pid
        )["failures"])

        foreign = old_lines.replace(
            f"{old_pid} 24001 I Adreno", "31000 31001 I Adreno"
        )
        self.assertEqual(MODULE.classify_reload_surface_teardown(
            foreign, new_pid
        )["failures"], [])

    def test_media_teardown_rejects_recurrence_size_context_and_wrong_owner(self):
        cases = (
            self._r9_media_teardown(span_ms=400),
            self._r9_media_teardown(count=33),
            self._r9_media_teardown(include_context=False),
            self._r9_media_teardown(producer=29739),
        )
        for log in cases:
            with self.subTest(log=log[:80]):
                self.assertTrue(
                    MODULE.classify_reload_surface_teardown(log, 29739)["failures"]
                )

    def test_cached_empty_bridge_without_components_is_accepted(self):
        activities = self._reload_activity_dump()
        windows = self._reload_window_dump()

        def adb_result(_adb, _serial, *args, **_kwargs):
            if args[:2] == ("shell", "test -d /proc/333"):
                return mock.Mock(returncode=0, stdout="")
            if args[:2] == ("shell", "pidof com.thorium.preview:frontend_restart"):
                return mock.Mock(returncode=0, stdout="333\n")
            if args[:5] == ("shell", "dumpsys", "activity", "services",
                            "com.thorium.preview"):
                return mock.Mock(returncode=0, stdout="ACTIVITY MANAGER SERVICES\n")
            if args[:4] == ("shell", "dumpsys", "activity", "processes"):
                return mock.Mock(returncode=0, stdout=(
                    "  *APP* UID 10165 ProcessRecord{abc 333:com.thorium.preview:frontend_restart/u0a165}\n"
                    "    oom adj: max=1001 curRaw=905 setRaw=905 cur=905 set=905\n"
                    "    curProcState=19 setProcState=19 cached=true empty=true\n"
                ))
            if args[:3] == ("shell", "cat", "/proc/333/oom_score_adj"):
                return mock.Mock(returncode=0, stdout="905\n")
            self.fail(f"unexpected adb call: {args}")

        with mock.patch.object(MODULE.qa, "adb", side_effect=adb_result):
            proof = MODULE.bridge_process_state(
                Path("/adb"), "serial", 333, activities, windows
            )
        self.assertTrue(proof["bridgeProcessAlive"])
        self.assertTrue(proof["bridgeCachedEmpty"])
        self.assertTrue(proof["bridgeServiceGone"])
        self.assertTrue(proof["bridgeForegroundGone"])
        self.assertTrue(proof["bridgeProcessAcceptable"])

    def test_bridge_with_component_or_foreground_state_is_rejected(self):
        base = self._reload_activity_dump()
        windows = self._reload_window_dump()

        def run(services="", process_suffix="curProcState=CACHED_EMPTY"):
            def adb_result(_adb, _serial, *args, **_kwargs):
                if args[:2] == ("shell", "test -d /proc/333"):
                    return mock.Mock(returncode=0, stdout="")
                if args[:2] == ("shell", "pidof com.thorium.preview:frontend_restart"):
                    return mock.Mock(returncode=0, stdout="333\n")
                if args[:5] == ("shell", "dumpsys", "activity", "services",
                                "com.thorium.preview"):
                    return mock.Mock(returncode=0, stdout=services)
                if args[:4] == ("shell", "dumpsys", "activity", "processes"):
                    return mock.Mock(returncode=0, stdout=(
                        "* ProcessRecord{abc 333:com.thorium.preview:frontend_restart/u0a1}\n"
                        f"  {process_suffix}\n"
                    ))
                if args[:3] == ("shell", "cat", "/proc/333/oom_score_adj"):
                    return mock.Mock(returncode=0, stdout="950\n")
                self.fail(f"unexpected adb call: {args}")
            with mock.patch.object(MODULE.qa, "adb", side_effect=adb_result):
                return MODULE.bridge_process_state(
                    Path("/adb"), "serial", 333, base, windows
                )

        self.assertFalse(run(services="ServiceRecord pid=333")["bridgeProcessAcceptable"])
        self.assertFalse(run(process_suffix=(
            "curProcState=CACHED_EMPTY hasForegroundServices=true"
        ))["bridgeProcessAcceptable"])

    def test_bridge_chronology_rejects_wrong_pids_and_manual_relaunch(self):
        valid = "\n".join((
            "I/LucentImport( 333): Frontend restart bridge ready oldPid=111 "
            "bridgePid=333 resumed=true focused=true firstFrameDrawn=true",
            "I/LucentImport( 333): Frontend restart observed old process exit oldPid=111",
            "I/LucentImport( 333): Frontend restart bridge launching fresh Qt process attempt=1",
        ))
        proof = MODULE.bridge_reload_chronology(valid, 111, 222)
        self.assertEqual(proof["bridgePid"], 333)
        self.assertLess(proof["readyOffset"], proof["oldExitOffset"])
        self.assertLess(proof["oldExitOffset"], proof["launchOffset"])

        wrong = valid.replace("observed old process exit oldPid=111",
                              "observed old process exit oldPid=999")
        with self.assertRaisesRegex(RuntimeError, "PID/attempt mismatch"):
            MODULE.bridge_reload_chronology(wrong, 111, 222)
        wrong_logger = valid.replace(
            "I/LucentImport( 333): Frontend restart observed",
            "I/LucentImport( 444): Frontend restart observed",
        )
        with self.assertRaisesRegex(RuntimeError, "PID/attempt mismatch"):
            MODULE.bridge_reload_chronology(wrong_logger, 111, 222)
        with self.assertRaisesRegex(RuntimeError, "incomplete or ambiguous"):
            MODULE.bridge_reload_chronology(
                "I/ActivityManager( 222): Displayed MainActivity", 111, 222
            )

    def test_import_reload_waits_for_lifecycle_instead_of_fixed_sleep(self):
        old_activities = self._reload_activity_dump(
            main_token="mainold", preview_token="previewold"
        )
        requests = [
            {"state": "idle", "running": False, "updatedAt": 1},
            {"state": "scanning", "running": True, "updatedAt": 2},
            {"state": "complete", "running": False, "updatedAt": 3},
            {"ok": True},
        ]
        lifecycle = {"oldPid": 111, "newPid": 222, "stablePolls": 2}
        with mock.patch.object(MODULE, "import_service_request",
                               side_effect=requests), \
                mock.patch.object(MODULE, "main_process_pid", return_value=111), \
                mock.patch.object(MODULE.qa, "adb",
                                  return_value=mock.Mock(stdout=old_activities)), \
                mock.patch.object(MODULE.qa, "logs", return_value="baseline\n"), \
                mock.patch.object(MODULE, "timestamped_logs",
                                  return_value="baseline-timed\n"), \
                mock.patch.object(MODULE, "wait_frontend_reload",
                                  return_value=lifecycle) as wait, \
                mock.patch.object(MODULE.time, "sleep") as sleep:
            result = MODULE.wait_import_complete(
                Path("/adb"), "serial", timeout=1.0
            )
        self.assertEqual(result["reloadLifecycle"], lifecycle)
        wait.assert_called_once_with(
            Path("/adb"), "serial", 111, "previewold", "baseline\n",
            "baseline-timed\n"
        )
        sleep.assert_not_called()

    def test_import_scan_disconnect_then_status_complete_does_not_repost(self):
        old_activities = self._reload_activity_dump(
            main_token="mainold", preview_token="previewold"
        )
        requests = [
            {"state": "idle", "running": False, "updatedAt": 10},
            MODULE.http.client.RemoteDisconnected("closed after delivery"),
            {"state": "scanning", "running": True, "updatedAt": 11},
            {"state": "complete", "running": False, "updatedAt": 12},
            {"ok": False},
        ]
        with mock.patch.object(MODULE, "import_service_request",
                               side_effect=requests) as request, \
                mock.patch.object(MODULE, "main_process_pid", return_value=111), \
                mock.patch.object(MODULE.qa, "adb",
                                  return_value=mock.Mock(stdout=old_activities)), \
                mock.patch.object(MODULE.qa, "logs", return_value="baseline\n"), \
                mock.patch.object(MODULE, "timestamped_logs",
                                  return_value="baseline-timed\n"), \
                mock.patch.object(MODULE.time, "sleep"):
            result = MODULE.wait_import_complete(
                Path("/adb"), "serial", timeout=1.0
            )
        scan_posts = [call for call in request.call_args_list
                      if call.args[2] == "/import/scan"]
        self.assertEqual(len(scan_posts), 1)
        self.assertEqual(result["state"], "complete")
        self.assertFalse(result["reloadLifecycle"]["reloadRequested"])

    def test_import_scan_disconnect_never_recovers_times_out_without_post_storm(self):
        clock = {"now": 0.0}
        calls = {"status": 0, "scan": 0}

        def request(_adb, _serial, path, method="GET"):
            if path == "/import/status":
                calls["status"] += 1
                if calls["status"] == 1:
                    return {"state": "idle", "running": False,
                            "updatedAt": 20}
                raise MODULE.http.client.RemoteDisconnected("still unavailable")
            if path == "/import/scan" and method == "POST":
                calls["scan"] += 1
                raise MODULE.http.client.RemoteDisconnected("delivery unknown")
            self.fail(f"unexpected request {method} {path}")

        def sleep(seconds):
            clock["now"] += seconds

        with mock.patch.object(MODULE, "import_service_request",
                               side_effect=request), \
                mock.patch.object(MODULE.time, "monotonic",
                                  side_effect=lambda: clock["now"]), \
                mock.patch.object(MODULE.time, "sleep", side_effect=sleep):
            with self.assertRaisesRegex(RuntimeError,
                                        "import/scan did not complete"):
                MODULE.wait_import_complete(
                    Path("/adb"), "serial", timeout=1.0
                )
        self.assertEqual(calls["scan"], 1)
        self.assertGreaterEqual(calls["status"], 2)

    def test_import_scan_malformed_success_and_http_error_fail_immediately(self):
        idle = {"state": "idle", "running": False, "updatedAt": 30}
        with mock.patch.object(MODULE, "import_service_request",
                               side_effect=[idle, []]):
            with self.assertRaisesRegex(RuntimeError,
                                        "malformed successful import scan"):
                MODULE.wait_import_complete(
                    Path("/adb"), "serial", timeout=1.0
                )

        http_error = MODULE.urllib.error.HTTPError(
            "http://127.0.0.1/import/scan", 500, "application failure",
            hdrs=None, fp=None,
        )
        with mock.patch.object(MODULE, "import_service_request",
                               side_effect=[idle, http_error]):
            with self.assertRaises(MODULE.urllib.error.HTTPError):
                MODULE.wait_import_complete(
                    Path("/adb"), "serial", timeout=1.0
                )

    def test_import_scan_disconnect_then_malformed_status_fails_closed(self):
        idle = {"state": "idle", "running": False, "updatedAt": 40}
        with mock.patch.object(MODULE, "import_service_request", side_effect=[
                idle,
                MODULE.http.client.RemoteDisconnected("delivery unknown"),
                {"state": "not-a-real-state", "running": False},
        ]):
            with self.assertRaisesRegex(RuntimeError,
                                        "malformed successful import status"):
                MODULE.wait_import_complete(
                    Path("/adb"), "serial", timeout=1.0
                )

    def test_import_status_source_locks_every_state_and_running_invariant(self):
        active = {
            "permission", "scanning", "discovering", "identified",
            "transferring", "artwork", "video", "scores", "writing",
            "artless",
        }
        terminal = {"idle", "complete", "error"}
        self.assertEqual(MODULE.IMPORT_ACTIVE_STATES, active)
        self.assertEqual(MODULE.IMPORT_TERMINAL_STATES, terminal)
        self.assertEqual(MODULE.IMPORT_STATES, active | terminal)
        importer = (ROOT / "android-companion" / "src" / "com" / "thorium" /
                    "preview" / "ImportManager.java").read_text(encoding="utf-8")
        emitted = set(MODULE.re.findall(
            r'(?:setStatus|setDetailedStatus)\("([a-z]+)"', importer
        )) | {"idle"}
        self.assertEqual(emitted, MODULE.IMPORT_STATES)
        self.assertIn(
            'next.put("running", !"complete".equals(state) && '
            '!"error".equals(state) && !"idle".equals(state));',
            importer,
        )

        for state in sorted(active):
            accepted = MODULE.validated_import_status(
                {"state": state, "running": True}, "test status"
            )
            self.assertEqual(accepted["state"], state)
            with self.assertRaisesRegex(RuntimeError,
                                        "active state is not running"):
                MODULE.validated_import_status(
                    {"state": state, "running": False}, "test status"
                )
        for state in sorted(terminal):
            accepted = MODULE.validated_import_status(
                {"state": state, "running": False}, "test status"
            )
            self.assertEqual(accepted["state"], state)
            with self.assertRaisesRegex(RuntimeError,
                                        "terminal state is running"):
                MODULE.validated_import_status(
                    {"state": state, "running": True}, "test status"
                )
        with self.assertRaisesRegex(RuntimeError, "running flag"):
            MODULE.validated_import_status(
                {"state": "scanning"}, "test status"
            )
        with self.assertRaisesRegex(RuntimeError, "state='queued'"):
            MODULE.validated_import_status(
                {"state": "queued", "running": True}, "test status"
            )

    def test_import_waits_for_transferring_generation_before_new_scan(self):
        old_activities = self._reload_activity_dump(
            main_token="mainold", preview_token="previewold"
        )
        requests = [
            {"state": "transferring", "running": True, "updatedAt": 50},
            {"state": "complete", "running": False, "updatedAt": 51},
            {"state": "scanning", "running": True, "updatedAt": 52},
            {"state": "transferring", "running": True, "updatedAt": 53},
            {"state": "complete", "running": False, "updatedAt": 54},
            {"ok": False},
        ]
        with mock.patch.object(MODULE, "import_service_request",
                               side_effect=requests) as request, \
                mock.patch.object(MODULE, "main_process_pid", return_value=111), \
                mock.patch.object(MODULE.qa, "adb",
                                  return_value=mock.Mock(stdout=old_activities)), \
                mock.patch.object(MODULE.qa, "logs", return_value="baseline\n"), \
                mock.patch.object(MODULE, "timestamped_logs",
                                  return_value="baseline-timed\n"), \
                mock.patch.object(MODULE.time, "sleep"):
            result = MODULE.wait_import_complete(
                Path("/adb"), "serial", timeout=1.0
            )
        calls = request.call_args_list
        scan_positions = [i for i, call in enumerate(calls)
                          if call.args[2] == "/import/scan"]
        self.assertEqual(scan_positions, [2])
        self.assertEqual(calls[0].args[2], "/import/status")
        self.assertEqual(calls[1].args[2], "/import/status")
        self.assertEqual(result["state"], "complete")
        self.assertFalse(result["reloadLifecycle"]["reloadRequested"])

    def test_prior_active_import_cannot_regress_to_idle_and_retrigger(self):
        with mock.patch.object(MODULE, "import_service_request", side_effect=[
                {"state": "artwork", "running": True, "updatedAt": 60},
                {"state": "idle", "running": False, "updatedAt": 61},
        ]) as request:
            with self.assertRaisesRegex(RuntimeError,
                                        "became idle without a terminal"):
                MODULE.wait_import_complete(
                    Path("/adb"), "serial", timeout=1.0
                )
        self.assertFalse(any(call.args[2] == "/import/scan"
                             for call in request.call_args_list))

    def test_prior_active_error_is_bound_before_independent_scan(self):
        old_activities = self._reload_activity_dump(
            main_token="mainold", preview_token="previewold"
        )
        requests = [
            {"state": "transferring", "running": True, "updatedAt": 70},
            {"state": "error", "running": False, "updatedAt": 71,
             "message": "prior generation failed"},
            {"state": "discovering", "running": True, "updatedAt": 72},
            {"state": "complete", "running": False, "updatedAt": 73},
            {"ok": False},
        ]
        with mock.patch.object(MODULE, "import_service_request",
                               side_effect=requests) as request, \
                mock.patch.object(MODULE, "main_process_pid", return_value=111), \
                mock.patch.object(MODULE.qa, "adb",
                                  return_value=mock.Mock(stdout=old_activities)), \
                mock.patch.object(MODULE.qa, "logs", return_value="baseline\n"), \
                mock.patch.object(MODULE, "timestamped_logs",
                                  return_value="baseline-timed\n"), \
                mock.patch.object(MODULE.time, "sleep"):
            result = MODULE.wait_import_complete(
                Path("/adb"), "serial", timeout=1.0
            )
        scan_posts = [call for call in request.call_args_list
                      if call.args[2] == "/import/scan"]
        self.assertEqual(len(scan_posts), 1)
        self.assertEqual(result["state"], "complete")

    def test_embedded_theme_catalog_drives_menu_order(self):
        qml = b'''ListModel { id: systemCatalog
          ListElement { name: "ALL"; collectionName: ""; folder: "all" }
          ListElement { name: "NES"; collectionName: "NES"; folder: "nes" }
          ListElement { name: "N64"; collectionName: "N64"; folder: "n64" }
        }
        // Predecode official platform logotypes'''
        nested = io.BytesIO()
        with zipfile.ZipFile(nested, "w") as theme:
            theme.writestr("theme.qml", qml)
            theme.writestr("theme.cfg", b"name: test")
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        apk = Path(temporary.name) / "test.apk"
        with zipfile.ZipFile(apk, "w") as archive:
            archive.writestr("assets/pegasus-lucent-theme.zip", nested.getvalue())
        _qml, _cfg, order = MODULE.embedded_theme(apk)
        self.assertEqual(order, ["all", "nes", "n64"])

    def test_frozen_theme_digest_matches_current_product_source(self):
        theme = (ROOT / "theme" / "theme.qml").read_bytes()
        cfg = (ROOT / "theme" / "theme.cfg").read_bytes()
        self.assertEqual(hashlib.sha256(theme).hexdigest(),
                         MODULE.FROZEN_THEME_QML)
        self.assertEqual(hashlib.sha256(cfg).hexdigest(),
                         MODULE.FROZEN_THEME_CFG)

    def test_packaged_engine_identity_supports_libretro_and_native_adapter(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        apk = Path(temporary.name) / "engines.apk"
        with zipfile.ZipFile(apk, "w") as archive:
            archive.writestr(
                "lib/arm64-v8a/liblucent_core_azahar.so", b"azahar")
            archive.writestr(
                "lib/arm64-v8a/liblucent_native_adapter_eden.so", b"eden")
            archive.writestr(
                "lib/arm64-v8a/liblucent_native_adapter_cemu.so", b"cemu")
        self.assertEqual(hashlib.sha256(b"azahar").hexdigest(),
                         MODULE.packaged_engine_sha256(apk, "azahar"))
        self.assertEqual(hashlib.sha256(b"eden").hexdigest(),
                         MODULE.packaged_engine_sha256(apk, "eden"))
        self.assertEqual(hashlib.sha256(b"cemu").hexdigest(),
                         MODULE.packaged_engine_sha256(apk, "cemu"))

    def test_visible_order_uses_live_library_index_not_fixed_assumptions(self):
        # Exercise the ordering join without coupling the test to a device.
        matrix = MODULE.load_matrix(TOOLS / "runtime-acceptance-matrix.json")
        catalog = ["all", "nes", "megadrive", "gb", "n64"]
        active = {"systems": {"n64": {}, "nes": {}}}
        with unittest.mock.patch.object(MODULE, "embedded_theme",
                                        return_value=(b"", b"", catalog)):
            self.assertEqual(MODULE.visible_system_order(Path("x.apk"), active),
                             ["all", "nes", "n64"])
        self.assertGreater(len(matrix), 0)

    def test_catalog_display_names_map_folder_to_on_screen_name(self):
        qml = b'''ListModel { id: systemCatalog
          ListElement { name: "ALL"; collectionName: ""; folder: "all" }
          ListElement { name: "GAME BOY"; collectionName: "GB"; folder: "gb" }
          ListElement { name: "GAME BOY COLOR"; collectionName: "GBC"; folder: "gbc" }
          ListElement { name: "GAME BOY ADVANCE"; collectionName: "GBA"; folder: "gba" }
        }
        // Predecode official platform logotypes'''
        nested = io.BytesIO()
        with zipfile.ZipFile(nested, "w") as theme:
            theme.writestr("theme.qml", qml)
            theme.writestr("theme.cfg", b"name: test")
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        apk = Path(temporary.name) / "test.apk"
        with zipfile.ZipFile(apk, "w") as archive:
            archive.writestr("assets/pegasus-lucent-theme.zip", nested.getvalue())
        self.assertEqual(MODULE.catalog_display_names(apk), {
            "all": "all",
            "gb": "gameboy",
            "gbc": "gameboycolor",
            "gba": "gameboyadvance",
        })

    def test_resolve_list_folder_prefers_longest_display_name(self):
        names = {
            "gb": "gameboy",
            "gbc": "gameboycolor",
            "gba": "gameboyadvance",
            "n64": "nintendo64",
        }
        # The longest contained display name wins so "GAME BOY" never shadows
        # "GAME BOY ADVANCE".
        self.assertEqual(
            MODULE.resolve_list_folder("GAME BOY ADVANCE", names), "gba")
        self.assertEqual(MODULE.resolve_list_folder("GAME BOY", names), "gb")
        self.assertEqual(
            MODULE.resolve_list_folder("GAME BOY COLOR", names), "gbc")
        self.assertEqual(
            MODULE.resolve_list_folder("NINTENDO 64", names), "n64")
        # Unreadable / unknown headers do not resolve to any folder.
        self.assertIsNone(MODULE.resolve_list_folder("", names))
        self.assertIsNone(MODULE.resolve_list_folder("PLAYSTATION", names))

    def test_controller_axis_parser_accepts_thor_z_rz_pair(self):
        value = '''
          ABS_Z                : value 0, min -32768, max 32767, fuzz 0, flat 4096
          ABS_RZ               : value 0, min -32768, max 32767, fuzz 0, flat 4096
        '''
        axes = MODULE.PhysicalController.parse_axes(value)
        self.assertEqual(axes["ABS_Z"], (-32768, 32767, 0))
        self.assertEqual(axes["ABS_RZ"], (-32768, 32767, 0))

    def test_exact_quick_tap_parser_uses_kernel_edges(self):
        translated = """
          [ 1234.100000] /dev/input/event5: EV_KEY KEY_VOLUMEDOWN DOWN
          [ 1234.100020] /dev/input/event5: EV_SYN SYN_REPORT 00000000
          [ 1234.140100] /dev/input/event5: EV_KEY KEY_VOLUMEDOWN UP
          [ 1234.140120] /dev/input/event5: EV_SYN SYN_REPORT 00000000
        """
        proof = MODULE.parse_quick_key_edges(
            translated, MODULE.PhysicalController.VOLUME_DOWN
        )
        self.assertAlmostEqual(proof["holdMs"], 40.1, places=2)
        self.assertEqual(proof["downEventCount"], 1)
        self.assertEqual(proof["upEventCount"], 1)
        self.assertEqual(proof["repeatCount"], 0)

        raw = """
          [ 2000.000000] 0001 0073 00000001
          [ 2000.000010] 0000 0000 00000000
          [ 2000.039900] 0001 0073 00000000
          [ 2000.039910] 0000 0000 00000000
        """
        proof = MODULE.parse_quick_key_edges(
            raw, MODULE.PhysicalController.VOLUME_UP
        )
        self.assertAlmostEqual(proof["holdMs"], 39.9, places=2)

    def test_exact_quick_tap_parser_rejects_repeat_or_missing_up(self):
        repeated = """
          [ 1.000000] EV_KEY KEY_VOLUMEDOWN DOWN
          [ 1.500000] EV_KEY KEY_VOLUMEDOWN REPEAT
          [ 1.600000] EV_KEY KEY_VOLUMEDOWN UP
        """
        with self.assertRaises(RuntimeError):
            MODULE.parse_quick_key_edges(
                repeated, MODULE.PhysicalController.VOLUME_DOWN
            )
        with self.assertRaises(RuntimeError):
            MODULE.parse_quick_key_edges(
                "[ 1.000000] EV_KEY KEY_VOLUMEUP DOWN",
                MODULE.PhysicalController.VOLUME_UP,
            )

    def test_volume_gate_uses_one_device_script_and_kernel_timestamps(self):
        source = (TOOLS / "run_runtime_acceptance_qa.py").read_text(
            encoding="utf-8"
        )
        method = source.split("def exact_quick_key_pair", 1)[1].split(
            "\n    def ", 1
        )[0]
        self.assertIn('"shell", "getevent", "-lt"', method)
        self.assertIn('"shell", "sh"', method)
        self.assertIn("sleep {seconds:.3f}", method)
        self.assertIn("device_sleep_ms", method)
        self.assertIn("parse_quick_key_edges", method)
        gate = source.split("def quick_tap_volume_evidence", 1)[1].split(
            "\ndef run_system", 1
        )[0]
        self.assertIn("exact quick-tap volume evidence failed", gate)
        self.assertIn("volume_proof.verify_quick_pairs", gate)
        self.assertIn('calibration["holdMs"]', gate)
        self.assertNotIn(
            'controller.key(controller.VOLUME_DOWN, "physical-volume-down", hold=0.04)',
            gate,
        )

    def test_harness_has_no_direct_game_intent_or_virtual_navigation(self):
        source = (TOOLS / "run_runtime_acceptance_qa.py").read_text(encoding="utf-8")
        self.assertNotIn("LAUNCH_INTERNAL_GAME", source)
        self.assertNotIn('"input", "keyevent"', source)
        self.assertIn("sendevent", source)
        self.assertIn("physical-a-launch", source)
        self.assertIn("QtActivityDelegate.createSurface", source)
        self.assertIn("performResumeActivity com.thorium.preview displayId 0", source)
        self.assertIn("exactSelectionRestored", source)
        self.assertIn("Stop returned to a different library selection", source)
        self.assertIn("physical A did not reach the in-process launch interceptor", source)

    def test_stop_return_confirms_menu_move_before_opposite_restore_key(self):
        source = (TOOLS / "run_runtime_acceptance_qa.py").read_text(
            encoding="utf-8"
        )
        body = source.split("def stop_and_return", 1)[1].split(
            "\ndef ", 1
        )[0]
        down = body.index("for move_attempt in range(3)")
        confirmation = body.index("if move_confirmed:", down)
        restore = body.index('controller.UP, "dpad-up-restore"', confirmation)
        self.assertLess(down, confirmation)
        self.assertLess(confirmation, restore)
        self.assertIn("selected_header_ocr(moved)", body)
        self.assertIn("not selected_title_matches", body)
        self.assertIn("restore_deadline = time.monotonic() + 1.50", body)

    def test_wii_framegen_motion_uses_lateral_screen_space_sweep(self):
        source = (TOOLS / "run_runtime_acceptance_qa.py").read_text(
            encoding="utf-8"
        )
        worker = source.split("def sustain_physical_motion", 1)[1].split(
            "motion_thread =", 1
        )[0]
        wii = worker.split('if case.folder == "wii":', 1)[1].split(
            'elif case.folder == "switch":', 1
        )[0]
        self.assertIn("right_scale=0.30", wii)
        self.assertIn(
            'pattern = (("left", "right"), ("right", "left"))',
            worker,
        )

    def test_native_adapter_first_guest_frame_satisfies_only_exact_route(self):
        log = """
          LucentPhase3Engine: First guest frame engine=eden system=switch totalMs=15886
        """
        self.assertTrue(MODULE.has_presented_frame_telemetry(
            log, "eden", "switch"
        ))
        self.assertFalse(MODULE.has_presented_frame_telemetry(
            log, "eden", "wiiu"
        ))
        self.assertFalse(MODULE.has_presented_frame_telemetry(
            log, "cemu", "switch"
        ))

    def test_phase2_health_must_follow_the_exact_route(self):
        valid = "\n".join((
            "Health engine=azahar fps=59.8 frames=100",
            "In-window route accepted engine=azahar system=3ds activity=MainActivity",
            "Health engine=azahar fps=59.7 frames=200",
        ))
        self.assertTrue(MODULE.has_presented_frame_telemetry(
            valid, "azahar", "3ds"
        ))
        stale_only = "\n".join((
            "Health engine=azahar fps=59.8 frames=100",
            "In-window route accepted engine=azahar system=3ds activity=MainActivity",
        ))
        self.assertFalse(MODULE.has_presented_frame_telemetry(
            stale_only, "azahar", "3ds"
        ))

    def test_native_adapter_audio_playback_must_follow_the_exact_route(self):
        # Cemu and aPS3e export no measured-fps hook, so their engine-owned
        # guest-advance evidence is audio playback primed from adapter-drained
        # guest DSP samples — accepted only after the exact matching route.
        valid = "\n".join((
            "In-window route accepted engine=cemu system=wiiu activity=MainActivity",
            "Adapter audio playback started engine=cemu primedSamples=19200",
        ))
        self.assertTrue(MODULE.has_presented_frame_telemetry(
            valid, "cemu", "wiiu"
        ))
        stale_only = "\n".join((
            "Adapter audio playback started engine=cemu primedSamples=19200",
            "In-window route accepted engine=cemu system=wiiu activity=MainActivity",
        ))
        self.assertFalse(MODULE.has_presented_frame_telemetry(
            stale_only, "cemu", "wiiu"
        ))
        self.assertFalse(MODULE.has_presented_frame_telemetry(
            valid, "aps3e", "ps3"
        ))

    def test_aps3e_health_after_route_satisfies_presented_frame(self):
        valid = "\n".join((
            "In-window route accepted engine=aps3e system=ps3 activity=MainActivity",
            "Presentation health generator=1 role=primary displayId=0 "
            "lockedFps=40 outputFps=80",
        ))
        self.assertTrue(MODULE.has_presented_frame_telemetry(
            valid, "aps3e", "ps3"
        ))
        valid_base = "\n".join((
            "In-window route accepted engine=aps3e system=ps3 activity=MainActivity",
            "Presentation health base generator=1 role=primary displayId=0 "
            "lockedFps=40 outputFps=80",
        ))
        self.assertTrue(MODULE.has_presented_frame_telemetry(
            valid_base, "aps3e", "ps3"
        ))
        stale = "\n".join((
            "Presentation health base generator=1 role=primary displayId=0 "
            "lockedFps=40 outputFps=80",
            "In-window route accepted engine=aps3e system=ps3 activity=MainActivity",
        ))
        self.assertFalse(MODULE.has_presented_frame_telemetry(
            stale, "aps3e", "ps3"
        ))

    def test_slow_disc_boot_systems_get_extended_assisted_presented_wait(self):
        source = (TOOLS / "run_runtime_acceptance_qa.py").read_text(encoding="utf-8")
        self.assertIn('slow_disc_boot = case.folder in {"wiiu", "ps3"}', source)
        self.assertIn("timeout=360.0 if slow_disc_boot else 60.0", source)
        self.assertIn(
            'f"physical-advance-{case.folder}-boot-gate"',
            source,
        )

    def test_switch_waits_for_nvdec_and_recognized_navigation_before_proof(self):
        source = (TOOLS / "run_runtime_acceptance_qa.py").read_text(encoding="utf-8")
        self.assertIn(
            "switch_navigation = navigate_switch_to_gameplay(",
            source,
        )
        self.assertNotIn(
            'if case.folder in {"ps2", "psp", "wii", "windows", "switch"}:',
            source,
        )
        self.assertLess(
            source.index("switch_navigation = navigate_switch_to_gameplay("),
            source.index('"emufusion_framegen_proof", "1"'),
        )

    def test_switch_nvdec_lifecycle_requires_every_open_to_close(self):
        opened = MODULE.SWITCH_NVDEC_OPEN
        closed = MODULE.SWITCH_NVDEC_CLOSE
        self.assertEqual(MODULE.switch_nvdec_lifecycle(""), {
            "opened": 0, "closed": 0, "valid": True,
            "complete": False, "active": 0,
        })
        incomplete = MODULE.switch_nvdec_lifecycle(
            "\n".join((opened, opened, closed))
        )
        self.assertTrue(incomplete["valid"])
        self.assertFalse(incomplete["complete"])
        self.assertEqual(incomplete["active"], 1)
        complete = MODULE.switch_nvdec_lifecycle(
            "\n".join((opened, opened, closed, closed))
        )
        self.assertTrue(complete["valid"])
        self.assertTrue(complete["complete"])
        self.assertEqual(complete["active"], 0)
        malformed = MODULE.switch_nvdec_lifecycle(closed)
        self.assertFalse(malformed["valid"])

    def test_switch_screen_classifier_fails_closed_on_unknown_ui(self):
        self.assertEqual(MODULE.classify_switch_screen(
            "Game\nAccessibility\nAudio\nBack"
        ), "settings")
        self.assertEqual(MODULE.classify_switch_screen(
            "Press A to continue"
        ), "title-prompt")
        self.assertEqual(MODULE.classify_switch_screen(
            "Pilgrimage\nOptions\nCredits"
        ), "play-menu")
        self.assertEqual(MODULE.classify_switch_screen(
            "Save Slot 1\nEmpty Slot"
        ), "save-menu")
        self.assertEqual(MODULE.classify_switch_screen(
            "Start this pilgrimage?\nYes\nNo"
        ), "confirm-menu")
        self.assertEqual(MODULE.classify_switch_screen(
            "The Game Kitchen"
        ), "unknown")

    def test_switch_proof_motion_cannot_accept_menu_rows(self):
        source = (TOOLS / "run_runtime_acceptance_qa.py").read_text(
            encoding="utf-8"
        )
        proof = source.split("def sustain_physical_motion", 1)[1].split(
            "motion_thread =", 1
        )[0]
        branch = proof.split(
            'elif case.folder in {"switch", "wiiu", "nds"}:', 1
        )[1].split('elif case.folder == "ps2":', 1)[0]
        self.assertIn('hold=(3.5 if left == "left" else 1.2)', branch)
        self.assertNotIn("controller.A", branch)
        self.assertIn('"physical-switch-b-advance"', branch)
        self.assertNotIn("motion_pair", branch)

    def test_switch_navigation_trace_freezes_fail_closed_policy(self):
        source = (TOOLS / "run_runtime_acceptance_qa.py").read_text(
            encoding="utf-8"
        )
        navigation = source.split("def navigate_switch_to_gameplay", 1)[1].split(
            "def selected_title_matches", 1
        )[0]
        self.assertIn('if kind == "settings":', navigation)
        self.assertIn("controller.B", navigation)
        self.assertIn('elif kind == "title-prompt":', navigation)
        self.assertIn('kind in {"play-menu", "save-menu", "choice-menu"}',
                      navigation)
        self.assertIn('kind == "confirm-menu"', navigation)
        self.assertIn("refusing blind input", navigation)
        self.assertIn("prove_switch_gameplay_motion", navigation)
        self.assertIn("write_switch_navigation_trace", navigation)

    def test_switch_unknown_transition_waits_without_blind_input(self):
        source = (TOOLS / "run_runtime_acceptance_qa.py").read_text(
            encoding="utf-8"
        )
        wait = source.split(
            "def wait_switch_recognized_after_action", 1
        )[1].split("def navigate_switch_to_gameplay", 1)[0]
        self.assertIn('if kind != "unknown":', wait)
        self.assertIn("stable_count >= 2", wait)
        self.assertIn("no blind input was sent", wait)
        self.assertNotIn("controller.", wait)

        navigation = source.split(
            "def navigate_switch_to_gameplay", 1
        )[1].split("def selected_title_matches", 1)[0]
        self.assertIn('kind == "unknown" and play_selections == 0', navigation)
        self.assertIn("wait_switch_recognized_after_action", navigation)

    def test_psp_navigation_reaches_gameplay_before_framegen_proof(self):
        source = (TOOLS / "run_runtime_acceptance_qa.py").read_text(encoding="utf-8")
        self.assertIn('12 if case.folder in {"psp", "dreamcast"} else (', source)
        self.assertIn('case.folder in {"psp", "dreamcast"} and attempt % 2 == 0', source)
        self.assertLess(
            source.index('12 if case.folder in {"psp", "dreamcast"} else ('),
            source.index('"emufusion_framegen_proof", "1"'),
        )

    def test_playstation_navigation_uses_thor_odin_style_cross_not_circle(self):
        source = (TOOLS / "run_runtime_acceptance_qa.py").read_text(
            encoding="utf-8"
        )
        navigation = source.split(
            '# Cold first launches for these systems', 1
        )[1].split('real_nes_readiness =', 1)[0]
        self.assertIn('case.folder in {"ps2", "psp", "dreamcast"}', navigation)
        self.assertIn('controller.B if case.folder in {"ps2", "psp", "dreamcast"}', navigation)

        motion = source.split("def sustain_physical_motion", 1)[1].split(
            "motion_thread =", 1
        )[0]
        # PS2 proof motion is a continuously held forward stick (GTA III
        # street traversal, Thor 2026-08-15); buttons are never pressed
        # during proof. PSP keeps the Cross action.
        ps2_branch = motion.split('elif case.folder == "ps2":', 1)[1].split(
            "else:", 1
        )[0]
        self.assertIn('controller.motion_pair(left, right, hold=2.0)',
                      ps2_branch)
        self.assertIn('"physical-cross-ps2-sprint"', ps2_branch)
        self.assertIn('action_key = (controller.B if case.folder in {"psp", "ps3"}',
                      motion)
        self.assertIn('controller.key(action_key, action_label', motion)
        self.assertIn('"physical-cross-gameplay-action"', motion)

    def test_ps3_collection_uses_cross_not_circle(self):
        source = (TOOLS / "run_runtime_acceptance_qa.py").read_text(
            encoding="utf-8"
        )
        run = source.split("def run_game_from_system_menu", 1)[1].split(
            "def main_activity_surface_layers", 1
        )[0]
        marker = 'skip_label="physical-cross-ps3"'
        self.assertIn(marker, run)
        start = run.index(marker)
        ps3_wait = run[max(0, start - 800): start + 1200]
        self.assertIn("confirm_key=controller.B", ps3_wait)
        self.assertIn(
            'skip_cycle=(controller.B, controller.START, "left")', ps3_wait
        )
        self.assertIn("loop_cycle=(controller.B,)", ps3_wait)
        self.assertIn("timeout=1080.0", ps3_wait)
        self.assertIn("motion_min=0.0", ps3_wait)
        self.assertIn("use_best_windows=True", ps3_wait)
        self.assertIn("min_structure=8.0", ps3_wait)
        self.assertIn("prefix, -1, presented_path,", run)
        self.assertNotIn("confirm_key=controller.A", ps3_wait)
        self.assertNotIn("loop_cycle=(controller.A,)", ps3_wait)
        self.assertNotIn("loop_cycle=(controller.B, controller.START)", ps3_wait)
        self.assertIn(
            'boot_key = controller.B if case.folder == "ps3"', run
        )

    def test_ps2_proof_waits_for_title_departure_and_sustained_gameplay(self):
        # Physical recalibration 2026-08-15 (Thor, God of War, schema-39
        # checkpoint): the emulated PS2 scans out continuously near 60 Hz, so
        # the historical movie-dip phase never occurs. Title departure is
        # proven with screenshot differences; proof arming further requires
        # sustained trailing >=50-tier windows plus live inter-probe motion.
        def health(presents, producer, locked, output):
            return (
                "I/EmuFusionFrameGen( 321): Presentation health generator=1 "
                "role=primary displayId=0 proofContract=legacy "
                f"presents={presents} generated=0 real=0 promoted=0 "
                f"submitted=0 producerHz={producer:.2f} "
                f"lockedFps={locked} outputFps={output} panelFps=120\n"
            )

        baseline = health(120, 60.0, 60, 120)
        movie = health(240, 30.0, 30, 60)
        first_gameplay = health(360, 59.9, 60, 120)
        second_gameplay = health(480, 59.9, 60, 120)
        self.assertEqual("boot", MODULE.ps2_navigation_cadence_phase(
            baseline + movie, 120
        ))
        self.assertEqual("title-ready", MODULE.ps2_navigation_cadence_phase(
            baseline + first_gameplay + second_gameplay, 120
        ))
        # Title cadence stays sticky across a later low-tier window; there is
        # no longer any cadence-only "movie-started" phase.
        self.assertEqual("title-ready", MODULE.ps2_navigation_cadence_phase(
            baseline + first_gameplay + second_gameplay + movie, 120
        ))
        # Trailing stable-tier windows only count windows newer than the
        # baseline; every supported tier (20-60) qualifies as long as the
        # producer actually supports the locked tier, and an unsupported
        # window resets the trailing count.
        unstable = health(600, 31.0, 60, 120)
        self.assertEqual(0, MODULE.ps2_sustained_gameplay_windows(
            baseline, 120
        ))
        self.assertEqual(0, MODULE.ps2_sustained_gameplay_windows(
            baseline + first_gameplay + unstable, 120
        ))
        self.assertEqual(3, MODULE.ps2_sustained_gameplay_windows(
            baseline + movie + first_gameplay + second_gameplay, 120
        ))
        self.assertEqual(2, MODULE.ps2_sustained_gameplay_windows(
            baseline + unstable + first_gameplay + second_gameplay, 120
        ))
        drop = health(600, 15.0, 15, 15)
        self.assertEqual(0, MODULE.ps2_sustained_gameplay_windows(
            baseline + first_gameplay * 10 + drop, 120
        ))
        self.assertEqual(10, MODULE.ps2_best_gameplay_windows(
            baseline + first_gameplay * 10 + drop, 120
        ))
        self.assertGreaterEqual(MODULE.PS2_SUSTAINED_GAMEPLAY_WINDOWS, 8)
        self.assertGreater(MODULE.PS2_TITLE_DEPARTURE_MEAN_DIFF, 0.0)
        self.assertGreater(MODULE.PS2_LIVE_MOTION_MEAN_DIFF, 0.0)

        source = (TOOLS / "run_runtime_acceptance_qa.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("drive_ps2_title_past_title_menu(", source)
        self.assertIn("screenshot_mean_abs_diff(", source)
        self.assertIn("interProbeMotionMeanDiff", source)
        # The PS2 flow drives GTA III deterministically: one Cross at
        # title-ready, bounded spaced Cross presses for New Game and
        # cutscene skipping, then proof arms only on a sustained stable
        # tier with BRIGHT fast inter-probe motion from held-forward
        # traversal — the brightness floor keeps proof off dark
        # transitions, which physically starved the dense vector gates on
        # every attract/cinematic candidate.
        self.assertIn('"physical-cross-ps2-title-menu"', source)
        self.assertIn('skip_label: str = "physical-cross-ps2"', source)
        self.assertIn('f"{skip_label}-menu-or-skip-', source)
        self.assertIn("motion >= motion_min", source)
        self.assertIn("motion_min = PS2_ATTRACT_MOTION_MEAN_DIFF", source)
        self.assertGreater(MODULE.PS2_ATTRACT_MOTION_MEAN_DIFF,
                           MODULE.PS2_LIVE_MOTION_MEAN_DIFF)
        self.assertLess(
            source.index("wait_ps2_post_cinematic_gameplay("),
            source.index('"emufusion_framegen_proof", "1"'),
        )

        # Scene-content starvation may recollect on a later scene; any other
        # failure class in the same rejection must raise immediately.
        def gate_message(failures):
            return (
                "frame-generation gate needs one uniquely strongest primary "
                "gameplay layer; passed=0 rejected=[{'layer': "
                "'SurfaceView[com.thorium.preview/x](BLAST)#1', 'latency': "
                "'/tmp/latency.txt', 'role': 'primary', 'displayId': 0, "
                f"'failures': {failures!r}}}]"
            )

        self.assertTrue(MODULE._is_content_starved_framegen_failure(
            gate_message(["too few genuinely changing pixels were sampled",
                          "too few changing pixels have a confident selected "
                          "motion vector"])
        ))
        self.assertFalse(MODULE._is_content_starved_framegen_failure(
            gate_message(["too few genuinely changing pixels were sampled",
                          "presented cadence below the 96% threshold"])
        ))
        self.assertFalse(MODULE._is_content_starved_framegen_failure(
            "dense proof atlas reported errors"
        ))
        self.assertTrue(MODULE._is_content_starved_framegen_failure(
            "timed out waiting for a current >=11-second frame-generation "
            "steady tier: primary/display-0 current tier is not steady for "
            "11 seconds"
        ))
        self.assertIn(
            '"nds", "n3ds", "dreamcast", "ps3"',
                      source)
        self.assertTrue(MODULE._is_content_starved_framegen_failure(
            "frame-generation gate needs one uniquely strongest primary "
            "gameplay layer; passed=0 rejected=[{'failures': "
            "['primary/display-0 has no latency-overlapping real "
            ">=11-second steady tier']}]"
        ))

    def test_wii_title_uses_a_b_but_motion_window_uses_mapped_a_in_safe_ir(self):
        source = (TOOLS / "run_runtime_acceptance_qa.py").read_text(encoding="utf-8")
        proof = source.split("def sustain_physical_motion", 1)[1].split(
            "motion_thread =", 1
        )[0]
        self.assertIn('if case.folder == "wii":', proof)
        self.assertIn('(controller.A, controller.B)', source)
        self.assertIn('chord_codes=(controller.B,)', proof)
        self.assertNotIn('chord_codes=(controller.A, controller.B)', proof)
        self.assertIn('"physical-wii-a-gameplay-action"', proof)
        self.assertIn('right_scale=0.30', proof)

    def test_wii_launch_aims_slot_and_play_instead_of_repeating_cancel_chord(self):
        source = (TOOLS / "run_runtime_acceptance_qa.py").read_text(
            encoding="utf-8"
        )
        navigation = source.split(
            'if case.folder in {"psp", "wii", "windows", "dreamcast", "wiiu"}:', 1
        )[1].split('ps2_gameplay_readiness =', 1)[0]
        self.assertIn('if attempt == 0:', navigation)
        self.assertIn('(controller.A, controller.B)', navigation)
        self.assertIn('visible, prompt_text = wii_galaxy_title_prompt(', navigation)
        self.assertIn('prompt_deadline = time.monotonic() + 25.0', navigation)
        self.assertIn('time.monotonic() + 12.0', navigation)
        self.assertIn('if not prompt_seen or not prompt_cleared:', navigation)
        self.assertIn('visible = True', navigation)
        self.assertIn('1 if case.folder == "wii" else 3', navigation)
        self.assertIn('(-0.28, 0.11, "physical-wii-a-select-save-slot-1")', navigation)
        self.assertIn('(0.27, -0.10, "physical-wii-a-confirm-or-create-yes")', navigation)
        self.assertIn('(-0.55, 0.18, "physical-wii-a-select-mario-icon")', navigation)
        self.assertIn('(0.27, -0.10, "physical-wii-a-confirm-mario-icon")', navigation)
        self.assertIn('"physical-wii-a-play-file"', navigation)
        self.assertIn('time.sleep(3.0)', navigation)
        self.assertIn('if case.folder == "wii":', navigation)
        self.assertIn('for page in range(24):', navigation)
        self.assertIn('"physical-wii-a-story-or-gameplay-', navigation)
        self.assertLess(
            navigation.index('"physical-wii-a-play-file"'),
            navigation.index('for page in range(24):'),
        )

    def test_framegen_keeps_retained_and_new_surface_candidates(self):
        source = (TOOLS / "run_runtime_acceptance_qa.py").read_text(
            encoding="utf-8"
        )
        body = source.split("def frame_generation_evidence(", 1)[1].split(
            "def run_title", 1
        )[0]
        self.assertIn("new_layers = [layer for layer in after_layers", body)
        self.assertIn("layers = list(after_layers)", body)
        self.assertIn("_unique_strongest_framegen_candidate(", body)
        self.assertNotIn("exactly one newly-created", body)

    def test_framegen_candidate_requires_unique_strongest_raw_overlap(self):
        candidate = lambda role, display, overlap: {
            "role": role, "displayId": display,
            "surfaceFlingerRawOverlapFrames": overlap,
        }
        rows = [
            ("old", Path("old"), candidate("primary", 0, 103)),
            ("new", Path("new"), candidate("primary", 0, 99)),
        ]
        selected = MODULE._unique_strongest_framegen_candidate(
            rows, "primary", 0)
        self.assertEqual(selected[0], "old")
        rows[1][2]["surfaceFlingerRawOverlapFrames"] = 103
        self.assertIsNone(MODULE._unique_strongest_framegen_candidate(
            rows, "primary", 0))

    def test_lower_touch_motion_runs_during_dual_screen_proof(self):
        source = (TOOLS / "run_runtime_acceptance_qa.py").read_text(encoding="utf-8")
        proof = source.split("def frame_generation_evidence", 1)[1]
        self.assertIn("if case.lower_touch:", proof)
        self.assertIn("inject_lower_motion(adb, serial, lower_phase)", proof)
        self.assertIn('"touchscreen", "-d", "4"', source)

    def test_ds_and_3ds_leave_black_attract_state_before_proof(self):
        source = (TOOLS / "run_runtime_acceptance_qa.py").read_text(
            encoding="utf-8"
        )
        navigation = source.split(
            "def navigate_handheld_dual_screen_to_visible_ui", 1
        )[1].split("\ndef ", 1)[0]
        self.assertIn('case.folder not in {"nds", "n3ds"}', navigation)
        self.assertIn("controller.START", navigation)
        self.assertIn("controller.A", navigation)
        self.assertIn("consecutive_visible >= 2", navigation)
        self.assertIn("secondary_token(adb, serial)", navigation)
        run = source.split("def run_game_from_system_menu", 1)[1].split(
            "def main_activity_surface_layers", 1
        )[0]
        navigation_call = run.index(
            "navigate_handheld_dual_screen_to_visible_ui("
        )
        proof_call = run.index("frame_generation_evidence(")
        self.assertLess(navigation_call, proof_call)
        self.assertIn('"dualGameplayNavigation": dual_gameplay_navigation', run)

    def test_dual_navigation_requires_two_visible_lower_frames(self):
        class Controller:
            START = 315
            A = 304

            def __init__(self):
                self.events = []

            def key(self, code, label, hold):
                self.events.append((code, label, hold))

        case = MODULE.SystemCase(
            "n3ds", ("n3ds", "3ds"), ("azahar",), 2,
            dual_screen=True, lower_touch=True,
        )
        controller = Controller()
        frames = iter((
            {"visible": False},
            {"visible": True},
            {"visible": True},
        ))
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        with mock.patch.object(MODULE, "secondary_token", return_value="local:4"), \
                mock.patch.object(MODULE, "screenshot",
                                  side_effect=lambda *_args: next(frames)), \
                mock.patch.object(MODULE.time, "sleep"):
            report = MODULE.navigate_handheld_dual_screen_to_visible_ui(
                Path("adb"), "serial", controller, case,
                Path(temporary.name), "n3ds-title-01",
            )
        self.assertEqual(report["rounds"], 3)
        self.assertEqual(report["consecutiveVisibleFrames"], 2)
        self.assertEqual(report["physicalControls"], ["START", "A"])
        self.assertEqual([event[0] for event in controller.events],
                         [315, 304, 315, 304, 315, 304])

    def test_nds_hunters_driver_taps_touch_to_start_and_skip(self):
        source = (TOOLS / "run_runtime_acceptance_qa.py").read_text(
            encoding="utf-8"
        )
        run = source.split("def run_game_from_system_menu", 1)[1].split(
            "def main_activity_surface_layers", 1
        )[0]
        self.assertIn("drive_nds_hunters_past_touch_menus(", run)
        self.assertLess(
            run.index("navigate_handheld_dual_screen_to_visible_ui("),
            run.index("drive_nds_hunters_past_touch_menus("),
        )
        self.assertLess(
            run.index("drive_nds_hunters_past_touch_menus("),
            run.index("frame_generation_evidence("),
        )
        self.assertIn('"ndsNavigation": nds_navigation', run)
        self.assertIn('case.folder == "nds"', run)
        self.assertIn('"nds", "n3ds", "dreamcast", "ps3"', run)
        self.assertEqual(MODULE.NDS_HUNTERS_TOUCH_TO_START, (620, 563))
        self.assertEqual(MODULE.NDS_HUNTERS_SKIP, (1193, 1032))
        self.assertIn(MODULE.NDS_HUNTERS_TOUCH_TO_START,
                      MODULE.NDS_HUNTERS_MENU_TAPS)
        self.assertIn(MODULE.NDS_HUNTERS_SKIP, MODULE.NDS_HUNTERS_MENU_TAPS)

        class Controller:
            START = 315
            A = 304

            def __init__(self):
                self.events = []

            def key(self, code, label, hold):
                self.events.append((code, label, hold))

        taps = []

        def fake_tap(adb, serial, x, y, hold_ms=180):
            taps.append((x, y, hold_ms))

        controller = Controller()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        with mock.patch.object(MODULE, "secondary_token", return_value="local:4"), \
                mock.patch.object(MODULE, "inject_display4_tap", side_effect=fake_tap), \
                mock.patch.object(MODULE, "screenshot",
                                  return_value={"visible": True}), \
                mock.patch.object(MODULE.time, "sleep"):
            report = MODULE.drive_nds_hunters_past_touch_menus(
                Path("adb"), "serial", controller,
                Path(temporary.name), "nds-title-01",
            )
        self.assertEqual(report["touchToStart"], [620, 563])
        self.assertEqual(report["skip"], [1193, 1032])
        self.assertEqual(report["rounds"], 10)
        self.assertEqual(taps[0][:2], (620, 563))
        self.assertIn((1193, 1032), {point[:2] for point in taps})
        self.assertTrue(controller.events)

    def test_preproof_schema22_is_not_a_steady_qualification_run(self):
        ready = [self._segment_health(index) for index in range(1, 14)]
        for row in ready:
            row["proof_schema_version"] = 22
        clock = [0.0]

        def advance(delay):
            clock[0] += delay

        with mock.patch.object(
                MODULE, "_framegen_health_records", return_value=ready), \
                mock.patch.object(MODULE.time, "monotonic",
                                  side_effect=lambda: clock[0]), \
                mock.patch.object(MODULE.time, "sleep", side_effect=advance):
            with self.assertRaisesRegex(
                    RuntimeError, "not a qualification proof schema"):
                MODULE._wait_for_current_framegen_steady(
                    lambda: "schema22-log", [("primary", 0)],
                    deadline=0.05, poll_seconds=0.1,
                )

    def test_handheld_primary_two_x_requires_locked_times_two(self):
        records = [self._segment_health(index) for index in range(1, 14)]
        for row in records:
            row["output"] = int(row["locked"]) * 2
        with mock.patch.object(
                MODULE, "_framegen_health_records", return_value=records):
            report = MODULE.handheld_primary_two_x_evidence("primary-log")
        self.assertTrue(report["passed"])
        self.assertEqual(report["lockedFps"], 60)
        self.assertEqual(report["outputFps"], 120)
        self.assertTrue(report["handheldPrimaryTwoX"])
        for row in records:
            row["output"] = 90
        with mock.patch.object(
                MODULE, "_framegen_health_records", return_value=records):
            with self.assertRaisesRegex(RuntimeError, "not 2x"):
                MODULE.handheld_primary_two_x_evidence("bad-log")

    def test_handheld_primary_two_x_accepts_nds10_device_log(self):
        path = (ROOT / "unified-android" / "build" /
                "runtime-acceptance-qa-2026-08-16-nds10" /
                "nds-title-01-framegen-logcat.txt")
        if not path.is_file():
            self.skipTest("nds10 device log is not on disk")
        report = MODULE.handheld_primary_two_x_evidence(
            path.read_text(encoding="utf-8", errors="replace")
        )
        self.assertTrue(report["passed"])
        self.assertIn(report["lockedFps"], {20, 30, 40, 50, 60})
        self.assertEqual(report["outputFps"], int(report["lockedFps"]) * 2)

    def test_ps3_accepts_any_primary_two_x_segment(self):
        two_x = [self._segment_health(index, locked=20) for index in range(1, 15)]
        for row in two_x:
            row["output"] = 40
        drop = [self._segment_health(index, locked=15) for index in range(15, 21)]
        for row in drop:
            row["output"] = 15
        records = two_x + drop
        with mock.patch.object(
                MODULE, "_framegen_health_records", return_value=records):
            with self.assertRaisesRegex(RuntimeError, "not steady"):
                MODULE.handheld_primary_two_x_evidence("trailing-drop")
            report = MODULE.primary_two_x_any_segment("any-segment")
        self.assertTrue(report["passed"])
        self.assertEqual(report["lockedFps"], 20)
        self.assertEqual(report["outputFps"], 40)
        self.assertTrue(report["primaryTwoXAnySegment"])
        source = (TOOLS / "run_runtime_acceptance_qa.py").read_text(
            encoding="utf-8"
        )
        evidence = source.split("def frame_generation_evidence", 1)[1]
        self.assertIn('if case.folder == "ps3":', evidence)
        self.assertIn("primary_two_x_any_segment(", evidence)

    def test_handheld_dual_screen_qualifies_on_primary_plus_identity(self):
        source = (TOOLS / "run_runtime_acceptance_qa.py").read_text(
            encoding="utf-8"
        )
        evidence = source.split("def frame_generation_evidence", 1)[1]
        self.assertIn('case.folder not in {"nds", "n3ds"}', evidence)
        self.assertIn("secondaryIdentityOnly", evidence)
        self.assertLess(
            evidence.index('case.dual_screen and case.folder in {"nds", "n3ds"}'),
            evidence.index("uniquely strongest secondary"),
        )

    def test_proof_switch_is_clean_before_and_after_every_title(self):
        source = (TOOLS / "run_runtime_acceptance_qa.py").read_text(encoding="utf-8")
        run = source.split("def run_game_from_system_menu", 1)[1].split(
            "def main_activity_surface_layers", 1
        )[0]
        clear = '"settings", "delete", "global",'
        arm = ('"settings", "put", "global",\n'
               '           "emufusion_framegen_proof", "1"')
        launch = 'controller.key(controller.A, "physical-a-launch"'
        self.assertLess(run.index(clear), run.index(launch))
        self.assertLess(run.index(arm),
                        run.index("generated = frame_generation_evidence("))
        # Proof is armed exactly once BEFORE the scene-retry loop (per-attempt
        # re-arming trips the verifier's exactly-once generator-proof
        # contract) and cleared once in the finally block so no following
        # title inherits proof state.
        collection = run.split("scene_attempts = 7", 1)[1].split(
            "n64_runtime =", 1
        )[0]
        self.assertIn(arm, collection)
        self.assertLess(collection.index(arm),
                        collection.index("for scene_attempt in range("))
        finally_block = collection.split("finally:", 1)[1]
        self.assertIn(clear, finally_block)
        self.assertIn('"emufusion_framegen_proof"', finally_block)

    def test_motion_worker_is_always_stopped_after_capture_failure(self):
        source = (TOOLS / "run_runtime_acceptance_qa.py").read_text(encoding="utf-8")
        framegen = source.split("def frame_generation_evidence", 1)[1].split(
            "def _music_volume", 1
        )[0]
        capture = framegen.split("motion_thread.start()", 1)[1].split(
            "report_path =", 1
        )[0]
        self.assertIn("try:", capture)
        self.assertIn("finally:", capture)
        self.assertIn("motion_stop.set()", capture)
        self.assertIn("motion_thread.join(timeout=2.0)", capture)

    @staticmethod
    def _segment_health(sequence, *, locked=60, pid=123, generator=1):
        end = sequence * 1_000_000_000
        return {
            "pid": pid, "generator": generator, "locked": locked,
            "health_sequence": sequence,
            "window_start_ns": end - 1_000_000_000,
            "window_end_ns": end,
            "proof": sequence * 3,
        }

    def test_framegen_segment_rejects_historical_run_rolled_out_of_sf_ring(self):
        records = [self._segment_health(index) for index in range(1, 14)]
        records.extend(self._segment_health(index, locked=50)
                       for index in range(14, 16))
        records.extend(self._segment_health(index)
                       for index in range(16, 23))
        timestamps = [21_900_000_000 + index * 700_000 for index in range(128)]
        with self.assertRaisesRegex(RuntimeError, "no latency-overlapping"):
            MODULE._steady_framegen_segment(
                records, "primary", 0,
                actual_present_timestamps=timestamps,
            )

    def test_framegen_segment_waits_past_late_transient_and_binds_new_suffix(self):
        records = [self._segment_health(index) for index in range(1, 14)]
        records.extend(self._segment_health(index, locked=50)
                       for index in range(14, 16))
        records.extend(self._segment_health(index)
                       for index in range(16, 29))
        timestamps = [27_900_000_000 + index * 700_000 for index in range(128)]
        segment, end = MODULE._steady_framegen_segment(
            records, "primary", 0,
            actual_present_timestamps=timestamps,
        )
        self.assertEqual(segment["proofBaselineWindowEndNs"], 16_000_000_000)
        self.assertEqual(segment["endWindowEndNs"], 28_000_000_000)
        self.assertEqual(end["health_sequence"], 28)

    def test_framegen_segment_keeps_legacy_and_schema36_runs_partitioned(self):
        legacy = [self._segment_health(index) for index in range(1, 14)]
        segment, _end = MODULE._steady_framegen_segment(
            legacy, "primary", 0)
        self.assertNotIn("expectedPresentationEpoch", segment)

        mixed = [dict(self._segment_health(1), proof_schema_version=36,
                      window_presentation_epoch=7,
                      proof_evidence_presentation_epoch=7)]
        mixed.extend(self._segment_health(index) for index in range(2, 15))
        segment, _end = MODULE._steady_framegen_segment(
            mixed, "primary", 0)
        self.assertEqual(segment["proofBaselineWindowEndNs"], 2_000_000_000)
        self.assertNotIn("expectedPresentationEpoch", segment)

        strict = [self._segment_health(1)]
        strict.extend(dict(self._segment_health(index),
                           proof_schema_version=36,
                           window_presentation_epoch=8,
                           proof_evidence_presentation_epoch=8)
                      for index in range(2, 15))
        segment, _end = MODULE._steady_framegen_segment(
            strict, "primary", 0)
        self.assertEqual(segment["proofBaselineWindowEndNs"], 2_000_000_000)
        self.assertEqual(segment["expectedPresentationEpoch"], 8)

    def test_v37_segment_starts_after_last_unbuffered_output_slot(self):
        records = []
        for sequence in range(1, 20):
            record = dict(
                self._segment_health(sequence),
                proof_schema_version=37,
                window_presentation_epoch=51,
                proof_evidence_presentation_epoch=51,
                window_due_no_endpoint=4 if sequence == 4 else 0,
                window_presents=90 if sequence == 4 else 120,
                output=120,
            )
            records.append(record)
        segment, end = MODULE._steady_framegen_segment(
            records, "primary", 0)
        self.assertEqual(segment["proofBaselineWindowEndNs"], 4_000_000_000)
        self.assertEqual(segment["endWindowEndNs"], 19_000_000_000)
        self.assertEqual(end["health_sequence"], 19)

        # The same epoch is not ready until a full clean suffix exists.
        with self.assertRaisesRegex(RuntimeError, "not steady for 11 seconds"):
            MODULE._steady_framegen_segment(records[:14], "primary", 0)

    def test_v38_segment_keeps_healthy_source_wait_inside_steady_run(self):
        records = []
        for sequence in range(1, 17):
            record = dict(
                self._segment_health(sequence),
                proof_schema_version=38,
                window_presentation_epoch=87,
                proof_evidence_presentation_epoch=87,
                window_due_no_endpoint=1 if sequence in (5, 12) else 0,
                window_presents=120,
                output=120,
            )
            # Exact r57 shape: one extra physical callback makes the window
            # slightly longer, but 120 successful swaps still clear 96%.
            if sequence in (5, 12):
                record["window_start_ns"] = (
                    record["window_end_ns"] - 1_009_000_000
                )
            records.append(record)
        segment, end = MODULE._steady_framegen_segment(
            records, "primary", 0)
        self.assertEqual(segment["proofBaselineWindowEndNs"], 1_000_000_000)
        self.assertEqual(end["health_sequence"], 16)

    def test_framegen_segment_rejects_ambiguous_equal_raw_overlap(self):
        records = [self._segment_health(index) for index in range(1, 15)]
        timestamps = (
            [12_100_000_000 + index * 10_000_000 for index in range(62)] +
            [13_100_000_000 + index * 10_000_000 for index in range(62)]
        )
        with self.assertRaisesRegex(RuntimeError, "overlap is ambiguous"):
            MODULE._steady_framegen_segment(
                records, "primary", 0,
                actual_present_timestamps=timestamps,
            )

    def test_framegen_latency_capture_accepts_one_active_layer_per_stream(self):
        stale = Path("stale-primary.txt")
        active = Path("active-primary.txt")
        records = [
            ("stale-surface", stale, "primary", 0),
            ("active-surface", active, "primary", 0),
        ]
        with mock.patch.object(
                MODULE.frame_gen, "parse_latency",
                side_effect=[{"actualPresentTimestamps": [1]},
                             {"actualPresentTimestamps": [2]}]), \
                mock.patch.object(MODULE, "_framegen_health_records",
                                  return_value=[{"health_sequence": 1}]), \
                mock.patch.object(
                    MODULE, "_steady_framegen_segment",
                    side_effect=[RuntimeError("stale layer"), ({}, {})]):
            MODULE._require_latency_coverage_for_streams(
                "captured", records, [("primary", 0)])

    def test_framegen_latency_capture_requires_each_display_not_every_layer(self):
        records = [
            ("active-primary", Path("primary.txt"), "primary", 0),
            ("stale-secondary", Path("secondary-old.txt"), "secondary", 4),
            ("active-secondary", Path("secondary.txt"), "secondary", 4),
        ]
        with mock.patch.object(
                MODULE.frame_gen, "parse_latency",
                side_effect=[{"actualPresentTimestamps": [1]},
                             {"actualPresentTimestamps": [2]},
                             {"actualPresentTimestamps": [3]}]), \
                mock.patch.object(MODULE, "_framegen_health_records",
                                  return_value=[{"health_sequence": 1}]), \
                mock.patch.object(
                    MODULE, "_steady_framegen_segment",
                    side_effect=[({}, {}), RuntimeError("stale layer"),
                                 ({}, {})]):
            MODULE._require_latency_coverage_for_streams(
                "captured", records, [("primary", 0), ("secondary", 4)])

        with mock.patch.object(
                MODULE.frame_gen, "parse_latency",
                side_effect=[{"actualPresentTimestamps": [1]},
                             {"actualPresentTimestamps": [2]},
                             {"actualPresentTimestamps": [3]}]), \
                mock.patch.object(MODULE, "_framegen_health_records",
                                  return_value=[{"health_sequence": 1}]), \
                mock.patch.object(
                    MODULE, "_steady_framegen_segment",
                    side_effect=[({}, {}), RuntimeError("stale layer"),
                                 RuntimeError("stale layer")]):
            with self.assertRaisesRegex(
                    RuntimeError,
                    "secondary/display-4"):
                MODULE._require_latency_coverage_for_streams(
                    "captured", records,
                    [("primary", 0), ("secondary", 4)])

    def test_framegen_current_steady_poll_is_bounded_and_can_recover(self):
        insufficient = [self._segment_health(index) for index in range(1, 5)]
        ready = [self._segment_health(index) for index in range(1, 14)]
        clock = [0.0]

        def advance(delay):
            clock[0] += delay

        with mock.patch.object(
                MODULE, "_framegen_health_records",
                side_effect=[insufficient, ready]), \
                mock.patch.object(MODULE.time, "monotonic",
                                  side_effect=lambda: clock[0]), \
                mock.patch.object(MODULE.time, "sleep", side_effect=advance):
            self.assertEqual(MODULE._wait_for_current_framegen_steady(
                lambda: "ready-log", [("primary", 0)],
                deadline=1.0, poll_seconds=0.1,
            ), "ready-log")

        clock[0] = 0.0
        sleeps = []

        def bounded_advance(delay):
            sleeps.append(delay)
            clock[0] += delay

        with mock.patch.object(
                MODULE, "_framegen_health_records", return_value=insufficient), \
                mock.patch.object(MODULE.time, "monotonic",
                                  side_effect=lambda: clock[0]), \
                mock.patch.object(MODULE.time, "sleep",
                                  side_effect=bounded_advance):
            with self.assertRaisesRegex(RuntimeError, "timed out waiting"):
                MODULE._wait_for_current_framegen_steady(
                    lambda: "stale-log", [("primary", 0)],
                    deadline=0.05, poll_seconds=0.1,
                )
        self.assertEqual(sleeps, [0.05])

    def test_framegen_current_steady_rejects_readiness_observed_at_42_05(self):
        ready = [self._segment_health(index) for index in range(1, 14)]
        clock = [0.0]
        reads = []

        def late_log():
            reads.append(clock[0])
            clock[0] = 42.05
            return "late-ready-log"

        with mock.patch.object(MODULE, "_framegen_health_records",
                               return_value=ready), \
                mock.patch.object(MODULE.time, "monotonic",
                                  side_effect=lambda: clock[0]):
            with self.assertRaisesRegex(RuntimeError, "timed out waiting"):
                MODULE._wait_for_current_framegen_steady(
                    late_log, [("primary", 0)], deadline=42.0,
                )
        self.assertEqual(reads, [0.0])

    def test_framegen_sf_and_log_capture_cannot_finish_after_deadline(self):
        for label in ("SurfaceFlinger", "logcat"):
            with self.subTest(label=label):
                clock = [0.0]
                received = []

                def crosses_deadline(remaining):
                    received.append(remaining)
                    clock[0] = 42.05
                    return label

                with mock.patch.object(MODULE.time, "monotonic",
                                       side_effect=lambda: clock[0]):
                    with self.assertRaisesRegex(RuntimeError,
                                                "capture deadline"):
                        MODULE._framegen_bounded_capture(
                            42.0, f"{label} capture deadline",
                            crosses_deadline,
                        )
                self.assertEqual(received, [42.0])

    def test_r18_late_cap_needs_shared_42_second_condition_deadline(self):
        cap_boundary_ns = 330_777_981_598_190
        baseline_end_ns = 330_779_197_644_805
        timeout_end_ns = 330_791_607_859_279
        mean_window_ns = 1_241_021_447
        records = [{
            "pid": 28304, "generator": 1, "locked": 60,
            "health_sequence": 17,
            "window_start_ns": 330_776_934_250_274,
            "window_end_ns": cap_boundary_ns, "proof": 32,
        }]
        previous_end = cap_boundary_ns
        for sequence in range(18, 34):
            if sequence <= 28:
                end = baseline_end_ns + round(
                    (sequence - 18) *
                    (timeout_end_ns - baseline_end_ns) / 10
                )
            else:
                end = timeout_end_ns + (sequence - 28) * mean_window_ns
            records.append({
                "pid": 28304, "generator": 1, "locked": 50,
                "health_sequence": sequence,
                "window_start_ns": previous_end,
                "window_end_ns": end,
                "proof": 34 + (sequence - 18) * 2,
            })
            previous_end = end
        through_timeout = records[:12]  # sequence 17 through exact r18 seq28
        through_ready = records

        clock = [0.0]

        def advance(delay):
            clock[0] += delay

        def health_for_clock(_log, _role, _display_id):
            return through_ready if clock[0] >= 38.2 else through_timeout

        with mock.patch.object(
                MODULE, "_framegen_health_records",
                side_effect=health_for_clock), \
                mock.patch.object(MODULE.time, "monotonic",
                                  side_effect=lambda: clock[0]), \
                mock.patch.object(MODULE.time, "sleep", side_effect=advance):
            with self.assertRaisesRegex(RuntimeError,
                                        "fewer than 30 segment proof samples"):
                MODULE._wait_for_current_framegen_steady(
                    lambda: "r18-log", [("primary", 0)],
                    deadline=32.0, poll_seconds=0.1,
                )

        clock[0] = 0.0
        with mock.patch.object(
                MODULE, "_framegen_health_records",
                side_effect=health_for_clock), \
                mock.patch.object(MODULE.time, "monotonic",
                                  side_effect=lambda: clock[0]), \
                mock.patch.object(MODULE.time, "sleep", side_effect=advance):
            self.assertEqual(MODULE._wait_for_current_framegen_steady(
                lambda: "r18-ready-log", [("primary", 0)],
                deadline=MODULE.FRAMEGEN_CURRENT_STEADY_DEADLINE_SECONDS,
                poll_seconds=0.1,
            ), "r18-ready-log")
        self.assertLess(clock[0], MODULE.FRAMEGEN_CURRENT_STEADY_DEADLINE_SECONDS)
        segment, end = MODULE._steady_framegen_segment(
            through_ready, "primary", 0)
        self.assertEqual(segment["proofBaselineWindowEndNs"], baseline_end_ns)
        self.assertEqual(end["proof"] - 34, 30)
        self.assertGreaterEqual(
            end["window_end_ns"] - baseline_end_ns, 11_000_000_000)

    def test_framegen_readiness_captures_sf_immediately_with_one_deadline(self):
        source = inspect.getsource(MODULE.frame_generation_evidence)
        collect = source.split("def collect_latency_records", 1)[1].split(
            "motion_thread.start()", 1)[0]
        self.assertIn("FRAMEGEN_CURRENT_STEADY_DEADLINE_SECONDS", collect)
        wait_at = collect.index("_wait_for_current_framegen_steady")
        sf_at = collect.index("dumpsys SurfaceFlinger --latency")
        self.assertLess(wait_at, sf_at)
        self.assertNotIn("time.sleep", collect[wait_at:sf_at])
        self.assertIn("deadline=deadline", collect[wait_at:sf_at])
        self.assertIn("timeout=remaining", collect)
        self.assertIn("_framegen_bounded_capture", collect)

    def test_framegen_qualification_session_binds_raw_sf_endpoints(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        log = root / "log.txt"
        latency = root / "latency.txt"
        log.write_text("bound log\n", encoding="utf-8")
        latency.write_text("bound latency\n", encoding="utf-8")
        records = [self._segment_health(index) for index in range(1, 14)]
        timestamps = (
            [12_700_000_000 + index * 5_000_000 for index in range(32)] +
            [13_010_000_000 + index * 10_000_000 for index in range(96)]
        )
        parsed = {
            "actualPresentTimestamps": timestamps,
            "firstActualPresentNs": timestamps[0],
            "lastActualPresentNs": timestamps[-1],
        }
        with mock.patch.object(MODULE, "_framegen_health_records",
                               return_value=records), \
                mock.patch.object(MODULE.frame_gen, "parse_latency",
                                  return_value=parsed):
            manifest, _segment_id = MODULE._write_framegen_qualification(
                log, latency, root, "gc-title-01", "primary", 0, {},
            )
        identity = json.loads(manifest.read_text(encoding="utf-8"))["identity"]
        self.assertEqual(identity["sessionEndNs"], timestamps[-1] + 1)
        self.assertLessEqual(identity["sessionStartNs"], timestamps[0])

    def test_dual_screen_reports_require_two_generators_in_one_process(self):
        primary = {"generator": {"generator": 7, "pid": 1234}}
        secondary = {"generator": {"generator": 9, "pid": 1234}}
        MODULE.require_independent_dual_generators(primary, secondary)
        with self.assertRaisesRegex(RuntimeError, "share one generator"):
            MODULE.require_independent_dual_generators(
                primary, {"generator": {"generator": 7, "pid": 1234}}
            )
        with self.assertRaisesRegex(RuntimeError, "crossed app processes"):
            MODULE.require_independent_dual_generators(
                primary, {"generator": {"generator": 9, "pid": 9876}}
            )

    def test_dual_screen_reports_require_distinct_compositor_layers(self):
        source = (TOOLS / "run_runtime_acceptance_qa.py").read_text(encoding="utf-8")
        framegen = source.split("def frame_generation_evidence", 1)[1].split(
            "def _music_volume", 1
        )[0]
        self.assertIn("require_independent_dual_generators(report, secondary_report)",
                      framegen)
        self.assertIn("if secondary_layer == layer:", framegen)

    def test_framegen_visible_output_gate_rejects_a_black_panel(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "black.png"
        image = Image.new("RGB", (1240, 1080), "black")
        image.save(path)
        metrics = MODULE.image_metrics(image, path)
        self.assertFalse(metrics["visible"])
        with self.assertRaisesRegex(RuntimeError, "no visible compositor output"):
            MODULE.require_visible_frame_generation_output(
                metrics, "secondary", 4
            )

    def test_framegen_report_requires_identity_matched_safe_motion_bound(self):
        report = {
            "role": "secondary",
            "displayId": 4,
            "generator": {"generator": 9, "pid": 1234},
        }
        with self.assertRaisesRegex(RuntimeError, "no identity-matched motion bound"):
            MODULE.require_safe_motion_bound("", report)
        log = (
            "Motion bounds generator=9 role=secondary displayId=4 "
            "source=256x192 maxFlowPixels=19.2 maxFlowFraction=0.1"
        )
        bound = MODULE.require_safe_motion_bound(log, report)
        self.assertEqual(bound["maxFlowPixels"], 19.2)
        self.assertEqual(bound["sourceHeight"], 192)
        unsafe = log.replace("maxFlowPixels=19.2", "maxFlowPixels=80.0").replace(
            "maxFlowFraction=0.1", "maxFlowFraction=0.4166667"
        )
        with self.assertRaisesRegex(RuntimeError, "source-relative limit"):
            MODULE.require_safe_motion_bound(unsafe, report)

    def test_framegen_runtime_gate_captures_both_physical_displays(self):
        source = (TOOLS / "run_runtime_acceptance_qa.py").read_text(
            encoding="utf-8"
        )
        framegen = source.split("def frame_generation_evidence", 1)[1].split(
            "def _music_volume", 1
        )[0]
        self.assertIn('("primary", 0): screenshot(', framegen)
        self.assertIn('visible_outputs[("secondary", 4)] = screenshot(', framegen)
        self.assertIn("require_visible_frame_generation_output(", framegen)
        self.assertIn("require_safe_motion_bound(", framegen)

    def test_n3ds_runtime_requires_the_clockwise_display_four_path(self):
        valid = "\n".join((
            "LucentPreview: showGameplaySurface generation=6 displayId=4 "
            "clockwiseQuarterTurn=true",
            "LucentPreview: clockwise gameplay surfaceCreated generation=6 "
            "buffer=1080x1240",
        ))
        report = MODULE.require_n3ds_clockwise_lower(valid)
        self.assertTrue(report["clockwiseQuarterTurn"])
        self.assertEqual(report["producerBuffer"], "1080x1240")
        with self.assertRaisesRegex(RuntimeError, "clockwise surface path"):
            MODULE.require_n3ds_clockwise_lower(
                valid.replace("clockwiseQuarterTurn=true",
                              "clockwiseQuarterTurn=false")
            )
        with self.assertRaisesRegex(RuntimeError, "not portrait"):
            MODULE.require_n3ds_clockwise_lower(
                valid.replace("buffer=1080x1240", "buffer=1240x1080")
            )

    def test_named_title_matching_does_not_accept_shared_franchise_only(self):
        self.assertTrue(MODULE.selected_title_matches(
            "Super Mario Galaxy 2", "SUPER MARIO GALAXY 2 CRITICS 9.1"
        ))
        self.assertFalse(MODULE.selected_title_matches(
            "Super Mario Galaxy 2", "SUPER MARIO GALAXY CRITICS 9.1"
        ))
        self.assertTrue(MODULE.selected_title_matches(
            "The Legend of Zelda: A Link Between Worlds",
            "THE LEGEND OF ZELDA A LINK BETWEEN WORLDS",
        ))
        self.assertTrue(MODULE.selected_title_matches(
            "1943: The Battle of Midway",
            "NINTENDO ENTERTAINMENT SYSTEM The Battle of Midw USERS 7.2",
        ))
        self.assertTrue(MODULE.selected_title_matches(
            "Capcom vs. SNK 2: Mark of the Millennium 2001",
            "Capcom vs. SNK 2: Mark of the Mille",
        ))
        self.assertFalse(MODULE.selected_title_matches(
            "Capcom vs. SNK 2: Mark of the Millennium 2001",
            "Capcom vs. SNK: Mark of the Millennium 2001",
        ))

    def test_required_titles_are_exactly_resolved_and_then_filled(self):
        case = MODULE.SystemCase(
            "wii", ("wii",), ("dolphin",), 2,
            required_titles=("Super Mario Galaxy", "Super Mario Galaxy 2"),
        )
        keys = ["wii|Donkey Kong Country Returns",
                "wii|Super Mario Galaxy", "wii|Super Mario Galaxy 2"]
        self.assertEqual(MODULE.title_position(keys, "Super Mario Galaxy 2"), 2)
        self.assertEqual(MODULE.acceptance_titles(case, keys, 3), [
            "Super Mario Galaxy", "Super Mario Galaxy 2",
            "Donkey Kong Country Returns",
        ])
        with self.assertRaises(RuntimeError):
            MODULE.title_position(keys, "Metroid Prime")

    def test_one_title_request_does_not_append_after_required_title_is_full(self):
        case = MODULE.SystemCase(
            "gc", ("gamecube", "gc"), ("dolphin",), 2,
            required_titles=("Metroid Prime",),
        )
        keys = ["gamecube|Mario Party 6", "gamecube|Metroid Prime"]
        self.assertEqual(
            MODULE.acceptance_titles(case, keys, 1), ["Metroid Prime"]
        )

    def test_game_list_identity_rejects_r16_all_systems_snes_drift(self):
        def fake_ocr(_path, box, _psm):
            if box == (35, 125, 1000, 180):
                return "ALL SYSTEMS | SUPER NINTENDO"
            return "123 / 5519 SELECT TO PLAY"

        names = {"nes": "nintendoentertainmentsystem",
                 "snes": "supernintendo", "all": "allsystems"}
        with mock.patch.object(MODULE, "ocr_region", side_effect=fake_ocr):
            identity = MODULE.game_list_identity(Path("frame.png"), names)
        self.assertTrue(identity["aggregate"])
        self.assertEqual(identity["folder"], "all")
        self.assertEqual(identity["current"], 123)
        self.assertEqual(identity["total"], 5519)
        with mock.patch.object(MODULE, "game_list_identity",
                               return_value=identity), \
                mock.patch.object(MODULE, "current_game_view",
                                  return_value="list"):
            with self.assertRaisesRegex(MODULE.AlphaNavigationDrift,
                                        "drifted from 'nes'"):
                MODULE.assert_game_list_checkpoint(
                    Path("frame.png"), "nes", 123, 5519, names
                )

    def test_alpha_navigation_uses_eight_row_pages_and_bounded_rows(self):
        class Controller:
            RIGHT, LEFT, DOWN, UP = 547, 546, 545, 544

            def __init__(self):
                self.keys = []

            def key(self, code, label, hold=0.0):
                self.keys.append((code, label, hold))

        controller = Controller()
        keys = [f"{index:06d}|Game {index}" for index in range(1083)]
        keys[479] = "000479|Lucent Callback Test"
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(MODULE, "screenshot"), \
                mock.patch.object(MODULE, "assert_game_list_checkpoint",
                                  return_value=1083) as checkpoint, \
                mock.patch.object(MODULE, "selected_header_ocr",
                                  return_value="Lucent Callback Test"), \
                mock.patch.object(MODULE, "selected_title_matches",
                                  return_value=True):
            result = MODULE.move_to_title(
                Path("/adb"), "serial", controller, 0, 479,
                "Lucent Callback Test", Path(directory), "nes-title-01",
                "nes", {"nes": "nintendoentertainmentsystem"}, keys,
            )
        self.assertEqual(result, 479)
        labels = [label for _code, label, _hold in controller.keys]
        self.assertEqual(labels.count("dpad-right-exact-page"), 59)
        self.assertEqual(labels.count("dpad-down-exact-title"), 7)
        self.assertNotIn("dpad-down-exact-title", labels[:59])
        # Initial + eight bounded page checkpoints + final selected frame.
        self.assertEqual(checkpoint.call_count, 10)

    def test_alpha_navigation_recovers_only_from_exact_origin(self):
        case = MODULE.SystemCase("nes", (), ("mesen",), 1)
        keys = ["000000|10-Yard Fight", "000001|Lucent Callback Test"]

        class Controller:
            A = 304

            def __init__(self):
                self.keys = []

            def key(self, code, label, hold=0.0):
                self.keys.append((code, label))

        controller = Controller()
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(MODULE, "move_to_title", side_effect=[
                    MODULE.AlphaNavigationDrift("foreign system"), 1,
                ]) as move, \
                mock.patch.object(MODULE, "go_to_cover_system") as origin, \
                mock.patch.object(MODULE, "screenshot"), \
                mock.patch.object(MODULE, "assert_cover_system") as cover, \
                mock.patch.object(MODULE, "force_alpha_list") as force, \
                mock.patch.object(MODULE, "library_index", return_value={
                    "systems": {"nes": {"alpha": keys}}
                }), mock.patch.object(MODULE.time, "sleep"):
            result = MODULE.select_title_alpha(
                Path("/adb"), "serial", controller, case, ["all", "nes"],
                {"nes": "nintendoentertainmentsystem"}, keys, 0,
                "Lucent Callback Test", Path(directory), "nes-title-01",
            )
        self.assertEqual(result, 1)
        origin.assert_called_once()
        cover.assert_called_once()
        force.assert_called_once()
        self.assertEqual(controller.keys, [(304, "physical-a-reopen-system")])
        self.assertEqual(move.call_args_list[1].args[3], 0)

    def test_alpha_navigation_rejects_stale_index_during_recovery(self):
        case = MODULE.SystemCase("nes", (), ("mesen",), 1)
        keys = ["000000|10-Yard Fight", "000001|Lucent Callback Test"]
        controller = mock.Mock(A=304)
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(MODULE, "move_to_title",
                                  side_effect=MODULE.AlphaNavigationDrift("drift")), \
                mock.patch.object(MODULE, "go_to_cover_system"), \
                mock.patch.object(MODULE, "screenshot"), \
                mock.patch.object(MODULE, "assert_cover_system"), \
                mock.patch.object(MODULE, "force_alpha_list"), \
                mock.patch.object(MODULE, "library_index", return_value={
                    "systems": {"nes": {"alpha": [keys[0]]}}
                }), mock.patch.object(MODULE.time, "sleep"):
            with self.assertRaisesRegex(MODULE.AlphaNavigationDrift,
                                        "live Alpha index changed"):
                MODULE.select_title_alpha(
                    Path("/adb"), "serial", controller, case,
                    ["all", "nes"],
                    {"nes": "nintendoentertainmentsystem"}, keys, 0,
                    "Lucent Callback Test", Path(directory), "nes-title-01",
                )

    def test_alpha_navigation_rejects_stale_visible_count(self):
        identity = {"aggregate": False, "folder": "nes", "current": 65,
                    "total": 1082, "systemOcr": "NINTENDO ENTERTAINMENT SYSTEM"}
        with mock.patch.object(MODULE, "game_list_identity",
                               return_value=identity), \
                mock.patch.object(MODULE, "current_game_view",
                                  return_value="list"):
            with self.assertRaisesRegex(MODULE.AlphaNavigationDrift,
                                        "Alpha count changed"):
                MODULE.assert_game_list_checkpoint(
                    Path("frame.png"), "nes", 65, 1083,
                    {"nes": "nintendoentertainmentsystem"},
                )

    def test_r18_translucent_counter_uses_exact_title_checkpoint(self):
        names = {"nes": "nintendoentertainmentsystem"}

        def r18_ocr(_path, box, _psm):
            if box == (35, 125, 1000, 180):
                return "NINTENDO ENTERTAINMENT SYSTEM"
            self.fail("later r18 checkpoint must not OCR the translucent counter")

        exact_header = (
            "NINTENDO ENTERTAINMENT SYSTEM | a ao Bases Loaded 4 = = Li "
            "Tiel cd ro Oe, F.BORDS | NINTENDO ENTERTAINMENT SYSTEM | = "
            "Bases Loaded 4 | BasesLoaded4"
        )
        with mock.patch.object(MODULE, "ocr_region", side_effect=r18_ocr), \
                mock.patch.object(MODULE, "current_game_view",
                                  return_value="list"), \
                mock.patch.object(MODULE, "selected_header_ocr",
                                  return_value=exact_header):
            total = MODULE.assert_game_list_checkpoint(
                Path("r18-row65.png"), "nes", 65, 1083, names,
                expected_title="Bases Loaded 4", require_counter=False,
            )
        self.assertEqual(total, 1083)

    def test_later_alpha_checkpoint_rejects_wrong_title_and_layout(self):
        identity = {"aggregate": False, "folder": "nes", "current": None,
                    "total": None, "systemOcr":
                    "NINTENDO ENTERTAINMENT SYSTEM", "counterOcr": ""}
        with mock.patch.object(MODULE, "game_list_identity",
                               return_value=identity), \
                mock.patch.object(MODULE, "current_game_view",
                                  return_value="list"), \
                mock.patch.object(MODULE, "selected_header_ocr",
                                  return_value="Battletoads"):
            with self.assertRaisesRegex(MODULE.AlphaNavigationDrift,
                                        "immutable Alpha title"):
                MODULE.assert_game_list_checkpoint(
                    Path("frame.png"), "nes", 65, 1083,
                    {"nes": "nintendoentertainmentsystem"},
                    expected_title="Bases Loaded 4", require_counter=False,
                )
        with mock.patch.object(MODULE, "game_list_identity",
                               return_value=identity), \
                mock.patch.object(MODULE, "current_game_view",
                                  return_value="covers"):
            with self.assertRaisesRegex(MODULE.AlphaNavigationDrift,
                                        "left the proven List"):
                MODULE.assert_game_list_checkpoint(
                    Path("frame.png"), "nes", 65, 1083,
                    {"nes": "nintendoentertainmentsystem"},
                    expected_title="Bases Loaded 4", require_counter=False,
                )

    def test_r19_busy_footer_does_not_override_exact_system_and_title(self):
        identity = {"aggregate": False, "folder": None, "current": None,
                    "total": None, "systemOcr":
                    "busy wallpaper OCR", "counterOcr": ""}
        exact_header = (
            "NINTENDO ENTERTAINMENT SYSTEM Destiny of an Emperor CRITICS N/A "
            "USERS 7.4 RELEASE 1989 | Destiny of an Emperor"
        )
        with mock.patch.object(MODULE, "game_list_identity",
                               return_value=identity), \
                mock.patch.object(MODULE, "current_game_view",
                                  return_value=None) as footer, \
                mock.patch.object(MODULE, "nes_system_label_ocr",
                                  return_value=
                                  "NINTENDO ENTERTAINMENT SYSTEM"), \
                mock.patch.object(MODULE, "selected_header_ocr",
                                  return_value=exact_header):
            self.assertEqual(MODULE.assert_game_list_checkpoint(
                Path("r19-destiny.png"), "nes", 193, 1083,
                {"nes": "nintendoentertainmentsystem"},
                expected_title="Destiny of an Emperor", require_counter=False,
                require_list_layout=False,
            ), 1083)
        footer.assert_not_called()

    def test_r19_unique_two_row_offset_is_physically_corrected_and_rechecked(self):
        class Controller:
            RIGHT, LEFT, DOWN, UP = 547, 546, 545, 544

            def __init__(self):
                self.keys = []

            def key(self, code, label, hold=0.0):
                self.keys.append((code, label, hold))

        keys = [f"{index:06d}|QA Game {index:04d}" for index in range(300)]
        keys[192] = "000192|Destiny of an Emperor"
        keys[194] = "000194|Dezaemon"
        controller = Controller()
        checkpoint_results = [
            300, 300, 300,
            MODULE.AlphaNavigationDrift("expected Destiny; observed Dezaemon"),
            300, 300,
        ]
        context = {"aggregate": False, "folder": "nes", "current": None,
                   "total": None, "systemOcr":
                   "NINTENDO ENTERTAINMENT SYSTEM", "counterOcr": ""}
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(MODULE, "screenshot"), \
                mock.patch.object(MODULE, "assert_game_list_checkpoint",
                                  side_effect=checkpoint_results) as checkpoints, \
                mock.patch.object(MODULE, "game_list_identity",
                                  return_value=context), \
                mock.patch.object(MODULE, "selected_header_ocr",
                                  side_effect=[
                                      "NINTENDO ENTERTAINMENT SYSTEM Dezaemon",
                                      "NINTENDO ENTERTAINMENT SYSTEM "
                                      "Destiny of an Emperor",
                                  ]):
            result = MODULE.move_to_title(
                Path("/adb"), "serial", controller, 0, 192,
                "Destiny of an Emperor", Path(directory), "nes-title-01",
                "nes", {"nes": "nintendoentertainmentsystem"}, keys,
            )
        self.assertEqual(result, 192)
        labels = [label for _code, label, _hold in controller.keys]
        self.assertEqual(labels.count("dpad-right-exact-page"), 24)
        self.assertEqual(labels.count("dpad-up-alpha-correction"), 2)
        self.assertEqual(checkpoints.call_count, 6)
        corrected_call = checkpoints.call_args_list[4]
        self.assertEqual(corrected_call.kwargs["expected_title"],
                         "Destiny of an Emperor")

    def test_alpha_offset_correction_rejects_unresolvable_or_ambiguous_title(self):
        keys = ["000000|Alpha", "000001|Beta", "000002|Beta Special"]
        with self.assertRaisesRegex(MODULE.AlphaNavigationDrift,
                                    "does not resolve uniquely"):
            MODULE.resolve_alpha_header_position("Unknown Selection", keys)
        with self.assertRaisesRegex(MODULE.AlphaNavigationDrift,
                                    "does not resolve uniquely"):
            MODULE.resolve_alpha_header_position("Beta Special Beta", keys)

    def test_row_zero_uses_immutable_live_keys_when_translucent_count_is_unreadable(self):
        class Controller:
            RIGHT, LEFT, DOWN, UP = 547, 546, 545, 544

            def __init__(self):
                self.keys = []

            def key(self, code, label, hold=0.0):
                self.keys.append((code, label, hold))

        keys = ["000000|A", "000001|B", "000002|C"]
        controller = Controller()
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(MODULE, "screenshot"), \
                mock.patch.object(MODULE, "assert_game_list_checkpoint",
                                  return_value=3), \
                mock.patch.object(MODULE, "selected_header_ocr",
                                  return_value="C"), \
                mock.patch.object(MODULE, "selected_title_matches",
                                  return_value=True):
            result = MODULE.move_to_title(
                Path("/adb"), "serial", controller, 0, 2, "C",
                Path(directory), "prefix", "nes",
                {"nes": "nintendoentertainmentsystem"}, keys,
            )
        self.assertEqual(result, 2)
        self.assertEqual([row[1] for row in controller.keys],
                         ["dpad-down-exact-title"] * 2)

    def test_nes_playable_scan_cannot_stop_before_exact_real_samples(self):
        case = MODULE.SystemCase("nes", (), ("mesen",), 1)
        keys = [
            "000000|10-Yard Fight", "000001|1943: The Battle of Midway",
            "000002|2048", "000003|720", "000004|8 Eyes",
            "000479|Lucent Callback Test",
        ]
        paths = {MODULE.normalize(MODULE.title_from_key(key)): {"/" + str(i)}
                 for i, key in enumerate(keys)}
        required = ("Lucent Callback Test", *MODULE.NES_REAL_QUALIFICATION_TITLES)
        with mock.patch.object(MODULE, "metadata_title_files",
                               return_value=paths), \
                mock.patch.object(MODULE, "title_has_live_rom",
                                  return_value=True):
            playable = MODULE.playable_alpha_keys(
                Path("/adb"), "serial", case, keys, 4, required
            )
        self.assertEqual(playable[-1], "000479|Lucent Callback Test")
        observed = {MODULE.normalize(MODULE.title_from_key(key))
                    for key in playable}
        self.assertTrue({MODULE.normalize(value) for value in required}
                        .issubset(observed))

    # ---- route closure after startup: external routing is legitimate --------

    MAIN_ACTIVITY = (
        "com.thorium.preview/org.pegasus_frontend.android.MainActivity")

    def _internal_launch(self, engine, system):
        return ("launch: am start -a com.thorium.preview.LAUNCH_INTERNAL_GAME "
                f"-n {self.MAIN_ACTIVITY} "
                f"--es engine_id {engine} --es system {system}")

    def _external_view_install(self, package):
        return ("launch: am start -a android.intent.action.VIEW "
                f"-d https://play.google.com/store/apps/details?id={package}")

    def _external_trampoline(self, package):
        return ("launch: am start -a com.thorium.preview.LAUNCH_FILE "
                "-n com.thorium.preview/com.thorium.preview.RomLaunchActivity "
                '--es path "{file.path}" '
                f"--es target_package {package} "
                "--es target_activity .MainActivity "
                "--es target_action android.intent.action.VIEW")

    def _foreign_broadcast(self):
        return ("launch: am broadcast -a android.intent.action.MAIN "
                "-n org.foreign.launcher/.Receiver")

    @staticmethod
    def _route_text(*blocks):
        lines = []
        for shortname, launch in blocks:
            lines.append(f"collection: {shortname.upper()}")
            lines.append(f"shortname: {shortname}")
            lines.append(launch)
        return "\n".join(lines) + "\n"

    def _post_startup_route_errors(self, route_text, sim_routes):
        """Reproduce the harness's device-independent post-startup checks.

        Mirrors run_runtime_acceptance_qa.main's invalidMetadataLaunchers and
        internal route-closure comparison (the APK-bound verify() step needs a
        real device and is exercised separately).
        """
        rc = MODULE.route_closure
        errors = []
        for row in rc.invalid_launch_lines(route_text):
            errors.append("non-lucent launcher: " + str(row["commandSha256"]))
        externals = MODULE.external_route_systems(route_text)
        installed = rc.routes_from_text(route_text)
        internal_installed = {r for r in installed if r.system not in externals}
        expected_internal = {r for r in sim_routes if r.system not in externals}
        if internal_installed != expected_internal:
            errors.append("internal route difference")
        return errors, externals

    def test_startup_route_closure_tolerates_external_routes(self):
        Route = MODULE.route_closure.Route
        # Startup metadata mixes an internal route (nes->mesen), an external
        # install page (switch, no packaged internal engine) and a user-set
        # external system that DOES have an internal engine (n64->mupen in the
        # internal-only simulation) routed out through the RomLaunchActivity
        # trampoline. All three must pass the after-startup route-closure check.
        route_text = self._route_text(
            ("nes", self._internal_launch("mesen", "nes")),
            ("switch", self._external_view_install("org.eden")),
            ("n64", self._external_trampoline("org.mupen")),
        )
        sim_routes = {Route("nes", "mesen"), Route("n64", "mupen")}
        errors, externals = self._post_startup_route_errors(route_text, sim_routes)
        self.assertEqual(errors, [])
        self.assertEqual(externals, {"switch", "n64"})

    def test_startup_route_closure_still_fails_broken_internal_route(self):
        Route = MODULE.route_closure.Route
        # nes claims an internal in-window route to an engine the candidate does
        # not package. It is NOT an external route, so it stays in the strict
        # comparison and diverges from the simulation.
        route_text = self._route_text(
            ("nes", self._internal_launch("unpackaged", "nes")),
            ("switch", self._external_view_install("org.eden")),
        )
        sim_routes = {Route("nes", "mesen")}
        errors, externals = self._post_startup_route_errors(route_text, sim_routes)
        self.assertIn("internal route difference", errors)
        self.assertNotIn("nes", externals)

    def test_startup_route_closure_still_fails_non_lucent_launcher(self):
        Route = MODULE.route_closure.Route
        route_text = self._route_text(
            ("nes", self._internal_launch("mesen", "nes")),
            ("gb", self._foreign_broadcast()),
        )
        sim_routes = {Route("nes", "mesen")}
        errors, externals = self._post_startup_route_errors(route_text, sim_routes)
        self.assertTrue(any(e.startswith("non-lucent launcher") for e in errors))
        # A foreign broadcast is never mistaken for a legitimate external route.
        self.assertEqual(externals, set())

    def test_external_route_systems_ignores_internal_and_stale_launchers(self):
        # Only lines that audit as "external-route" exempt their system.
        stale_same_activity = (
            "launch: am start "
            f"-n {self.MAIN_ACTIVITY} --es engine_id mesen --es system nes")
        route_text = self._route_text(
            ("nes", self._internal_launch("mesen", "nes")),
            ("snes", stale_same_activity),
        )
        self.assertEqual(MODULE.external_route_systems(route_text), set())

    def test_active_sort_detector_uses_selected_accent_in_frozen_geometry(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "sort.png"
        image = Image.new("RGB", (1920, 1080), (3, 5, 9))
        draw = ImageDraw.Draw(image)
        for index in range(4):
            left = 48 + index * 150
            fill = (12, 16, 22) if index != 2 else (35, 184, 116)
            draw.rounded_rectangle((left, 350, left + 142, 394), 7, fill=fill)
        image.save(path)
        self.assertEqual(MODULE.active_sort_index(path), 2)

    def test_game_view_reader_combines_tight_footer_crops(self):
        path = Path("unused.png")
        with mock.patch.object(
                MODULE, "ocr_region",
                side_effect=["noise Y VIEW: LIST X SETTINGS", "more noise"]
        ) as reader:
            self.assertEqual(MODULE.current_game_view(path), "list")
        self.assertEqual(reader.call_count, 2)
        self.assertTrue(all(call.args[1] == (950, 995, 1400, 1070)
                            for call in reader.call_args_list))

    def test_game_view_reader_distinguishes_covers_and_fails_closed(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "unknown.png"
        Image.new("RGB", (1920, 1080), (20, 20, 20)).save(path)
        with mock.patch.object(
                MODULE, "ocr_region",
                side_effect=["Y VIEW: COVERS", ""]
        ):
            self.assertEqual(MODULE.current_game_view(path), "covers")
        with mock.patch.object(
                MODULE, "ocr_region", return_value="unreadable footer"
        ):
            self.assertIsNone(MODULE.current_game_view(path))

    def test_game_view_reader_uses_selected_row_geometry_when_footer_is_busy(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "list.png"
        image = Image.new("RGB", (1920, 1080), (24, 26, 30))
        draw = ImageDraw.Draw(image)
        draw.rectangle((690, 320, 1870, 395), fill=(70, 110, 205))
        draw.rectangle((690, 410, 1870, 480), fill=(24, 26, 30))
        image.save(path)
        with mock.patch.object(
                MODULE, "ocr_region", return_value="wallpaper noise"
        ):
            self.assertEqual(MODULE.current_game_view(path), "list")

    def _dual_case(self):
        return MODULE.SystemCase(
            "nds", ("nds", "ds"), ("melonds-ds",), 1,
            dual_screen=True, lower_touch=True,
            required_titles=("Cobalt Demo",),
        )

    def _single_case(self):
        return MODULE.SystemCase("nes", ("nes",), ("mesen",), 1)

    def _start_line(self, intent, tail=""):
        return ("01-01 00:00:00.000  1234  1234 I ActivityTaskManager: "
                f"START u0 {{{intent}}}{tail}")

    def test_dual_screen_secondary_gameplay_activity_is_whitelisted(self):
        # EmuFusion's OWN PreviewActivity on the physical lower display, with the
        # SECONDARY_GAMEPLAY action, is the single permitted second Activity.
        secondary = self._start_line(
            "act=com.thorium.preview.SECONDARY_GAMEPLAY "
            "cmp=com.thorium.preview/.PreviewActivity",
            " from uid 10123",
        )
        routed = "\n".join([
            "In-window route accepted engine=melonds-ds system=nds",
            secondary,
            "performResumeActivity com.thorium.preview displayId 4",
        ])
        count, violations = MODULE.classify_new_activity_starts(
            routed, "", self._dual_case())
        self.assertEqual(count, 1)
        self.assertEqual(violations, [])
        # Corroborated by a resume on a non-primary display.
        self.assertIsNotNone(MODULE.SECONDARY_GAMEPLAY_RESUME.search(routed))

    def test_dual_screen_accepts_reused_resumed_lower_window_with_surface(self):
        routed = "\n".join([
            "LucentSecondary: request served by the resumed lower-display activity "
            "generation=1 system=nds",
            "LucentPreview: showGameplaySurface generation=1 displayId=4 "
            "clockwiseQuarterTurn=false",
            "EmuFusionFrameGen: Frame generator attached generator=2 "
            "role=secondary displayId=4 output=1240x1080",
        ])
        self.assertIsNotNone(MODULE.SECONDARY_GAMEPLAY_REUSED.search(routed))

    def test_dual_screen_rejects_foreign_package_activity(self):
        routed = "\n".join([
            self._start_line(
                "act=android.intent.action.MAIN "
                "cmp=org.melonds.emulator/.EmulatorActivity"),
        ])
        count, violations = MODULE.classify_new_activity_starts(
            routed, "", self._dual_case())
        self.assertEqual(count, 0)
        self.assertEqual(len(violations), 1)

    def test_dual_screen_rejects_display_zero_and_main_activity(self):
        # A MainActivity relaunch (top-screen / display 0) is never whitelisted.
        main_relaunch = self._start_line(
            "act=android.intent.action.MAIN "
            "cmp=com.thorium.preview/org.pegasus_frontend.android.MainActivity")
        _count, violations = MODULE.classify_new_activity_starts(
            main_relaunch, "", self._dual_case())
        self.assertEqual(len(violations), 1)
        # Even a SECONDARY_GAMEPLAY-labelled start pinned to display 0 is rejected.
        pinned = self._start_line(
            "act=com.thorium.preview.SECONDARY_GAMEPLAY "
            "cmp=com.thorium.preview/.PreviewActivity",
            " from uid 10123 on displayId=0")
        count, violations = MODULE.classify_new_activity_starts(
            pinned, "", self._dual_case())
        self.assertEqual(count, 0)
        self.assertEqual(len(violations), 1)

    def test_single_screen_never_whitelists_a_second_activity(self):
        secondary = self._start_line(
            "act=com.thorium.preview.SECONDARY_GAMEPLAY "
            "cmp=com.thorium.preview/.PreviewActivity")
        count, violations = MODULE.classify_new_activity_starts(
            secondary, "", self._single_case())
        self.assertEqual(count, 0)
        self.assertEqual(len(violations), 1)

    def test_baseline_activity_starts_are_not_counted_as_new(self):
        secondary = self._start_line(
            "act=com.thorium.preview.SECONDARY_GAMEPLAY "
            "cmp=com.thorium.preview/.PreviewActivity")
        # The same start already present in the pre-launch baseline snapshot is
        # not treated as a new launch.
        count, violations = MODULE.classify_new_activity_starts(
            secondary, secondary, self._dual_case())
        self.assertEqual(count, 0)
        self.assertEqual(violations, [])

    def test_in_process_assertions_include_dual_screen_whitelist(self):
        source = (TOOLS / "run_runtime_acceptance_qa.py").read_text(encoding="utf-8")
        self.assertIn("classify_new_activity_starts", source)
        self.assertIn(
            "dual-screen secondary gameplay window never resumed", source)
        self.assertIn("SECONDARY_GAMEPLAY_RESUME", source)
        self.assertIn(
            "menu A launch started an Activity instead of staying in-process",
            source)

    def test_stop_gate_is_five_hundred_milliseconds_and_background_save(self):
        source = (TOOLS / "run_runtime_acceptance_qa.py").read_text(encoding="utf-8")
        self.assertIn("visible_latency > 500", source)
        self.assertIn("begin_visible_return_recording", source)
        self.assertIn("inject_held_stop_device_clocked", source)
        self.assertIn("parse_winscope_frame_timestamps", source)
        self.assertIn('"thresholdLowerBoundElapsedNs"', source)
        self.assertNotIn(
            "the in-process monotonic marker remains the\n"
            "    # fail-closed <=500 ms latency clock",
            source,
        )
        self.assertIn(
            "background runtime-state disposition did not complete", source
        )
        self.assertIn("runtime_checkpoint_outcome", source)
        self.assertIn('checkpoint_outcome == "committed"', source)
        self.assertIn('checkpoint_outcome == "quarantined"', source)
        self.assertIn("assert_no_interstitial", source)
        self.assertIn('"activityStart"', source)
        self.assertIn('"performResume"', source)
        self.assertIn('"qtCreateSurface"', source)
        self.assertIn('"input", "touchscreen", "-d", "4"', source)
        self.assertIn("inject_display4_tap(adb, serial, 960, 270, hold_ms=220)", source)
        self.assertIsNotNone(MODULE.PROHIBITED_TEXT.search("LUCENT"))
        self.assertIsNotNone(MODULE.PROHIBITED_TEXT.search("POWERED BY PEGASUS"))

    def test_nes_campaign_is_physical_bidirectional_and_hash_bound(self):
        source = (TOOLS / "run_runtime_acceptance_qa.py").read_text(encoding="utf-8")
        campaign = source.split("def nes_frame_generation_campaign", 1)[1].split(
            "\ndef frame_generation_evidence", 1)[0]
        self.assertIn("schedule = [60, 50, 40, 30, 40, 50, 60]", campaign)
        self.assertIn("inputs.append(_select_nes_cadence(controller, tier))",
                      campaign)
        self.assertIn("proof_resets.append(_reset_nes_qualification_proof(",
                      campaign)
        self.assertNotIn("if index:", campaign)
        self.assertLess(
            campaign.index("inputs.append(_select_nes_cadence(controller, tier))"),
            campaign.index("proof_resets.append(_reset_nes_qualification_proof("),
        )
        self.assertLess(
            campaign.index("proof_resets.append(_reset_nes_qualification_proof("),
            campaign.index("dumpsys SurfaceFlinger --latency-clear"),
        )
        self.assertIn("time.sleep(22.0)", campaign)
        self.assertIn("Select+", source)
        for tier in (30, 40, 50, 60):
            self.assertIn(f'f"steady-{{tier}}"', campaign)
        for transition in MODULE.nes_qa.TRANSITIONS:
            self.assertIn(transition, MODULE.nes_qa.TRANSITIONS)
        segment_helper = source.split(
            "def _write_nes_framegen_segment", 1
        )[1].split("\ndef nes_frame_generation_campaign", 1)[0]
        self.assertIn("qualification_path=qualification", segment_helper)
        self.assertIn("segment_id=str(segment", segment_helper)
        self.assertIn("snapshot_nes_logcat_capture", campaign)

    def test_r25_pathological_fixture_remains_failed_content_only_calibration(self):
        failures = [
            "most synthetic output is indistinguishable from fixed-pixel crossfade",
            "motion field and non-crossfade synthetic output are not correlated",
            "motion-compensated pixels do not spatially follow their selected vectors",
        ]
        result = MODULE.calibration_framegen_result(
            {"passed": False, "failures": failures, "proofSchemaVersion": 21},
            "steady-60",
        )
        self.assertFalse(result["passed"])
        self.assertFalse(result["contentQualityPassed"])
        self.assertTrue(result["calibrationOnly"])
        self.assertFalse(result["contentQualificationEligible"])
        self.assertEqual(result["failures"], failures)

    def test_calibration_rejects_cadence_reset_and_unexpected_failures(self):
        failures = (
            "generator did not present at its 120 FPS target",
            "qualification proof reset baseline counters are nonzero",
            "forbidden runtime marker: shader compile failed",
        )
        for failure in failures:
            with self.subTest(failure=failure), self.assertRaisesRegex(
                    RuntimeError, "non-content failures"):
                MODULE.calibration_framegen_result(
                    {"passed": False, "failures": [failure]}, "steady-60"
                )

    def test_nes_real_game_closure_requires_three_exact_full_passes(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        output = Path(temporary.name)
        games = []
        for index, title in enumerate(MODULE.NES_REAL_QUALIFICATION_TITLES):
            manifest = output / f"real-{index}.json"
            manifest.write_text("{}", encoding="utf-8")
            games.append({
                "expectedTitle": title,
                "qualificationRole": {"calibrationFixture": False,
                                      "realGame": True},
                "frameGeneration": {"passed": True},
                "nesRealTitleQualification": {"passed": True,
                                              "manifest": str(manifest)},
            })
        with mock.patch.object(
                MODULE.nes_qa, "verify_real_game_closure",
                return_value={"passed": True, "errors": []}) as verify:
            result = MODULE.write_nes_real_game_closure(output, games)
        self.assertTrue(result["passed"])
        verify.assert_called_once()
        closure = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
        self.assertEqual({game["title"] for game in closure["games"]},
                         set(MODULE.NES_REAL_QUALIFICATION_TITLES))

    def test_nes_real_game_closure_rejects_missing_or_failed_title(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        output = Path(temporary.name)
        def entry(title, passed=True):
            manifest = output / (MODULE.normalize(title) + ".json")
            manifest.write_text("{}", encoding="utf-8")
            return {
                "expectedTitle": title,
                "qualificationRole": {"calibrationFixture": False,
                                      "realGame": True},
                "frameGeneration": {"passed": passed},
                "nesRealTitleQualification": {"passed": passed,
                                              "manifest": str(manifest)},
            }
        titles = MODULE.NES_REAL_QUALIFICATION_TITLES
        with self.assertRaisesRegex(RuntimeError, "lacks exactly one"):
            MODULE.write_nes_real_game_closure(
                output, [entry(title) for title in titles[:-1]]
            )
        with self.assertRaisesRegex(RuntimeError, "full qualification failed"):
            MODULE.write_nes_real_game_closure(
                output, [entry(titles[0], False),
                         entry(titles[1]), entry(titles[2])]
            )

    def test_r22_stale_initial_mode_is_rejected_and_full_campaign_passes(self):
        def health_runs(spec):
            window_end = 1_000_000_000
            records = []
            for tier, count in spec:
                for _ in range(count):
                    records.append({"locked": tier,
                                    "window_end_ns": window_end})
                    window_end += 5_500_000_000
            return records

        r22 = [(60, 15), (50, 5), (40, 11), (50, 46), (40, 23),
               (30, 25), (40, 23), (50, 24), (60, 22)]
        with mock.patch.object(MODULE, "_framegen_health_records",
                               return_value=health_runs(r22)):
            with self.assertRaisesRegex(RuntimeError,
                                        "seven real >=11-second HEALTH runs"):
                MODULE._nes_health_runs("Qualification proof generator=1")

        fixed = [*r22[:3], (60, 4), (50, 4), (40, 4), (30, 4),
                 (40, 4), (50, 4), (60, 4)]
        with mock.patch.object(MODULE, "_framegen_health_records",
                               return_value=health_runs(fixed)):
            accepted = MODULE._nes_health_runs(
                "Qualification proof generator=1"
            )
        self.assertEqual([run[0]["locked"] for run in accepted],
                         [60, 50, 40, 30, 40, 50, 60])
        self.assertTrue(all(len(run) == 4 for run in accepted))

    def test_nes_proof_reset_observes_false_true_and_zero_baseline(self):
        attach = (
            "I/EmuFusionFrameGen(1234): Frame generator attached generator=7 "
            "role=primary displayId=0 proofContract="
            "affine-neighbor-regional-flow-v20-content-unique "
            "proofSchemaVersion=20"
        )
        marker = lambda enabled: (
            "I/EmuFusionFrameGen(1234): Qualification proof generator=7 "
            f"enabled={str(enabled).lower()} proofContract="
            "affine-neighbor-regional-flow-v20-content-unique "
            "proofSchemaVersion=20"
        )
        logs = [
            "\n".join((attach, marker(True))),
            "\n".join((attach, marker(True))),
            "\n".join((attach, marker(True), marker(False))),
            "\n".join((attach, marker(True), marker(False), marker(True))),
            "\n".join((attach, marker(True), marker(False), marker(True),
                        "health")),
        ]
        baseline = {key: 0 for key in MODULE.frame_gen.RESET_COUNTER_FIELDS}
        baseline.update({"pid": 1234, "generator": 7, "role": "primary",
                         "display_id": 0, "line_index": 4,
                         "window_end_ns": 99_000_000_000})
        capture = {"pid": 1234, "handle": mock.Mock(),
                   "path": Path("session.txt")}
        with mock.patch.object(MODULE, "_live_nes_log_text",
                               side_effect=logs), mock.patch.object(
                                   MODULE, "_nes_framegen_records_with_lines",
                                   return_value=[baseline]), mock.patch.object(
                                   MODULE.qa, "adb") as adb:
            reset = MODULE._reset_nes_qualification_proof(
                Path("/adb"), "serial", capture, 60
            )
        settings = [call.args[3:] for call in adb.call_args_list]
        self.assertEqual(settings, [
            ("settings", "delete", "global", "emufusion_framegen_proof"),
            ("settings", "put", "global", "emufusion_framegen_proof", "1"),
        ])
        self.assertEqual(reset, {
            "tier": 60, "pid": 1234, "generator": 7,
            "disabledLineIndex": 2, "enabledLineIndex": 3,
            "baselineWindowEndNs": 99_000_000_000,
        })

    def test_nes_latency_binding_rejects_transition_contaminated_run_tail(self):
        good = {"window_end_ns": 200, "window_start_ns": 100,
                "locked": 40, "window_ms": 1000, "window_presents": 120,
                "window_generated": 80, "window_promoted": 40,
                "output": 120}
        contaminated = {"window_end_ns": 300, "window_start_ns": 201,
                        "locked": 40, "window_ms": 1000,
                        "window_presents": 120, "window_generated": 85,
                        "window_promoted": 35, "output": 120}
        latency = {"actualPresentTimestamps": list(range(120, 160))}
        with mock.patch.object(MODULE.frame_gen, "parse_latency",
                               return_value=latency):
            selected = MODULE._nes_latency_bound_health(
                [good, contaminated], Path("latency.txt"), 40, 50
            )
        self.assertIs(selected, good)

    def test_nes_schema36_uses_rational_output_lattice(self):
        cases = (
            (60, 120, 60, 60),
            (50, 60, 10, 50),
            (40, 60, 20, 40),
            (30, 60, 30, 30),
            (20, 40, 20, 20),
        )
        latency = {"actualPresentTimestamps": list(range(100, 140))}
        with mock.patch.object(MODULE.frame_gen, "parse_latency",
                               return_value=latency):
            for source, output, exact_real, generated in cases:
                with self.subTest(source=source, output=output):
                    record = {
                        "proof_schema_version": 36,
                        "window_end_ns": 1_000_000_100,
                        "window_start_ns": 100,
                        "locked": source, "panel": 120, "output": output,
                        "window_ms": 1000,
                        "window_presents": output,
                        "window_generated": generated,
                        "window_promoted": source,
                        "window_real_priority": exact_real,
                    }
                    self.assertIs(
                        MODULE._nes_latency_bound_health(
                            [record], Path("latency.txt"), source, 50),
                        record)

            old_x2 = {
                "proof_schema_version": 36,
                "window_end_ns": 1_000_000_100,
                "window_start_ns": 100,
                "locked": 50, "panel": 120, "output": 100,
                "window_ms": 1000, "window_presents": 100,
                "window_generated": 50, "window_promoted": 50,
                "window_real_priority": 50,
            }
            with self.assertRaisesRegex(RuntimeError, "no cadence-correct"):
                MODULE._nes_latency_bound_health(
                    [old_x2], Path("latency.txt"), 50, 50)

    def test_runner_schema36_binds_endpoint_ordinals_to_accepted_real(self):
        groups = {key: "0" for key in (
            "proof", "window_presentation_epoch",
            "proof_evidence_presentation_epoch",
            "proof_evidence_enqueued_in_epoch", "proof_evidence_accepted",
            "proof_evidence_excluded",
            "proof_evidence_last_accepted_atlas_sequence",
            "dense_proof_atlas_layout", "dense_proof_atlas_completed",
            "dense_proof_atlas_enqueued", "dense_proof_atlas_pending",
            "dense_diagnostic_last_atlas_sequence",
            "dense_diagnostic_last_pair_sequence",
            "dense_diagnostic_last_previous_endpoint",
            "dense_diagnostic_last_current_endpoint", "dense_promotions",
            "real", "promoted", "panel", "locked", "output",
            "window_presents", "window_generated", "window_promoted",
            "window_real_priority", "window_synthetic_selected",
            "window_synthetic_quota_opening",
            "window_synthetic_pair_created",
            "window_synthetic_quota_skipped", "synthetic_quota_pending",
        )}
        groups.update({
            "proof": "2", "window_presentation_epoch": "9",
            "proof_evidence_presentation_epoch": "9",
            "proof_evidence_enqueued_in_epoch": "2",
            "proof_evidence_accepted": "2",
            "proof_evidence_last_accepted_atlas_sequence": "2",
            "dense_proof_atlas_layout": "4",
            "dense_proof_atlas_completed": "2",
            "dense_proof_atlas_enqueued": "2",
            "dense_diagnostic_last_atlas_sequence": "2",
            "dense_diagnostic_last_pair_sequence": "2",
            "dense_diagnostic_last_previous_endpoint": "13",
            "dense_diagnostic_last_current_endpoint": "14",
            "dense_promotions": "2", "real": "14", "promoted": "13",
            "panel": "120", "locked": "50", "output": "60",
            "window_presents": "60", "window_generated": "50",
            "window_promoted": "50", "window_real_priority": "10",
            "window_synthetic_selected": "50",
            "window_synthetic_pair_created": "50",
            "dense_variant": "fragment-160x90-v36-epoch-bound-packed-mask",
        })
        normalized = []
        with mock.patch.object(
                MODULE, "_require_framegen_v35_diagnostic_hierarchy",
                side_effect=lambda record: normalized.append(record)):
            MODULE._require_framegen_v36_evidence_hierarchy(groups)
        self.assertEqual(normalized[0]["promoted"], "14")

        groups["dense_diagnostic_last_current_endpoint"] = "15"
        with mock.patch.object(
                MODULE, "_require_framegen_v35_diagnostic_hierarchy"), \
                self.assertRaisesRegex(RuntimeError, "impossible epoch evidence"):
            MODULE._require_framegen_v36_evidence_hierarchy(groups)

    def test_runner_parses_only_complete_schema37_timestamp_transport(self):
        def materialize(pattern, overrides):
            def replace(match):
                name = match.group(1)
                if name in overrides:
                    return str(overrides[name])
                if name == "role":
                    return "primary"
                if name == "proof_contract":
                    return MODULE._FRAMEGEN_V37_CONTRACT
                if name == "dense_variant":
                    return "fragment-128x72-v37-timestamp-resample"
                if name == "dense_diagnostic_mask_layout":
                    return "packed-nearest-bf-v1"
                return "1"
            return re.sub(
                r"\(\?P<([a-z0-9_]+)>[^)]*\)", replace, pattern
            ).replace(".*?", "producerHz=50.00 ")

        common = {
            "generator": 7, "display_id": 0, "proof_schema_version": 37,
            "health_sequence": 9, "presents": 120,
            "window_start_ns": 1_000_000_000,
            "window_end_ns": 2_000_000_000,
            "proof_evidence_presentation_epoch": 4,
            "proof_evidence_enqueued_in_epoch": 2,
            "endpoint_fifo_coalesced": 0,
            "endpoint_timestamp_corrections": 0,
            "dense_diagnostic_last_target_source_ns": 1_500_000_000,
        }
        base = materialize(MODULE.frame_gen.HEALTH_BASE_V37.pattern, common)
        extension = materialize(
            MODULE.frame_gen.HEALTH_DENSE_EXTENSION_V37.pattern, common)
        prefix = "08-14 12:00:00.000  4321  4322 I EmuFusionFrameGen: "
        with mock.patch.object(
                MODULE.frame_gen, "_v37_diagnostic_hierarchy", return_value=[]), \
                mock.patch.object(
                    MODULE.frame_gen, "_v37_output_accounting_hierarchy",
                    return_value=[]):
            records = MODULE._framegen_health_transport_records(
                prefix + base + "\n" + prefix + extension)
        self.assertEqual(37, records[0]["proof_schema_version"])
        self.assertEqual(1_500_000_000,
                         records[0]["dense_diagnostic_last_target_source_ns"])

        truncated = re.sub(
            r" endpointTimestampCorrections=\d+", "", base, count=1)
        self.assertNotEqual(base, truncated)
        with self.assertRaisesRegex(RuntimeError, "malformed or truncated"):
            MODULE._framegen_health_transport_records(
                prefix + truncated + "\n" + prefix + extension)

    def test_runner_parses_only_complete_schema38_vector_transport(self):
        def materialize(pattern, overrides):
            def replace(match):
                name = match.group(1)
                if name in overrides:
                    return str(overrides[name])
                if name == "role":
                    return "primary"
                if name == "proof_contract":
                    return MODULE._FRAMEGEN_V38_CONTRACT
                if name == "dense_variant":
                    return "fragment-128x72-v38-vector-trajectory"
                if name == "dense_diagnostic_mask_layout":
                    return "packed-nearest-bf-v1"
                return "1"
            return re.sub(
                r"\(\?P<([a-z0-9_]+)>[^)]*\)", replace, pattern
            ).replace(".*?", "producerHz=50.00 ")

        common = {
            "generator": 7, "display_id": 0, "proof_schema_version": 38,
            "health_sequence": 9, "presents": 120,
            "window_start_ns": 1_000_000_000,
            "window_end_ns": 2_000_000_000,
            "proof_evidence_presentation_epoch": 4,
            "proof_evidence_enqueued_in_epoch": 2,
            "endpoint_fifo_coalesced": 0,
            "endpoint_timestamp_corrections": 0,
            "dense_diagnostic_last_target_source_ns": 1_500_000_000,
        }
        base = materialize(MODULE.frame_gen.HEALTH_BASE_V38.pattern, common)
        extension = materialize(
            MODULE.frame_gen.HEALTH_DENSE_EXTENSION_V38.pattern, common)
        prefix = "08-14 12:00:00.000  4321  4322 I EmuFusionFrameGen: "
        with mock.patch.object(
                MODULE.frame_gen, "_v37_diagnostic_hierarchy", return_value=[]), \
                mock.patch.object(
                    MODULE.frame_gen, "_v37_output_accounting_hierarchy",
                    return_value=[]):
            records = MODULE._framegen_health_transport_records(
                prefix + base + "\n" + prefix + extension)
        self.assertEqual(38, records[0]["proof_schema_version"])
        self.assertEqual(MODULE._FRAMEGEN_V38_CONTRACT,
                         records[0]["proof_contract"])
        mixed_extension = extension.replace(
            "proofSchemaVersion=38", "proofSchemaVersion=37", 1
        ).replace(MODULE._FRAMEGEN_V38_CONTRACT,
                  MODULE._FRAMEGEN_V37_CONTRACT, 1)
        with self.assertRaisesRegex(RuntimeError, "identity mismatch"):
            MODULE._framegen_health_transport_records(
                prefix + base + "\n" + prefix + mixed_extension)

    def test_runner_parses_only_complete_schema39_present_timed_transport(self):
        def materialize(pattern, overrides):
            def replace(match):
                name = match.group(1)
                if name in overrides:
                    return str(overrides[name])
                if name == "role":
                    return "primary"
                if name == "proof_contract":
                    return MODULE._FRAMEGEN_V39_CONTRACT
                if name == "dense_variant":
                    return "fragment-128x72-v39-present-timed-vector-trajectory"
                if name == "dense_diagnostic_mask_layout":
                    return "packed-nearest-bf-v1"
                if name == "presentation_timing_mode":
                    return "egl-android-next-vsync"
                return "1"
            return re.sub(
                r"\(\?P<([a-z0-9_]+)>[^)]*\)", replace, pattern
            ).replace(".*?", "producerHz=50.00 ")

        common = {
            "generator": 7, "display_id": 0, "proof_schema_version": 39,
            "health_sequence": 9, "presents": 120,
            "window_start_ns": 1_000_000_000,
            "window_end_ns": 2_000_000_000,
            "proof_evidence_presentation_epoch": 4,
            "proof_evidence_enqueued_in_epoch": 2,
            "endpoint_fifo_coalesced": 0,
            "endpoint_timestamp_corrections": 0,
            "dense_diagnostic_last_target_source_ns": 1_500_000_000,
            "presentation_timing_mode": "egl-android-next-vsync",
            "cadence_reject_consecutive_windows": 3,
        }
        base = materialize(MODULE.frame_gen.HEALTH_BASE_V39.pattern, common)
        extension = materialize(
            MODULE.frame_gen.HEALTH_DENSE_EXTENSION_V39.pattern, common)
        prefix = "08-14 12:00:00.000  4321  4322 I EmuFusionFrameGen: "
        with mock.patch.object(
                MODULE.frame_gen, "_v37_diagnostic_hierarchy", return_value=[]), \
                mock.patch.object(
                    MODULE.frame_gen, "_v37_output_accounting_hierarchy",
                    return_value=[]):
            records = MODULE._framegen_health_transport_records(
                prefix + base + "\n" + prefix + extension)
        self.assertEqual(39, records[0]["proof_schema_version"])
        self.assertEqual("egl-android-next-vsync",
                         records[0]["presentation_timing_mode"])
        self.assertEqual(3, records[0]["cadence_reject_consecutive_windows"])
        for field in ("presentationTimingMode",
                      "cadenceRejectConsecutiveWindows"):
            with self.subTest(field=field), self.assertRaisesRegex(
                    RuntimeError, "malformed or truncated"):
                truncated = re.sub(
                    rf" {field}=[a-z0-9-]+", "", base, count=1)
                self.assertNotEqual(base, truncated)
                MODULE._framegen_health_transport_records(
                    prefix + truncated + "\n" + prefix + extension)

    def test_nes_every_title_uses_device_clocked_launch_and_runtime_geometry(self):
        source = (TOOLS / "run_runtime_acceptance_qa.py").read_text(encoding="utf-8")
        launch = source.split("def run_game_from_system_menu", 1)[1].split(
            "def require_safe_motion_bound", 1)[0]
        self.assertIn('if case.folder == "nes":', launch)
        self.assertIn("begin_nes_launch_capture", launch)
        capture = source.split("def begin_nes_launch_capture", 1)[1].split(
            "\ndef finish_visible_return_recording", 1
        )[0]
        self.assertLess(capture.index("begin_visible_return_recording"),
                        capture.index("inject_nes_launch_device_clocked"))
        self.assertIn("require_nes_runtime_geometry", launch)
        self.assertIn("calibration_fixture=nes_fixture is not None", launch)
        with tempfile.TemporaryDirectory() as folder:
            gameplay = Path(folder) / "gameplay.png"
            image = Image.new("RGB", (1920, 1080), (0, 0, 0))
            ImageDraw.Draw(image).rectangle((240, 0, 1679, 1079),
                                            fill=(255, 255, 255))
            image.save(gameplay)
            local = (
                "Core frame presented engine=mesen system=nes sequence=1 size=256x240 "
                "nonblack=1 surface=1440x1080 coreAspect=1.333333 "
                "aspect=1.3333334 destination=0,0 1440x1080"
            )
            proof = MODULE.require_nes_runtime_geometry(local, gameplay)
            self.assertTrue(proof["fullHeight"])
            self.assertEqual(proof["runtimeCoordinateSpace"],
                             "local-aspect-surface")
            self.assertEqual(proof["runtimeDestination"], "0,0 1440x1080")
            self.assertEqual(proof["globalScreenshot"]["activeLeft"], 240)
            self.assertEqual(proof["globalScreenshot"]["activeHeight"], 1080)

            global_surface = local.replace(
                "surface=1440x1080", "surface=1920x1080"
            ).replace("destination=0,0", "destination=240,0")
            self.assertEqual(MODULE.require_nes_runtime_geometry(
                global_surface, gameplay
            )["runtimeCoordinateSpace"], "global-panel-surface")

            invalid = (
                local.replace("destination=0,0", "destination=0,1"),
                local.replace("1440x1080", "1440x1079", 1),
                local.replace("aspect=1.3333334", "aspect=1.7777778"),
                local.replace("destination=0,0 1440x1080",
                              "destination=0,0 1430x1080"),
            )
            for record in invalid:
                with self.subTest(record=record), self.assertRaises(RuntimeError):
                    MODULE.require_nes_runtime_geometry(record, gameplay)

            clipped = Path(folder) / "clipped.png"
            clipped_image = Image.new("RGB", (1920, 1080), (0, 0, 0))
            ImageDraw.Draw(clipped_image).rectangle(
                (240, 30, 1679, 1049), fill=(255, 255, 255)
            )
            clipped_image.save(clipped)
            with self.assertRaisesRegex(RuntimeError, "global screenshot"):
                MODULE.require_nes_runtime_geometry(local, clipped)

    def test_r30_real_nes_geometry_uses_runtime_rectangle_not_bright_edge_inference(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            gameplay = root / "10-yard-fight.png"
            image = Image.new("RGB", (1920, 1080), "black")
            # Authored black space remains inside both valid 4:3 edges, as in
            # the exact r30 capture. Material pixels still touch panel top and
            # bottom without calibration-ROM edge markers.
            ImageDraw.Draw(image).rectangle(
                (400, 0, 1519, 1079), fill=(80, 38, 18)
            )
            image.save(gameplay)
            local = (
                "Core frame presented engine=mesen system=nes sequence=1 "
                "size=256x240 nonblack=1 surface=1440x1080 "
                "coreAspect=1.333333 aspect=1.3333334 "
                "destination=0,0 1440x1080"
            )
            proof = MODULE.require_nes_runtime_geometry(
                local, gameplay, calibration_fixture=False
            )
            self.assertFalse(proof["calibrationFixture"])
            self.assertEqual(proof["runtimeCoordinateSpace"],
                             "local-aspect-surface")
            pixels = proof["globalScreenshot"]
            self.assertEqual(pixels["expectedActiveLeft"], 240)
            self.assertEqual(pixels["expectedActiveWidth"], 1440)
            self.assertTrue(pixels["fullHeight"])
            self.assertGreater(pixels["topEdgeMaterialFraction"], 0.7)
            self.assertGreater(pixels["bottomEdgeMaterialFraction"], 0.7)

            # The identical commercial screenshot must not satisfy the
            # calibration ROM's independently authored white-marker oracle.
            with self.assertRaisesRegex(RuntimeError,
                                        "calibration global screenshot"):
                MODULE.require_nes_runtime_geometry(
                    local, gameplay, calibration_fixture=True
                )

    def test_real_nes_geometry_rejects_bars_pillars_shift_and_runtime_mismatch(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            local = (
                "Core frame presented engine=mesen system=nes sequence=1 "
                "size=256x240 nonblack=1 surface=1440x1080 "
                "coreAspect=1.333333 aspect=1.3333334 "
                "destination=0,0 1440x1080"
            )

            def save(name, box):
                path = root / name
                image = Image.new("RGB", (1920, 1080), "black")
                ImageDraw.Draw(image).rectangle(box, fill=(90, 45, 20))
                image.save(path)
                return path

            bars = save("bars.png", (400, 32, 1519, 1047))
            shifted = save("shifted.png", (220, 0, 1659, 1079))
            bad_pillar = save("pillar.png", (400, 0, 1519, 1079))
            pillar_image = Image.open(bad_pillar).convert("RGB")
            ImageDraw.Draw(pillar_image).rectangle(
                (0, 160, 30, 919), fill=(255, 255, 255)
            )
            pillar_image.save(bad_pillar)
            cases = (
                (bars, "top/bottom bar or clipped"),
                (shifted, "nonblack outer pillars"),
                (bad_pillar, "nonblack outer pillars"),
            )
            for path, message in cases:
                with self.subTest(path=path.name), self.assertRaisesRegex(
                        RuntimeError, "real-title global screenshot") as raised:
                    MODULE.require_nes_runtime_geometry(
                        local, path, calibration_fixture=False
                    )
                self.assertIn(message, str(raised.exception.__cause__))

            valid = save("valid.png", (400, 0, 1519, 1079))
            wrong_records = (
                local.replace("aspect=1.3333334", "aspect=1.7777778"),
                local.replace("destination=0,0 1440x1080",
                              "destination=0,20 1440x1060"),
                local.replace("surface=1440x1080", "surface=1920x1080"),
            )
            for record in wrong_records:
                with self.subTest(record=record), self.assertRaises(RuntimeError):
                    MODULE.require_nes_runtime_geometry(
                        record, valid, calibration_fixture=False
                    )

    def test_r31_ten_yard_player_state_is_bound_to_cursor_pixels(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            text = "10-YARD FIGHT 1 PLAYER 2 PLAYERS 1985 IREM NINTENDO"

            def menu(name, cursor_y):
                path = root / name
                image = Image.new("RGB", (1920, 1080), "black")
                ImageDraw.Draw(image).rectangle(
                    (700, cursor_y, 740, cursor_y + 24), fill=(220, 45, 20)
                )
                image.save(path)
                return path

            one = menu("one.png", 660)
            two = menu("two.png", 730)
            self.assertEqual(MODULE.real_nes_gameplay_state(
                "10-Yard Fight", text, one
            ), "10-yard-1-player")
            self.assertEqual(MODULE.real_nes_gameplay_state(
                "10-Yard Fight", text, two
            ), "10-yard-2-player")
            with self.assertRaisesRegex(RuntimeError, "cursor is absent/ambiguous"):
                MODULE.real_nes_gameplay_state(
                    "10-Yard Fight", text, menu("none.png", 500)
                )
            with self.assertRaisesRegex(RuntimeError, "cursor-bound"):
                MODULE.real_nes_gameplay_state("10-Yard Fight", text)

    def test_real_nes_gameplay_frames_require_sustained_motion_and_no_title(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)

            def frame(index, colour):
                path = root / f"field-{index}.png"
                image = Image.new("RGB", (1920, 1080), "black")
                ImageDraw.Draw(image).rectangle(
                    (400, 0, 1519, 1079), fill=colour
                )
                image.save(path)
                return path

            moving = [frame(index, (40 + index * 18, 30, 15))
                      for index in range(4)]
            with mock.patch.object(MODULE, "ocr", return_value="00:00 1ST 10 10"):
                result = MODULE.analyze_real_nes_gameplay_frames(
                    moving, "10-Yard Fight"
                )
            self.assertEqual(result["changedPairs"], 3)
            self.assertTrue(result["titleMenuAbsent"])

            with mock.patch.object(MODULE, "ocr", return_value="00:00 1ST"), \
                    self.assertRaisesRegex(RuntimeError, "sustain material"):
                MODULE.analyze_real_nes_gameplay_frames(
                    [moving[0], moving[0], moving[0]], "10-Yard Fight"
                )

            title = frame(9, (70, 30, 15))
            texts = {
                moving[0].name: "00:00 1ST",
                moving[1].name: "00:01 1ST",
                title.name: "10-YARD FIGHT 2 PLAYERS",
            }
            with mock.patch.object(
                    MODULE, "ocr", side_effect=lambda path: texts[path.name]), \
                    mock.patch.object(MODULE, "_ten_yard_selected_player",
                                      return_value=2), \
                    self.assertRaisesRegex(RuntimeError, "regressed to a title"):
                MODULE.analyze_real_nes_gameplay_frames(
                    [moving[0], moving[1], title], "10-Yard Fight"
                )

    def test_real_nes_activation_actions_are_title_state_specific(self):
        controller = mock.Mock(
            STOP=314, START=315, LEFT=546, A=304
        )
        cases = (
            ("10-Yard Fight", "10-yard-2-player", [314]),
            ("10-Yard Fight", "10-yard-1-player", [315]),
            ("10-Yard Fight", "10-yard-skill", [315]),
            ("1943: The Battle of Midway", "1943-start-menu", [315]),
            ("8 Eyes", "8-eyes-player-select", [546, 315]),
            ("8 Eyes", "8-eyes-initiate-continue", [315]),
            ("8 Eyes", "8-eyes-level-select", [304, 315]),
        )
        for title, state, expected_codes in cases:
            with self.subTest(title=title, state=state), \
                    mock.patch.object(MODULE.time, "sleep"):
                controller.reset_mock()
                actions = MODULE._drive_real_nes_menu_state(
                    controller, title, state, 1, 100
                )
                self.assertEqual(
                    [call.args[0] for call in controller.key.call_args_list],
                    expected_codes,
                )
                self.assertEqual(len(actions), len(expected_codes))
                self.assertEqual([item["controllerCode"] for item in actions],
                                 expected_codes)

    def test_r32_gameplay_probe_returns_immediately_on_recognized_menu(self):
        controller = mock.Mock(RIGHT=1, LEFT=2, UP=3, DOWN=4)
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(MODULE, "screenshot"), \
                mock.patch.object(MODULE, "ocr", return_value="menu"), \
                mock.patch.object(MODULE, "real_nes_gameplay_state",
                                  return_value="10-yard-1-player"), \
                mock.patch.object(MODULE.time, "sleep") as sleeper:
            frames, states, elapsed, samples = MODULE._capture_real_nes_gameplay_probe(
                Path("/adb"), "serial", controller, Path(folder), "title-02",
                "10-Yard Fight", 1,
            )
        self.assertEqual(len(frames), 1)
        self.assertEqual(states, ["10-yard-1-player"])
        self.assertEqual(elapsed, 0)
        self.assertEqual(len(samples), 1)
        controller.key.assert_not_called()
        sleeper.assert_not_called()

    def test_r32_menu_during_sustained_probe_aborts_without_more_inputs(self):
        controller = mock.Mock(RIGHT=1, LEFT=2, UP=3, DOWN=4)
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(MODULE, "screenshot"), \
                mock.patch.object(MODULE, "ocr", return_value="frame"), \
                mock.patch.object(
                    MODULE, "real_nes_gameplay_state",
                    side_effect=(None, None, "10-yard-1-player")), \
                mock.patch.object(MODULE.time, "monotonic_ns",
                                  side_effect=(100, 200, 1_000_000_100,
                                               2_000_000_100)), \
                mock.patch.object(MODULE.time, "sleep") as sleeper:
            frames, states, elapsed, samples = MODULE._capture_real_nes_gameplay_probe(
                Path("/adb"), "serial", controller, Path(folder), "title-02",
                "10-Yard Fight", 2,
            )
        self.assertEqual(len(frames), 3)
        self.assertEqual(states, [None, None, "10-yard-1-player"])
        self.assertEqual(elapsed, 2_000_000_000)
        self.assertEqual(controller.key.call_count, 2)
        self.assertEqual(sleeper.call_count, 2)

    def test_r32_sustained_clock_starts_after_first_menu_free_sample(self):
        controller = mock.Mock(RIGHT=1, LEFT=2, UP=3, DOWN=4)
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(MODULE, "screenshot"), \
                mock.patch.object(MODULE, "ocr", return_value="gameplay"), \
                mock.patch.object(MODULE, "real_nes_gameplay_state",
                                  return_value=None), \
                mock.patch.object(MODULE.time, "monotonic_ns",
                                  side_effect=(
                                      1_000, 1_100, 3_000_001_000,
                                      6_000_001_000, 9_000_001_000,
                                      12_000_001_000, 15_000_001_000,
                                      18_000_001_000, 19_000_001_000)), \
                mock.patch.object(MODULE.time, "sleep"):
            frames, states, elapsed, samples = MODULE._capture_real_nes_gameplay_probe(
                Path("/adb"), "serial", controller, Path(folder), "title-02",
                "10-Yard Fight", 3,
            )
        self.assertEqual(len(frames), 8)
        self.assertEqual(states, [None] * 8)
        self.assertEqual(elapsed, 19_000_000_000)
        self.assertEqual(len(samples), 8)
        self.assertEqual(controller.key.call_count, 7)

    def test_real_nes_readiness_requires_three_nonzero_health_windows(self):
        frames = [Path(f"frame-{index}.png") for index in range(8)]
        samples = [{"path": str(path), "hostMonotonicNs": index * 3_000_000_001,
                    "state": None} for index, path in enumerate(frames)]
        baseline = {"window_end_ns": 0, "window_promoted": 60,
                    "pid": 123, "generator": 7}
        health = [
            {"window_end_ns": index + 1, "window_promoted": 60,
             "pid": 123, "generator": 7}
            for index in range(3)
        ]
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(
                    MODULE, "_capture_real_nes_gameplay_probe",
                    return_value=(frames, [None] * 8, 21_000_000_007,
                                  samples)), \
                mock.patch.object(MODULE, "_live_nes_log_text",
                                  side_effect=("before", "after")), \
                mock.patch.object(MODULE, "_framegen_health_records",
                                  side_effect=([baseline], [baseline, *health])), \
                mock.patch.object(MODULE, "analyze_real_nes_gameplay_frames",
                                  return_value={"frames": [
                                      {"path": str(path)} for path in frames
                                  ], "sustainedMaterialMotion": True}):
            result = MODULE.prepare_real_nes_gameplay(
                Path("/adb"), "serial", mock.Mock(), Path(folder), "title-02",
                "10-Yard Fight", {"pid": 1},
            )
        self.assertTrue(result["saveStatePreserved"])
        self.assertEqual(len(result["attempts"][0]["healthWindows"]), 3)
        self.assertEqual(result["actions"], [])

    def test_real_nes_readiness_does_not_accept_zero_promotion_health(self):
        frames = [Path(f"frame-{index}.png") for index in range(8)]
        samples = [{"path": str(path), "hostMonotonicNs": index * 3_000_000_001,
                    "state": None} for index, path in enumerate(frames)]
        baseline = {"window_end_ns": 0, "window_promoted": 60,
                    "pid": 123, "generator": 7}
        zero = [{"window_end_ns": index + 1,
                 "window_promoted": 0 if index == 2 else 60,
                 "pid": 123, "generator": 7}
                for index in range(3)]
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(
                    MODULE, "_capture_real_nes_gameplay_probe",
                    return_value=(frames, [None] * 8, 21_000_000_007,
                                  samples)), \
                mock.patch.object(MODULE, "_live_nes_log_text",
                                  side_effect=[value for _ in range(6)
                                               for value in ("before", "after")]), \
                mock.patch.object(MODULE, "_framegen_health_records",
                                  side_effect=[value for _ in range(6)
                                               for value in ([baseline],
                                                             [baseline, *zero])]), \
                mock.patch.object(MODULE, "analyze_real_nes_gameplay_frames",
                                  return_value={"frames": [
                                      {"path": str(path)} for path in frames
                                  ]}), \
                mock.patch.object(MODULE, "_drive_real_nes_menu_state",
                                  return_value=["unpause"]), \
                self.assertRaisesRegex(RuntimeError,
                                       "never reached sustained gameplay"):
            MODULE.prepare_real_nes_gameplay(
                Path("/adb"), "serial", mock.Mock(), Path(folder), "title-02",
                "10-Yard Fight", {"pid": 1},
            )

    def test_real_nes_readiness_requires_strictly_more_than_19_seconds(self):
        frames = [Path(f"frame-{index}.png") for index in range(8)]
        baseline = {"window_end_ns": 0, "window_promoted": 60,
                    "pid": 123, "generator": 7}
        health = [{"window_end_ns": index + 1, "window_promoted": 60,
                   "pid": 123, "generator": 7} for index in range(3)]
        for elapsed in (18_999_000_000, 19_000_000_000):
            samples = [{"path": str(path),
                        "hostMonotonicNs": round(index * elapsed / 7),
                        "state": None}
                       for index, path in enumerate(frames)]
            with self.subTest(elapsed=elapsed), tempfile.TemporaryDirectory() as folder, \
                    mock.patch.object(
                        MODULE, "_capture_real_nes_gameplay_probe",
                        return_value=(frames, [None] * 8, elapsed, samples)), \
                    mock.patch.object(MODULE, "_live_nes_log_text",
                                      side_effect=[value for _ in range(6)
                                                   for value in ("before", "after")]), \
                    mock.patch.object(MODULE, "_framegen_health_records",
                                      side_effect=[value for _ in range(6)
                                                   for value in ([baseline],
                                                                 [baseline, *health])]), \
                    mock.patch.object(MODULE, "analyze_real_nes_gameplay_frames",
                                      return_value={"frames": []}), \
                    mock.patch.object(MODULE, "_drive_real_nes_menu_state",
                                      return_value=[]), \
                    self.assertRaisesRegex(RuntimeError,
                                           "never reached sustained gameplay"):
                MODULE.prepare_real_nes_gameplay(
                    Path("/adb"), "serial", mock.Mock(), Path(folder), "title-02",
                    "10-Yard Fight", {"pid": 1},
                )

    def test_real_nes_readiness_rejects_cross_pid_or_generator_health(self):
        frames = [Path(f"frame-{index}.png") for index in range(8)]
        samples = [{"path": str(path), "hostMonotonicNs": index + 1,
                    "state": None} for index, path in enumerate(frames)]
        baseline = {"window_end_ns": 1, "window_promoted": 60,
                    "pid": 123, "generator": 7}
        foreign = {"window_end_ns": 2, "window_promoted": 60,
                   "pid": 999, "generator": 7}
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(MODULE, "_capture_real_nes_gameplay_probe",
                                  return_value=(frames, [None] * 8,
                                                20_000_000_000, samples)), \
                mock.patch.object(MODULE, "_live_nes_log_text",
                                  side_effect=("before", "after")), \
                mock.patch.object(MODULE, "_framegen_health_records",
                                  side_effect=([baseline], [baseline, foreign])), \
                self.assertRaisesRegex(RuntimeError, "crossed PID/generator"):
            MODULE.prepare_real_nes_gameplay(
                Path("/adb"), "serial", mock.Mock(), Path(folder), "title-02",
                "10-Yard Fight", {"pid": 1},
            )

    def test_static_gameplay_recovery_binds_last_observed_sample_timestamp(self):
        frames = [Path(f"frame-{index}.png") for index in range(8)]
        samples = [{"path": str(path),
                    "hostMonotonicNs": 1_000_000_000 + index * 3_000_000_001,
                    "state": None} for index, path in enumerate(frames)]
        baseline = {"window_end_ns": 0, "window_promoted": 60,
                    "pid": 123, "generator": 7}
        health = [{"window_end_ns": index + 1, "window_promoted": 60,
                   "pid": 123, "generator": 7} for index in range(3)]
        drive = mock.Mock(return_value=[])
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(MODULE, "_capture_real_nes_gameplay_probe",
                                  return_value=(frames, [None] * 8,
                                                21_000_000_007, samples)), \
                mock.patch.object(MODULE, "_live_nes_log_text",
                                  side_effect=[value for _ in range(6)
                                               for value in ("before", "after")]), \
                mock.patch.object(MODULE, "_framegen_health_records",
                                  side_effect=[value for _ in range(6)
                                               for value in ([baseline],
                                                             [baseline, *health])]), \
                mock.patch.object(MODULE, "analyze_real_nes_gameplay_frames",
                                  side_effect=RuntimeError(
                                      "did not sustain material frame changes")), \
                mock.patch.object(MODULE, "_drive_real_nes_menu_state", drive), \
                self.assertRaisesRegex(RuntimeError,
                                       "never reached sustained gameplay"):
            MODULE.prepare_real_nes_gameplay(
                Path("/adb"), "serial", mock.Mock(), Path(folder), "title-02",
                "10-Yard Fight", {"pid": 1},
            )
        self.assertEqual(drive.call_count, 6)
        self.assertTrue(all(call.args[2] == "static-gameplay"
                            for call in drive.call_args_list))
        self.assertTrue(all(call.args[4] == samples[-1]["hostMonotonicNs"]
                            for call in drive.call_args_list))

    def test_real_nes_proof_health_rejects_any_zero_or_cross_identity_window(self):
        baseline = {"window_end_ns": 100, "pid": 123, "generator": 7}
        valid = [baseline, *[
            {"window_end_ns": 200 + index * 100, "window_promoted": 60,
             "pid": 123, "generator": 7}
            for index in range(4)
        ]]
        proof = MODULE.require_real_nes_proof_health(valid, baseline)
        self.assertEqual(proof["windowCount"], 4)
        self.assertEqual(proof["zeroPromotionWindows"], 0)
        zero = [dict(record) for record in valid]
        zero[2]["window_promoted"] = 0
        with self.assertRaisesRegex(RuntimeError, "zero-promotion"):
            MODULE.require_real_nes_proof_health(zero, baseline)
        foreign = [dict(record) for record in valid]
        foreign[3]["pid"] = 999
        with self.assertRaisesRegex(RuntimeError, "crossed PID/generator"):
            MODULE.require_real_nes_proof_health(foreign, baseline)
        with self.assertRaisesRegex(RuntimeError, "fewer than three"):
            MODULE.require_real_nes_proof_health(valid[:3], baseline)

    def test_real_nes_run_arms_proof_only_after_readiness(self):
        source = inspect.getsource(MODULE.run_game_from_system_menu)
        self.assertLess(source.index("prepare_real_nes_gameplay"),
                        source.index('"emufusion_framegen_proof", "1"'))
        self.assertIn("nesRealGameplayReadiness", source)

    def test_abandoned_nes_capture_cleanup_is_idempotent(self):
        class Process:
            def __init__(self):
                self.terminated = 0

            def poll(self):
                return None

            def terminate(self):
                self.terminated += 1

            def wait(self, timeout):
                return 0

        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "capture.txt"
        handle = path.open("wb")
        handle.write(b"raw\n")
        process = Process()
        capture = {"kind": "kernel", "path": path, "handle": handle,
                   "process": process, "finalized": False}
        MODULE.ACTIVE_NES_CAPTURES.append(capture)
        self.assertEqual(MODULE.finish_abandoned_nes_captures(), [])
        self.assertEqual(process.terminated, 1)
        self.assertEqual(MODULE.finish_abandoned_nes_captures(), [])
        self.assertEqual(process.terminated, 1)

    def test_nes_samples_fixture_plus_three_real_titles_and_resumes_each(self):
        source = (TOOLS / "run_runtime_acceptance_qa.py").read_text(encoding="utf-8")
        self.assertIn('requested_titles = max(titles, 4) if case.folder == "nes"',
                      source)
        self.assertEqual(MODULE.NES_REAL_QUALIFICATION_TITLES, (
            "10-Yard Fight", "1943: The Battle of Midway", "8 Eyes",
        ))
        self.assertIn('"calibrationFixture": True, "realGame": False', source)
        self.assertIn('"calibrationFixture": False, "realGame": True', source)
        self.assertIn("def nes_real_title_resume_evidence", source)
        self.assertIn("nes-real-title-enter-pause", source)
        self.assertIn("sampled real NES title did not reach an exact stable Start pause",
                      source)
        self.assertIn('"sampledRealTitle": True', source)

    def test_indexed_fixture_uses_exact_title_and_hash_not_source_basename(self):
        source = (TOOLS / "run_runtime_acceptance_qa.py").read_text(encoding="utf-8")
        lookup = source.split("def indexed_nes_qualification", 1)[1].split(
            "def indexed_title_rom_identity", 1
        )[0]
        self.assertIn("NES_QUALIFICATION_SHA256", lookup)
        self.assertIn('fixture_title = normalize("Lucent Callback Test")', lookup)
        self.assertIn("Path(path).name", lookup)
        self.assertNotIn("Path(path).name == NES_QUALIFICATION_FILE", lookup)

    def test_indexed_fixture_accepts_importer_destination_filename(self):
        case = MODULE.SystemCase("nes", (), ("mesen",), 1)
        path = "/sdcard/Games/nes/Lucent Callback Test.nes"
        with mock.patch.object(MODULE, "metadata_title_files", return_value={
                "lucentcallbacktest": {path}}), mock.patch.object(
                    MODULE, "remote_sha256",
                    return_value=MODULE.NES_QUALIFICATION_SHA256):
            result = MODULE.indexed_nes_qualification(
                Path("/adb"), "serial", case,
                ["000000|Lucent Callback Test"],
            )
        self.assertEqual(result["path"], path)
        self.assertEqual(result["file"], "Lucent Callback Test.nes")

    def test_import_screensaver_is_physically_woken_before_menu_readiness(self):
        source = (TOOLS / "run_runtime_acceptance_qa.py").read_text(encoding="utf-8")
        wake = source.index('"physical-wake-after-import"')
        readiness = source.index("wait_visible_menu(args.adb, args.serial, output)")
        run_system = source.index("record = run_system(")
        self.assertLess(wake, readiness)
        self.assertLess(readiness, run_system)
        self.assertIn("controller.key(\n        controller.DOWN", source)
        # Wake is not a replacement for the OCR gate: the existing readiness
        # function must still require an interactive view and reject splash.
        readiness_body = source.split("def wait_visible_menu", 1)[1].split(
            "def changed_pixels", 1
        )[0]
        self.assertIn("interactive = (", readiness_body)
        self.assertIn("if interactive and not splash", readiness_body)

    def test_nes_fixture_stage_and_cleanup_are_ownership_scoped(self):
        fixture = ROOT / "engines/build/qa-fixtures/lucent-callback-test.nes"
        completed = mock.Mock(returncode=0, stdout="pushed")
        target = "/storage/emulated/0/Games/nes/Lucent Callback Test.nes"
        identity = ("/storage/emulated/0/Download/"
                    "Lucent Callback Test.nes:24592")
        row = {"sourceIdentity": identity, "system": "nes",
               "title": "Lucent Callback Test", "file": target}
        with mock.patch.object(MODULE, "exact_remote_nes_fixture_paths",
                               side_effect=[set(), {target}]), \
                mock.patch.object(MODULE, "read_import_registry",
                                  side_effect=[{}, {identity: row}]), \
                mock.patch.object(MODULE, "remote_canonical_path",
                                  side_effect=lambda _a, _s, value:
                                  MODULE.canonical_shared_path(value)), \
                mock.patch.object(MODULE, "remote_path_exists", return_value=False), \
                mock.patch.object(MODULE, "remote_sha256",
                                  return_value=MODULE.NES_QUALIFICATION_SHA256), \
                mock.patch.object(MODULE.subprocess, "run", return_value=completed), \
                mock.patch.object(MODULE, "wait_import_complete"), \
                mock.patch.object(MODULE, "library_index", return_value={}), \
                mock.patch.object(MODULE, "resolve_live_nes_qualification",
                                  return_value={"title": "Lucent Callback Test",
                                                "path": "/sdcard/Games/nes/"
                                                        "Lucent Callback Test.nes",
                                                "sha256": MODULE.NES_QUALIFICATION_SHA256}), \
                mock.patch.object(MODULE.qa, "adb"):
            stage = MODULE.stage_nes_qualification_fixture(
                Path("/adb"), "serial", fixture
            )
        self.assertTrue(stage["createdByRun"])
        self.assertEqual(stage["createdPaths"], [target])
        self.assertEqual(stage["indexedPath"], target)
        self.assertEqual(stage["sourceIdentity"], identity)
        with mock.patch.object(MODULE, "remote_sha256",
                               return_value=MODULE.NES_QUALIFICATION_SHA256), \
                mock.patch.object(MODULE, "read_import_registry",
                                  side_effect=[{identity: row}, {}]), \
                mock.patch.object(MODULE, "remote_canonical_path",
                                  side_effect=lambda _a, _s, value:
                                  MODULE.canonical_shared_path(value)), \
                mock.patch.object(MODULE, "delete_owned_nes_registry_row",
                                  return_value={"ok": True}), \
                mock.patch.object(MODULE, "remote_path_exists", return_value=False), \
                mock.patch.object(MODULE.qa, "adb"), \
                mock.patch.object(MODULE, "wait_import_complete"), \
                mock.patch.object(MODULE, "exact_remote_nes_fixture_paths",
                                  return_value=set()), \
                mock.patch.object(MODULE, "library_index",
                                  return_value={"systems": {"nes": []}}):
            cleanup = MODULE.cleanup_nes_qualification_fixture(
                Path("/adb"), "serial", stage
            )
        self.assertTrue(cleanup["absenceVerified"])
        self.assertEqual(set(cleanup["removedPaths"]), set(stage["createdPaths"]))

    def test_preexisting_nes_fixture_is_never_deleted(self):
        owner = "/storage/emulated/0/Games/nes/lucent-callback-test.nes"
        fixture = ROOT / "engines/build/qa-fixtures/lucent-callback-test.nes"
        identity = "/storage/emulated/0/Download/owner-copy.nes:24592"
        row = {"sourceIdentity": identity, "system": "nes",
               "title": "Lucent Callback Test", "file": owner}
        with mock.patch.object(MODULE, "exact_remote_nes_fixture_paths",
                               return_value={owner}), \
                mock.patch.object(MODULE, "read_import_registry",
                                  return_value={identity: row}), \
                mock.patch.object(MODULE, "remote_canonical_path",
                                  side_effect=lambda _a, _s, value:
                                  MODULE.canonical_shared_path(value)), \
                mock.patch.object(MODULE, "remote_sha256",
                                  return_value=MODULE.NES_QUALIFICATION_SHA256), \
                mock.patch.object(MODULE, "library_index", return_value={}), \
                mock.patch.object(MODULE, "resolve_live_nes_qualification",
                                  return_value={"title": "Lucent Callback Test",
                                                "path": owner,
                                                "sha256": MODULE.NES_QUALIFICATION_SHA256}), \
                mock.patch.object(MODULE.qa, "adb") as adb_call:
            stage = MODULE.stage_nes_qualification_fixture(
                Path("/adb"), "serial", fixture
            )
            cleanup = MODULE.cleanup_nes_qualification_fixture(
                Path("/adb"), "serial", stage
            )
        self.assertFalse(stage["createdByRun"])
        self.assertTrue(cleanup["preexistingPreserved"])
        adb_call.assert_not_called()

    def test_stage_failure_rolls_back_only_new_exact_hash_paths(self):
        fixture = ROOT / "engines/build/qa-fixtures/lucent-callback-test.nes"
        source = "/storage/emulated/0/Download/Lucent Callback Test.nes"
        target = "/storage/emulated/0/Games/nes/Lucent Callback Test.nes"
        completed = mock.Mock(returncode=0, stdout="pushed")
        with mock.patch.object(
                MODULE, "exact_remote_nes_fixture_paths",
                side_effect=[set(), {source, target}, set()]), \
                mock.patch.object(MODULE, "read_import_registry",
                                  side_effect=[{}, {}, {}]), \
                mock.patch.object(MODULE, "remote_canonical_path",
                                  side_effect=lambda _a, _s, value:
                                  MODULE.canonical_shared_path(value)), \
                mock.patch.object(MODULE, "remote_path_exists",
                                  side_effect=[False, True, True, False, False]), \
                mock.patch.object(MODULE, "remote_sha256",
                                  return_value=MODULE.NES_QUALIFICATION_SHA256), \
                mock.patch.object(MODULE.subprocess, "run", return_value=completed), \
                mock.patch.object(MODULE, "wait_import_complete",
                                  side_effect=[RuntimeError("import failed"), {}]), \
                mock.patch.object(MODULE.qa, "adb") as adb_call:
            with self.assertRaisesRegex(RuntimeError, "import failed"):
                MODULE.stage_nes_qualification_fixture(
                    Path("/adb"), "serial", fixture
                )
        removed = {str(call.args[-1]).removeprefix("rm -f ")
                   for call in adb_call.call_args_list
                   if len(call.args) >= 1 and
                   str(call.args[-1]).startswith("rm -f ")}
        self.assertEqual(removed, {shlex.quote(source), shlex.quote(target)})

    def test_remote_path_canonicalization_is_quoted_and_mount_alias_safe(self):
        raw = "/sdcard/Games/nes/Lucent Callback Test.nes"
        canonical = "/storage/emulated/0/Games/nes/Lucent Callback Test.nes"
        completed = mock.Mock(returncode=0, stdout=canonical + "\n")
        with mock.patch.object(MODULE.qa, "adb", return_value=completed) as adb_call:
            resolved = MODULE.remote_canonical_path(
                Path("/adb"), "serial", raw
            )
        self.assertEqual(resolved, canonical)
        self.assertEqual(
            adb_call.call_args.args,
            (Path("/adb"), "serial", "shell",
             "readlink -f -- " + shlex.quote(raw)),
        )

        find_result = mock.Mock(returncode=0, stdout=raw + "\n")
        with mock.patch.object(MODULE.qa, "adb", return_value=find_result), \
                mock.patch.object(MODULE, "remote_sha256",
                                  return_value=MODULE.NES_QUALIFICATION_SHA256), \
                mock.patch.object(MODULE, "remote_canonical_path",
                                  return_value=canonical):
            paths = MODULE.exact_remote_nes_fixture_paths(
                Path("/adb"), "serial"
            )
        self.assertEqual(paths, {canonical})

    def test_true_different_indexed_path_is_rejected_and_rolled_back(self):
        fixture = ROOT / "engines/build/qa-fixtures/lucent-callback-test.nes"
        target = "/storage/emulated/0/Games/nes/Lucent Callback Test.nes"
        other = "/storage/emulated/0/Games/other/Lucent Callback Test.nes"
        completed = mock.Mock(returncode=0, stdout="pushed")
        resolved = {"title": "Lucent Callback Test", "path": other,
                    "sha256": MODULE.NES_QUALIFICATION_SHA256}
        with mock.patch.object(MODULE, "read_import_registry",
                               side_effect=[{}, {}, {}]), \
                mock.patch.object(MODULE, "exact_remote_nes_fixture_paths",
                                  side_effect=[set(), {target}, {target}, set()]), \
                mock.patch.object(MODULE, "remote_canonical_path",
                                  side_effect=lambda _a, _s, value:
                                  MODULE.canonical_shared_path(value)), \
                mock.patch.object(MODULE, "remote_path_exists",
                                  side_effect=[False, True, False]), \
                mock.patch.object(MODULE, "remote_sha256",
                                  return_value=MODULE.NES_QUALIFICATION_SHA256), \
                mock.patch.object(MODULE.subprocess, "run", return_value=completed), \
                mock.patch.object(MODULE, "wait_import_complete"), \
                mock.patch.object(MODULE, "library_index", return_value={}), \
                mock.patch.object(MODULE, "resolve_live_nes_qualification",
                                  return_value=resolved), \
                mock.patch.object(MODULE.qa, "adb") as adb_call:
            with self.assertRaisesRegex(RuntimeError, "importer-created destination"):
                MODULE.stage_nes_qualification_fixture(
                    Path("/adb"), "serial", fixture
                )
        self.assertIn(
            mock.call(Path("/adb"), "serial", "shell",
                      "rm -f " + shlex.quote(target)),
            adb_call.call_args_list,
        )

    def test_nested_download_fixture_is_not_treated_as_discoverable(self):
        fixture = ROOT / "engines/build/qa-fixtures/lucent-callback-test.nes"
        nested = ("/storage/emulated/0/Download/EmuFusionQA-old/"
                  "Lucent Callback Test.nes")
        target = "/storage/emulated/0/Games/nes/Lucent Callback Test.nes"
        completed = mock.Mock(returncode=0, stdout="pushed")
        identity = ("/storage/emulated/0/Download/"
                    "Lucent Callback Test.nes:24592")
        row = {"sourceIdentity": identity, "system": "nes",
               "title": "Lucent Callback Test", "file": target}
        with mock.patch.object(MODULE, "exact_remote_nes_fixture_paths",
                               side_effect=[{nested}, {nested, target}]), \
                mock.patch.object(MODULE, "read_import_registry",
                                  side_effect=[{}, {identity: row}]), \
                mock.patch.object(MODULE, "remote_canonical_path",
                                  side_effect=lambda _a, _s, value:
                                  MODULE.canonical_shared_path(value)), \
                mock.patch.object(MODULE, "library_index", return_value={}), \
                mock.patch.object(MODULE, "resolve_live_nes_qualification",
                                  side_effect=[RuntimeError("not indexed"),
                                               {"title": "Lucent Callback Test",
                                                "path": target,
                                                "sha256": MODULE.NES_QUALIFICATION_SHA256}]), \
                mock.patch.object(MODULE, "remote_path_exists", return_value=False), \
                mock.patch.object(MODULE, "remote_sha256",
                                  return_value=MODULE.NES_QUALIFICATION_SHA256), \
                mock.patch.object(MODULE.subprocess, "run", return_value=completed), \
                mock.patch.object(MODULE, "wait_import_complete"), \
                mock.patch.object(MODULE.qa, "adb"):
            stage = MODULE.stage_nes_qualification_fixture(
                Path("/adb"), "serial", fixture
            )
        self.assertEqual(stage["preexistingPaths"], [nested])
        self.assertEqual(stage["createdPaths"], [target])
        self.assertNotIn(nested, stage["createdPaths"])

    def test_root_download_collision_is_refused_without_overwrite(self):
        fixture = ROOT / "engines/build/qa-fixtures/lucent-callback-test.nes"
        with mock.patch.object(MODULE, "exact_remote_nes_fixture_paths",
                               return_value=set()), \
                mock.patch.object(MODULE, "read_import_registry", return_value={}), \
                mock.patch.object(MODULE, "remote_path_exists", return_value=True), \
                mock.patch.object(MODULE.subprocess, "run") as push:
            with self.assertRaisesRegex(RuntimeError, "refusing to overwrite"):
                MODULE.stage_nes_qualification_fixture(
                    Path("/adb"), "serial", fixture
                )
        push.assert_not_called()

    def test_live_fixture_resolution_binds_exact_title_path_and_hash(self):
        path = "/sdcard/Games/nes/Lucent Callback Test.nes"
        index = {"systems": {"nes": {"alpha": [
            "nes|lucent callback test"
        ]}}}
        with mock.patch.object(MODULE, "metadata_title_files",
                               return_value={"lucentcallbacktest": {path}}), \
                mock.patch.object(MODULE, "remote_canonical_path",
                                  side_effect=lambda _a, _s, value:
                                  MODULE.canonical_shared_path(value)), \
                mock.patch.object(MODULE, "remote_sha256",
                                  return_value=MODULE.NES_QUALIFICATION_SHA256):
            resolved = MODULE.resolve_live_nes_qualification(
                Path("/adb"), "serial", index
            )
        self.assertEqual(resolved["path"], MODULE.canonical_shared_path(path))
        self.assertEqual(resolved["title"], "Lucent Callback Test")
        self.assertEqual(resolved["sha256"], MODULE.NES_QUALIFICATION_SHA256)
        duplicate = {"systems": {"nes": {"alpha": [
            "000000|Lucent Callback Test", "000001|Lucent Callback Test"
        ]}}}
        with self.assertRaisesRegex(RuntimeError, "exactly one"):
            MODULE.resolve_live_nes_qualification(
                Path("/adb"), "serial", duplicate
            )

    def test_canonical_metafiles_resolves_exact_fixture_path(self):
        canonical = (
            "/storage/emulated/0/Android/data/com.thorium.preview/files/"
            "pegasus-frontend/metafiles"
        )
        metadata_path = canonical + "/99-lucent-auto-nes.metadata.pegasus.txt"
        rom_path = "/storage/emulated/0/Games/nes/Lucent Callback Test.nes"
        metadata = "\n".join((
            "collection: Nintendo Entertainment System",
            "shortname: nes",
            "game: Lucent Callback Test",
            "file: " + rom_path,
        ))

        def adb_result(_adb, _serial, *args, **_kwargs):
            if args[:2] == ("shell", "find"):
                return mock.Mock(
                    stdout=(metadata_path + "\n" if args[2] == canonical else ""),
                    returncode=0,
                )
            if args[:2] == ("exec-out", "cat"):
                self.assertEqual(args[2], metadata_path)
                return mock.Mock(stdout=metadata, returncode=0)
            self.fail(f"unexpected adb call: {args}")

        case = MODULE.SystemCase("nes", ("famicom",), ("mesen",), 1)
        with mock.patch.object(MODULE.qa, "adb", side_effect=adb_result):
            files = MODULE.metadata_title_files(Path("/adb"), "serial", case)
        self.assertEqual(files, {"lucentcallbacktest": {rom_path}})

    def test_metadata_title_files_unions_fixture_and_owner_roots(self):
        canonical = (
            "/storage/emulated/0/Android/data/com.thorium.preview/files/"
            "pegasus-frontend/metafiles"
        )
        owner = (
            "/storage/emulated/0/Android/data/com.thorium.preview/files/"
            "pegasus-frontend/metadata"
        )
        fixture_metadata = canonical + "/99-lucent-auto-nes.metadata.pegasus.txt"
        owner_metadata = owner + "/12-nes.metadata.pegasus.txt"
        fixture_rom = "/storage/emulated/0/Games/nes/Lucent Callback Test.nes"
        real_roms = {
            "10yardfight": "/storage/6432-6661/ROMS/nes/10-Yard Fight.nes",
            "1943thebattleofmidway":
                "/storage/6432-6661/ROMS/nes/1943 - The Battle of Midway.nes",
            "8eyes": "/storage/6432-6661/ROMS/nes/8 Eyes.nes",
        }
        payloads = {
            fixture_metadata: (
                "game: Lucent Callback Test\nfile: " + fixture_rom + "\n"
            ),
            owner_metadata: "\n".join((
                "game: 10-Yard Fight", "file: " + real_roms["10yardfight"],
                "game: 1943: The Battle of Midway",
                "file: " + real_roms["1943thebattleofmidway"],
                "game: 8 Eyes", "file: " + real_roms["8eyes"],
            )),
        }

        def adb_result(_adb, _serial, *args, **_kwargs):
            if args[:2] == ("shell", "find"):
                rows = {canonical: fixture_metadata, owner: owner_metadata}
                return mock.Mock(stdout=rows.get(args[2], "") +
                                 ("\n" if args[2] in rows else ""), returncode=0)
            if args[:2] == ("exec-out", "cat"):
                return mock.Mock(stdout=payloads[args[2]], returncode=0)
            self.fail(f"unexpected adb call: {args}")

        case = MODULE.SystemCase("nes", ("famicom",), ("mesen",), 1)
        with mock.patch.object(MODULE.qa, "adb", side_effect=adb_result):
            files = MODULE.metadata_title_files(Path("/adb"), "serial", case)
        self.assertEqual(files["lucentcallbacktest"], {fixture_rom})
        for title, path in real_roms.items():
            self.assertEqual(files[title], {path})

    def test_metadata_title_files_deduplicates_aliases_and_rejects_conflicts(self):
        roots = (
            "/storage/emulated/0/Android/data/com.thorium.preview/files/"
            "pegasus-frontend/metafiles",
            "/storage/emulated/0/Android/data/com.thorium.preview/files/"
            "pegasus-frontend/metadata",
        )
        files = [root + f"/{index:02d}-nes.metadata.pegasus.txt"
                 for index, root in enumerate(roots)]

        def run(payloads):
            def adb_result(_adb, _serial, *args, **_kwargs):
                if args[:2] == ("shell", "find"):
                    for root, path in zip(roots, files):
                        if args[2] == root:
                            return mock.Mock(stdout=path + "\n", returncode=0)
                    return mock.Mock(stdout="", returncode=0)
                if args[:2] == ("exec-out", "cat"):
                    return mock.Mock(stdout=payloads[args[2]], returncode=0)
                self.fail(f"unexpected adb call: {args}")
            case = MODULE.SystemCase("nes", (), ("mesen",), 1)
            with mock.patch.object(MODULE.qa, "adb", side_effect=adb_result):
                return MODULE.metadata_title_files(Path("/adb"), "serial", case)

        duplicate = {
            files[0]: "game: 10-Yard Fight\nfile: /sdcard/Games/nes/10.nes\n",
            files[1]: ("game: 10-Yard Fight\n"
                       "file: /storage/emulated/0/Games/nes/10.nes\n"),
        }
        self.assertEqual(run(duplicate), {
            "10yardfight": {"/storage/emulated/0/Games/nes/10.nes"}
        })

        conflict = dict(duplicate)
        conflict[files[1]] = (
            "game: Different Game\n"
            "file: /storage/emulated/0/Games/nes/10.nes\n"
        )
        with self.assertRaisesRegex(RuntimeError, "metadata title conflict"):
            run(conflict)

    def test_sampled_title_identity_rejects_two_distinct_live_paths(self):
        case = MODULE.SystemCase("nes", (), ("mesen",), 1)
        with mock.patch.object(MODULE, "metadata_title_files", return_value={
                "10yardfight": {"/games/a.nes", "/games/b.nes"}}):
            with self.assertRaisesRegex(RuntimeError, "needs one exact ROM"):
                MODULE.indexed_title_rom_identity(
                    Path("/adb"), "serial", case, "10-Yard Fight"
                )

    def test_metadata_index_uses_canonical_metafiles_before_legacy_roots(self):
        canonical = (
            "/storage/emulated/0/Android/data/com.thorium.preview/files/"
            "pegasus-frontend/metafiles"
        )
        metadata_path = canonical + "/99-lucent-auto-nes.metadata.pegasus.txt"
        metadata = "shortname: nes\ngame: Lucent Callback Test\n"
        roots = []

        def adb_result(_adb, _serial, *args, **_kwargs):
            if args[:2] == ("shell", "find"):
                roots.append(args[2])
                return mock.Mock(stdout=metadata_path + "\n", returncode=0)
            if args[:2] == ("exec-out", "cat"):
                return mock.Mock(stdout=metadata, returncode=0)
            self.fail(f"unexpected adb call: {args}")

        with mock.patch.object(MODULE.qa, "adb", side_effect=adb_result):
            index = MODULE.metadata_library_index(Path("/adb"), "serial")
        self.assertEqual(roots, [canonical])
        self.assertEqual(index["systems"]["nes"]["alpha"],
                         ["000000|Lucent Callback Test"])

    def test_live_index_absence_after_import_rolls_back_destination(self):
        fixture = ROOT / "engines/build/qa-fixtures/lucent-callback-test.nes"
        target = "/storage/emulated/0/Games/nes/Lucent Callback Test.nes"
        completed = mock.Mock(returncode=0, stdout="pushed")
        with mock.patch.object(MODULE, "exact_remote_nes_fixture_paths",
                               side_effect=[set(), {target}, {target}, set()]), \
                mock.patch.object(MODULE, "read_import_registry",
                                  side_effect=[{}, {}, {}]), \
                mock.patch.object(MODULE, "remote_canonical_path",
                                  side_effect=lambda _a, _s, value:
                                  MODULE.canonical_shared_path(value)), \
                mock.patch.object(MODULE, "remote_path_exists",
                                  side_effect=[False, True, False]), \
                mock.patch.object(MODULE, "remote_sha256",
                                  return_value=MODULE.NES_QUALIFICATION_SHA256), \
                mock.patch.object(MODULE.subprocess, "run", return_value=completed), \
                mock.patch.object(MODULE, "wait_import_complete"), \
                mock.patch.object(MODULE, "library_index", return_value={}), \
                mock.patch.object(MODULE, "resolve_live_nes_qualification",
                                  side_effect=RuntimeError("live index absent")), \
                mock.patch.object(MODULE.qa, "adb") as adb_call:
            with self.assertRaisesRegex(RuntimeError, "live index absent"):
                MODULE.stage_nes_qualification_fixture(
                    Path("/adb"), "serial", fixture
                )
        self.assertTrue(any(call.args[-1:] ==
                            ("rm -f " + shlex.quote(target),)
                            for call in adb_call.call_args_list))

    def test_spaced_fixture_paths_use_one_quoted_remote_shell_command(self):
        path = "/storage/emulated/0/Games/nes/Lucent Callback Test.nes"
        completed = mock.Mock(returncode=0, stdout="")
        with mock.patch.object(MODULE.qa, "adb", return_value=completed) as adb_call:
            self.assertTrue(MODULE.remote_path_exists(
                Path("/adb"), "serial", path
            ))
        self.assertEqual(
            adb_call.call_args.args,
            (Path("/adb"), "serial", "shell", "test -e " + shlex.quote(path)),
        )

        stage = {"createdByRun": True, "createdPaths": [path]}
        identity = ("/storage/emulated/0/Download/"
                    "Lucent Callback Test.nes:24592")
        row = {"sourceIdentity": identity, "system": "nes",
               "title": "Lucent Callback Test", "file": path}
        stage.update({"sourceIdentity": identity, "indexedPath": path})
        with mock.patch.object(MODULE, "remote_sha256",
                               return_value=MODULE.NES_QUALIFICATION_SHA256), \
                mock.patch.object(MODULE, "read_import_registry",
                                  side_effect=[{identity: row}, {}]), \
                mock.patch.object(MODULE, "remote_canonical_path",
                                  side_effect=lambda _a, _s, value:
                                  MODULE.canonical_shared_path(value)), \
                mock.patch.object(MODULE, "delete_owned_nes_registry_row",
                                  return_value={"ok": True}), \
                mock.patch.object(MODULE, "remote_path_exists",
                                  side_effect=[True, False]), \
                mock.patch.object(MODULE, "wait_import_complete"), \
                mock.patch.object(MODULE, "exact_remote_nes_fixture_paths",
                                  return_value=set()), \
                mock.patch.object(MODULE, "library_index",
                                  return_value={"systems": {"nes": {"alpha": []}}}), \
                mock.patch.object(MODULE.qa, "adb", return_value=completed) as adb_call:
            proof = MODULE.cleanup_nes_qualification_fixture(
                Path("/adb"), "serial", stage
            )
        self.assertTrue(proof["absenceVerified"])
        self.assertIn(
            mock.call(Path("/adb"), "serial", "shell",
                      "rm -f " + shlex.quote(path)),
            adb_call.call_args_list,
        )

    def test_cleanup_rejects_lowercase_live_fixture_row(self):
        path = "/storage/emulated/0/Games/nes/Lucent Callback Test.nes"
        identity = ("/storage/emulated/0/Download/"
                    "Lucent Callback Test.nes:24592")
        row = {"sourceIdentity": identity, "system": "nes",
               "title": "Lucent Callback Test", "file": path}
        stage = {"createdByRun": True, "createdPaths": [path],
                 "sourceIdentity": identity, "indexedPath": path}
        index = {"systems": {"nes": {"alpha": [
            "nes|lucent callback test"
        ]}}}
        with mock.patch.object(MODULE, "remote_sha256",
                               return_value=MODULE.NES_QUALIFICATION_SHA256), \
                mock.patch.object(MODULE, "wait_import_complete"), \
                mock.patch.object(MODULE, "exact_remote_nes_fixture_paths",
                                  return_value=set()), \
                mock.patch.object(MODULE, "read_import_registry",
                                  side_effect=[{identity: row}, {}]), \
                mock.patch.object(MODULE, "remote_canonical_path",
                                  side_effect=lambda _a, _s, value:
                                  MODULE.canonical_shared_path(value)), \
                mock.patch.object(MODULE, "delete_owned_nes_registry_row",
                                  return_value={"ok": True}), \
                mock.patch.object(MODULE, "remote_path_exists", return_value=False), \
                mock.patch.object(MODULE, "library_index", return_value=index), \
                mock.patch.object(MODULE.qa, "adb"):
            with self.assertRaisesRegex(RuntimeError, "row remained"):
                MODULE.cleanup_nes_qualification_fixture(
                    Path("/adb"), "serial", stage
                )

    def test_repeat_run_cleanup_removes_registry_so_second_stage_imports(self):
        fixture = ROOT / "engines/build/qa-fixtures/lucent-callback-test.nes"
        target = "/storage/emulated/0/Games/nes/Lucent Callback Test.nes"
        identity = ("/storage/emulated/0/Download/"
                    "Lucent Callback Test.nes:24592")
        row = {"sourceIdentity": identity, "system": "nes",
               "title": "Lucent Callback Test", "file": target}
        resolved = {"title": "Lucent Callback Test", "path": target,
                    "sha256": MODULE.NES_QUALIFICATION_SHA256}
        completed = mock.Mock(returncode=0, stdout="pushed")
        empty_index = {"systems": {"nes": {"alpha": []}}}
        with mock.patch.object(
                MODULE, "read_import_registry",
                side_effect=[{}, {identity: row}, {identity: row}, {},
                             {}, {identity: row}, {identity: row}, {}]), \
                mock.patch.object(MODULE, "remote_canonical_path",
                                  side_effect=lambda _a, _s, value:
                                  MODULE.canonical_shared_path(value)), \
                mock.patch.object(
                    MODULE, "exact_remote_nes_fixture_paths",
                    side_effect=[set(), {target}, set(),
                                 set(), {target}, set()]), \
                mock.patch.object(MODULE, "remote_path_exists",
                                  side_effect=[False, False, False,
                                               False, False, False]), \
                mock.patch.object(MODULE, "remote_sha256",
                                  return_value=MODULE.NES_QUALIFICATION_SHA256), \
                mock.patch.object(MODULE.subprocess, "run",
                                  return_value=completed) as push, \
                mock.patch.object(MODULE, "wait_import_complete"), \
                mock.patch.object(MODULE, "library_index",
                                  return_value=empty_index), \
                mock.patch.object(MODULE, "resolve_live_nes_qualification",
                                  return_value=resolved), \
                mock.patch.object(MODULE, "delete_owned_nes_registry_row",
                                  return_value={"ok": True}) as delete, \
                mock.patch.object(MODULE.qa, "adb"):
            first = MODULE.stage_nes_qualification_fixture(
                Path("/adb"), "serial", fixture
            )
            first_cleanup = MODULE.cleanup_nes_qualification_fixture(
                Path("/adb"), "serial", first
            )
            second = MODULE.stage_nes_qualification_fixture(
                Path("/adb"), "serial", fixture
            )
            second_cleanup = MODULE.cleanup_nes_qualification_fixture(
                Path("/adb"), "serial", second
            )
        self.assertEqual(push.call_count, 2)
        self.assertEqual(delete.call_count, 2)
        self.assertTrue(first_cleanup["absenceVerified"])
        self.assertTrue(second_cleanup["absenceVerified"])
        self.assertEqual(first["sourceIdentity"], identity)
        self.assertEqual(second["sourceIdentity"], identity)

    def test_stale_source_identity_refuses_stage_without_touching_owner_state(self):
        fixture = ROOT / "engines/build/qa-fixtures/lucent-callback-test.nes"
        identity = ("/storage/emulated/0/Download/"
                    "Lucent Callback Test.nes:24592")
        stale = {"sourceIdentity": identity, "system": "nes",
                 "title": "Different Game",
                 "file": "/sdcard/Games/nes/Other.nes"}
        with mock.patch.object(MODULE, "read_import_registry",
                               return_value={identity: stale}), \
                mock.patch.object(MODULE, "exact_remote_nes_fixture_paths",
                                  return_value=set()), \
                mock.patch.object(MODULE, "remote_path_exists") as exists, \
                mock.patch.object(MODULE.subprocess, "run") as push:
            with self.assertRaisesRegex(RuntimeError, "already registered"):
                MODULE.stage_nes_qualification_fixture(
                    Path("/adb"), "serial", fixture
                )
        exists.assert_not_called()
        push.assert_not_called()

    def test_registry_delete_failure_stops_before_raw_unlink(self):
        target = "/storage/emulated/0/Games/nes/Lucent Callback Test.nes"
        identity = ("/storage/emulated/0/Download/"
                    "Lucent Callback Test.nes:24592")
        row = {"sourceIdentity": identity, "system": "nes",
               "title": "Lucent Callback Test", "file": target}
        stage = {"createdByRun": True, "createdPaths": [target],
                 "sourceIdentity": identity, "indexedPath": target}
        with mock.patch.object(MODULE, "read_import_registry",
                               return_value={identity: row}), \
                mock.patch.object(MODULE, "remote_canonical_path",
                                  side_effect=lambda _a, _s, value:
                                  MODULE.canonical_shared_path(value)), \
                mock.patch.object(MODULE, "remote_sha256",
                                  return_value=MODULE.NES_QUALIFICATION_SHA256), \
                mock.patch.object(MODULE, "delete_owned_nes_registry_row",
                                  side_effect=RuntimeError("delete rejected")), \
                mock.patch.object(MODULE, "wait_import_complete") as scan, \
                mock.patch.object(MODULE.qa, "adb") as adb_call:
            with self.assertRaisesRegex(RuntimeError, "delete rejected"):
                MODULE.cleanup_nes_qualification_fixture(
                    Path("/adb"), "serial", stage
                )
        scan.assert_not_called()
        self.assertFalse(any("rm -f" in str(call.args)
                             for call in adb_call.call_args_list))

    def test_supported_registry_delete_requires_ok_true_and_encoded_identity(self):
        identity = ("/storage/emulated/0/Download/"
                    "Lucent Callback Test.nes:24592")
        with mock.patch.object(MODULE, "import_service_request",
                               return_value={"ok": True}) as request:
            result = MODULE.delete_owned_nes_registry_row(
                Path("/adb"), "serial", identity
            )
        self.assertTrue(result["ok"])
        requested_path = request.call_args.args[2]
        self.assertIn("/game/delete?id=%2Fstorage%2Femulated%2F0%2FDownload%2F",
                      requested_path)
        self.assertIn("%3A24592", requested_path)
        with mock.patch.object(MODULE, "import_service_request",
                               return_value={"ok": False}):
            with self.assertRaisesRegex(RuntimeError, "ok=true"):
                MODULE.delete_owned_nes_registry_row(
                    Path("/adb"), "serial", identity
                )

    def test_outermost_main_finally_cleans_stage_after_failure(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        result = Path(temporary.name) / "results.json"
        report = {"nesFixtureLifecycle": {"stage": {}, "cleanup": None}}
        MODULE.ACTIVE_NES_STAGE_CONTEXT = {
            "adb": Path("/adb"), "serial": "serial",
            "stage": {"createdByRun": True}, "report": report,
            "resultPath": result,
        }
        proof = {"performed": True, "absenceVerified": True}
        with mock.patch.object(MODULE, "_runtime_main",
                               side_effect=RuntimeError("gate failed")), \
                mock.patch.object(MODULE, "cleanup_nes_qualification_fixture",
                                  return_value=proof) as cleanup:
            with self.assertRaisesRegex(RuntimeError, "gate failed"):
                MODULE.main()
        cleanup.assert_called_once()
        self.assertEqual(report["nesFixtureLifecycle"]["cleanup"], proof)

    def test_list_view_smoke_binds_same_required_title_rom_and_core(self):
        case = mock.Mock()
        case.folder = "gc"
        case.required_titles = ("Metroid Prime",)
        case.engines = ("dolphin",)
        controller = mock.Mock()
        controller.A = 96
        controller.UP = 103
        controller.DOWN = 108
        apk = Path("/tmp/exact.apk")
        rom = {"sha256": "a" * 64, "path": "/storage/game.ciso"}
        with tempfile.TemporaryDirectory() as temporary, \
                mock.patch.object(MODULE, "screenshot"), \
                mock.patch.object(MODULE, "list_view_highlighted_folder",
                                  return_value="gc"), \
                mock.patch.object(MODULE, "indexed_title_rom_identity",
                                  return_value=rom) as indexed, \
                mock.patch.object(MODULE, "packaged_engine_sha256",
                                  return_value="b" * 64), \
                mock.patch.object(MODULE, "run_game_from_system_menu",
                                  return_value={"passed": True}) as launch, \
                mock.patch.object(MODULE.time, "sleep"):
            result = MODULE.run_list_view_smoke(
                Path("/adb"), "serial", controller, case, ["gc"],
                {"gc": "GameCube"}, Path(temporary), "c" * 64, apk,
            )
        self.assertEqual(result["status"], "PASS")
        indexed.assert_called_once_with(
            Path("/adb"), "serial", case, "Metroid Prime"
        )
        kwargs = launch.call_args.kwargs
        self.assertEqual(kwargs["expected_title"], "Metroid Prime")
        self.assertEqual(kwargs["rom_identity"], rom)
        self.assertEqual(kwargs["core_hashes"], {"dolphin": "b" * 64})
        self.assertEqual(kwargs["apk"], apk)


if __name__ == "__main__":
    unittest.main()
