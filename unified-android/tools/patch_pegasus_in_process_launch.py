#!/usr/bin/env python3
"""Keep the pinned Pegasus QML engine warm for EmuFusion's in-window games.

Pegasus's Android launcher emits ``processLaunchOk`` after Java accepts an
``am start`` command.  Its second signal subscriber normally tears down the
entire QML engine and stops the gamepad, then rebuilds both as soon as Android
reports the Activity launch.  EmuFusion intercepts its one internal command in
the existing MainActivity, so that external-process lifecycle is both wrong
and the source of a visible startup splash plus lost selection state.

The base APK is SHA-256 pinned by build.sh and retains symbols.  Patch the
exact ARM64 body of the processLaunchOk subscriber so it completes Pegasus's
API/provider bookkeeping and ProcessLauncher cleanup without touching the
frontend or gamepad.  Every byte is checked before and after replacement;
unknown or already-patched inputs fail closed.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path


PATCH_OFFSET = 0x75FD8
EXPECTED = bytes.fromhex(
    # ldr x0,[x19,#0x18]; bl FrontendLayer::teardown;
    # ldr x8,[x19,#0x10]; ldp; add; ldr; b GamepadManager::stop
    "600e40f9" "49e0ff97" "680a40f9" "fd7b41a9"
    "00810491" "f30742f8" "b0e3ff17"
)
REPLACEMENT = bytes.fromhex(
    # ldr x0,[x19,#8]; bl ApiObject::onGameProcessFinished;
    # ldr x0,[x19,#0x20]; bl ProcessLauncher::afterRun; restore; ret
    "600640f9" "3b3f0094" "601240f9" "79170094"
    "fd7b41a9" "f30742f8" "c0035fd6"
)


def patch(path: Path) -> tuple[str, str]:
    payload = bytearray(path.read_bytes())
    if payload[:4] != b"\x7fELF" or payload[4] != 2 or payload[5] != 1:
        raise ValueError("frontend is not a little-endian ELF64 file")
    if len(payload) < PATCH_OFFSET + len(EXPECTED):
        raise ValueError("frontend is shorter than the locked patch offset")
    found = bytes(payload[PATCH_OFFSET:PATCH_OFFSET + len(EXPECTED)])
    if found == REPLACEMENT:
        raise ValueError("frontend already contains the in-process launch patch")
    if found != EXPECTED:
        raise ValueError(
            "frontend launch subscriber differs at locked offset: " + found.hex()
        )
    before = hashlib.sha256(payload).hexdigest()
    payload[PATCH_OFFSET:PATCH_OFFSET + len(REPLACEMENT)] = REPLACEMENT
    if bytes(payload[PATCH_OFFSET:PATCH_OFFSET + len(REPLACEMENT)]) != REPLACEMENT:
        raise AssertionError("post-patch byte verification failed")
    path.write_bytes(payload)
    after = hashlib.sha256(payload).hexdigest()
    return before, after


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_pegasus_in_process_launch.py <libpegasus-fe.so>")
    try:
        before, after = patch(Path(sys.argv[1]))
    except (OSError, ValueError) as error:
        raise SystemExit(str(error)) from error
    print(f"Pegasus in-process launch patch: {before} -> {after}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
