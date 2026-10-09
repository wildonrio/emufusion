#!/usr/bin/env python3
"""Guard the pinned Qt Android gamepad plugin against late input events.

Qt Gamepad 5.15 posts controller callbacks through ``qApp``.  Android may
deliver a final key event after Qt has destroyed the application object; the
upstream helper then calls ``qApp->thread()`` with a null receiver and crashes
inside ``QObject::thread()``.  The APK's Qt toolchain is pinned and no matching
host qmake is available, so the unified build applies the equivalent source
fix (``if (!qApp) return``) to the exact ARM64 plugin.

Both key branches load qApp before converging on the thread call.  Each
three-instruction replacement inserts a null branch to the existing successful
cleanup path and folds ADRP+ADD into an equivalent ADR.  Input bytes, offsets,
and the complete input ELF hash are locked; drift and repeat application fail
closed.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path


INPUT_SHA256 = "31d7e24f0ca8af155f59fb1424b7f674998a4a23bc5d010032a97578356ea413"

PATCHES = (
    (
        0x846C,
        bytes.fromhex("290000d0e803152a29611591"),
        # cbz x0,0x85ec; adr x9,0xe558; mov w8,w21
        bytes.fromhex("000c00b449070310e803152a"),
    ),
    (
        0x8508,
        bytes.fromhex("290000d0e803152a29611791"),
        # cbz x0,0x85ec; adr x9,0xe5d8; mov w8,w21
        bytes.fromhex("200700b469060310e803152a"),
    ),
)


def patch(path: Path) -> tuple[str, str]:
    payload = bytearray(path.read_bytes())
    if payload[:6] != b"\x7fELF\x02\x01":
        raise ValueError("Qt Android gamepad plugin is not little-endian ELF64")
    before = hashlib.sha256(payload).hexdigest()
    if before != INPUT_SHA256:
        if all(bytes(payload[offset:offset + len(replacement)]) == replacement
               for offset, _expected, replacement in PATCHES):
            raise ValueError("Qt Android gamepad null guard is already applied")
        raise ValueError(f"unexpected Qt Android gamepad plugin checksum: {before}")

    for offset, expected, replacement in PATCHES:
        found = bytes(payload[offset:offset + len(expected)])
        if found != expected:
            raise ValueError(
                f"Qt Android gamepad bytes differ at 0x{offset:x}: {found.hex()}"
            )
        payload[offset:offset + len(replacement)] = replacement

    for offset, _expected, replacement in PATCHES:
        if bytes(payload[offset:offset + len(replacement)]) != replacement:
            raise AssertionError(f"post-patch verification failed at 0x{offset:x}")
    path.write_bytes(payload)
    return before, hashlib.sha256(payload).hexdigest()


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit(
            "usage: patch_qt_android_gamepad_null_guard.py "
            "<libplugins_gamepads_androidgamepad.so>"
        )
    try:
        before, after = patch(Path(sys.argv[1]))
    except (OSError, ValueError) as error:
        raise SystemExit(str(error)) from error
    print(f"Qt Android gamepad null guard: {before} -> {after}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
