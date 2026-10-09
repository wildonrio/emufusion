"""Synthetic RGBA fixtures; no device evidence is created."""
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zlib

PATH = Path(__file__).resolve().parents[1] / "decode_triplet_capture.py"
SPEC = importlib.util.spec_from_file_location("decode_triplet_capture", PATH)
decoder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(decoder)


class DecodeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="emufusion-rgba-fixture-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.raw = bytes(range(24))
        self.metadata = {"schema_version": 1, "pixel_format": "RGBA8_UNORM", "instrumented": True,
                         "quality_status": "UNVERIFIED", "width": 3, "height": 2,
                         "row_stride_bytes": 12, "image_bytes": 24,
                         "phase_numerator": 1, "phase_denominator": 2,
                         "content_timestamp_rounding": "floor-nanosecond",
                         "left_timestamp_ns": 100, "right_timestamp_ns": 200, "content_timestamp_ns": 150,
                         "images": {key: key + ".rgba" for key in ("left", "generated", "right")}}
        for name in self.metadata["images"].values():
            (self.root / name).write_bytes(self.raw)
        self.path = self.root / "capture.json"
        self.persist()

    def persist(self):
        self.path.write_text(json.dumps(self.metadata))

    def test_roundtrip_exact_rgba_rows_dimensions_and_alpha(self):
        report = decoder.decode(self.path, self.root / "png")
        self.assertEqual(report["quality_status"], "UNVERIFIED")
        png = (self.root / "png" / "generated.png").read_bytes()
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        offset, payload = 8, b""
        while offset < len(png):
            length = struct.unpack(">I", png[offset:offset + 4])[0]
            kind = png[offset + 4:offset + 8]
            data = png[offset + 8:offset + 8 + length]
            if kind == b"IHDR":
                self.assertEqual(struct.unpack(">IIBBBBB", data), (3, 2, 8, 6, 0, 0, 0))
            if kind == b"IDAT":
                payload += data
            offset += length + 12
        self.assertEqual(zlib.decompress(payload), b"\0" + self.raw[:12] + b"\0" + self.raw[12:])

    def test_partial_native_dump_is_rejected(self):
        (self.root / "generated.rgba").write_bytes(self.raw[:-1])
        with self.assertRaisesRegex(ValueError, "partial"):
            decoder.decode(self.path, self.root / "png")
        self.assertFalse((self.root / "png").exists())

    def test_conversion_refuses_to_overwrite(self):
        (self.root / "png").mkdir()
        with self.assertRaises(FileExistsError):
            decoder.decode(self.path, self.root / "png")

    def test_capture_path_escape_rejected(self):
        self.metadata["images"]["generated"] = "../other.rgba"
        self.persist()
        with self.assertRaisesRegex(ValueError, "basename"):
            decoder.decode(self.path, self.root / "png")

    def test_aliased_roles_rejected(self):
        self.metadata["images"]["generated"] = "left.rgba"
        self.persist()
        with self.assertRaisesRegex(ValueError, "identities"):
            decoder.decode(self.path, self.root / "png")

    def test_odd_span_floor_midpoint_preserves_exact_mathematical_phase(self):
        self.metadata["right_timestamp_ns"] = 201
        self.persist()
        report = decoder.decode(self.path, self.root / "png")
        self.assertEqual((report["phase_numerator"], report["phase_denominator"]), (1, 2))
        self.assertEqual(report["content_timestamp_rounding"], "floor-nanosecond")

    def test_odd_span_ceil_midpoint_rejected(self):
        self.metadata.update(right_timestamp_ns=201, content_timestamp_ns=151)
        self.persist()
        with self.assertRaisesRegex(ValueError, "midpoint"):
            decoder.decode(self.path, self.root / "png")

    def test_missing_rounding_policy_rejected(self):
        del self.metadata["content_timestamp_rounding"]
        self.persist()
        with self.assertRaisesRegex(ValueError, "rounding"):
            decoder.decode(self.path, self.root / "png")


if __name__ == "__main__":
    unittest.main()
