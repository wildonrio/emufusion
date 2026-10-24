#!/usr/bin/env python3
"""Stop the hidden Pegasus splash from redrawing the library every refresh.

The frontend's SplashLayer.qml runs its progress-bar animation with
``loops: Animation.Infinite`` and no ``running`` guard. main.qml hides the
splash with ``visible: focus`` once the theme loads, which does not stop an
animation, and any running animation makes Qt Quick render every vsync. On the
Thor the library's Qt surface therefore redrew at ~120 Hz for the whole
session, behind in-window games too (QtThread ~12% of a core; a theme of one
black rectangle still redrew at ~71 Hz), 2026-10-24.

The frontend embeds its QML source uncompressed in its resources, so this is an
equal-length edit of exactly that block, re-indented to fit. Neither a
``running: root.visible`` guard nor a finite loop count stopped it on the Thor
(the profile still showed the splash's width animation every frame), so the
stripe animation no longer starts at all: the progress bar still shows progress
through its margin binding; only the moving stripe on the (already blanked)
splash is gone. Nothing else changes.
"""

from pathlib import Path
import sys

OLD = (b"            SequentialAnimation on animatedWidth {\n"
       b"                loops: Animation.Infinite\n"
       b"                PropertyAnimation { duration: 500; to: vpx(68) }\n"
       b"                PropertyAnimation { duration: 0; to: 0 }\n"
       b"            }\n")
CORE = (b"            SequentialAnimation on animatedWidth {\n"
        b"    running: false\n"
        b"    loops: 1\n"
        b"    PropertyAnimation { duration: 500; to: vpx(68) }\n"
        b"    PropertyAnimation { duration: 0; to: 0 }\n"
        b"            }")
assert len(CORE) < len(OLD)
NEW = CORE + b" " * (len(OLD) - len(CORE) - 1) + b"\n"
assert len(NEW) == len(OLD)


def _form(running: bytes, loops: bytes) -> bytes:
    """An earlier staged form of this patch (2026-10-24), padded to OLD's length."""
    block = (b"            SequentialAnimation on animatedWidth {\n"
             b"    running: " + running + b"\n"
             b"    loops: " + loops + b"\n"
             b"    PropertyAnimation { duration: 500; to: vpx(68) }\n"
             b"    PropertyAnimation { duration: 0; to: 0 }\n"
             b"            }")
    return block + b" " * (len(OLD) - len(block) - 1) + b"\n"


EARLIER = (_form(b"root.visible", b"Animation.Infinite"), _form(b"root.visible", b"360"))


def patch(blob: bytes) -> bytes:
    if blob.count(NEW) == 1 and not any(form in blob for form in (OLD,) + EARLIER):
        return blob
    for before in (OLD,) + EARLIER:
        if blob.count(before) == 1:
            return blob.replace(before, NEW)
    raise SystemExit("expected one splash animation block")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_pegasus_splash_idle.py <libpegasus-fe.so>")
    path = Path(sys.argv[1])
    blob = path.read_bytes()
    patched = patch(blob)
    if patched == blob:
        print("Splash stripe animation already disabled")
        return
    path.write_bytes(patched)
    print(f"Splash stripe animation no longer starts ({len(OLD)} bytes, in place)")


if __name__ == "__main__":
    main()
