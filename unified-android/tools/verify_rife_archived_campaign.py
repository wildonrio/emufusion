#!/usr/bin/env python3
"""Re-verify a RIFE campaign assembled from immutable physical captures.

This is deliberately stricter than concatenating timing reports.  Every
capture root must prove the same installed APK, Thor target, N64 route, core,
and ROM identity.  Each component is re-derived from its original complete
log and raw SurfaceFlinger timestamps, and process-local timing identities are
partitioned by an explicit archive-session identity.

The result remains timing/numeric evidence only.  It can never set
``qualified=true`` because moving-game visual inspection is an independent
acceptance requirement.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import verify_rife_frame_generation_timing as timing


EXPECTED_ENGINE = "mupen64plus-next"
EXPECTED_SYSTEM = "n64"
EXPECTED_CORE = "liblucent_core_mupen64plus_next.so"
HEX_64 = re.compile(r"^[0-9a-f]{64}$")
ROUTE_RE = re.compile(
    r"LucentInWindow\(\s*(\d+)\): In-window route accepted "
    r"engine=([^\s]+) system=([^\s]+)"
)
CORE_RE = re.compile(r"core library loaded path=([^\s]+)")
GOODNAME_RE = re.compile(r"mupen64plus: Goodname:\s*(.+?)\s*$", re.MULTILINE)
MD5_RE = re.compile(r"mupen64plus: MD5:\s*([0-9A-Fa-f]{32})")
CRC_RE = re.compile(
    r"mupen64plus: CRC:\s*([0-9A-Fa-f]{8})\s+([0-9A-Fa-f]{8})"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise timing.EvidenceError(message)


def _one(pattern: re.Pattern[str], text: str, label: str) -> tuple[str, ...]:
    matches = pattern.findall(text)
    normalized = []
    for match in matches:
        normalized.append((match,) if isinstance(match, str) else tuple(match))
    unique = sorted(set(normalized))
    _require(len(unique) == 1, f"archived RIFE {label} is missing or ambiguous")
    return unique[0]


def _actual_present_timestamps(path: Path) -> list[int]:
    lines = [line.strip() for line in path.read_text(
        encoding="utf-8", errors="replace").splitlines() if line.strip()]
    _require(len(lines) >= 32,
             "archived SurfaceFlinger evidence has fewer than 31 frames")
    int(lines[0])  # Validate the refresh-period header.
    maximum = (1 << 63) - 1
    timestamps = []
    for line in lines[1:]:
        columns = line.split()
        if len(columns) < 3:
            continue
        actual = int(columns[1])
        if 0 < actual < maximum:
            timestamps.append(actual)
    _require(len(timestamps) >= 31,
             "archived SurfaceFlinger evidence has too few actual presents")
    _require(all(right > left for left, right in zip(
        timestamps, timestamps[1:])),
        "archived SurfaceFlinger actual presents are not monotonic")
    return timestamps


def _root_binding(root: Path) -> dict[str, Any]:
    results_path = root / "results.json"
    _require(results_path.is_file(), "archived capture lacks results.json")
    try:
        results = json.loads(results_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise timing.EvidenceError(
            "archived capture results are unreadable") from error
    expected = str(results.get("expectedSha256", ""))
    exact = results.get("exactInstall") or {}
    route = results.get("routeClosure") or {}
    _require(bool(HEX_64.fullmatch(expected)),
             "archived capture has no immutable APK hash")
    _require(str(exact.get("candidateSha256", "")) == expected and
             str(exact.get("installedSha256", "")) == expected,
             "archived capture installed a different APK")
    _require(route.get("pass") is True and
             str(route.get("apkSha256", "")) == expected,
             "archived capture route closure is not bound to its APK")
    n64_routes = [value for value in route.get("routes", [])
                  if value.get("system") == EXPECTED_SYSTEM and
                  value.get("engine") == "mupen64plusnext"]
    _require(len(n64_routes) == 1 and n64_routes[0].get("pass") is True and
             Path(str(n64_routes[0].get("core", ""))).name == EXPECTED_CORE,
             "archived capture lacks the exact N64 core route")
    target = results.get("target") or {}
    target_binding = {
        "manufacturer": str(target.get("manufacturer", "")),
        "model": str(target.get("model", "")),
        "serial": str(target.get("serial", "")),
    }
    _require(all(target_binding.values()) and
             target_binding["manufacturer"] == "AYN" and
             target_binding["model"] == "AYN Thor",
             "archived capture target is not the bound AYN Thor")
    return {
        "apkSha256": expected,
        "target": target_binding,
        "results": str(results_path.resolve()),
        "resultsSha256": _sha256(results_path),
    }


def verify_archived_campaign(capture_roots: list[Path]) -> dict[str, Any]:
    _require(len(capture_roots) >= 2,
             "archived RIFE campaign requires multiple capture roots")
    resolved = [path.resolve() for path in capture_roots]
    _require(len(set(resolved)) == len(resolved),
             "archived RIFE campaign repeats a capture root")
    bindings = [_root_binding(root) for root in resolved]
    reference_apk = bindings[0]["apkSha256"]
    reference_target = bindings[0]["target"]
    _require(all(value["apkSha256"] == reference_apk and
                 value["target"] == reference_target for value in bindings),
             "archived RIFE capture roots changed APK or target")

    reports: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    rom_identity: tuple[str, str, str, str] | None = None
    session_ids: set[str] = set()
    for root, binding in zip(resolved, bindings):
        logs = sorted(root.glob(
            "*-rife-campaign-attempt-*-framegen-logcat.txt"))
        _require(bool(logs), "archived capture root has no RIFE components")
        root_reports: list[dict[str, Any]] = []
        root_artifacts: list[dict[str, Any]] = []
        root_pid = 0
        for ordinal, log_path in enumerate(logs, 1):
            log_text = log_path.read_text(encoding="utf-8", errors="replace")
            route_pid, engine, system = _one(
                ROUTE_RE, log_text, "in-window route")
            _require(engine == EXPECTED_ENGINE and system == EXPECTED_SYSTEM,
                     "archived RIFE route changed engine or system")
            pid = int(route_pid)
            _require(pid > 0 and (root_pid == 0 or pid == root_pid),
                     "archived capture root changed app process")
            root_pid = pid
            core_path, = _one(CORE_RE, log_text, "core library")
            _require(Path(core_path).name == EXPECTED_CORE,
                     "archived RIFE core library changed")
            goodname, = _one(GOODNAME_RE, log_text, "ROM goodname")
            md5, = _one(MD5_RE, log_text, "ROM MD5")
            crc_a, crc_b = _one(CRC_RE, log_text, "ROM CRC")
            current_rom = (goodname.strip(), md5.upper(),
                           crc_a.upper(), crc_b.upper())
            if rom_identity is None:
                rom_identity = current_rom
            _require(current_rom == rom_identity,
                     "archived RIFE campaign changed ROM identity")

            stem = log_path.name[:-len("-framegen-logcat.txt")]
            candidates = []
            for latency_path in sorted(root.glob(
                    stem + "-surfaceflinger-latency-*.txt")):
                try:
                    report = timing.verify_timing(
                        log_text, role="primary", display_id=0,
                        actual_present_timestamps=
                            _actual_present_timestamps(latency_path),
                        minimum_span_ns=timing.MIN_RUNTIME_SPAN_NS,
                    )
                except (OSError, ValueError, timing.EvidenceError):
                    continue
                candidates.append((
                    int(report["surfaceFlingerRawOverlapFrames"]),
                    latency_path, report,
                ))
            _require(bool(candidates),
                     "archived RIFE component has no valid compositor trace")
            candidates.sort(key=lambda value: value[0], reverse=True)
            _require(len(candidates) == 1 or
                     candidates[0][0] > candidates[1][0],
                     "archived RIFE component has ambiguous compositor traces")
            overlap, latency_path, report = candidates[0]
            checkpoint_matches = sorted(root.glob(
                f"*-rife-campaign-segment-{ordinal:02d}.png"))
            _require(len(checkpoint_matches) == 1 and
                     checkpoint_matches[0].stat().st_size > 0,
                     "archived RIFE component lacks its race checkpoint")
            root_reports.append(report)
            root_artifacts.append({
                "component": ordinal,
                "pid": pid,
                "log": str(log_path),
                "logSha256": _sha256(log_path),
                "latency": str(latency_path),
                "latencySha256": _sha256(latency_path),
                "raceCheckpoint": str(checkpoint_matches[0]),
                "raceCheckpointSha256": _sha256(checkpoint_matches[0]),
                "rawSurfaceFlingerOverlapFrames": overlap,
            })
        session_seed = "|".join((
            binding["resultsSha256"], str(root_pid),
            str(min(int(value["timingStartNs"]) for value in root_reports)),
            str(max(int(value["timingEndNs"]) for value in root_reports)),
        ))
        session = hashlib.sha256(session_seed.encode("ascii")).hexdigest()
        _require(session not in session_ids,
                 "archived RIFE capture session identity repeated")
        session_ids.add(session)
        for report, artifact in zip(root_reports, root_artifacts):
            report["captureSession"] = session
            artifact["captureSession"] = session
            reports.append(report)
            artifacts.append(artifact)

    campaign = timing.verify_campaign(reports)
    _require(rom_identity is not None, "archived campaign has no ROM identity")
    campaign["archiveBinding"] = {
        "apkSha256": reference_apk,
        "target": reference_target,
        "engine": EXPECTED_ENGINE,
        "system": EXPECTED_SYSTEM,
        "coreLibrary": EXPECTED_CORE,
        "rom": {
            "goodname": rom_identity[0],
            "md5": rom_identity[1],
            "crc": [rom_identity[2], rom_identity[3]],
        },
        "captureRoots": bindings,
    }
    campaign["artifacts"] = artifacts
    campaign["qualificationBlockedBy"] = \
        "moving-game manual visual inspection"
    campaign["qualified"] = False
    return campaign


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture-root", action="append", type=Path,
                        required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = verify_archived_campaign(args.capture_root)
    except (OSError, ValueError, timing.EvidenceError) as error:
        print(json.dumps({"timingPassed": False, "error": str(error)},
                         sort_keys=True))
        return 1
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
