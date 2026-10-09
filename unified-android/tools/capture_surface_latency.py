#!/usr/bin/env python3
"""Read one exact live SurfaceFlinger layer; reject empty/invalid evidence.

Does not wake hardware, clear history, choose a layer, or certify cadence.
ADB's remote shell needs its own quoting, even with local subprocess argv.
Raw stdout is preserved before validation so a failed capture remains auditable.
"""
import argparse
import json
from pathlib import Path
import shlex
import subprocess


def latency_command(adb, serial, layer):
    if not serial or not layer or "\n" in layer or "\r" in layer:
        raise ValueError("exact serial and single-line layer name required")
    return [str(adb), "-s", serial, "shell",
            "dumpsys SurfaceFlinger --latency " + shlex.quote(layer)]


def inspect_history(raw):
    lines = raw.splitlines()
    if not lines or not lines[0].isdigit() or int(lines[0]) <= 0:
        raise ValueError("missing positive refresh period")
    valid = []
    intervals = []
    previous = None
    invalid = 0
    for line in lines[1:]:
        if not line.strip():
            continue
        columns = line.split()
        if len(columns) != 3 or not all(value.isdigit() for value in columns):
            raise ValueError("malformed three-column history row")
        row = tuple(map(int, columns))
        if not all(0 < value < 2**63 - 1 for value in row):
            invalid += 1
            previous = None
            continue
        actual = row[1]
        if valid and actual <= valid[-1]:
            raise ValueError("non-increasing actual-present timestamps")
        if previous is not None:
            intervals.append(actual - previous)
        previous = actual
        valid.append(actual)
    if not intervals:
        raise ValueError("no adjacent valid presents; empty history is not evidence")
    return {"period_ns": int(lines[0]), "valid_rows": len(valid),
            "invalid_rows": invalid, "adjacent_intervals": len(intervals),
            "min_interval_ns": min(intervals), "max_interval_ns": max(intervals),
            "qualification": "NOT_ASSESSED"}


def capture(adb, serial, layer, output, runner=subprocess.run):
    # Exclusive creation prevents silently overwriting a previous capture.
    with Path(output).open("x") as saved:
        result = runner(latency_command(adb, serial, layer), text=True,
                        capture_output=True, timeout=15)
        saved.write(result.stdout)
    if result.returncode:
        raise RuntimeError("ADB capture failed: " + result.stderr.strip())
    return inspect_history(result.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", required=True)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--layer", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(json.dumps(capture(args.adb, args.serial, args.layer, args.output), indent=2))


if __name__ == "__main__":
    main()
