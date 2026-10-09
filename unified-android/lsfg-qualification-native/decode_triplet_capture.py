#!/usr/bin/env python3
"""Lossless offline RGBA-to-PNG conversion; never certifies image quality.

Usage: python3 decode_triplet_capture.py capture-1.json --output-dir decoded
The full-resolution pixels are neither resized, gamma-converted nor edited.
Native row zero stays row zero; inspect orientation against game output.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import zlib


def png_rgba(width, height, raw):
    if type(width) is not int or type(height) is not int or width <= 0 or height <= 0:
        raise ValueError("invalid image dimensions")
    if width * height * 12 > 64 * 1024 * 1024 or len(raw) != width * height * 4:
        raise ValueError("image size mismatch or native capture bound exceeded")
    def chunk(kind, payload):
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))
    stride = width * 4
    scanlines = b"".join(b"\0" + raw[row * stride:(row + 1) * stride] for row in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(scanlines)) + chunk(b"IEND", b""))


def decode(metadata_path, output):
    metadata_path = Path(metadata_path).resolve()
    metadata = json.loads(metadata_path.read_text())
    if metadata.get("schema_version") != 1 or metadata.get("pixel_format") != "RGBA8_UNORM":
        raise ValueError("unsupported capture schema/format")
    if metadata.get("quality_status") != "UNVERIFIED" or metadata.get("instrumented") is not True:
        raise ValueError("capture omitted instrumentation/unverified status")
    if (metadata.get("phase_numerator") != 1 or metadata.get("phase_denominator") != 2 or
            metadata.get("content_timestamp_rounding") != "floor-nanosecond"):
        raise ValueError("capture omitted exact phase and floor midpoint rounding policy")
    left, right, content = (metadata.get(key) for key in
                            ("left_timestamp_ns", "right_timestamp_ns", "content_timestamp_ns"))
    if (any(type(value) is not int or not 0 < value < 2**64 for value in (left, right, content)) or
            not left < content < right or content - left != (right - left) // 2):
        raise ValueError("invalid floor midpoint content timestamp")
    width, height = metadata["width"], metadata["height"]
    if metadata["row_stride_bytes"] != width * 4 or metadata["image_bytes"] != width * height * 4:
        raise ValueError("raw image layout mismatch")
    images = metadata.get("images", {})
    if set(images) != {"left", "generated", "right"} or len(set(images.values())) != 3:
        raise ValueError("missing/distinct triplet image identities")
    raw_images = {}
    for role, name in images.items():
        if not isinstance(name, str) or Path(name).name != name:
            raise ValueError("capture image must be an adjacent basename")
        path = metadata_path.parent / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("capture image missing or symlinked")
        if path.stat().st_size != metadata["image_bytes"]:
            raise ValueError("partial capture image")
        raw_images[role] = path.read_bytes()
    # Refuse an existing directory; a conversion cannot overwrite evidence.
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    report = {"quality_status": "UNVERIFIED", "phase_numerator": 1, "phase_denominator": 2,
              "content_timestamp_rounding": "floor-nanosecond", "source_metadata_sha256":
              hashlib.sha256(metadata_path.read_bytes()).hexdigest(), "images": {}}
    for role, raw in raw_images.items():
        encoded = png_rgba(width, height, raw)
        with (output / (role + ".png")).open("xb") as stream:
            stream.write(encoded)
        report["images"][role] = {"raw_sha256": hashlib.sha256(raw).hexdigest(),
                                   "png_sha256": hashlib.sha256(encoded).hexdigest(),
                                   "path": role + ".png", "width": width, "height": height}
    with (output / "decode-manifest.json").open("x") as stream:
        json.dump(report, stream, indent=2)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("metadata", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(decode(args.metadata, args.output_dir), indent=2))
