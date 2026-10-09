#!/usr/bin/env python3
"""Fail-closed observer for the Eden/CoreTiming Switch crash gate.

This tool never launches, exits, pauses, resumes, or injects input. A device
operator must put a known game into active gameplay first. The observer then
requires a stable process, fresh positive engine-FPS telemetry, changing pixels,
and a human-approved gameplay ROI on every formal ten-minute run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import struct
import subprocess
import sys
import threading
import time
import uuid


FPS_RE = re.compile(r"averageGameFps=([0-9]+(?:\.[0-9]+)?)")
CRASH_RE = re.compile(
    r"(?:Fatal signal|SIGSEGV|signal 11|fibonacci_heap|CoreTiming::|"
    r"Killing .*thorium|installPackageLI)", re.IGNORECASE)
PSNR_RE = re.compile(r"average:([0-9.]+|inf)", re.IGNORECASE)
SSIM_RE = re.compile(r"All:([0-9.]+)")


class GateFailure(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(command: list[str], *, timeout: float = 30, binary: bool = False):
    completed = subprocess.run(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=timeout, check=False, text=not binary)
    if completed.returncode != 0:
        stderr = completed.stderr if not binary else completed.stderr.decode(errors="replace")
        raise GateFailure(f"command failed ({completed.returncode}): {' '.join(command)}\n{stderr}")
    return completed.stdout


def adb_command(adb: str, serial: str, *arguments: str) -> list[str]:
    return [adb, "-s", serial, *arguments]


def one_pid(adb: str, serial: str, package: str) -> int:
    output = run(adb_command(adb, serial, "shell", "pidof", package)).strip()
    fields = output.split()
    if len(fields) != 1 or not fields[0].isdigit():
        raise GateFailure(f"expected exactly one {package} pid, got {output!r}")
    return int(fields[0])


def assert_foreground(adb: str, serial: str, package: str) -> None:
    output = run(adb_command(adb, serial, "shell", "dumpsys", "activity", "activities"))
    pattern = re.compile(r"(?:topResumedActivity|mResumedActivity|ResumedActivity).*" +
                         re.escape(package) + r"/", re.IGNORECASE)
    if not pattern.search(output):
        raise GateFailure(f"{package} is not the top resumed activity")


def capture(adb: str, serial: str, destination: Path) -> tuple[int, int]:
    png = run(adb_command(adb, serial, "exec-out", "screencap", "-p"),
              timeout=20, binary=True)
    if len(png) < 24 or png[:8] != b"\x89PNG\r\n\x1a\n":
        raise GateFailure("screencap did not return a PNG")
    width, height = struct.unpack(">II", png[16:24])
    if width < 640 or height < 360:
        raise GateFailure(f"implausible screenshot dimensions {width}x{height}")
    destination.write_bytes(png)
    return width, height


def ffmpeg_metric(ffmpeg: str, first: Path, second: Path, filter_name: str,
                  crop: list[int] | None = None) -> float:
    if crop:
        x, y, width, height = crop
        graph = (f"[0:v]crop={width}:{height}:{x}:{y}[a];"
                 f"[1:v]crop={width}:{height}:{x}:{y}[b];[a][b]{filter_name}")
    else:
        graph = filter_name
    completed = subprocess.run(
        [ffmpeg, "-hide_banner", "-nostdin", "-i", str(first), "-i", str(second),
         "-lavfi", graph, "-f", "null", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    if completed.returncode != 0:
        raise GateFailure(f"ffmpeg {filter_name} failed:\n{completed.stderr}")
    expression = SSIM_RE if filter_name == "ssim" else PSNR_RE
    matches = expression.findall(completed.stderr)
    if not matches:
        raise GateFailure(f"ffmpeg emitted no {filter_name} metric")
    value = matches[-1].lower()
    return float("inf") if value == "inf" else float(value)


class LogObserver:
    def __init__(self, adb: str, serial: str):
        self.lines: queue.Queue[tuple[float, str]] = queue.Queue()
        self.all_lines: list[str] = []
        self.process = subprocess.Popen(
            # Do not tag-filter this stream. FPS comes from LucentPhase3Engine,
            # but native crash, package-kill and install-contention evidence is
            # emitted by DEBUG, crash_dump, ActivityManager and PackageManager.
            # A filtered stream would make the crash gate silently blind.
            adb_command(adb, serial, "logcat", "-v", "epoch", "-T", "1"),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            bufsize=1)
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def _read(self) -> None:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            line = line.rstrip("\n")
            self.all_lines.append(line)
            self.lines.put((time.monotonic(), line))

    def drain(self) -> list[tuple[float, str]]:
        result = []
        while True:
            try:
                result.append(self.lines.get_nowait())
            except queue.Empty:
                return result

    def close(self) -> None:
        self.process.terminate()
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=3)


def load_proof(path: Path) -> dict:
    proof = json.loads(path.read_text(encoding="utf-8"))
    required = ("schemaVersion", "gameId", "referenceImage", "referenceSha256",
                "crop", "minimumSsim", "approvedBy", "approvedAt")
    missing = [key for key in required if key not in proof]
    if missing:
        raise GateFailure(f"proof manifest is missing: {', '.join(missing)}")
    if proof["schemaVersion"] != 1 or not proof["approvedBy"] or not proof["approvedAt"]:
        raise GateFailure("proof manifest is not a human-approved schemaVersion 1 proof")
    reference = (path.parent / proof["referenceImage"]).resolve()
    if not reference.is_file() or sha256(reference) != proof["referenceSha256"]:
        raise GateFailure("gameplay reference image is missing or its SHA-256 does not match")
    crop = proof["crop"]
    if (not isinstance(crop, list) or len(crop) != 4 or
            any(not isinstance(value, int) or value < 0 for value in crop) or
            crop[2] <= 0 or crop[3] <= 0):
        raise GateFailure("proof crop must be [x, y, positive width, positive height]")
    proof["referencePath"] = str(reference)
    return proof


def observe(args: argparse.Namespace) -> int:
    if args.duration_seconds < 600 and not args.allow_short_smoke:
        raise GateFailure("formal runs must be at least 600 seconds")
    if args.sample_seconds < 2 or args.sample_seconds > 30:
        raise GateFailure("sample interval must be between 2 and 30 seconds")
    if args.minimum_fps <= 0 or args.maximum_psnr <= 0:
        raise GateFailure("FPS and PSNR thresholds must be positive")
    proof = load_proof(args.proof_manifest)
    adapter = args.adapter.resolve()
    if not adapter.is_file():
        raise GateFailure(f"missing adapter artifact: {adapter}")

    run_id = str(uuid.uuid4())
    output = args.output.resolve() / run_id
    frames = output / "frames"
    frames.mkdir(parents=True, exist_ok=False)
    result_path = output / "result.json"
    started_wall = time.time()
    result = {
        "schemaVersion": 1, "runId": run_id, "status": "FAIL",
        "formal": args.duration_seconds >= 600, "gameId": proof["gameId"],
        "adapterSha256": sha256(adapter), "durationRequestedSeconds": args.duration_seconds,
        "sampleIntervalSeconds": args.sample_seconds, "samples": [],
        "proofManifestSha256": sha256(args.proof_manifest.resolve()),
        "startedEpochSeconds": started_wall,
    }
    observer: LogObserver | None = None
    failure: str | None = None
    try:
        initial_pid = one_pid(args.adb, args.serial, args.package)
        assert_foreground(args.adb, args.serial, args.package)
        result["pid"] = initial_pid
        observer = LogObserver(args.adb, args.serial)
        time.sleep(1.0)
        observer.drain()  # discard the one historical line requested by -T 1
        gate_started = time.monotonic()
        previous: Path | None = None
        latest_fps: tuple[float, float] | None = None
        sample_index = 0
        while time.monotonic() - gate_started < args.duration_seconds:
            deadline = gate_started + (sample_index + 1) * args.sample_seconds
            time.sleep(max(0.0, deadline - time.monotonic()))
            now = time.monotonic()
            if observer.process.poll() is not None:
                raise GateFailure("logcat observer ended during the run")
            for received, line in observer.drain():
                if CRASH_RE.search(line):
                    raise GateFailure(f"crash/contention marker in logcat: {line}")
                match = FPS_RE.search(line)
                if match:
                    latest_fps = (received, float(match.group(1)))
            if latest_fps is None or now - latest_fps[0] > args.sample_seconds + 3:
                raise GateFailure("no fresh engine FPS sample in this interval")
            if latest_fps[1] < args.minimum_fps:
                raise GateFailure(f"engine FPS fell below {args.minimum_fps}: {latest_fps[1]}")
            current_pid = one_pid(args.adb, args.serial, args.package)
            if current_pid != initial_pid:
                raise GateFailure(f"pid changed from {initial_pid} to {current_pid}")
            assert_foreground(args.adb, args.serial, args.package)
            current = frames / f"frame-{sample_index:04d}.png"
            dimensions = capture(args.adb, args.serial, current)
            ssim = ffmpeg_metric(args.ffmpeg, Path(proof["referencePath"]), current,
                                  "ssim", proof["crop"])
            if ssim < float(proof["minimumSsim"]):
                raise GateFailure(
                    f"gameplay proof ROI SSIM {ssim:.5f} is below {proof['minimumSsim']}")
            psnr = None
            if previous is not None:
                psnr = ffmpeg_metric(args.ffmpeg, previous, current, "psnr")
                if psnr == float("inf") or psnr > args.maximum_psnr:
                    raise GateFailure(f"frame is frozen/nearly frozen (PSNR {psnr})")
            result["samples"].append({
                "elapsedSeconds": round(now - gate_started, 3), "pid": current_pid,
                "averageGameFps": latest_fps[1], "screenshot": str(current.relative_to(output)),
                "screenshotSha256": sha256(current), "dimensions": list(dimensions),
                "gameplayProofSsim": ssim, "previousFramePsnr": psnr,
            })
            previous = current
            sample_index += 1
        result["durationObservedSeconds"] = time.monotonic() - gate_started
        if len(result["samples"]) < 2:
            raise GateFailure("fewer than two screenshots were observed")
        result["status"] = "PASS"
    except Exception as error:  # preserve a machine-readable failed run
        failure = str(error)
        result["failure"] = failure
    finally:
        if observer is not None:
            observer.close()
            (output / "logcat.txt").write_text("\n".join(observer.all_lines) + "\n",
                                               encoding="utf-8")
        result["finishedEpochSeconds"] = time.time()
        result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                               encoding="utf-8")
    print(result_path)
    if failure:
        print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    print("PASS: automated run gates passed; retain the approved proof manifest with this result")
    return 0


def verify_series(args: argparse.Namespace) -> int:
    if len(args.results) != 3:
        raise GateFailure("exactly three result.json files are required")
    records = [json.loads(path.read_text(encoding="utf-8")) for path in args.results]
    for index, record in enumerate(records, 1):
        if record.get("status") != "PASS" or not record.get("formal"):
            raise GateFailure(f"run {index} is not a passed formal run")
        if record.get("durationObservedSeconds", 0) < 600:
            raise GateFailure(f"run {index} observed less than ten minutes")
    for field in ("gameId", "adapterSha256"):
        if len({record.get(field) for record in records}) != 1:
            raise GateFailure(f"the three runs do not share {field}")
    if len({record.get("runId") for record in records}) != 3:
        raise GateFailure("run IDs are not distinct")
    ordered = sorted(records, key=lambda record: record["startedEpochSeconds"])
    if records != ordered:
        raise GateFailure("result files are not in chronological order")
    summary = {
        "schemaVersion": 1, "status": "PASS", "gate": "three-consecutive-10-minute-runs",
        "gameId": records[0]["gameId"], "adapterSha256": records[0]["adapterSha256"],
        "runIds": [record["runId"] for record in records],
    }
    args.output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    print(args.output)
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    subparsers = root.add_subparsers(dest="command", required=True)
    observe_parser = subparsers.add_parser("observe")
    observe_parser.add_argument("--adb", required=True)
    observe_parser.add_argument("--serial", required=True)
    observe_parser.add_argument("--proof-manifest", type=Path, required=True)
    observe_parser.add_argument("--output", type=Path, required=True)
    observe_parser.add_argument("--adapter", type=Path, default=Path(
        "engines/build/arm64-v8a/liblucent_native_adapter_eden.so"))
    observe_parser.add_argument("--ffmpeg", default="/opt/homebrew/bin/ffmpeg")
    observe_parser.add_argument("--package", default="com.thorium.preview")
    observe_parser.add_argument("--duration-seconds", type=int, default=600)
    observe_parser.add_argument("--sample-seconds", type=int, default=5)
    observe_parser.add_argument("--minimum-fps", type=float, default=1.0)
    observe_parser.add_argument("--maximum-psnr", type=float, default=55.0)
    observe_parser.add_argument("--allow-short-smoke", action="store_true")
    observe_parser.set_defaults(function=observe)
    series = subparsers.add_parser("verify-series")
    series.add_argument("results", type=Path, nargs="+")
    series.add_argument("--output", type=Path, required=True)
    series.set_defaults(function=verify_series)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        return args.function(args)
    except GateFailure as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
