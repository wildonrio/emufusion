#!/usr/bin/env python3
"""Bounded physical strict-Off cadence proof for one built-in game route."""

from __future__ import annotations

import argparse
import json
import math
import re
import shlex
import statistics
import subprocess
import time
from pathlib import Path


PACKAGE = "com.thorium.preview"
ACTIVITY = "com.thorium.preview/org.pegasus_frontend.android.MainActivity"
ACTION = "com.thorium.preview.LAUNCH_INTERNAL_GAME"
ALLOWED_SOURCE_HZ = (120.0, 60.0, 40.0, 30.0, 24.0, 20.0, 15.0, 12.0, 10.0)

ROUTE = re.compile(r"In-window route accepted engine=(\S+) system=(\S+)")
STRICT_OFF = re.compile(
    r"Frame generation Off; engine owns the display Surface directly "
    r"surfaceIdentity=(true|false) rendererCreated=(\d+) liveRenderers=(\d+)\b"
)
SOFTWARE_CLOCK = re.compile(
    r"Display-synchronized core clock engine=(\S+) system=(\S+) "
    r"declaredHz=([0-9.]+) synchronizedHz=([0-9.]+) panelHz=([0-9.]+) "
    r"uniform=(true|false)"
)
HARDWARE_CLOCK = re.compile(
    r"Display-synchronized hardware core declaredHz=([0-9.]+) "
    r"synchronizedHz=([0-9.]+) panelHz=([0-9.]+) uniform=(true|false)"
)
PRODUCER_CLOCK = re.compile(
    r"Producer clock engine=(\S+) declaredVideoHz=([0-9.]+)"
)
NATIVE_SPEED = re.compile(
    r"engine speed engine=(\S+) system=(\S+) averageGameFps=([0-9.]+)"
)
PANEL_MODE = re.compile(
    r"Requested native gameplay panel mode display=0 modeId=(\d+) "
    r"refreshHz=([0-9.]+)"
)
HEALTH = re.compile(
    r"Health engine=(\S+) fps=([0-9.]+) frames=(\d+) "
    r"audioUnderruns=(-?\d+) audioReceived=(\d+) audioWritten=(\d+) "
    r"audioDropped=(\d+) audioRate=(\d+) audioStarted=(true|false) "
    r"audioHead=(\d+)"
)
RUNTIME = re.compile(
    r"Runtime telemetry engine=(\S+) system=(\S+) frames=(\d+) "
    r"elapsedMs=(\d+) measuredFps=([0-9.]+) targetFps=([0-9.]+).*?"
    r"audioDroppedFrames=(\d+) audioFocusDroppedFrames=(\d+).*?"
    r"audioWriteErrors=(\d+) audioNativeDrainBoundHits=(\d+) "
    r"audioUnderruns=(\d+).*?directMailboxBusyDrops=(\d+).*?"
    r"directPresentFailures=(\d+) directPresentFps=([0-9.]+).*?"
    r"videoPoolExhaustions=(\d+)"
)


def adb(adb_path: Path, serial: str, *arguments: str,
        check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(adb_path), "-s", serial, *arguments], check=check,
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )


def remote_shell(adb_path: Path, serial: str, arguments: list[str],
                 check: bool = True) -> subprocess.CompletedProcess[str]:
    command = " ".join(shlex.quote(value) for value in arguments)
    return adb(adb_path, serial, "shell", command, check=check)


def actual_timestamps(latency_text: str) -> list[int]:
    values: set[int] = set()
    for line in latency_text.splitlines():
        columns = line.split()
        if len(columns) < 3 or not all(value.isdigit() for value in columns[:3]):
            continue
        actual = int(columns[1])
        if 0 < actual < (1 << 63) - 1:
            values.add(actual)
    return sorted(values)


def actual_timestamp_windows(latency_text: str) -> list[list[int]]:
    return [values for block in latency_text.split("\n---capture---\n")
            if (values := actual_timestamps(block))]


def nearest_allowed(hz: float) -> float:
    return min(ALLOWED_SOURCE_HZ, key=lambda candidate: abs(candidate - hz))


def rolling_health_fps(rows: list[re.Match[str]]) -> list[float]:
    """Recover rolling FPS from cumulative health rows.

    The engine health logger reports frames plus average FPS since launch.  Using
    that average directly makes shader compilation and other cold-start work look
    like an ongoing cadence fault.  Frame/average gives the cumulative elapsed
    time, so consecutive rows provide the bounded rolling rate we actually need.
    """
    rates: list[float] = []
    for previous, current in zip(rows, rows[1:]):
        previous_fps = float(previous.group(2))
        current_fps = float(current.group(2))
        previous_frames = int(previous.group(3))
        current_frames = int(current.group(3))
        if previous_fps <= 0.0 or current_fps <= 0.0:
            continue
        elapsed = current_frames / current_fps - previous_frames / previous_fps
        advanced = current_frames - previous_frames
        if elapsed > 0.0 and advanced > 0:
            rates.append(advanced / elapsed)
    return rates


def health_counter_increases(rows: list[re.Match[str]], group: int) -> list[int]:
    return [
        int(current.group(group)) - int(previous.group(group))
        for previous, current in zip(rows, rows[1:])
        if int(current.group(group)) > int(previous.group(group))
    ]


def analyze(log_text: str, latency_text: str, engine: str,
            system: str, minimum_presents: int = 100,
            expected_present_hz: float | None = None) -> dict[str, object]:
    errors: list[str] = []
    # A guest video clock or callback count does not establish a game's genuine
    # image/presentation rate. The caller must identify its intended test rate.
    if (expected_present_hz is None or not math.isfinite(expected_present_hz)
            or expected_present_hz <= 0):
        errors.append("missing independently established presentation target")
        expected_present_hz = None
    route_matches = list(ROUTE.finditer(log_text))
    route = next((match for match in reversed(route_matches)
                  if match.group(1) == engine and match.group(2) == system), None)
    if route is None:
        errors.append("missing exact in-window route")
        bounded = log_text
    else:
        bounded = log_text[route.start():]
    off_rows = list(STRICT_OFF.finditer(bounded))
    # An earlier clean attachment cannot certify a later surface recreation.
    # This runner certifies a fresh-process Off launch, so both lifetime-created
    # and currently-live counts must remain zero at every observed attachment.
    if not off_rows or any(row.group(1) != "true" or
                           int(row.group(2)) != 0 or int(row.group(3)) != 0
                           for row in off_rows):
        errors.append("strict Off did not preserve direct Surface identity")

    declared = synchronized = advertised_panel = None
    software = [match for match in SOFTWARE_CLOCK.finditer(bounded)
                if match.group(1) == engine and match.group(2) == system]
    hardware = list(HARDWARE_CLOCK.finditer(bounded))
    producer = [match for match in PRODUCER_CLOCK.finditer(bounded)
                if match.group(1) == engine]
    native_speed = [match for match in NATIVE_SPEED.finditer(bounded)
                    if match.group(1) == engine and match.group(2) == system and
                    float(match.group(3)) > 0.0]
    native_rates = [float(match.group(3)) for match in native_speed[-4:]]
    observed_engine_hz = (nearest_allowed(statistics.median(native_rates))
                          if len(native_rates) >= 4 else None)
    uniform = None
    if software:
        clock = software[-1]
        declared, synchronized, advertised_panel = map(
            float, (clock.group(3), clock.group(4), clock.group(5)))
        uniform = clock.group(6) == "true"
    elif hardware:
        clock = hardware[-1]
        declared, synchronized, advertised_panel = map(
            float, (clock.group(1), clock.group(2), clock.group(3)))
        uniform = clock.group(4) == "true"
        if producer and abs(float(producer[-1].group(2)) - declared) > 0.001:
            errors.append("producer clock differs from synchronized core declaration")
    if declared is None and observed_engine_hz is None:
        errors.append("missing measured engine source clock")
    if synchronized is not None:
        if not uniform:
            errors.append("engine clock is not uniform on Thor")
        if abs(synchronized - declared) / declared > 0.0075:
            errors.append("game-speed correction exceeds 0.75 percent")

    # The host's initial panel choice legitimately precedes the exact-route
    # marker. Logcat is cleared immediately before this one launch, so the last
    # app-scoped request in the full capture still belongs to this case.
    panel_matches = list(PANEL_MODE.finditer(log_text))
    requested_panel = float(panel_matches[-1].group(2)) if panel_matches else None
    if requested_panel is None:
        errors.append("missing app-scoped native panel-mode request")

    health = [match for match in HEALTH.finditer(bounded)
              if match.group(1) == engine]
    runtime = [match for match in RUNTIME.finditer(bounded)
               if match.group(1) == engine and match.group(2) == system]
    engine_windows = 0
    engine_rolling_fps: list[float] = []
    if health:
        rows = health[-min(4, len(health)):]
        engine_rolling_fps = rolling_health_fps(rows)
        engine_windows = len(engine_rolling_fps)
        if len(engine_rolling_fps) < 2:
            errors.append("insufficient engine-retired frame windows")
        for index, fps in enumerate(engine_rolling_fps, 1):
            target = synchronized or nearest_allowed(fps)
            if abs(fps - target) > max(0.75, target * 0.015):
                errors.append(f"engine window {index} left cadence tolerance")
        if (health_counter_increases(rows, 4) or
                health_counter_increases(rows, 7)):
            errors.append("engine sample gained an audio discontinuity")
        for index, row in enumerate(rows, 1):
            if row.group(9) != "true" or int(row.group(10)) <= 0:
                errors.append(f"engine window {index} has an audio discontinuity")
    elif runtime:
        rows = runtime[-min(4, len(runtime)):]
        engine_windows = len(rows)
        if len(rows) < 3:
            errors.append("insufficient software-core telemetry windows")
        for index, row in enumerate(rows, 1):
            target = float(row.group(6))
            if abs(float(row.group(5)) - target) > max(0.75, target * 0.015):
                errors.append(f"software window {index} left cadence tolerance")
            if any(int(row.group(group)) != 0
                   for group in (7, 8, 9, 10, 11, 12, 13, 15)):
                errors.append(f"software window {index} dropped audio or video")
    elif observed_engine_hz is not None:
        engine_windows = len(native_rates)
        for index, fps in enumerate(native_rates, 1):
            if abs(fps - observed_engine_hz) > max(
                    0.75, observed_engine_hz * 0.015):
                errors.append(f"native engine window {index} left cadence tolerance")

    timestamp_windows = actual_timestamp_windows(latency_text)
    timestamps = sorted({value for window in timestamp_windows for value in window})
    observed = mean_hz = minimum_ns = maximum_ns = None
    maximum_hold_slots = None
    expected_hold_slots = None
    incorrect_hold_count = None
    hold_histogram: dict[int, int] = {}
    if len(timestamp_windows) < 4 or any(
            len(window) < minimum_presents for window in timestamp_windows):
        errors.append("insufficient untouched SurfaceFlinger windows")
    else:
        interval_windows = [[second - first for first, second in zip(
            window, window[1:]) if second > first]
            for window in timestamp_windows]
        intervals = [value for window in interval_windows for value in window]
        headers = [block.strip().splitlines()[0] for block in
                   latency_text.split("\n---capture---\n") if block.strip()]
        periods = [int(value) for value in headers if value.isdigit() and int(value) > 0]
        if len(periods) != len(timestamp_windows):
            errors.append("missing observed refresh period")
        scan_ns = statistics.median(periods) if periods else None
        if scan_ns is None:
            # Retain diagnostics, but a missing physical clock can never pass.
            scan_ns = 1_000_000_000.0 / (requested_panel or 60.0)
        else:
            observed = 1_000_000_000.0 / scan_ns
            if any(abs(value - scan_ns) > scan_ns * 0.001 for value in periods):
                errors.append("physical refresh changed during sample")
            if requested_panel is not None and abs(observed - requested_panel) > requested_panel * 0.001:
                errors.append("observed refresh period differs from requested panel mode")
        tolerance_ns = max(300_000.0, scan_ns * 0.04)
        hold_slots = [max(1, round(interval / scan_ns)) for interval in intervals]
        maximum_hold_slots = max(hold_slots)
        for slots in hold_slots:
            hold_histogram[slots] = hold_histogram.get(slots, 0) + 1
        if any(abs(interval - slots * scan_ns) > tolerance_ns
               for interval, slots in zip(intervals, hold_slots)):
            errors.append("SurfaceFlinger update left the physical scan lattice")
        if expected_present_hz is not None:
            ratio = 1_000_000_000.0 / (scan_ns * expected_present_hz)
            if ratio < 1 - 0.001 or abs(ratio - round(ratio)) > 0.001:
                errors.append("presentation target does not divide physical refresh")
            else:
                expected_hold_slots = round(ratio)
                incorrect_hold_count = sum(slots != expected_hold_slots for slots in hold_slots)
                if incorrect_hold_count:
                    errors.append("uneven or incorrect physical frame holds")
        mean_hz = len(intervals) * 1_000_000_000.0 / sum(
            window[-1] - window[0] for window in timestamp_windows)
        minimum_ns, maximum_ns = min(intervals), max(intervals)

    fatal = re.search(
        r"Engine session error|Renderer stopped|Fatal signal|ANR in " +
        re.escape(PACKAGE), bounded, re.I)
    if fatal:
        errors.append("engine/session crash marker present")
    return {
        "pass": not errors,
        "errors": errors,
        "engine": engine,
        "system": system,
        "declaredHz": declared,
        "synchronizedHz": synchronized,
        "observedEngineHz": observed_engine_hz,
        "nativeEngineFps": native_rates,
        "advertisedPanelHz": advertised_panel,
        "requestedPanelHz": requested_panel,
        "engineWindows": engine_windows,
        "engineRollingFps": engine_rolling_fps,
        "surfacePresentSamples": len(timestamps),
        "surfaceWindows": len(timestamp_windows),
        "observedSurfaceTierHz": observed,
        "surfaceMeanHz": mean_hz,
        "surfaceIntervalMinNs": minimum_ns,
        "surfaceIntervalMaxNs": maximum_ns,
        "surfaceMaximumHoldSlots": maximum_hold_slots,
        "expectedPresentHz": expected_present_hz,
        "expectedHoldSlots": expected_hold_slots,
        "incorrectHoldCount": incorrect_hold_count,
        "holdSlotHistogram": hold_histogram,
    }


def gameplay_layer(adb_path: Path, serial: str) -> str | None:
    listing = adb(adb_path, serial, "shell", "dumpsys", "SurfaceFlinger",
                  "--list").stdout
    candidates = [line.strip() for line in listing.splitlines()
                  if "SurfaceView[com.thorium.preview/" in line and
                  "MainActivity](BLAST)" in line]
    return candidates[-1] if candidates else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--adb", required=True, type=Path)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--engine", required=True)
    parser.add_argument("--system", required=True)
    parser.add_argument("--path", required=True)
    parser.add_argument("--title", default="strict-off-cadence")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--settle-seconds", type=float, default=12.0)
    parser.add_argument("--sample-seconds", type=float, default=24.0)
    parser.add_argument("--expected-present-hz", type=float, required=True,
                        help="Independently established presentation target, not guest callback rate")
    parser.add_argument("--sleep-after", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    adb(args.adb, args.serial, "shell", "am", "force-stop", PACKAGE)
    adb(args.adb, args.serial, "logcat", "-c")
    remote_shell(args.adb, args.serial, ["input", "keyevent", "224"])
    remote_shell(args.adb, args.serial,
                 ["cmd", "display", "set-brightness", "0.12"], check=False)
    remote_shell(args.adb, args.serial, ["wm", "dismiss-keyguard"], check=False)
    launch = remote_shell(args.adb, args.serial, [
        "am", "start", "--display", "0", "-W", "-n", ACTIVITY,
        "-a", ACTION, "--activity-single-top", "--activity-clear-top",
        "--es", "path", args.path, "--es", "engine_id", args.engine,
        "--es", "system_id", args.system, "--es", "game_id",
        "strict-off-" + args.system, "--es", "title", args.title,
    ], check=False)
    if launch.returncode or "Error:" in launch.stdout:
        raise SystemExit("launch failed: " + launch.stdout)
    deadline = time.monotonic() + 45.0
    layer = None
    while time.monotonic() < deadline:
        log_now = adb(args.adb, args.serial, "logcat", "-d", "-v", "threadtime").stdout
        exact_route = (f"In-window route accepted engine={args.engine} "
                       f"system={args.system}")
        if exact_route in log_now:
            layer = gameplay_layer(args.adb, args.serial)
            if layer:
                break
        time.sleep(0.5)
    if layer is None:
        raise SystemExit("no exact gameplay SurfaceView appeared")
    time.sleep(args.settle_seconds)
    remote_shell(args.adb, args.serial,
                 ["dumpsys", "SurfaceFlinger", "--latency-clear", layer])
    captures: list[str] = []
    window_seconds = args.sample_seconds / 4.0
    for _ in range(4):
        time.sleep(window_seconds)
        captures.append(remote_shell(
            args.adb, args.serial,
            ["dumpsys", "SurfaceFlinger", "--latency", layer],
            check=False,
        ).stdout)
    log_text = adb(args.adb, args.serial, "logcat", "-d", "-v", "threadtime").stdout
    latency_text = "\n---capture---\n".join(captures)
    result = analyze(log_text, latency_text, args.engine, args.system,
                     expected_present_hz=args.expected_present_hz)
    result["layer"] = layer
    result["path"] = args.path
    (args.output / "logcat.txt").write_text(log_text, encoding="utf-8")
    (args.output / "surfaceflinger-latency.txt").write_text(
        latency_text, encoding="utf-8")
    (args.output / "result.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    adb(args.adb, args.serial, "shell", "am", "force-stop", PACKAGE)
    if args.sleep_after:
        remote_shell(args.adb, args.serial, ["input", "keyevent", "223"])
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
