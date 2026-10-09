#!/usr/bin/env python3
"""Qualify EmuFusion's runnable Phase 2 engines on an authorized AYN Thor.

This harness deliberately requires user-supplied game images. It verifies that
EmuFusion's one MainActivity/Window owns both library and in-process gameplay,
injects an A-button through the Thor's real Odin Controller input node, observes
live video/audio health, commits Quick Resume, kills EmuFusion, and proves a live
restore in a new process.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import secrets
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops
from collections import Counter


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = "com.thorium.preview"
MAIN_ACTIVITY = f"{PACKAGE}/org.pegasus_frontend.android.MainActivity"
GAME_ACTIVITY = "org.pegasus_frontend.android.MainActivity"
ACTION_LAUNCH = "com.thorium.preview.LAUNCH_INTERNAL_GAME"
_phase1_qa = None


def phase1_qa_module():
    """Reuse the exact cross-phase Activity/window/recents policy oracle."""
    global _phase1_qa
    if _phase1_qa is not None:
        return _phase1_qa
    module_spec = importlib.util.spec_from_file_location(
        "phase1_activity_policy_oracle",
        ROOT / "unified-android/tools/run_phase1a_activity_qa.py",
    )
    module = importlib.util.module_from_spec(module_spec)
    assert module_spec.loader is not None
    sys.modules[module_spec.name] = module
    module_spec.loader.exec_module(module)
    _phase1_qa = module
    return module


@dataclass(frozen=True)
class Case:
    system: str
    engine: str
    title: str
    rom: str
    minimum_fps: float
    require_zero_initial_underruns: bool
    expected_audio_rate: int


def case_artifact_prefix(case: Case) -> str:
    title = re.sub(r"[^a-z0-9]+", "-", case.title.lower()).strip("-")
    return f"{case.system}-{case.engine}-{title or 'content'}"[:120]


def run(command: list[str], *, check: bool = True, binary: bool = False,
        timeout: float | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(command, cwd=ROOT, check=check, capture_output=True,
                          text=not binary, timeout=timeout)


def adb(adb_path: Path, serial: str, *args: str, check: bool = True,
        binary: bool = False, timeout: float | None = None) -> subprocess.CompletedProcess:
    return run([str(adb_path), "-s", serial, *args], check=check, binary=binary,
               timeout=timeout)


def wait_until(predicate, description: str, timeout: float = 60.0):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = predicate()
        except Exception as failure:  # retained in the timeout diagnostic
            last = failure
        if last is not None and last is not False:
            return last
        time.sleep(0.5)
    raise RuntimeError(f"timed out waiting for {description}; last={last!r}")


def logs(adb_path: Path, serial: str) -> str:
    return adb(adb_path, serial, "logcat", "-d", "-v", "brief").stdout


def activities(adb_path: Path, serial: str) -> str:
    return adb(adb_path, serial, "shell", "dumpsys", "activity", "activities").stdout


def windows(adb_path: Path, serial: str) -> str:
    return adb(adb_path, serial, "shell", "dumpsys", "window").stdout


def strict_gameplay_identity(adb_path: Path, serial: str) -> dict[str, object] | bool:
    return phase1_qa_module().strict_gameplay_identity(adb_path, serial)


def thor_preview_recreated(adb_path: Path, serial: str) -> bool:
    activity_components = re.findall(
        r"\* Hist\s+#\d+: ActivityRecord\{[^\n]*\su\d+\s+"
        r"(com\.thorium\.preview/[^\s}]+)",
        activities(adb_path, serial),
    )
    window_components = re.findall(
        r"Window #\d+ Window\{[^\n]*\su\d+\s+(com\.thorium\.preview/[^\s}]+)\}:",
        windows(adb_path, serial),
    )
    return ("com.thorium.preview/.PreviewActivity" in activity_components and
            "com.thorium.preview/com.thorium.preview.PreviewActivity" in
            window_components)


def game_resumed(adb_path: Path, serial: str) -> bool:
    value = activities(adb_path, serial)
    return bool(re.search(
        rf"topResumedActivity=.*{re.escape(PACKAGE)}/"
        rf"{re.escape(GAME_ACTIVITY)}",
        value,
    ))


def frontend_resumed(adb_path: Path, serial: str) -> bool:
    return bool(re.search(
        r"topResumedActivity=.*com\.thorium\.preview/"
        r"org\.pegasus_frontend\.android\.MainActivity",
        activities(adb_path, serial),
    ))


def main_activity_identity(adb_path: Path, serial: str) -> dict[str, str]:
    value = activities(adb_path, serial)
    matches = set(re.findall(
        r"ActivityRecord\{([0-9a-f]+)[^\n]*\s"
        r"com\.thorium\.preview/org\.pegasus_frontend\.android\.MainActivity"
        r"\}\s+t(\d+)", value,
    ))
    if len(matches) != 1:
        raise RuntimeError(
            f"expected one live Lucent MainActivity record, observed {sorted(matches)}"
        )
    token, task = next(iter(matches))
    return {"activityToken": token, "taskId": task,
            "component": GAME_ACTIVITY}


def start_library(adb_path: Path, serial: str) -> dict[str, str]:
    wake_and_unlock(adb_path, serial)
    shell_command(adb_path, serial, [
        "am", "start", "--display", "0", "-W", "-n", MAIN_ACTIVITY,
        "-a", "android.intent.action.MAIN",
        "--activity-single-top", "--activity-clear-top",
    ], check=False)
    wait_until(lambda: frontend_resumed(adb_path, serial),
               "Lucent library MainActivity", 30.0)
    return main_activity_identity(adb_path, serial)


def shell_command(adb_path: Path, serial: str, parts: list[str],
                  *, check: bool = True) -> subprocess.CompletedProcess:
    # Passing one quoted command string preserves game paths containing spaces
    # through adb's remote shell parser.
    command = " ".join(shlex.quote(part) for part in parts)
    return adb(adb_path, serial, "shell", command, check=check)


def wake_and_unlock(adb_path: Path, serial: str) -> None:
    # A physical qualification run may begin after the device cooled with its
    # displays off. Starting an activity behind keyguard produces OEM-specific
    # pause/resume timeouts and is not an engine failure.
    adb(adb_path, serial, "shell", "input", "keyevent", "KEYCODE_WAKEUP")
    adb(adb_path, serial, "shell", "wm", "dismiss-keyguard", check=False)
    time.sleep(0.5)


def launch(adb_path: Path, serial: str, case: Case,
           qualification_session: str) -> dict[str, object]:
    wake_and_unlock(adb_path, serial)
    completed = shell_command(adb_path, serial, [
        "am", "start", "--display", "0", "-W", "-n", MAIN_ACTIVITY,
        "-a", ACTION_LAUNCH,
        "--activity-single-top", "--activity-clear-top",
        "--es", "path", case.rom,
        "--es", "engine_id", case.engine,
        "--es", "system_id", case.system,
        "--es", "game_id", (
            f"phase2-thor-{case.system}-" +
            hashlib.sha256(case.rom.encode("utf-8")).hexdigest()[:12]
        ),
        "--es", "title", case.title,
        "--ez", "qualification_only", "true",
        "--es", "qualification_session", qualification_session,
    ], check=False)
    if completed.returncode != 0 or "Error:" in completed.stdout:
        raise RuntimeError("qualification launch failed: " + completed.stdout)
    wait_until(lambda: game_resumed(adb_path, serial), "Lucent MainActivity", 20.0)
    accepted = f"In-window route accepted engine={case.engine} system={case.system}"
    wait_until(lambda: accepted in logs(adb_path, serial),
               "in-window engine route", 20.0)
    return wait_until(
        lambda: strict_gameplay_identity(adb_path, serial),
        "one Lucent Activity/task/window/process after lower-preview closure",
        20.0,
    )


HEALTH = re.compile(
    r"Health engine=(\S+) fps=([0-9.]+) frames=(\d+) "
    r"audioUnderruns=(-?\d+) audioReceived=(\d+) audioWritten=(\d+) audioRate=(\d+)"
)


def health_rows(log: str, engine: str) -> list[dict[str, int | float]]:
    rows = []
    for match in HEALTH.finditer(log):
        if match.group(1) != engine:
            continue
        row = {
            "fps": float(match.group(2)),
            "frames": int(match.group(3)),
            "audioUnderruns": int(match.group(4)),
            "audioReceived": int(match.group(5)),
            "audioWritten": int(match.group(6)),
            "audioRate": int(match.group(7)),
        }
        # The engine telemetry reports cumulative FPS, which hides whether a
        # long JIT warm-up has recovered. Derive the most recent 300-frame
        # interval so the sustained-performance gate measures current speed.
        if rows and row["fps"] > 0 and rows[-1]["fps"] > 0:
            elapsed = row["frames"] / row["fps"]
            previous_elapsed = rows[-1]["frames"] / rows[-1]["fps"]
            elapsed_delta = elapsed - previous_elapsed
            if elapsed_delta > 0:
                row["intervalFps"] = round(
                    (row["frames"] - rows[-1]["frames"]) / elapsed_delta, 2
                )
        rows.append(row)
    return rows


def stable_health(adb_path: Path, serial: str, case: Case,
                  baseline_rows: int = 0) -> dict[str, int | float] | bool:
    if case.engine == "scummvm":
        return stable_scummvm_health(
            logs(adb_path, serial), case, baseline_rows
        )
    rows = health_rows(logs(adb_path, serial), case.engine)[baseline_rows:]
    if not rows:
        return False
    latest = rows[-1]
    # Cumulative FPS permanently includes cold JIT/shader compilation and can
    # remain below target long after current gameplay has recovered.  Once a
    # 300-frame interval exists, qualify the current interval instead.  This
    # still rejects a slow engine while avoiding a false failure caused solely
    # by bounded startup work (notably Azahar's first Vulkan shader cache).
    effective_fps = latest.get("intervalFps", latest["fps"])
    audio_rate_tolerance = max(1, case.expected_audio_rate // 100)
    if (effective_fps < case.minimum_fps or latest["audioReceived"] <= 0 or
            latest["audioWritten"] <= 0 or
            abs(latest["audioRate"] - case.expected_audio_rate) >
            audio_rate_tolerance):
        return False
    if case.require_zero_initial_underruns:
        return latest if latest["audioUnderruns"] == 0 else False
    # A JIT core can compile blocks during startup. Its queue is healthy when the
    # underrun counter stops increasing across consecutive 300-frame samples.
    if (len(rows) < 2 or rows[-2]["audioUnderruns"] != latest["audioUnderruns"] or
            latest.get("intervalFps", 0) < 55.0):
        return False
    return latest


SCUMMVM_HEALTH = re.compile(
    r"Runtime telemetry engine=(\S+) system=(\S+) frames=(\d+) "
    r"elapsedMs=(\d+) measuredFps=([0-9.]+) targetFps=([0-9.]+) "
    r"audioFrames=(\d+) audioStarted=(true|false)"
)


def scummvm_health_rows(log: str, engine: str = "scummvm") -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for match in SCUMMVM_HEALTH.finditer(log):
        if match.group(1) != engine:
            continue
        rows.append({
            "system": match.group(2),
            "frames": int(match.group(3)),
            "elapsedMs": int(match.group(4)),
            "measuredFps": float(match.group(5)),
            "targetFps": float(match.group(6)),
            "audioFrames": int(match.group(7)),
            "audioStarted": match.group(8) == "true",
        })
    return rows


def stable_scummvm_health(log: str, case: Case,
                          baseline_rows: int = 0) -> dict[str, object] | bool:
    rows = scummvm_health_rows(log, case.engine)[baseline_rows:]
    if not rows:
        return False
    latest = rows[-1]
    minimum = max(case.minimum_fps, float(latest["targetFps"]) * 0.90)
    return latest if (
        latest["system"] == case.system and
        float(latest["measuredFps"]) >= minimum and
        int(latest["audioFrames"]) > 0 and
        bool(latest["audioStarted"])
    ) else False


def image_metrics(path: Path) -> dict[str, int | float | bool]:
    image = Image.open(path).convert("RGB")
    width, height = image.size
    crop = image.crop((width // 8, height // 10, width * 7 // 8, height * 9 // 10))
    pixels = list(crop.getdata())
    visible = sum(max(pixel) >= 18 for pixel in pixels)
    sampled = pixels[::max(1, len(pixels) // 50_000)]
    colors = Counter(sampled)
    distinct = len(colors)
    dominant_fraction = (max(colors.values()) / len(sampled)) if sampled else 1.0
    # A core can report healthy frames/audio while presenting an untouched
    # frontend marker, a mostly-black target with one noisy padding band, or
    # uninitialized edge rows. Those are renderer failures, not gameplay.
    sentinel = (23, 179, 241)
    sentinel_pixels = sum(
        all(abs(pixel[channel] - sentinel[channel]) <= 3 for channel in range(3))
        for pixel in sampled
    )
    sentinel_fraction = sentinel_pixels / max(1, len(sampled))

    row_step = max(1, height // 180)
    column_step = max(1, width // 320)
    active_rows = 0
    sampled_rows = 0
    for y in range(0, height, row_step):
        row = [image.getpixel((x, y)) for x in range(0, width, column_step)]
        sampled_rows += 1
        if sum(max(pixel) >= 18 for pixel in row) >= max(1, len(row) // 20):
            active_rows += 1
    active_row_fraction = active_rows / max(1, sampled_rows)

    def region_energy(x0: int, y0: int, x1: int,
                      y1: int) -> tuple[float, float, float]:
        transitions: list[int] = []
        row_step = max(1, (y1 - y0) // 24)
        column_step = max(1, (x1 - x0) // 48)
        for y in range(y0, y1, row_step):
            previous = None
            for x in range(x0, x1, column_step):
                pixel = image.getpixel((x, y))
                if previous is not None:
                    transitions.append(max(abs(pixel[channel] - previous[channel])
                                           for channel in range(3)))
                previous = pixel
        for x in range(x0, x1, column_step):
            previous = None
            for y in range(y0, y1, row_step):
                pixel = image.getpixel((x, y))
                if previous is not None:
                    transitions.append(max(abs(pixel[channel] - previous[channel])
                                           for channel in range(3)))
                previous = pixel
        if not transitions:
            return 0.0, 0.0, 0.0
        return (sum(value > 96 for value in transitions) / len(transitions),
                sum(value > 12 for value in transitions) / len(transitions),
                sum(transitions) / len(transitions))

    # Sample narrow outer bands separately from their immediately adjacent
    # inner bands. The original eight-percent horizontal average allowed a
    # 24px strip of uninitialized pixels to be diluted by valid game content.
    horizontal_band = max(2, height * 2 // 100)
    vertical_band = max(2, width * 4 // 100)
    top_speckle, top_fine_speckle, top_energy = region_energy(
        0, 0, width, horizontal_band
    )
    bottom_speckle, bottom_fine_speckle, bottom_energy = region_energy(
        0, height - horizontal_band, width, height
    )
    upper_inner_speckle, upper_inner_fine_speckle, _ = region_energy(
        0, horizontal_band, width, min(height, horizontal_band * 3)
    )
    lower_inner_speckle, lower_inner_fine_speckle, _ = region_energy(
        0, max(0, height - horizontal_band * 3), width,
        height - horizontal_band
    )
    left_speckle, left_fine_speckle, left_energy = region_energy(
        0, 0, vertical_band, height
    )
    right_speckle, right_fine_speckle, right_energy = region_energy(
        width - vertical_band, 0, width, height
    )
    left_inner_speckle, left_inner_fine_speckle, _ = region_energy(
        vertical_band, 0, min(width, vertical_band * 3), height
    )
    right_inner_speckle, right_inner_fine_speckle, _ = region_energy(
        max(0, width - vertical_band * 3), 0,
        width - vertical_band, height
    )
    middle_speckle, middle_fine_speckle, _ = region_energy(
        width * 46 // 100, height * 46 // 100,
        width * 54 // 100, height * 54 // 100
    )

    top_corrupt = (top_speckle > 0.36 and
                   top_speckle > upper_inner_speckle + 0.20 and
                   top_energy > 72.0)
    bottom_corrupt = (bottom_speckle > 0.36 and
                      bottom_speckle > lower_inner_speckle + 0.20 and
                      bottom_energy > 72.0)
    left_corrupt = ((left_speckle > 0.40 and
                     left_speckle > left_inner_speckle + 0.22 and
                     left_speckle > middle_speckle + 0.20 and
                     left_energy > 76.0) or
                    (left_fine_speckle > 0.52 and
                     left_fine_speckle > middle_fine_speckle + 0.38 and
                     left_energy > 18.0))
    right_corrupt = ((right_speckle > 0.40 and
                      right_speckle > right_inner_speckle + 0.22 and
                      right_speckle > middle_speckle + 0.20 and
                      right_energy > 76.0) or
                     (right_fine_speckle > 0.52 and
                      right_fine_speckle > middle_fine_speckle + 0.38 and
                      right_energy > 18.0))
    corrupted_horizontal_edge = top_corrupt or bottom_corrupt
    corrupted_side_edge = left_corrupt or right_corrupt
    corrupted_edge = corrupted_horizontal_edge or corrupted_side_edge
    visual_integrity = (sentinel_fraction < 0.10 and
                        active_row_fraction >= 0.20 and
                        not corrupted_edge)
    return {
        "width": width,
        "height": height,
        "centralVisiblePixels": visible,
        "centralVisibleFraction": round(visible / max(1, len(pixels)), 6),
        "centralSampledColorCount": distinct,
        "centralDominantColorFraction": round(dominant_fraction, 6),
        "frontendSentinelFraction": round(sentinel_fraction, 6),
        "activeRowFraction": round(active_row_fraction, 6),
        "topEdgeSpeckleFraction": round(top_speckle, 6),
        "bottomEdgeSpeckleFraction": round(bottom_speckle, 6),
        "topEdgeFineSpeckleFraction": round(top_fine_speckle, 6),
        "bottomEdgeFineSpeckleFraction": round(bottom_fine_speckle, 6),
        "upperInnerSpeckleFraction": round(upper_inner_speckle, 6),
        "lowerInnerSpeckleFraction": round(lower_inner_speckle, 6),
        "upperInnerFineSpeckleFraction": round(upper_inner_fine_speckle, 6),
        "lowerInnerFineSpeckleFraction": round(lower_inner_fine_speckle, 6),
        "leftEdgeSpeckleFraction": round(left_speckle, 6),
        "rightEdgeSpeckleFraction": round(right_speckle, 6),
        "leftEdgeFineSpeckleFraction": round(left_fine_speckle, 6),
        "rightEdgeFineSpeckleFraction": round(right_fine_speckle, 6),
        "leftInnerSpeckleFraction": round(left_inner_speckle, 6),
        "rightInnerSpeckleFraction": round(right_inner_speckle, 6),
        "leftInnerFineSpeckleFraction": round(left_inner_fine_speckle, 6),
        "rightInnerFineSpeckleFraction": round(right_inner_fine_speckle, 6),
        "middleSpeckleFraction": round(middle_speckle, 6),
        "middleFineSpeckleFraction": round(middle_fine_speckle, 6),
        "horizontalEdgeCorruptionDetected": corrupted_horizontal_edge,
        "sideEdgeCorruptionDetected": corrupted_side_edge,
        "edgeCorruptionDetected": corrupted_edge,
        "visualIntegrity": visual_integrity,
        # Phase 2's real PSP/PS2 titles are content-heavy. A lower threshold
        # would let EmuFusion's small "Preparing …" label masquerade as a restored
        # game frame.
        "visible": (visible >= 50_000 and distinct >= 8 and
                    dominant_fraction < 0.98 and visual_integrity),
    }


def screenshot(adb_path: Path, serial: str,
               path: Path) -> dict[str, int | float | bool]:
    payload = adb(adb_path, serial, "exec-out", "screencap", "-p", binary=True).stdout
    path.write_bytes(payload)
    return image_metrics(path)


def controller_event_node(adb_path: Path, serial: str) -> str:
    listing = adb(adb_path, serial, "shell", "getevent", "-pl").stdout
    blocks = re.split(r"(?=add device \d+: )", listing)
    for block in blocks:
        if 'name:     "Odin Controller"' not in block:
            continue
        match = re.search(r"add device \d+: (/dev/input/event\d+)", block)
        if match:
            return match.group(1)
    raise RuntimeError("Thor Odin Controller input node was not found")


def press_physical_a(adb_path: Path, serial: str, event_node: str) -> None:
    # EV_KEY/BTN_GAMEPAD (0x130 = 304), then EV_SYN. This enters through the
    # same Linux input node as a human A-button press, unlike adb's virtual key.
    for value in ("1", "0"):
        adb(adb_path, serial, "shell", "sendevent", event_node, "1", "304", value)
        adb(adb_path, serial, "shell", "sendevent", event_node, "0", "0", "0")
        if value == "1":
            time.sleep(0.08)


def changed_pixels(before: Path, after: Path) -> int:
    first = Image.open(before).convert("RGB")
    second = Image.open(after).convert("RGB")
    if first.size != second.size:
        return first.size[0] * first.size[1]
    return sum(max(pixel) > 12 for pixel in ImageChops.difference(first, second).getdata())


def strict_frame_match(reference: Path, candidate: Path) -> dict[str, float | bool]:
    first = Image.open(reference).convert("RGB")
    second = Image.open(candidate).convert("RGB")
    if first.size != second.size:
        return {"matches": False, "meanAbsoluteDifference": 255.0,
                "changedPixelFraction": 1.0}
    difference = list(ImageChops.difference(first, second).getdata())
    count = max(1, len(difference))
    mean_absolute = sum(sum(pixel) / 3.0 for pixel in difference) / count
    changed_fraction = sum(max(pixel) > 12 for pixel in difference) / count
    return {
        "matches": mean_absolute <= 1.0 and changed_fraction <= 0.005,
        "meanAbsoluteDifference": round(mean_absolute, 6),
        "changedPixelFraction": round(changed_fraction, 6),
    }


def exit_to_lucent(adb_path: Path, serial: str, case: Case,
                   event_node: str) -> None:
    marker = f"Exit to Lucent invoked engine={case.engine} system={case.system}"
    # Exercise the Thor's user-facing Stop/Select contract itself: a short
    # press remains PSP Select, while a physical hold over one second saves and
    # returns to EmuFusion without relying on pause-menu state.
    phase1_qa_module().send_linux_key(
        adb_path, serial, event_node, 314, hold_seconds=1.15
    )
    wait_until(lambda: marker in logs(adb_path, serial), "Exit to Lucent marker", 15.0)
    returned = (f"Returned to Lucent immediately in same window engine={case.engine} "
                f"system={case.system}")
    wait_until(lambda: returned in logs(adb_path, serial),
               "same-window return marker", 60.0)
    latency_matches = re.findall(
        re.escape(returned) + r" latencyMs=(\d+)", logs(adb_path, serial)
    )
    if not latency_matches or int(latency_matches[-1]) >= 500:
        raise RuntimeError(
            "same-window UI return did not complete in under 500ms: " +
            repr(latency_matches[-1:] if latency_matches else [])
        )
    wait_until(lambda: frontend_resumed(adb_path, serial), "Lucent frontend", 60.0)
    # Library interactivity is deliberately decoupled from save latency. This
    # completion marker is emitted only after the engine-specific checkpoint
    # path succeeds and the retired native session is queued for teardown.
    commit = (f"Exit checkpoint finished after library return engine={case.engine} "
              f"system={case.system}")
    commit_description = (
        "ScummVM engine-native exit autosave commit"
        if case.engine == "scummvm"
        else "background exit checkpoint completion"
    )
    wait_until(lambda: commit in logs(adb_path, serial), commit_description, 60.0)
    wait_until(lambda: thor_preview_recreated(adb_path, serial),
               "Thor lower-screen preview recreation after return", 20.0)


def verify_case(adb_path: Path, serial: str, case: Case, output: Path,
                event_node: str, app_crash_markers,
                qualification_session: str) -> dict[str, object]:
    artifact_prefix = case_artifact_prefix(case)
    adb(adb_path, serial, "shell", "am", "force-stop", PACKAGE)
    library_identity = start_library(adb_path, serial)
    adb(adb_path, serial, "logcat", "-c")
    gameplay_identity = launch(adb_path, serial, case, qualification_session)
    activity_evidence = output / f"{artifact_prefix}-gameplay-activities.txt"
    window_evidence = output / f"{artifact_prefix}-gameplay-windows.txt"
    pid_evidence = output / f"{artifact_prefix}-gameplay-pids.txt"
    recents_evidence = output / f"{artifact_prefix}-gameplay-recents.txt"
    activity_evidence.write_text(activities(adb_path, serial), encoding="utf-8")
    window_evidence.write_text(windows(adb_path, serial), encoding="utf-8")
    pid_evidence.write_text(" ".join(gameplay_identity["packagePids"]) + "\n",
                            encoding="utf-8")
    recents_evidence.write_text(
        adb(adb_path, serial, "shell", "dumpsys", "activity", "recents").stdout,
        encoding="utf-8",
    )
    if ({key: gameplay_identity[key] for key in library_identity} != library_identity):
        raise RuntimeError(
            f"gameplay replaced Lucent's Activity/task: "
            f"{library_identity} -> {gameplay_identity}"
        )
    # A static GameCube prompt can legitimately stop duplicate XFB callbacks
    # before the health window fills. Exercise the mapped physical A first,
    # then measure health on the animated title/gameplay reached by that input.
    health = None if case.engine == "dolphin" else wait_until(
        lambda: stable_health(adb_path, serial, case),
        f"stable {case.engine} video/audio health", 100.0
    )
    presentation_geometry = None
    if case.engine == "dolphin":
        presentation_geometry = wait_until(
            lambda: next((line for line in logs(adb_path, serial).splitlines()
                          if re.search(
                              r"LucentGlesBackend(?:\(\s*\d+\))?: "
                              r"presentation geometry.*sourcePadding=0",
                              line,
                          )), False),
            "Dolphin complete-viewport presentation (no clipped/padded source)",
            20.0,
        )
        if "sourcePadding=1" in logs(adb_path, serial):
            raise RuntimeError("Dolphin presentation includes unwritten FBO padding")
    before = output / f"{artifact_prefix}-before-input.png"
    before_metrics = wait_until(
        lambda: (metrics := screenshot(adb_path, serial, before))["visible"] and metrics,
        "title-dependent visible gameplay frame (not black/FBO sentinel)", 60.0,
    )
    lower_blank_path = output / f"{artifact_prefix}-lower-blank.png"
    lower_blank = wait_until(
        lambda: (metrics := phase1_qa_module().secondary_blank_metrics(
            adb_path, serial, lower_blank_path))["blank"] and metrics,
        "black-only Thor lower display during single-screen gameplay",
        15.0,
    )
    press_physical_a(adb_path, serial, event_node)
    if case.engine == "scummvm":
        input_down = (f"Input consumed engine={case.engine} "
                      f"system={case.system} control=SOUTH")
        input_up = None
        wait_until(lambda: input_down in logs(adb_path, serial),
                   "mapped physical A-button event", 10.0)
    else:
        expected_button = 8 if case.system in ("gamecube", "wii") else 0
        input_down = (
            f"Physical input dispatched engine={case.engine} key=96 "
            f"control=SOUTH button={expected_button} pressed=true"
        )
        input_up = (
            f"Physical input dispatched engine={case.engine} key=96 "
            f"control=SOUTH button={expected_button} pressed=false"
        )
        wait_until(lambda: input_down in logs(adb_path, serial),
                   "mapped physical A-button down event", 10.0)
        wait_until(lambda: input_up in logs(adb_path, serial),
                   "mapped physical A-button up event", 10.0)
    after = output / f"{artifact_prefix}-after-input.png"
    if case.engine == "dolphin":
        # Dolphin's GameCube A is RetroPad A, not the generic RetroPad B at
        # the physical south position. Require the real button to leave the
        # title's initial prompt and settle on a complete frame. A transient
        # outline-only XFB submission must never count as an input response.
        semantic_response = None
        for attempt in range(5):
            if attempt:
                press_physical_a(adb_path, serial, event_node)
            time.sleep(1.0)
            candidate = screenshot(adb_path, serial, after)
            candidate_delta = changed_pixels(before, after)
            if candidate["visible"] and candidate_delta >= 50_000:
                semantic_response = (candidate, candidate_delta, attempt + 1)
                break
        if semantic_response is None:
            raise RuntimeError(
                "GameCube physical A did not leave the initial prompt on a complete frame"
            )
        after_metrics, delta, semantic_presses = semantic_response
        burst_metrics = []
        visible_burst_frames = 0
        for burst_attempt in range(3):
            burst_directory = output / (
                f"{artifact_prefix}-complete-frame-burst-{burst_attempt + 1}"
            )
            burst_directory.mkdir(exist_ok=True)
            candidate_burst = []
            for index in range(16):
                burst_path = burst_directory / f"frame-{index + 1:02d}.png"
                candidate_burst.append(screenshot(adb_path, serial, burst_path))
                time.sleep(0.11 if index % 3 else 0.17)
            candidate_visible = sum(bool(item["visible"]) for item in candidate_burst)
            if candidate_visible > visible_burst_frames:
                burst_metrics = candidate_burst
                visible_burst_frames = candidate_visible
            if candidate_visible == len(candidate_burst):
                break
            time.sleep(1.0)
        if visible_burst_frames != 16:
            raise RuntimeError(
                f"Dolphin submitted incomplete frames after navigation "
                f"({visible_burst_frames}/16 complete)"
            )
        health = wait_until(lambda: stable_health(adb_path, serial, case),
                            "stable dolphin video/audio health after navigation", 100.0)
    else:
        time.sleep(4.0)
        after_metrics = screenshot(adb_path, serial, after)
        delta = changed_pixels(before, after)
        semantic_presses = 1
        burst_metrics = []
        visible_burst_frames = 0
    if delta < 5_000:
        raise RuntimeError(f"physical A did not produce a visible response ({delta} pixels)")
    exit_to_lucent(adb_path, serial, case, event_node)
    returned_identity = main_activity_identity(adb_path, serial)
    if returned_identity != library_identity:
        raise RuntimeError(
            f"return replaced Lucent's Activity/task: "
            f"{library_identity} -> {returned_identity}"
        )

    adb(adb_path, serial, "shell", "am", "force-stop", PACKAGE)
    time.sleep(1.0)
    prelaunch_log = logs(adb_path, serial)
    if case.engine == "scummvm":
        health_baseline = len(scummvm_health_rows(prelaunch_log, case.engine))
        restored = None
        restore_baseline = 0
    else:
        health_baseline = len(health_rows(prelaunch_log, case.engine))
        restored = f"Restored Quick Resume engine={case.engine}"
        restore_baseline = prelaunch_log.count(restored)
    gameplay_identity_after_process_death = launch(
        adb_path, serial, case, qualification_session
    )
    if restored is not None:
        wait_until(lambda: logs(adb_path, serial).count(restored) > restore_baseline,
                   "new Quick Resume restore", 30.0)
    restored_health = wait_until(
        lambda: stable_health(adb_path, serial, case, health_baseline),
                                 f"live {case.engine} health after restore", 100.0)
    restored_path = output / f"{artifact_prefix}-restored.png"
    def restored_frame_proof():
        metrics = screenshot(adb_path, serial, restored_path)
        reference_match = strict_frame_match(after, restored_path)
        # Some valid saved moments are deliberately sparse transition/UI
        # frames and do not satisfy the title-level global visibility oracle.
        # Accept those only when the process-death frame reproduces the exact
        # pre-save reference within a very tight bound. Stable live health and
        # the matching state-identity restore marker are separate prerequisites
        # above; initial gameplay still must pass the full visibility gate.
        if metrics["visible"] or reference_match["matches"]:
            return {"metrics": metrics, "referenceMatch": reference_match}
        return False

    restored_proof = wait_until(
        restored_frame_proof,
        "visible or strict-reference-matched frame after process-death Quick Resume",
        60.0,
    )
    restored_metrics = restored_proof["metrics"]
    restore_reference_match = restored_proof["referenceMatch"]
    final_log = logs(adb_path, serial)
    crashes = app_crash_markers(final_log)
    if crashes:
        raise RuntimeError("Lucent crash markers: " + ", ".join(crashes))
    if "Audio FIFO overflow" in final_log:
        raise RuntimeError("core audio FIFO overflowed")
    return {
        "status": "PASS",
        "system": case.system,
        "engine": case.engine,
        "rom": case.rom,
        "inProcessActivity": GAME_ACTIVITY,
        "oneActivityWindowProcess": True,
        "libraryIdentity": library_identity,
        "gameplayIdentity": gameplay_identity,
        "gameplayIdentityAfterProcessDeath": gameplay_identity_after_process_death,
        "identityEvidence": {
            "activities": str(activity_evidence),
            "windows": str(window_evidence),
            "pids": str(pid_evidence),
            "recents": str(recents_evidence),
        },
        "returnedIdentity": returned_identity,
        "externalEmulatorObserved": False,
        "physicalInputNode": event_node,
        "physicalAChangedPixels": delta,
        "physicalASemanticPresses": semantic_presses,
        "physicalAInputDownDispatched": True,
        "physicalAInputUpDispatched": input_up is not None,
        "healthBeforeExit": health,
        "presentationGeometry": presentation_geometry,
        "healthAfterRestore": restored_health,
        "frameBeforeInput": before_metrics,
        "frameAfterInput": after_metrics,
        "completeFrameBurst": {
            "captured": len(burst_metrics),
            "complete": visible_burst_frames,
        } if burst_metrics else None,
        "frameAfterRestore": restored_metrics,
        "restoreReferenceMatch": restore_reference_match,
        "quickResumeCommitted": case.engine != "scummvm",
        "quickResumeRestoredAfterProcessDeath": case.engine != "scummvm",
        "qualificationStateNamespace": qualification_session,
        "engineNativeExitAutosaveCommitted": case.engine == "scummvm",
        "engineNativeResumePresentedAfterProcessDeath": case.engine == "scummvm",
        "thorLowerDisplayBlankDuringGameplay": lower_blank,
        "thorPreviewRecreatedAfterReturn": True,
        "audioFifoOverflow": False,
        "crashMarkers": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial", required=True)
    parser.add_argument("--adb", type=Path,
                        default=Path.home() / ".codex/tools/android-platform-tools/adb")
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--psp-rom", action="append", default=[])
    parser.add_argument("--apple2-rom", action="append", default=[])
    parser.add_argument("--amiga-rom", action="append", default=[])
    parser.add_argument("--amigacd32-rom", action="append", default=[])
    parser.add_argument("--saturn-rom", action="append", default=[])
    parser.add_argument("--gamecube-rom", action="append", default=[])
    parser.add_argument("--wii-rom", action="append", default=[])
    parser.add_argument("--ps2-rom",
                        help="legacy alias for --armsx2-ps2-rom")
    parser.add_argument("--play-ps2-rom", action="append", default=[])
    parser.add_argument("--armsx2-ps2-rom", action="append", default=[])
    parser.add_argument("--dreamcast-rom", action="append", default=[])
    parser.add_argument("--naomi-rom", action="append", default=[])
    parser.add_argument("--atomiswave-rom", action="append", default=[])
    parser.add_argument("--3ds-rom", action="append", default=[])
    parser.add_argument("--jaguar-rom", action="append", default=[])
    parser.add_argument("--scummvm-rom", action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--system", action="append",
                        choices=("apple2", "amiga", "amigacd32", "saturn", "gamecube", "wii", "psp",
                                 "ps2", "dreamcast", "naomi",
                                 "atomiswave", "3ds", "jaguar", "scummvm"),
                        help="run only this system (repeatable)")
    parser.add_argument("--allow-physical-thor", action="store_true")
    parser.add_argument(
        "--qualification-session",
        help=("reuse one strict qa-<32 hex> namespace to verify repeated "
              "save/restore generations without touching user states"),
    )
    parser.add_argument(
        "--require-three-titles", action="store_true",
        help="release gate: reject every selected system with fewer than three titles",
    )
    args = parser.parse_args()

    if (args.qualification_session is not None and not re.fullmatch(
            r"qa-[0-9a-f]{32}", args.qualification_session)):
        raise SystemExit("--qualification-session must match qa-[0-9a-f]{32}")

    if not args.allow_physical_thor:
        raise SystemExit("physical Phase 2 QA requires --allow-physical-thor")
    manufacturer = adb(args.adb, args.serial, "shell", "getprop",
                       "ro.product.manufacturer").stdout.strip().lower()
    model = adb(args.adb, args.serial, "shell", "getprop",
                "ro.product.model").stdout.strip().lower()
    if "ayn" not in manufacturer or "thor" not in model:
        raise SystemExit(f"target is not an AYN Thor: {manufacturer=} {model=}")
    requested = set(args.system or ())
    armsx2_ps2 = list(args.armsx2_ps2_rom)
    if args.ps2_rom:
        armsx2_ps2.append(args.ps2_rom)
    supplied = {
        "apple2": list(args.apple2_rom),
        "amiga": list(args.amiga_rom),
        "amigacd32": list(args.amigacd32_rom),
        "saturn": list(args.saturn_rom),
        "gamecube": list(args.gamecube_rom),
        "wii": list(args.wii_rom),
        "psp": list(args.psp_rom),
        "ps2": list(args.play_ps2_rom) + armsx2_ps2,
        "dreamcast": list(args.dreamcast_rom),
        "naomi": list(args.naomi_rom),
        "atomiswave": list(args.atomiswave_rom),
        "3ds": list(args.__dict__["3ds_rom"]),
        "jaguar": list(args.jaguar_rom),
        "scummvm": list(args.scummvm_rom),
    }
    if requested:
        missing = sorted(system for system in requested if not supplied[system])
        if missing:
            raise SystemExit("missing user-supplied image for: " + ", ".join(missing))
    elif not any(supplied.values()):
        raise SystemExit("supply at least one Phase 2 game image")
    if args.require_three_titles:
        scope = requested or {system for system, values in supplied.items() if values}
        undersupplied = sorted(
            f"{system} ({len(supplied[system])}/3)"
            for system in scope if len(supplied[system]) < 3
        )
        if undersupplied:
            raise SystemExit(
                "three-title release matrix is incomplete: " + ", ".join(undersupplied)
            )
    for rom in [value for values in supplied.values() for value in values]:
        exists = shell_command(
            args.adb, args.serial, ["test", "-f", rom], check=False
        ).returncode == 0
        if not exists:
            raise SystemExit(f"user-supplied game is missing: {rom}")

    module = phase1_qa_module()

    args.output.mkdir(parents=True, exist_ok=True)
    apk = args.apk.resolve()
    adb(args.adb, args.serial, "install", "--no-incremental", "-r", "-d", str(apk))
    adb(args.adb, args.serial, "shell", "pm", "grant", PACKAGE,
        "android.permission.POST_NOTIFICATIONS", check=False)
    adb(args.adb, args.serial, "shell", "appops", "set", "--uid", PACKAGE,
        "MANAGE_EXTERNAL_STORAGE", "allow", check=False)
    wake_and_unlock(args.adb, args.serial)
    event_node = controller_event_node(args.adb, args.serial)
    all_cases = []
    all_cases.extend(
        Case("apple2", "applewin", Path(rom).stem, rom, 55.0, True, 44_100)
        for rom in args.apple2_rom
    )
    all_cases.extend(
        Case("amiga", "puae", Path(rom).stem, rom, 49.0, True, 44_100)
        for rom in args.amiga_rom
    )
    all_cases.extend(
        Case("amigacd32", "puae", Path(rom).stem, rom, 49.0, True, 44_100)
        for rom in args.amigacd32_rom
    )
    all_cases.extend(
        Case("saturn", "beetle-saturn", Path(rom).stem, rom,
             55.0, True, 44_100)
        for rom in args.saturn_rom
    )
    all_cases.extend(
        Case("gamecube", "dolphin", Path(rom).stem, rom,
             55.0, False, 32_000)
        for rom in args.gamecube_rom
    )
    all_cases.extend(
        Case("wii", "dolphin", Path(rom).stem, rom,
             55.0, False, 32_000)
        for rom in args.wii_rom
    )
    all_cases.extend(
        Case("psp", "ppsspp", Path(rom).stem, rom, 55.0, True, 44_100)
        for rom in args.psp_rom
    )
    all_cases.extend(
        Case("ps2", "play", Path(rom).stem, rom, 55.0, False, 44_100)
        for rom in args.play_ps2_rom
    )
    all_cases.extend(
        Case("ps2", "armsx2", Path(rom).stem, rom, 55.0, False, 48_000)
        for rom in armsx2_ps2
    )
    all_cases.extend(
        Case("dreamcast", "flycast", Path(rom).stem, rom, 55.0, True, 44_100)
        for rom in args.dreamcast_rom
    )
    all_cases.extend(
        Case("naomi", "flycast", Path(rom).stem, rom, 55.0, True, 44_100)
        for rom in args.naomi_rom
    )
    all_cases.extend(
        Case("atomiswave", "flycast", Path(rom).stem, rom, 55.0, True, 44_100)
        for rom in args.atomiswave_rom
    )
    all_cases.extend(
        Case("3ds", "azahar", Path(rom).stem, rom, 55.0, False, 32_728)
        for rom in args.__dict__["3ds_rom"]
    )
    all_cases.extend(
        Case("jaguar", "virtualjaguar", Path(rom).stem, rom,
             55.0, True, 48_000)
        for rom in args.jaguar_rom
    )
    all_cases.extend(
        Case("scummvm", "scummvm", Path(rom).stem, rom,
             50.0, False, 0)
        for rom in args.scummvm_rom
    )
    cases = tuple(case for case in all_cases
                  if not requested or case.system in requested)
    records = []
    for case in cases:
        qualification_session = (args.qualification_session or
                                 "qa-" + secrets.token_hex(16))
        try:
            record = verify_case(args.adb, args.serial, case, args.output,
                                 event_node, module.app_crash_markers,
                                 qualification_session)
        except Exception as failure:
            artifact_prefix = case_artifact_prefix(case)
            (args.output / f"{artifact_prefix}-failure-activities.txt").write_text(
                activities(args.adb, args.serial), encoding="utf-8")
            (args.output / f"{artifact_prefix}-failure-windows.txt").write_text(
                windows(args.adb, args.serial), encoding="utf-8")
            (args.output / f"{artifact_prefix}-failure-logcat.txt").write_text(
                logs(args.adb, args.serial), encoding="utf-8")
            record = {"status": "FAIL", "system": case.system,
                      "engine": case.engine, "rom": case.rom,
                      "reason": str(failure),
                      "qualificationStateNamespace": qualification_session}
        records.append(record)
        print(f"{record['status']:4} {case.system} ({case.engine})", flush=True)

    report = {
        "schemaVersion": 1,
        "target": {"serial": args.serial, "manufacturer": manufacturer,
                   "model": model, "abi": "arm64-v8a"},
        "apk": str(apk),
        "apkSha256": hashlib.sha256(apk.read_bytes()).hexdigest(),
        "qualificationOnly": True,
        "userSuppliedContent": True,
        "threeTitleReleaseGate": args.require_three_titles,
        "systems": records,
        "counts": {
            "PASS": sum(row["status"] == "PASS" for row in records),
            "FAIL": sum(row["status"] == "FAIL" for row in records),
        },
    }
    (args.output / "results.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 1 if report["counts"]["FAIL"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
