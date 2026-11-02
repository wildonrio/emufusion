#!/usr/bin/env python3
"""Check (default) or repair the Thor lower panel's SurfaceFlinger framebuffer size.

Symptom: the lower screen shows its whole image squeezed into the left ~65% of the
panel with the right third black, in every app. Cause (firmware SurfaceFlinger,
Android 13 single-active-display mode switching): the lower display is recreated
with the upper panel's 1080x1920 mode, so its framebuffer and display space are
1080x1920 while the panel is 1080x1240. The HWC then maps that 1920-pixel space
onto 1240 rows (1240/1920 = 0.646). ADB screenshots show the logical composition
and look correct; the defect is only visible in `dumpsys SurfaceFlinger`
(RenderSurface size, FramebufferSurface buffers, SDM Dst Rect) or on the panel.
A reboot clears it; --repair clears it without a reboot.

Repair (shell uid, no root, nothing installed): set SurfaceFlinger's size for the
lower display back to its mode resolution, then show a 2x2 2%-alpha blur layer
for 0.6 s so one frame is GPU-composed and the HWC receives a correctly sized
client target. The helper dex is compiled from thor_lower_display/ into a
temporary directory and removed from host and device afterwards.

usage: thor_lower_display_repair.py [--repair [--force]] [--adb ADB] [--serial SERIAL]
exit: 0 healthy (or repaired), 2 mismatch found (check only), 1 error.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
JAVA_SOURCE = HERE / "thor_lower_display" / "SfLowerDisplay.java"
DEVICE_DEX = "/data/local/tmp/emufusion-lower-display-repair.dex"
DEFAULT_ADB = Path.home() / "Library/Android/sdk/platform-tools/adb"
DEFAULT_SERIAL = "427c87b2"
SDK = Path(os.environ.get("ANDROID_HOME", Path.home() / "Library/Android/sdk"))
JAVA_HOME = Path(os.environ.get(
    "JAVA_HOME", "/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home"))

_DISPLAY_HEADER = re.compile(r'^Display (\d+) \((internal|physical)([^)]*)\)', re.M)


def _blocks(dump):
    """{(display_id, kind): (flags, text)} for the per-display sections."""
    heads = list(_DISPLAY_HEADER.finditer(dump))
    blocks = {}
    for i, head in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(dump)
        # A section ends at the first unindented line after its header.
        text = dump[head.end():end]
        stop = re.search(r'\n(?=\S)', text)
        blocks[(head.group(1), head.group(2))] = (head.group(3), text[:stop.start()] if stop else text)
    return blocks


def parse_displays(dump):
    """Per internal display: primary flag, mode resolution, layer stack, framebuffer sizes."""
    blocks = _blocks(dump)
    displays = {}
    for (display_id, kind), (flags, text) in blocks.items():
        if kind != "internal":
            continue
        active = re.search(r'activeModeId=(\d+)', text)
        modes = dict(re.findall(r'\{id=(\d+), hwcId=\d+, resolution=(\d+x\d+)', text))
        resolution = modes.get(active.group(1)) if active else None
        if resolution is None and modes:
            resolution = next(iter(modes.values()))
        info = {"primary": "primary" in flags, "mode": resolution,
                "activeModeId": int(active.group(1)) if active else None,
                "layerStack": None, "renderSurface": None, "clientTarget": None}
        physical = blocks.get((display_id, "physical"))
        if physical:
            ptext = physical[1]
            stack = re.search(r'layerFilter=\{layerStack=(\d+)', ptext)
            size = re.search(r'^\s+size=\[(\d+) (\d+)\]', ptext, re.M)
            acquired = re.search(r'state=ACQUIRED[^\[\n]*\[(\d+)x(\d+):', ptext)
            info["layerStack"] = int(stack.group(1)) if stack else None
            info["renderSurface"] = f"{size.group(1)}x{size.group(2)}" if size else None
            info["clientTarget"] = f"{acquired.group(1)}x{acquired.group(2)}" if acquired else None
        displays[display_id] = info
    return displays


def lower_display(dump):
    """(display_id, info) of the non-primary internal display, or (None, None)."""
    for display_id, info in parse_displays(dump).items():
        if not info["primary"]:
            return display_id, info
    return None, None


def problems(info):
    """Human-readable mismatches between the panel mode and what SurfaceFlinger renders."""
    found = []
    if not info or not info["mode"]:
        return ["lower display mode not found in dumpsys SurfaceFlinger"]
    if info["renderSurface"] and info["renderSurface"] != info["mode"]:
        found.append(f"framebuffer {info['renderSurface']} != panel mode {info['mode']}")
    if info["clientTarget"] and info["clientTarget"] != info["mode"]:
        found.append(f"HWC client target {info['clientTarget']} != panel mode {info['mode']}")
    return found


class Device:
    def __init__(self, adb, serial):
        self.base = [str(adb), "-s", serial]

    def run(self, *args, check=True):
        result = subprocess.run(self.base + list(args), capture_output=True, text=True, timeout=120)
        if check and result.returncode != 0:
            raise RuntimeError(f"{' '.join(args)} failed: {result.stderr.strip() or result.stdout.strip()}")
        return result.stdout

    def surfaceflinger(self):
        return self.run("shell", "dumpsys SurfaceFlinger")


def build_dex(workdir):
    classes = workdir / "classes"
    classes.mkdir()
    android_jar = sorted((SDK / "platforms").glob("android-*/android.jar"))[-1]
    d8 = sorted((SDK / "build-tools").glob("*/d8"))[-1]
    subprocess.run([str(JAVA_HOME / "bin/javac"), "-source", "8", "-target", "8", "-nowarn",
                    "-cp", str(android_jar), "-d", str(classes), str(JAVA_SOURCE)],
                   check=True, capture_output=True, text=True)
    subprocess.run([str(d8), "--min-api", "26", "--output", str(workdir),
                    *map(str, classes.glob("*.class"))],
                   check=True, capture_output=True, text=True,
                   env=dict(os.environ, JAVA_HOME=str(JAVA_HOME)))
    return workdir / "classes.dex"


def repair(device, display_id, info):
    width, height = info["mode"].split("x")
    workdir = Path(tempfile.mkdtemp(prefix="thor-lower-display-"))
    try:
        dex = build_dex(workdir)
        device.run("push", str(dex), DEVICE_DEX)
        helper = f"CLASSPATH={DEVICE_DEX} app_process /system/bin SfLowerDisplay"
        print(device.run("shell", f"{helper} size {display_id} {width} {height}").strip())
        print(device.run("shell", f"{helper} client-frame {info['layerStack']} 600").strip())
    finally:
        device.run("shell", f"rm -f {DEVICE_DEX}", check=False)
        shutil.rmtree(workdir, ignore_errors=True)


def describe(display_id, info):
    return (f"lower display {display_id}: mode {info['mode']} (activeModeId {info['activeModeId']}), "
            f"framebuffer {info['renderSurface']}, client target {info['clientTarget']}, "
            f"layerStack {info['layerStack']}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repair", action="store_true",
                        help="fix a mismatch (the lower panel must be ON)")
    parser.add_argument("--force", action="store_true",
                        help="with --repair, re-apply even when no mismatch is found")
    parser.add_argument("--adb", type=Path, default=DEFAULT_ADB)
    parser.add_argument("--serial", default=os.environ.get("ANDROID_SERIAL", DEFAULT_SERIAL))
    args = parser.parse_args(argv)
    device = Device(args.adb, args.serial)
    display_id, info = lower_display(device.surfaceflinger())
    if display_id is None:
        print("no secondary internal display found")
        return 1
    print(describe(display_id, info))
    found = problems(info)
    if not found and not (args.repair and args.force):
        print("OK")
        return 0
    if found:
        print("MISMATCH: " + "; ".join(found))
    if not args.repair:
        return 2
    if info["layerStack"] is None:
        print("cannot repair: lower layer stack unknown")
        return 1
    repair(device, display_id, info)
    display_id, info = lower_display(device.surfaceflinger())
    print(describe(display_id, info))
    found = problems(info)
    print("REPAIRED" if not found else "STILL MISMATCHED: " + "; ".join(found))
    return 0 if not found else 1


if __name__ == "__main__":
    sys.exit(main())
