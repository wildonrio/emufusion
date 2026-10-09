#!/usr/bin/env python3
"""Fail-closed verifier for EmuFusion's Thor volume acceptance evidence.

The old runtime gate accepted a 5 -> 0 -> 5 final stream index and a logcat
subsequence.  That can pass when one press moves twice and another does not
move at all.  It also accepted one AppVolumeController ``gain=0`` log without
proving which audible sinks received that gain.  This verifier deliberately
requires both per-event observations and a PID-bound inventory of every sink
family the APK can make audible.

This is a QA tool.  It is not packaged in the Android application.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any


SCHEMA = "emufusion-volume-evidence-v2"
PACKAGE = "com.thorium.preview"
REQUIRED_SINK_ROLES = frozenset({
    "engine.libretro",
    "engine.ppsspp",
    "engine.native-adapter",
    "preview.media-player",
    "menu.soundpool",
    "browser.webview",
})
PLATFORM_STREAM_ROLES = frozenset({"browser.webview"})
# The shortest packaged menu cue is 44.966 ms. A per-ID gain application no
# later than 44 ms after SoundPool accepted playback is therefore guaranteed to
# target a still-in-flight cue rather than merely a completed/recycled ID.
SOUNDPOOL_ACTIVE_PROOF_MS = 44.0


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def _negative_infinity(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"-inf", "-infinity"}
    return isinstance(value, (int, float)) and math.isinf(float(value)) \
        and float(value) < 0


def _logcat_time_ms(line: str) -> float | None:
    match = re.search(
        r"\b(\d{2})-(\d{2})\s+(\d{2}):(\d{2}):(\d{2})\.(\d{3})\b", line
    )
    if match is None:
        return None
    month, day, hour, minute, second, millis = map(int, match.groups())
    try:
        value = datetime.datetime(2000, month, day, hour, minute, second,
                                  millis * 1000)
    except ValueError:
        return None
    return value.timestamp() * 1000.0


def _soundpool_message(line: str, expected_pid: int) -> str | None:
    # Android's brief logger: I/LucentMenuSfx( 27228): message
    brief = re.search(r"\bLucentMenuSfx\(\s*(\d+)\):\s*(.*)$", line)
    if brief is not None:
        return brief.group(2) if int(brief.group(1)) == expected_pid else None
    # Android threadtime: ... 27228 27301 I LucentMenuSfx: message
    threadtime = re.search(
        r"^\S+\s+\S+\s+(\d+)\s+\d+\s+[VDIWEF]\s+LucentMenuSfx:\s*(.*)$",
        line,
    )
    if threadtime is not None:
        return threadtime.group(2) if int(threadtime.group(1)) == expected_pid else None
    return None


def parse_soundpool_sink_transitions(logcat: str, pid: int) -> list[dict[str, Any]]:
    """Bind each in-flight SoundPool stream ID to its per-ID zero-gain log.

    The aggregate ``trackedStreams=N`` line is intentionally ignored: it was
    the previous false-pass because it did not show which IDs received gain.
    Only a positive-gain start followed by that exact ID's gain=0 line within
    the duration of the shortest packaged cue qualifies as an active sink.
    """
    if pid <= 0:
        raise ValueError("a positive EmuFusion PID is required")
    started: dict[int, tuple[float, float]] = {}
    muted: dict[int, tuple[float, float]] = {}
    start_pattern = re.compile(
        r"^SoundPool sink started stream=(\d+) gain=([-+0-9.eE]+)$"
    )
    gain_pattern = re.compile(
        r"^SoundPool sink gain stream=(\d+) gain=([-+0-9.eE]+)$"
    )
    for line in logcat.splitlines():
        message = _soundpool_message(line, pid)
        timestamp = _logcat_time_ms(line)
        if message is None or timestamp is None:
            continue
        match = start_pattern.match(message)
        if match is not None:
            stream_id, gain = int(match.group(1)), float(match.group(2))
            if stream_id > 0 and gain > 0:
                started[stream_id] = (timestamp, gain)
            continue
        match = gain_pattern.match(message)
        if match is not None:
            stream_id, gain = int(match.group(1)), float(match.group(2))
            if stream_id in started and gain == 0.0 and stream_id not in muted:
                muted[stream_id] = (timestamp, gain)
    if not started:
        raise ValueError("no positive-gain SoundPool sink start was logged for the PID")
    result: list[dict[str, Any]] = []
    for stream_id, (start_ms, start_gain) in sorted(started.items()):
        if stream_id not in muted:
            raise ValueError(
                f"SoundPool stream {stream_id} has no per-ID zero-gain application"
            )
        mute_ms, mute_gain = muted[stream_id]
        elapsed = mute_ms - start_ms
        if elapsed < 0 or elapsed > SOUNDPOOL_ACTIVE_PROOF_MS:
            raise ValueError(
                f"SoundPool stream {stream_id} zero gain arrived after {elapsed:.3f} ms; "
                f"active proof requires <= {SOUNDPOOL_ACTIVE_PROOF_MS:.0f} ms"
            )
        result.append({
            "soundPoolStreamId": stream_id,
            "startGain": start_gain,
            "localGainAtMute": mute_gain,
            "startToMuteMs": round(elapsed, 3),
            "perIdGainLogAtMute": True,
        })
    return result


def soundpool_sink_rows(logcat: str, pid: int, *,
                        mixer_before: tuple[Any, Any],
                        mixer_at_mute: tuple[Any, Any],
                        mixer_restored: tuple[Any, Any]) -> list[dict[str, Any]]:
    """Convert bounded per-ID logs plus AudioFlinger readings to report rows."""
    rows: list[dict[str, Any]] = []
    for transition in parse_soundpool_sink_transitions(logcat, pid):
        stream_id = transition["soundPoolStreamId"]
        rows.append({
            "id": f"soundpool:{stream_id}",
            "role": "menu.soundpool",
            "pid": pid,
            "stream": "STREAM_MUSIC",
            "activeBefore": True,
            "activeAtMute": True,
            "registeredWithController": True,
            "mixerLeftDbBefore": mixer_before[0],
            "mixerRightDbBefore": mixer_before[1],
            "mixerLeftDbAtMute": mixer_at_mute[0],
            "mixerRightDbAtMute": mixer_at_mute[1],
            "mixerLeftDbRestored": mixer_restored[0],
            "mixerRightDbRestored": mixer_restored[1],
            **transition,
        })
    return rows


def verify_pair(pair: Any, index: int = 0) -> list[str]:
    """Verify one isolated kernel-timed pair for immediate fail-fast use."""
    errors: list[str] = []
    label = f"quickPairs[{index}]"
    if not isinstance(pair, dict):
        return [f"{label} is not an object"]
    direction = pair.get("direction")
    if direction == "down":
        delta = -1
    elif direction == "up":
        delta = 1
    else:
        return [f"{label}.direction must be down or up"]
    hold_ms = pair.get("holdMs")
    if not _finite(hold_ms) or not 35 <= float(hold_ms) <= 60:
        errors.append(f"{label}.holdMs must prove a 35-60 ms quick tap")
    if pair.get("requestedHoldMs") != 40:
        errors.append(f"{label}.requestedHoldMs must be exactly 40")
    before = pair.get("before")
    after = pair.get("after")
    settled = pair.get("settledAfter")
    if not all(isinstance(value, int) for value in (before, after, settled)):
        errors.append(f"{label} needs integer before/after/settledAfter indices")
        return errors
    expected = before + delta
    if after != expected:
        errors.append(
            f"{label} pair moved {before}->{after}; expected exactly {expected}"
        )
    if settled != after:
        errors.append(
            f"{label} stream did not remain settled after UP: {after}->{settled}"
        )
    if pair.get("downEventCount") != 1 or pair.get("upEventCount") != 1:
        errors.append(f"{label} must contain exactly one kernel DOWN and one kernel UP")
    if pair.get("repeatCount", 0) != 0:
        errors.append(f"{label} contains a long-press repeat")
    changed = pair.get("levelChangedIndices")
    if changed != [expected]:
        errors.append(
            f"{label} must cause exactly one STREAM_MUSIC transition to {expected}"
        )
    applied = pair.get("controllerAppliedIndices")
    if not isinstance(applied, list) or not applied or applied[-1] != expected:
        errors.append(f"{label} controller gain never settled at index {expected}")
    elif any(value not in {before, expected} for value in applied):
        errors.append(f"{label} controller logged an unrelated gain index")
    return errors


def verify_quick_pairs(report: dict[str, Any], *,
                       expected_apk_sha256: str = "") -> list[str]:
    """Verify exact device-timed volume pairs without claiming sink coverage."""
    errors: list[str] = []
    if report.get("schemaVersion") != SCHEMA:
        errors.append(f"schemaVersion must be {SCHEMA}")
    if report.get("package") != PACKAGE:
        errors.append(f"package must be {PACKAGE}")

    sha = str(report.get("apkSha256", "")).lower()
    if len(sha) != 64 or any(ch not in "0123456789abcdef" for ch in sha):
        errors.append("apkSha256 is missing or malformed")
    if expected_apk_sha256 and sha != expected_apk_sha256.lower():
        errors.append("evidence APK hash does not match the candidate APK")
    pid = report.get("pid")
    if not isinstance(pid, int) or pid <= 0:
        errors.append("a positive EmuFusion PID is required")

    pairs = report.get("quickPairs")
    if not isinstance(pairs, list) or not pairs:
        errors.append("quickPairs must contain individually observed down/up pairs")
        pairs = []
    down_count = up_count = 0
    for index, pair in enumerate(pairs):
        errors.extend(verify_pair(pair, index))
        if not isinstance(pair, dict):
            continue
        direction = pair.get("direction")
        if direction == "down":
            down_count += 1
        elif direction == "up":
            up_count += 1
    if down_count < 2 or up_count < 2:
        errors.append("at least two quick taps in each direction are required")

    return errors


def verify(report: dict[str, Any], *, expected_apk_sha256: str = "") -> list[str]:
    errors = verify_quick_pairs(
        report, expected_apk_sha256=expected_apk_sha256
    )
    pid = report.get("pid")

    if report.get("sinkInventoryComplete") is not True:
        errors.append("sinkInventoryComplete must be true")
    sinks = report.get("sinks")
    if not isinstance(sinks, list):
        errors.append("sinks must be a PID-bound active-sink inventory")
        sinks = []
    roles = {str(row.get("role", "")) for row in sinks if isinstance(row, dict)}
    missing = sorted(REQUIRED_SINK_ROLES - roles)
    if missing:
        errors.append("missing sink roles: " + ", ".join(missing))
    identifiers: set[str] = set()
    controller_identifiers: set[str] = set()
    platform_stream_identifiers: set[str] = set()
    for index, sink in enumerate(sinks):
        label = f"sinks[{index}]"
        if not isinstance(sink, dict):
            errors.append(f"{label} is not an object")
            continue
        identifier = str(sink.get("id", ""))
        if not identifier or identifier in identifiers:
            errors.append(f"{label}.id must be non-empty and unique")
        identifiers.add(identifier)
        if sink.get("pid") != pid:
            errors.append(f"{label} is not bound to the EmuFusion PID")
        if sink.get("stream") != "STREAM_MUSIC":
            errors.append(f"{label} is not on STREAM_MUSIC")
        if sink.get("activeBefore") is not True or sink.get("activeAtMute") is not True:
            errors.append(f"{label} was not active across the mute transition")
        authority = sink.get("muteAuthority", "app-local")
        expected_authority = (
            "platform-stream" if sink.get("role") in PLATFORM_STREAM_ROLES
            else "app-local"
        )
        if authority != expected_authority:
            errors.append(
                f"{label} role {sink.get('role')!r} requires "
                f"muteAuthority={expected_authority!r}"
            )
        if authority == "app-local":
            controller_identifiers.add(identifier)
            if sink.get("registeredWithController") is not True:
                errors.append(f"{label} was not in AppVolumeController's sink inventory")
            if sink.get("localGainAtMute") != 0 and sink.get("localGainAtMute") != 0.0:
                errors.append(f"{label} local gain was not exactly zero at mute")
        elif authority == "platform-stream":
            platform_stream_identifiers.add(identifier)
            # Chromium/WebView exposes no public per-player gain handle. It can
            # qualify only through exact-PID AudioFlinger digital silence; a
            # visible STREAM_MUSIC index of zero is not evidence on the Thor.
            if sink.get("registeredWithController") is True:
                errors.append(f"{label} incorrectly claims an app-local WebView handle")
        else:
            errors.append(f"{label}.muteAuthority is unknown: {authority!r}")
        if not _negative_infinity(sink.get("mixerLeftDbAtMute")) or \
                not _negative_infinity(sink.get("mixerRightDbAtMute")):
            errors.append(f"{label} AudioFlinger output was not digitally silent")
        if not _finite(sink.get("mixerLeftDbBefore")) or \
                not _finite(sink.get("mixerRightDbBefore")):
            errors.append(f"{label} has no audible pre-mute mixer baseline")
        if not _finite(sink.get("mixerLeftDbRestored")) or \
                not _finite(sink.get("mixerRightDbRestored")):
            errors.append(f"{label} did not recover after unmute")
        if sink.get("role") == "menu.soundpool":
            if not isinstance(sink.get("soundPoolStreamId"), int) or \
                    sink.get("soundPoolStreamId") <= 0:
                errors.append(f"{label} has no concrete SoundPool stream ID")
            if sink.get("perIdGainLogAtMute") is not True:
                errors.append(f"{label} has no per-ID SoundPool gain=0 log")
            start_gain = sink.get("startGain")
            if not _finite(start_gain) or float(start_gain) <= 0:
                errors.append(f"{label} has no positive-gain SoundPool start")
            elapsed = sink.get("startToMuteMs")
            if not _finite(elapsed) or not 0 <= float(elapsed) <= SOUNDPOOL_ACTIVE_PROOF_MS:
                errors.append(f"{label} was not proved active when its gain reached zero")

    registered = report.get("registeredSinkIdsAtMute")
    registered_values = list(map(str, registered)) \
        if isinstance(registered, list) else []
    if not isinstance(registered, list) or \
            len(registered_values) != len(set(registered_values)) or \
            set(registered_values) != controller_identifiers:
        errors.append(
            "registeredSinkIdsAtMute does not exactly match the app-local "
            "controller sink inventory"
        )
    platform_stream = report.get("platformStreamSinkIdsAtMute")
    platform_stream_values = list(map(str, platform_stream)) \
        if isinstance(platform_stream, list) else []
    if not isinstance(platform_stream, list) or \
            len(platform_stream_values) != len(set(platform_stream_values)) or \
            set(platform_stream_values) != platform_stream_identifiers:
        errors.append(
            "platformStreamSinkIdsAtMute does not exactly match the "
            "platform-stream sink inventory"
        )
    if report.get("systemStreamIndexAtMute") != 0:
        errors.append("systemStreamIndexAtMute must be zero")
    if report.get("controllerGainAtMute") != 0 and \
            report.get("controllerGainAtMute") != 0.0:
        errors.append("controllerGainAtMute must be exactly zero")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--apk", type=Path)
    parser.add_argument("--quick-pairs-only", action="store_true",
                        help="verify the exact-40ms subgate without claiming "
                             "that all sink-family trials have been merged")
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    expected = ""
    if args.apk is not None:
        expected = hashlib.sha256(args.apk.read_bytes()).hexdigest()
    errors = (verify_quick_pairs if args.quick_pairs_only else verify)(
        report, expected_apk_sha256=expected
    )
    if errors:
        for error in errors:
            print("FAIL:", error)
        return 1
    if args.quick_pairs_only:
        print("PASS: every exact 40-ms quick pair moved STREAM_MUSIC exactly once")
    else:
        print("PASS: quick taps move exactly once and every active EmuFusion sink mutes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
