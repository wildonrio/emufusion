#!/usr/bin/env python3
"""Fail-closed direct-cadence evidence for one moving-game session.

This verifier deliberately joins three independent boundaries:
the core clock selected by EmuFusion, rolling engine/direct/audio telemetry, and
SurfaceFlinger's actual-present timestamps for the exact gameplay layer. A
correct average with alternating long/short holds is a failure.
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import re
from dataclasses import dataclass


CLOCK_RE = re.compile(
    r"Display-synchronized core clock engine=(\S+) system=(\S+) "
    r"declaredHz=([0-9.]+) synchronizedHz=([0-9.]+) panelHz=([0-9.]+) "
    r"uniform=(true|false)"
)

RUNTIME_RE = re.compile(
    r"Runtime telemetry engine=(\S+) system=(\S+) frames=(\d+) "
    r"elapsedMs=(\d+) measuredFps=([0-9.]+) targetFps=([0-9.]+) "
    r"audioFrames=(\d+) audioStarted=(true|false) audioHead=(\d+) "
    r"audioProducedFrames=(\d+) audioWrittenFrames=(\d+) "
    r"audioDroppedFrames=(\d+) audioFocusDroppedFrames=(\d+) "
    r"audioQueuedFrames=(\d+) audioPartialWrites=(\d+) audioZeroWrites=(\d+) "
    r"audioWriteErrors=(\d+) audioNativeDrainBoundHits=(\d+) audioUnderruns=(\d+) "
    r"directMailboxOffers=(\d+) directMailboxBusyDrops=(\d+) "
    r"directPresentAttempts=(\d+) directPresentSuccesses=(\d+) "
    r"directPresentFailures=(\d+) directPresentFps=([0-9.]+) "
    r"videoBufferAllocations=(\d+) videoPoolExhaustions=(\d+)"
)


@dataclass(frozen=True)
class Result:
    engine: str
    system: str
    declared_hz: float
    synchronized_hz: float
    panel_hz: float
    correction_percent: float
    telemetry_windows: int
    surface_present_samples: int
    surface_mean_hz: float
    surface_interval_min_ns: int
    surface_interval_max_ns: int


def _actual_present_timestamps(text: str) -> list[int]:
    values: list[int] = []
    for line in text.splitlines():
        columns = line.split()
        if len(columns) < 3 or not all(column.isdigit() for column in columns[:3]):
            continue
        actual = int(columns[1])
        # SurfaceFlinger uses INT64_MAX for a row whose actual-present fence
        # has not signalled. It is a pending sentinel, not a timestamp.
        if 0 < actual < (1 << 63) - 1 and (not values or actual > values[-1]):
            values.append(actual)
    return values


def verify(log_text: str, latency_text: str, engine: str, system: str,
           minimum_windows: int = 12, minimum_surface_samples: int = 600) -> Result:
    clocks = [match for match in CLOCK_RE.finditer(log_text)
              if match.group(1) == engine and match.group(2) == system]
    if not clocks:
        raise ValueError("missing exact display-synchronized core clock")
    clock = clocks[-1]
    declared = float(clock.group(3))
    synchronized = float(clock.group(4))
    panel = float(clock.group(5))
    if clock.group(6) != "true":
        raise ValueError("core clock is not uniform on the selected panel mode")
    correction = abs(synchronized - declared) / declared
    if correction > 0.0075:
        raise ValueError("automatic game-speed correction exceeds 0.75 percent")
    ratio = panel / synchronized
    if abs(ratio - round(ratio)) > 1.0e-6:
        raise ValueError("selected source clock is not an integer panel divisor")

    rows = [match for match in RUNTIME_RE.finditer(log_text, clock.end())
            if match.group(1) == engine and match.group(2) == system]
    if len(rows) < minimum_windows:
        raise ValueError("insufficient sustained rolling telemetry")
    rows = rows[-minimum_windows:]
    for index, row in enumerate(rows, 1):
        measured = float(row.group(5))
        target = float(row.group(6))
        direct = float(row.group(25))
        tolerance = synchronized * 0.0075
        if abs(target - synchronized) > 0.001:
            raise ValueError(f"window {index} reports the wrong target clock")
        if abs(measured - synchronized) > tolerance:
            raise ValueError(f"window {index} core clock left tolerance")
        if abs(direct - synchronized) > tolerance:
            raise ValueError(f"window {index} direct presentation left tolerance")
        if row.group(8) != "true" or int(row.group(9)) <= 0:
            raise ValueError(f"window {index} has no advancing audible output")
        # dropped, focus-dropped, write errors, native drain bound, underruns
        for group in (12, 13, 17, 18, 19):
            if int(row.group(group)) != 0:
                raise ValueError(f"window {index} has an audio discontinuity")
        offers = int(row.group(20))
        busy = int(row.group(21))
        attempts = int(row.group(22))
        successes = int(row.group(23))
        failures = int(row.group(24))
        if busy or failures or not (offers == attempts == successes):
            raise ValueError(f"window {index} dropped or failed a direct video frame")
        if int(row.group(26)) > 3 or int(row.group(27)) != 0:
            raise ValueError(f"window {index} exhausted the bounded video pool")

    timestamps = _actual_present_timestamps(latency_text)
    if len(timestamps) < minimum_surface_samples:
        raise ValueError("insufficient actual SurfaceFlinger presentation samples")
    timestamps = timestamps[-minimum_surface_samples:]
    intervals = [second - first for first, second in zip(timestamps, timestamps[1:])]
    expected_ns = 1_000_000_000.0 / synchronized
    interval_tolerance_ns = max(250_000.0, expected_ns * 0.03)
    for interval in intervals:
        if abs(interval - expected_ns) > interval_tolerance_ns:
            raise ValueError("SurfaceFlinger contains a long/short hold or missed frame")
    elapsed = timestamps[-1] - timestamps[0]
    mean_hz = len(intervals) * 1_000_000_000.0 / elapsed
    if abs(mean_hz - synchronized) > synchronized * 0.0025:
        raise ValueError("SurfaceFlinger mean cadence does not match the core clock")

    return Result(
        engine=engine, system=system, declared_hz=declared,
        synchronized_hz=synchronized, panel_hz=panel,
        correction_percent=correction * 100.0,
        telemetry_windows=len(rows), surface_present_samples=len(timestamps),
        surface_mean_hz=mean_hz, surface_interval_min_ns=min(intervals),
        surface_interval_max_ns=max(intervals),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", required=True, type=pathlib.Path)
    parser.add_argument("--latency", required=True, type=pathlib.Path)
    parser.add_argument("--engine", required=True)
    parser.add_argument("--system", required=True)
    parser.add_argument("--minimum-windows", type=int, default=12)
    parser.add_argument("--minimum-surface-samples", type=int, default=600)
    arguments = parser.parse_args()
    result = verify(
        arguments.log.read_text(encoding="utf-8", errors="replace"),
        arguments.latency.read_text(encoding="utf-8", errors="replace"),
        arguments.engine, arguments.system, arguments.minimum_windows,
        arguments.minimum_surface_samples,
    )
    print(json.dumps(result.__dict__, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
