#!/usr/bin/env python3
"""Blank the embedded Pegasus startup PNG so EmuFusion opens with no splash.

The frontend reserves a 700x227 startup image. Drawing a wordmark there made
every cold start flash a branded loading screen. EmuFusion replaces the slot with
a fully transparent PNG of the same geometry, so the library is the first thing
the user sees. Attribution lives in About/licensing, not on a splash.
"""

from __future__ import annotations

import base64
import struct
import sys
from pathlib import Path

SIGNATURE = b"\x89PNG\r\n\x1a\n"
WIDTH = 700
HEIGHT = 227
LUCENT_WORDMARK = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAArwAAADjCAYAAABn/cdIAAACf0lEQVR42u3BMQEAAADCoPVPbQsvoAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAADuBrQ6AAGZcTH5AAAAAElFTkSuQmCC"
)


def png_extent(blob: bytes, start: int) -> tuple[int, int, int]:
    cursor = start + len(SIGNATURE)
    width = height = -1
    while cursor + 12 <= len(blob):
        length = struct.unpack(">I", blob[cursor:cursor + 4])[0]
        kind = blob[cursor + 4:cursor + 8]
        payload = blob[cursor + 8:cursor + 8 + length]
        if kind == b"IHDR":
            width, height = struct.unpack(">II", payload[:8])
        cursor += 12 + length
        if kind == b"IEND":
            return width, height, cursor
    raise ValueError("unterminated embedded PNG")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_pegasus_splash.py <libpegasus-fe.so>")
    path = Path(sys.argv[1])
    blob = bytearray(path.read_bytes())
    matches = []
    cursor = 0
    while True:
        start = blob.find(SIGNATURE, cursor)
        if start < 0:
            break
        try:
            width, height, end = png_extent(blob, start)
        except (ValueError, struct.error):
            # A PNG signature can occur by chance inside another compressed
            # resource. Only complete, structurally valid PNGs are candidates.
            cursor = start + len(SIGNATURE)
            continue
        if (width, height) == (WIDTH, HEIGHT):
            matches.append((start, end))
        cursor = end
    if len(matches) != 1:
        raise SystemExit(
            f"expected one {WIDTH}x{HEIGHT} startup PNG, found {len(matches)}"
        )

    start, end = matches[0]
    slot = end - start
    if len(LUCENT_WORDMARK) > slot:
        raise SystemExit(
            f"Lucent wordmark ({len(LUCENT_WORDMARK)} bytes) exceeds "
            f"resource slot ({slot})"
        )
    blob[start:end] = LUCENT_WORDMARK + bytes(slot - len(LUCENT_WORDMARK))
    path.write_bytes(blob)
    print(
        f"Patched startup wordmark at {start} "
        f"({len(LUCENT_WORDMARK)}/{slot} bytes)"
    )


if __name__ == "__main__":
    main()
