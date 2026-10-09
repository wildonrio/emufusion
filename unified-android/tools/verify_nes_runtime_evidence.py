#!/usr/bin/env python3
"""Fail-closed offline checks for the deterministic NES qualification ROM.

The device runner records facts and raw artifacts; this verifier reopens the
pixels, telemetry and hashes rather than trusting its summary booleans.  It is
intentionally specific to ``emufusion-nes-v1`` so a commercial title or an old
static callback ROM cannot accidentally satisfy these semantic checks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageChops, ImageStat

sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify_frame_generation_evidence as frame_gen
import visible_return_video as return_video


SCHEMA_VERSION = 1
PROFILE = "emufusion-nes-v1"
EXPECTED_WIDTH = 1920
EXPECTED_HEIGHT = 1080
EXPECTED_ACTIVE_WIDTH = 1440
EXPECTED_LEFT = 240
CONTROL_NAMES = ("A", "B", "Select", "Start", "Up", "Down", "Left", "Right")
# Synthetic, deliberately separated field colours used only by offline test
# fixtures. Runtime mapping identity comes exclusively from marker Y below.
CONTROL_DISTINCT_TEST_RGB = {
    "A": (209, 116, 126), "B": (115, 210, 147),
    "Select": (209, 218, 115), "Start": (160, 165, 246),
    "Up": (236, 238, 236), "Down": (115, 149, 209),
    "Left": (115, 204, 189), "Right": (226, 178, 115),
}
CONTROL_MARKER_SOURCE_Y = {
    "A": 24, "B": 48, "Select": 72, "Start": 96,
    "Up": 120, "Down": 144, "Left": 168, "Right": 192,
}
SHA256 = re.compile(r"^[0-9a-f]{64}$")
TELEMETRY = re.compile(
    r"Runtime telemetry engine=mesen system=nes frames=(\d+) elapsedMs=(\d+) "
    r"measuredFps=([0-9.]+) targetFps=([0-9.]+) audioFrames=(\d+) "
    r"audioStarted=(true|false) audioHead=(\d+) audioProducedFrames=(\d+) "
    r"audioWrittenFrames=(\d+) audioDroppedFrames=(\d+) "
    r"audioFocusDroppedFrames=(\d+) audioQueuedFrames=(\d+) "
    r"audioPartialWrites=(\d+) audioZeroWrites=(\d+) audioWriteErrors=(\d+) "
    r"audioNativeDrainBoundHits=(\d+) audioUnderruns=(-?\d+)"
)
PCM_SIGNAL_LINE = re.compile(
    r"PCM signal telemetry engine=mesen system=nes .*marker=audio-pcm-signal"
)
STEADY_TIERS = (30, 40, 50, 60)
TRANSITIONS = ((60, 50), (50, 40), (40, 30),
               (30, 40), (40, 50), (50, 60))
CALIBRATION_CONTENT_FAILURES = frozenset({
    "motion field is effectively zero",
    "motion field has no confident vectors",
    "synthesized frames repeat a real endpoint too often",
    "sampled output content does not change often enough",
    "too few genuinely changing pixels were sampled",
    "synthetic pixels do not materially depart from both endpoints",
    "most synthetic output is indistinguishable from fixed-pixel crossfade",
    "too few synthesized samples contain measurable selected motion",
    "motion field and non-crossfade synthetic output are not correlated",
    "too few changing pixels have a confident selected motion vector",
    "motion-compensated pixels do not spatially follow their selected vectors",
})
EXPECTED_THOR_KEYLAYOUT_SHA256 = (
    "b00d7b3523a0d390b14082b4db1c925c449115baba94841029e62a3a3638eee8"
)
REAL_GAME_TITLES = (
    "10-Yard Fight", "1943: The Battle of Midway", "8 Eyes",
)
REAL_GAME_PROFILE = "emufusion-nes-real-title-v1"
REAL_GAME_CLOSURE_PROFILE = "emufusion-nes-real-game-closure-v1"
REAL_READINESS_MIN_NS = 19_000_000_000


@dataclass(frozen=True)
class TimedImage:
    index: int
    elapsed_ns: int
    path: Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_calibration_report(calculated: dict[str, object],
                                saved: dict[str, object], name: str) -> None:
    """Accept only full PASS or the fixture's enumerated content-only failure."""
    failures = calculated.get("failures")
    if (not isinstance(calculated.get("passed"), bool) or
            not isinstance(failures, list) or
            any(not isinstance(value, str) for value in failures)):
        raise ValueError(f"{name} frame generation is malformed")
    unexpected = sorted(set(failures) - CALIBRATION_CONTENT_FAILURES)
    if unexpected or (calculated["passed"] and failures) or \
            (not calculated["passed"] and not failures):
        raise ValueError(
            f"{name} has non-content calibration failures: "
            f"{unexpected or failures}"
        )
    expected_saved = dict(calculated)
    expected_saved.update({
        "calibrationOnly": True,
        "contentQualificationEligible": False,
        "contentQualityPassed": bool(calculated["passed"]),
    })
    if saved != expected_saved:
        raise ValueError(f"{name} saved report differs from recomputation")


def _image(path: Path) -> Image.Image:
    with Image.open(path) as opened:
        return opened.convert("RGB")


def _luma(pixel: tuple[int, int, int]) -> float:
    return 0.2126 * pixel[0] + 0.7152 * pixel[1] + 0.0722 * pixel[2]


def _mean_rgb(image: Image.Image) -> tuple[float, float, float]:
    mean = ImageStat.Stat(image).mean
    return tuple(round(float(value), 3) for value in mean[:3])


def _distance(left: Iterable[float], right: Iterable[float]) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right)))


def analyze_geometry(path: Path, *, allow_video_scale: bool = False) -> dict[str, object]:
    image = _image(path)
    if allow_video_scale and image.size == (960, 540):
        image = image.resize((EXPECTED_WIDTH, EXPECTED_HEIGHT), Image.Resampling.NEAREST)
    if image.size != (EXPECTED_WIDTH, EXPECTED_HEIGHT):
        raise ValueError(
            f"NES geometry requires 1920x1080 pixels, got {image.size[0]}x{image.size[1]}"
        )
    pixels = image.load()
    y0, y1 = 120, EXPECTED_HEIGHT - 120
    active_columns = []
    for x in range(EXPECTED_WIDTH):
        visible = sum(max(pixels[x, y]) >= 24 for y in range(y0, y1, 8))
        if visible >= ((y1 - y0) // 8) * 0.85:
            active_columns.append(x)
    active_rows = []
    for y in range(EXPECTED_HEIGHT):
        visible = sum(max(pixels[x, y]) >= 24 for x in range(0, EXPECTED_WIDTH, 8))
        if visible >= (EXPECTED_ACTIVE_WIDTH // 8) * 0.85:
            active_rows.append(y)
    if not active_columns or not active_rows:
        raise ValueError("NES source rectangle is not visibly measurable")
    left, right = min(active_columns), max(active_columns)
    top, bottom = min(active_rows), max(active_rows)
    width, height = right - left + 1, bottom - top + 1
    if abs(left - EXPECTED_LEFT) > 2 or abs(width - EXPECTED_ACTIVE_WIDTH) > 2:
        raise ValueError(
            f"NES is not centered full-height 4:3: left={left} width={width}"
        )
    if top > 1 or bottom < EXPECTED_HEIGHT - 2 or abs(height - EXPECTED_HEIGHT) > 2:
        raise ValueError(
            f"NES source does not touch both vertical edges: top={top} bottom={bottom}"
        )
    aspect = width / height
    if abs(aspect - 4 / 3) / (4 / 3) > 0.002:
        raise ValueError(f"NES active aspect is not 4:3: {aspect:.6f}")
    left_pillar = image.crop((0, 80, max(1, left - 2), EXPECTED_HEIGHT - 80))
    right_pillar = image.crop((right + 3, 80, EXPECTED_WIDTH, EXPECTED_HEIGHT - 80))
    pillar_luma = max(
        sum(_luma(pixel) for pixel in pillar.getdata()) / max(1, pillar.width * pillar.height)
        for pillar in (left_pillar, right_pillar)
    )
    if pillar_luma > 5.0:
        raise ValueError(f"NES side pillars are not black: meanLuma={pillar_luma:.3f}")
    # The qualification ROM's source-edge marker is deliberately broad enough
    # to survive non-integer aspect correction.  Sample inside all four edges.
    strips = (
        image.crop((left, 0, right + 1, 18)),
        image.crop((left, bottom - 17, right + 1, bottom + 1)),
        image.crop((left, 0, left + 24, bottom + 1)),
        image.crop((right - 23, 0, right + 1, bottom + 1)),
    )
    border_luma = [sum(_luma(pixel) for pixel in strip.getdata()) /
                   max(1, strip.width * strip.height) for strip in strips]
    if min(border_luma) < 90.0:
        raise ValueError(
            "NES edge-marker border is absent or clipped: " +
            ",".join(f"{value:.2f}" for value in border_luma)
        )
    return {
        "width": EXPECTED_WIDTH, "height": EXPECTED_HEIGHT,
        "activeLeft": left, "activeRight": right, "activeTop": top,
        "activeBottom": bottom, "activeWidth": width, "activeHeight": height,
        "activeAspect": round(aspect, 7), "pillarMeanLumaMax": round(pillar_luma, 4),
        "edgeMarkerMeanLuma": [round(value, 4) for value in border_luma],
        "fullHeight": True, "aspectPreserved": True,
    }


def evaluate_launch_video(frames: list[TimedImage], input_lower_bound_ns: int,
                          is_menu, is_guest, max_latency_ms: int = 500,
                          maximum_frame_gap_ms: int = 100) -> dict[str, object]:
    if input_lower_bound_ns <= 0 or not frames:
        raise ValueError("NES launch needs device-clocked input and video frames")
    if frames != sorted(frames, key=lambda frame: frame.elapsed_ns):
        raise ValueError("NES launch frames are not chronological")
    before = [frame for frame in frames if frame.elapsed_ns <= input_lower_bound_ns]
    if not before or not is_menu(before[-1].path):
        raise ValueError("NES launch recording lacks a pre-input library frame")
    relevant = [frame for frame in frames if input_lower_bound_ns <= frame.elapsed_ns <=
                input_lower_bound_ns + max_latency_ms * 1_000_000]
    if not relevant:
        raise ValueError("NES launch recording did not sample the 500 ms budget")
    chronology = [before[-1], *relevant]
    gap_ns = max((right.elapsed_ns - left.elapsed_ns
                  for left, right in zip(chronology, chronology[1:])), default=0)
    if gap_ns > maximum_frame_gap_ms * 1_000_000:
        raise ValueError("NES launch video cadence is too sparse")
    guest = next((frame for frame in relevant if is_guest(frame.path)), None)
    if guest is None:
        later = [frame for frame in frames if frame.elapsed_ns >=
                 input_lower_bound_ns + max_latency_ms * 1_000_000]
        if not later:
            raise ValueError("NES launch recording ended before disproving the budget")
        raise ValueError("NES guest pixels were not visible within 500 ms")
    latency_ms = math.ceil((guest.elapsed_ns - input_lower_bound_ns) / 1_000_000)
    return {
        "method": "screenrecord-winscope-v2-device-clock-upper-bound",
        "inputLowerBoundElapsedNs": input_lower_bound_ns,
        "firstGuestFrameIndex": guest.index,
        "firstGuestElapsedNs": guest.elapsed_ns,
        "visibleLatencyUpperBoundMs": latency_ms,
        "maxFrameGapMs": round(gap_ns / 1_000_000, 3),
        "preInputMenuFrame": True,
        "frameCount": len(frames),
    }


def control_colour(path: Path) -> tuple[float, float, float]:
    image = _image(path)
    if image.size != (EXPECTED_WIDTH, EXPECTED_HEIGHT):
        raise ValueError("NES control frame has the wrong physical dimensions")
    # Deep interior excludes white/red border, moving sprites and counter tile.
    return _mean_rgb(image.crop((420, 260, 1500, 880)))


def analyze_controls(neutral_path: Path,
                     control_paths: dict[str, Path]) -> dict[str, object]:
    if set(control_paths) != set(CONTROL_NAMES):
        raise ValueError("NES control proof requires all eight canonical controls")
    neutral = control_colour(neutral_path)
    colours = {name: control_colour(control_paths[name]) for name in CONTROL_NAMES}
    for name, colour in colours.items():
        if _distance(neutral, colour) < 18.0:
            raise ValueError(f"NES {name} did not materially change the fixture colour")
    for index, name in enumerate(CONTROL_NAMES):
        for other in CONTROL_NAMES[index + 1:]:
            if _distance(colours[name], colours[other]) < 12.0:
                raise ValueError(f"NES {name}/{other} responses are not distinguishable")
    # Field colours prove material, distinct control responses, but their
    # composed means change with the NES palette implementation and the
    # fixture's live scroll phase. The authored magenta marker Y below is the
    # semantic mapping oracle; arbitrary distinct colours cannot substitute
    # for the correct per-control marker position.
    marker_results = {}
    for name, colour in colours.items():
        # Sprite 1 is a reserved magenta plus at fixed source X=24 and a unique
        # Y for every control. Its dedicated palette cannot disappear into the
        # white Up field, so all eight mappings are position-bound.
        image = _image(control_paths[name])
        scores = {}
        for candidate, source_y in CONTROL_MARKER_SOURCE_Y.items():
            x0 = EXPECTED_LEFT + round(24 * 5.625)
            y0 = round((source_y + 1) * 4.5)
            crop = image.crop((x0, y0, x0 + 45, y0 + 36)).resize((8, 8))
            plus, corners = [], []
            for y in range(8):
                for x in range(8):
                    red, green, blue = crop.getpixel((x, y))
                    marker = (red >= 120 and blue >= 120 and
                              green + 60 <= min(red, blue))
                    if x in (3, 4) or y in (3, 4):
                        plus.append(1.0 if marker else 0.0)
                    else:
                        corners.append(1.0 if marker else 0.0)
            scores[candidate] = (sum(plus) / len(plus) -
                                 sum(corners) / len(corners))
        ordered = sorted((score, candidate) for candidate, score in scores.items())
        best_score, best_name = ordered[-1]
        if best_name != name or best_score < 0.20 or \
                best_score - ordered[-2][0] < 0.08:
            raise ValueError(
                f"NES physical {name} did not render its authored marker Y; "
                f"observed={best_name}"
            )
        marker_results[name] = {"matched": best_name,
                                "score": round(best_score, 4)}
    return {
        "neutralMeanRgb": neutral,
        "controls": {name: {"meanRgb": colours[name],
                             "distanceFromNeutral": round(_distance(neutral, colours[name]), 3)}
                     for name in CONTROL_NAMES},
        "markerOracles": marker_results,
        "allUnique": True,
    }


def analyze_motion(first_path: Path, second_path: Path, span_ms: int,
                   *, allow_video_scale: bool = False) -> dict[str, object]:
    if span_ms < 200:
        raise ValueError("NES continuous-motion samples span less than 200 ms")
    first, second = _image(first_path), _image(second_path)
    if allow_video_scale and first.size == second.size == (960, 540):
        first = first.resize((EXPECTED_WIDTH, EXPECTED_HEIGHT), Image.Resampling.NEAREST)
        second = second.resize((EXPECTED_WIDTH, EXPECTED_HEIGHT), Image.Resampling.NEAREST)
    if first.size != second.size or first.size != (EXPECTED_WIDTH, EXPECTED_HEIGHT):
        raise ValueError("NES motion frames have incompatible dimensions")
    crop = (EXPECTED_LEFT, 0, EXPECTED_LEFT + EXPECTED_ACTIVE_WIDTH, EXPECTED_HEIGHT)
    difference = ImageChops.difference(first.crop(crop), second.crop(crop))
    changed = sum(max(pixel) >= 12 for pixel in difference.getdata())
    total = EXPECTED_ACTIVE_WIDTH * EXPECTED_HEIGHT
    if changed < 100:
        raise ValueError(f"NES fixture did not visibly advance: changedPixels={changed}")
    # The authored nonperiodic field deliberately changes broadly when PPU
    # scroll advances. Distinguish it from a dissolve by showing that a small
    # horizontal translation explains the second interior materially better
    # than a zero-shift comparison. Localized sprite-only motion remains valid
    # for pre-Stop continuity and does not need the broad-field branch.
    first_field = first.crop((EXPECTED_LEFT + 80, 90,
                              EXPECTED_LEFT + EXPECTED_ACTIVE_WIDTH - 80, 990)) \
        .convert("L").resize((320, 180))
    second_field = second.crop((EXPECTED_LEFT + 80, 90,
                                EXPECTED_LEFT + EXPECTED_ACTIVE_WIDTH - 80, 990)) \
        .convert("L").resize((320, 180))
    direct_error = float(ImageStat.Stat(
        ImageChops.difference(first_field, second_field)).mean[0])
    candidates = []
    for shift in range(-10, 11):
        if shift == 0:
            continue
        if shift > 0:
            left = first_field.crop((0, 0, 320 - shift, 180))
            right = second_field.crop((shift, 0, 320, 180))
        else:
            left = first_field.crop((-shift, 0, 320, 180))
            right = second_field.crop((0, 0, 320 + shift, 180))
        candidates.append((float(ImageStat.Stat(
            ImageChops.difference(left, right)).mean[0]), shift))
    translated_error, translated_shift = min(candidates)
    if changed > total * 0.10 and (translated_error > direct_error * 0.80 or
                                  translated_error > 40.0):
        raise ValueError(
            "NES broad motion is not explained by authored horizontal scroll"
        )
    return {"spanMs": span_ms, "changedPixels": changed,
            "changedFraction": round(changed / total, 7),
            "directFieldError": round(direct_error, 4),
            "bestTranslatedFieldError": round(translated_error, 4),
            "bestTranslatedShift": translated_shift,
            "continuousMotion": True}


def semantic_state_signature(path: Path) -> str:
    image = _image(path)
    if image.size != (EXPECTED_WIDTH, EXPECTED_HEIGHT):
        raise ValueError("NES resume frame has the wrong physical dimensions")
    # Exclude the upper-left FPS badge/counter tile; retain the frozen motion
    # sprite and most of the authored field.  Raw screencap is lossless.
    crop = image.crop((EXPECTED_LEFT + 120, 180,
                       EXPECTED_LEFT + EXPECTED_ACTIVE_WIDTH - 120, 1010))
    return hashlib.sha256(crop.tobytes()).hexdigest()


def analyze_resume(before_path: Path, after_path: Path, log_text: str) -> dict[str, object]:
    before = semantic_state_signature(before_path)
    after = semantic_state_signature(after_path)
    if before != after:
        raise ValueError("NES Quick Resume did not restore the exact frozen visible state")
    commit = "Quick Resume committed engine=mesen system=nes"
    restore = "Quick Resume restored engine=mesen system=nes"
    commit_positions = [match.start() for match in re.finditer(re.escape(commit), log_text)]
    restore_positions = [match.start() for match in re.finditer(re.escape(restore), log_text)]
    semantic_commits = [] if len(restore_positions) < 2 else [
        position for position in commit_positions
        if restore_positions[-2] < position < restore_positions[-1]
    ]
    # A final library exit legitimately commits once more after the semantic
    # restore. Bind the exact save->restore interval between the last two
    # restore markers instead of incorrectly insisting the global log end at
    # restore.
    if len(commit_positions) < 2 or len(restore_positions) < 2 or \
            len(semantic_commits) != 1:
        raise ValueError(
            "NES semantic resume lacks a new post-save restore chronology"
        )
    return {"beforeSignature": before, "afterSignature": after,
            "exactFrozenStateRestored": True,
            "newPostSaveRestoreMarker": True}


def analyze_audio(log_text: str, *, require_tone: bool = True) -> dict[str, object]:
    matches = list(TELEMETRY.finditer(log_text))
    if not matches:
        raise ValueError("NES has no exact rolling audio telemetry")
    accepted = None
    for match in matches:
        values = match.groups()
        record = {
            "frames": int(values[0]), "elapsedMs": int(values[1]),
            "measuredFps": float(values[2]), "targetFps": float(values[3]),
            "audioFrames": int(values[4]), "audioStarted": values[5] == "true",
            "audioHead": int(values[6]), "audioProducedFrames": int(values[7]),
            "audioWrittenFrames": int(values[8]), "audioDroppedFrames": int(values[9]),
            "audioFocusDroppedFrames": int(values[10]), "audioQueuedFrames": int(values[11]),
            "audioPartialWrites": int(values[12]), "audioZeroWrites": int(values[13]),
            "audioWriteErrors": int(values[14]), "audioNativeDrainBoundHits": int(values[15]),
            "audioUnderruns": int(values[16]),
        }
        if (record["frames"] > 0 and record["measuredFps"] >= 59.0 and
                record["audioFrames"] > 0 and record["audioStarted"] and
                record["audioHead"] > 0 and record["audioProducedFrames"] > 0 and
                record["audioWrittenFrames"] > 0 and record["audioDroppedFrames"] == 0 and
                record["audioFocusDroppedFrames"] == 0 and
                record["audioWriteErrors"] == 0 and
                record["audioNativeDrainBoundHits"] == 0 and
                record["audioUnderruns"] == 0):
            accepted = record
    if accepted is None:
        raise ValueError("NES never produced one clean full-speed source/sink pipeline window")
    tone_lines = PCM_SIGNAL_LINE.findall(log_text)
    if not tone_lines or "marker=audio-pcm-signal-unavailable" in log_text:
        if require_tone:
            raise ValueError(
                "NES PCM delivery has no bound pre-AudioTrack spectrum telemetry"
            )
        accepted["toneObservable"] = False
        return accepted
    fields = dict(re.findall(r"\b([A-Za-z][A-Za-z0-9]+)=([^\s]+)", tone_lines[-1]))
    if (fields.get("audioSignalBoundary") != "pre-AudioTrack" or
            fields.get("audioSignalAudibilityProven") != "false"):
        raise ValueError("NES PCM signal record has an invalid measurement boundary")
    required = ("audioSignalSampleRateHz", "audioSignalWindowFrames",
                "audioSignalWindowSamples", "audioSignalWindowFrequencyResolutionHz",
                "audioSignalWindowOverflow", "audioSignalWindowLeftMin",
                "audioSignalWindowLeftMax", "audioSignalWindowLeftPeak",
                "audioSignalWindowLeftRms", "audioSignalWindowLeftToneHz",
                "audioSignalWindowLeftCrossings", "audioSignalWindowRightMin",
                "audioSignalWindowRightMax", "audioSignalWindowRightPeak",
                "audioSignalWindowRightRms", "audioSignalWindowRightToneHz",
                "audioSignalWindowRightCrossings")
    if any(key not in fields for key in required):
        raise ValueError("NES PCM signal record omits required rolling-window fields")
    sample_rate = int(fields["audioSignalSampleRateHz"])
    frames = int(fields["audioSignalWindowFrames"])
    samples = int(fields["audioSignalWindowSamples"])
    resolution = float(fields["audioSignalWindowFrequencyResolutionHz"])
    tone = {"sampleRate": sample_rate, "frames": frames, "samples": samples,
            "frequencyResolutionHz": resolution,
            "audibilityProven": False, "boundary": "pre-AudioTrack"}
    tolerance = max(3.0, resolution * 3.0)
    if (sample_rate < 32_000 or frames < 4096 or samples != frames * 2 or
            fields["audioSignalWindowOverflow"] != "false" or
            resolution <= 0 or abs(resolution - sample_rate / (frames - 1)) > 0.001):
        raise ValueError("NES PCM signal window counts/resolution/overflow are invalid")
    for channel in ("Left", "Right"):
        minimum = int(fields[f"audioSignalWindow{channel}Min"])
        maximum = int(fields[f"audioSignalWindow{channel}Max"])
        peak = int(fields[f"audioSignalWindow{channel}Peak"])
        rms = float(fields[f"audioSignalWindow{channel}Rms"])
        tone_hz = float(fields[f"audioSignalWindow{channel}ToneHz"])
        crossings = int(fields[f"audioSignalWindow{channel}Crossings"])
        if (minimum >= 0 or maximum <= 0 or peak <= 0 or peak > 32768 or
                rms <= 0 or rms > peak or crossings < 2 or tone_hz <= 0 or
                abs(tone_hz - 440.4) > tolerance):
            raise ValueError(
                f"NES PCM {channel.lower()} channel does not prove the authored tone"
            )
        tone[channel.lower()] = {
            "min": minimum, "max": maximum, "peak": peak, "rms": rms,
            "toneHz": tone_hz, "crossings": crossings,
        }
    if abs(tone["left"]["toneHz"] - tone["right"]["toneHz"]) > tolerance:
        raise ValueError("NES PCM spectrum does not prove the authored 440.4 Hz tone")
    accepted["toneObservable"] = True
    accepted["pcmSignal"] = tone
    return accepted


def analyze_cheat(before_path: Path, enabled_path: Path, disabled_path: Path,
                  log_text: str) -> dict[str, object]:
    before, enabled, disabled = (_image(before_path), _image(enabled_path),
                                 _image(disabled_path))
    if (before.size != enabled.size or before.size != disabled.size or
            before.size != (EXPECTED_WIDTH, EXPECTED_HEIGHT)):
        raise ValueError("NES cheat frames have incompatible dimensions")
    # Top border is stable white before the exact custom code, red while
    # enabled, and must return to the exact original state when disabled.
    box = (EXPECTED_LEFT + 80, 0, EXPECTED_LEFT + EXPECTED_ACTIVE_WIDTH - 80, 24)
    before_rgb = _mean_rgb(before.crop(box))
    enabled_rgb = _mean_rgb(enabled.crop(box))
    disabled_rgb = _mean_rgb(disabled.crop(box))
    distance = _distance(before_rgb, enabled_rgb)
    restored_distance = _distance(before_rgb, disabled_rgb)
    if distance < 50.0:
        raise ValueError("NES cheat callback returned without its material border effect")
    if restored_distance > 8.0:
        raise ValueError("NES cheat disable did not restore the original border state")
    if not re.search(
            r"Cheat apply returned engine=mesen system=nes .*id=qualification-red-border .*enabled=true .*"
            r"callbackReturned=true .*acknowledged=false .*effectProofRequired=true .*"
            r"marker=cheat-apply-returned", log_text):
        raise ValueError("NES cheat pixels lack the exact live enable marker")
    if not re.search(
            r"Cheat apply returned engine=mesen system=nes .*id=qualification-red-border .*enabled=false .*"
            r"callbackReturned=true .*acknowledged=false .*effectProofRequired=true .*"
            r"marker=cheat-apply-returned", log_text):
        raise ValueError("NES cheat pixels lack the exact live disable marker")
    if "marker=cheat-apply-failure" in log_text:
        raise ValueError("NES cheat evidence contains an apply failure")
    return {"beforeBorderMeanRgb": before_rgb,
            "enabledBorderMeanRgb": enabled_rgb,
            "disabledBorderMeanRgb": disabled_rgb,
            "borderColourDistance": round(distance, 3),
            "disableRestoreDistance": round(restored_distance, 3),
            "materialEffect": True, "disableRestored": True}


def analyze_cheat_panel(path: Path, log_text: str) -> dict[str, object]:
    panel = _image(path)
    if panel.width < 640 or panel.height < 360 or max(
            ImageStat.Stat(panel).mean[:3]) < 5.0:
        raise ValueError("NES Cheats panel capture is absent/blank")
    tesseract = Path("/opt/homebrew/bin/tesseract")
    if not tesseract.is_file():
        raise ValueError("tesseract is required to verify the NES Cheats panel")
    completed = subprocess.run(
        [str(tesseract), str(path), "stdout", "--psm", "6"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        timeout=30.0,
    )
    full_normalized = re.sub(r"[^a-z0-9]+", "", completed.stdout.lower())
    if (completed.returncode != 0 or "lucentcallbacktest" not in full_normalized or
            "cheats" not in full_normalized):
        raise ValueError("NES Cheats panel pixels lack the exact title/CHEATS heading")
    # Full-frame OCR on r26 correctly saw the heading and explanatory text but
    # omitted the selected white-on-purple row. Re-OCR only that logical
    # lower-display region; coordinates are scaled from the 1920x1080 layout.
    sx, sy = panel.width / 1920.0, panel.height / 1080.0
    logical_box = (70, 240, 1130, 330)
    scaled_box = (round(logical_box[0] * sx), round(logical_box[1] * sy),
                  round(logical_box[2] * sx), round(logical_box[3] * sy))
    row = panel.crop(scaled_box)
    with tempfile.NamedTemporaryFile(suffix=".png") as temporary:
        row.save(temporary.name)
        row_completed = subprocess.run(
            [str(tesseract), temporary.name, "stdout", "--psm", "6"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            timeout=30.0,
        )
    row_words = re.findall(r"[A-Z0-9]+", row_completed.stdout.upper())
    phrase = ["QUALIFICATION", "RED", "BORDER"]
    phrase_found = any(row_words[index:index + len(phrase)] == phrase
                       for index in range(len(row_words) - len(phrase) + 1))
    if (row_completed.returncode != 0 or not phrase_found or
            "OFF" not in row_words or "ON" in row_words):
        raise ValueError(
            "NES Cheats panel selected row is not exact Qualification red border OFF"
        )
    selected_colour_fraction = sum(
        max(red, green, blue) >= 80 and
        max(red, green, blue) - min(red, green, blue) >= 35
        for red, green, blue in row.getdata()
    ) / max(1, row.width * row.height)
    if selected_colour_fraction < 0.45:
        raise ValueError("NES Cheats panel qualification row is not visibly selected")
    marker = "Cheats panel shown engine=mesen system=nes count=1 lowerDisplay=true"
    if marker not in log_text:
        raise ValueError("NES Cheats panel pixels lack the exact one-row marker")
    return {"exactRowOcr": True, "rowCount": 1, "lowerDisplay": True,
            "fullPanelOcr": " ".join(completed.stdout.split()),
            "rowOcr": " ".join(row_completed.stdout.split()),
            "rowLogicalBox": list(logical_box),
            "selectedColourFraction": round(selected_colour_fraction, 6),
            "initialState": "OFF", "selected": True}


def evaluate_stop_video(frames: list[TimedImage], threshold_ns: int,
                        menu_reference: Path, max_latency_ms: int = 500,
                        maximum_frame_gap_ms: int = 100) -> dict[str, object]:
    if threshold_ns <= 0 or not frames:
        raise ValueError("NES Stop proof needs a device-clocked threshold and frames")
    ordered = sorted(frames, key=lambda frame: frame.elapsed_ns)
    if ordered != frames or len({frame.index for frame in frames}) != len(frames):
        raise ValueError("NES Stop frames are not unique and chronological")
    before = [frame for frame in frames if frame.elapsed_ns < threshold_ns]
    after = [frame for frame in frames if threshold_ns <= frame.elapsed_ns <=
             threshold_ns + max_latency_ms * 1_000_000]
    if len(before) < 2 or not after:
        raise ValueError("NES Stop proof does not bracket the held-key threshold")
    chronology = [before[-1], *after]
    gap_ns = max((right.elapsed_ns - left.elapsed_ns
                  for left, right in zip(chronology, chronology[1:])), default=0)
    if gap_ns > maximum_frame_gap_ms * 1_000_000:
        raise ValueError("NES Stop video cadence is too sparse")
    menu = _image(menu_reference)
    returned = next((frame for frame in after
                     if max(ImageStat.Stat(ImageChops.difference(
                         _image(frame.path), menu.resize(
                             _image(frame.path).size, Image.Resampling.BILINEAR
                         ))).mean[:3]) < 65.0), None)
    if returned is None:
        raise ValueError("NES library pixels were not visible within 500 ms of Stop")
    # Two raw pre-threshold samples at least 200 ms apart must show authored
    # motion, not merely a single stale gameplay screenshot before the menu.
    motion_pair = None
    for first in before:
        for second in reversed(before):
            span_ms = int((second.elapsed_ns - first.elapsed_ns) / 1_000_000)
            if span_ms >= 200:
                try:
                    motion = analyze_motion(
                        first.path, second.path, span_ms, allow_video_scale=True
                    )
                    motion_pair = (first, second, motion)
                    break
                except ValueError:
                    pass
        if motion_pair is not None:
            break
    if motion_pair is None:
        raise ValueError("NES Stop recording lacks continuous moving gameplay")
    return {
        "visibleReturnLatencyUpperBoundMs": math.ceil(
            (returned.elapsed_ns - threshold_ns) / 1_000_000
        ),
        "maxFrameGapMs": round(gap_ns / 1_000_000, 3),
        "continuousGameplayBeforeStop": True,
        "preStopMotion": motion_pair[2],
    }


_KERNEL_KEY_CODES = {
    # AOSP getevent names KEY_GAMEPAD (0x130) BTN_GAMEPAD on the Thor, while
    # some input.h/getevent versions print the synonymous BTN_SOUTH. Both are
    # the same exact Linux key code; no other face-button alias is accepted.
    "BTN_GAMEPAD": 304, "BTN_SOUTH": 304, "BTN_EAST": 305,
    "BTN_TL": 310, "BTN_SELECT": 314, "BTN_START": 315,
}


def _symbolic_kernel_event(line: str) -> tuple[int, int, int] | None:
    key = re.search(
        r"\bEV_KEY\s+(BTN_[A-Z0-9_]+)\s+(DOWN|UP|REPEAT)\s*$", line, re.I
    )
    if key:
        name = key.group(1).upper()
        if name not in _KERNEL_KEY_CODES:
            return None
        value = {"UP": 0, "DOWN": 1, "REPEAT": 2}[key.group(2).upper()]
        return 1, _KERNEL_KEY_CODES[name], value
    hat = re.search(
        r"\bEV_ABS\s+ABS_HAT0([XY])\s+([0-9a-f]{8}|-?\d+)\s*$",
        line, re.I,
    )
    if hat is None:
        return None
    raw_value = hat.group(2)
    if re.fullmatch(r"[0-9a-f]{8}", raw_value, re.I):
        value = int(raw_value, 16)
        if value & 0x80000000:
            value -= 1 << 32
    else:
        value = int(raw_value)
    return 3, 16 if hat.group(1).upper() == "X" else 17, value


def _kernel_events(text: str) -> list[tuple[int, int, int]]:
    events: list[tuple[int, int, int]] = []
    for line in text.splitlines():
        raw = re.search(r"\b000([13])\s+([0-9a-f]{4})\s+([0-9a-f]{8})\b",
                        line, re.I)
        if raw:
            kind, code, value = int(raw.group(1)), int(raw.group(2), 16), int(
                raw.group(3), 16)
            if value & 0x80000000:
                value -= 1 << 32
            events.append((kind, code, value))
            continue
        symbolic = _symbolic_kernel_event(line)
        if symbolic is not None:
            events.append(symbolic)
    return events


def _kernel_timed_events(text: str) -> list[tuple[int, int, int, int]]:
    result: list[tuple[int, int, int, int]] = []
    for line in text.splitlines():
        stamp = re.search(r"\[\s*(\d+(?:\.\d+)?)\]", line)
        if stamp is None:
            continue
        raw = re.search(r"\b000([13])\s+([0-9a-f]{4})\s+([0-9a-f]{8})\b",
                        line, re.I)
        if raw is not None:
            value = int(raw.group(3), 16)
            if value & 0x80000000:
                value -= 1 << 32
            event = int(raw.group(1)), int(raw.group(2), 16), value
        else:
            event = _symbolic_kernel_event(line)
        if event is not None:
            result.append((*event,
                           round(float(stamp.group(1)) * 1_000_000_000)))
    return result


def analyze_kernel_input_trace(text: str) -> dict[str, object]:
    key_names = {304: "A", 305: "B", 310: "L1", 314: "Select", 315: "Start"}
    edges: dict[int, list[int]] = {code: [] for code in key_names}
    hats: dict[int, list[int]] = {16: [], 17: []}
    for kind, code, value in _kernel_events(text):
        if kind == 1 and code in edges:
            edges[code].append(value)
        elif kind == 3 and code in hats:
            hats[code].append(value)
    # Exact qualification workflow: A launch, A control oracle, cheat enable,
    # cheat disable. The r28 symbolic trace therefore has four (not five)
    # code-304 pairs; pixels/logs independently bind each semantic effect.
    minimum_pairs = {304: 4, 305: 2, 310: 1, 314: 10, 315: 3}
    summary = {}
    for code, minimum in minimum_pairs.items():
        values = edges[code]
        if (2 in values or not values or values[-1] != 0 or
                values.count(1) != values.count(0) or values.count(1) < minimum or
                any(values[index:index + 2] != [1, 0]
                    for index in range(0, len(values), 2))):
            raise ValueError(
                f"NES kernel trace has repeats/missing/stuck {key_names[code]} edges"
            )
        summary[key_names[code]] = {"down": values.count(1),
                                    "up": values.count(0)}
    for axis, values in hats.items():
        if (not values or values[-1] != 0 or -1 not in values or 1 not in values or
                any(value not in (-1, 0, 1) for value in values)):
            raise ValueError(f"NES kernel trace lacks both directions/neutral on hat axis {axis}")
    return {"keys": summary, "hatXEvents": len(hats[16]),
            "hatYEvents": len(hats[17]), "noRepeatsOrStuckState": True}


def _real_health_records(text: str) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for line in text.splitlines():
        health = frame_gen.HEALTH.search(line)
        if health is None or health.group("role") != "primary" or \
                int(health.group("display_id")) != 0:
            continue
        pid = frame_gen.framegen_line_pid(line)
        if pid is None:
            raise ValueError("real-title HEALTH record lacks strict PID identity")
        record = {key: value if key in ("role", "proof_contract") else int(value)
                  for key, value in health.groupdict().items()}
        record["pid"] = pid
        records.append(record)
    records.sort(key=lambda item: int(item["window_end_ns"]))
    return records


def _expected_real_activation(title: str, state: str) -> list[tuple[int, int, int]]:
    if title == "10-Yard Fight":
        return [(1, 314, 1)] if state == "10-yard-2-player" else [(1, 315, 1)]
    if title == "1943: The Battle of Midway":
        return [(1, 315, 1)]
    if title == "8 Eyes":
        if state in {"8-eyes-2-player", "8-eyes-player-select"}:
            return [(3, 16, -1), (1, 315, 1)]
        if state == "8-eyes-level-select":
            return [(1, 304, 1), (1, 315, 1)]
        return [(1, 315, 1)]
    raise ValueError("unreviewed real-title activation identity")


def _real_menu_state_from_pixels(path: Path, title: str) -> str | None:
    tesseract = Path("/opt/homebrew/bin/tesseract")
    if not tesseract.is_file():
        raise ValueError("tesseract is required for real-title readiness")
    completed = subprocess.run(
        [str(tesseract), str(path), "stdout", "--psm", "6"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        timeout=30.0,
    )
    if completed.returncode != 0:
        raise ValueError("real-title readiness OCR failed")
    text = " ".join(completed.stdout.upper().split())
    if title == "10-Yard Fight":
        one = re.search(r"\b1\s+PLAYER\b", text) is not None
        two = re.search(r"\b2\s+PLAYERS?\b", text) is not None
        if one and two:
            image = _image(path)
            if image.size != (1920, 1080):
                raise ValueError("10-Yard readiness needs exact panel pixels")
            counts = {}
            for player, top, bottom in ((1, 620, 710), (2, 710, 800)):
                counts[player] = sum(
                    red >= 120 and red >= green * 1.4 and red >= blue * 1.4
                    for red, green, blue in image.crop((620, top, 800, bottom)).getdata()
                )
            selected = max(counts, key=counts.get)
            other = 1 if selected == 2 else 2
            if counts[selected] < 50 or counts[selected] - counts[other] < 25:
                raise ValueError("10-Yard readiness cursor is absent/ambiguous")
            return f"10-yard-{selected}-player"
        if two:
            return "10-yard-2-player"
        if one:
            return "10-yard-1-player"
        if re.search(r"\b(?:SKILL|BEGINNER|INTERMEDIATE|EXPERT)\b", text):
            return "10-yard-skill"
        if "10-YARD" in text and "FIGHT" in text:
            return "10-yard-title"
    elif title == "1943: The Battle of Midway":
        if ("PASSWORD" in text or "PRESS START" in text or
                ("1943" in text and "START" in text)):
            return "1943-start-menu"
    elif title == "8 Eyes":
        one = re.search(r"\b1\s+PLAYER\b", text) is not None
        two = re.search(r"\b2\s+PLAYERS?\b", text) is not None
        if one and two:
            return "8-eyes-player-select"
        if two:
            return "8-eyes-2-player"
        if one:
            return "8-eyes-1-player"
        has_continue, has_initiate = "CONTINUE" in text, "INITIATE" in text
        if has_continue and has_initiate:
            return "8-eyes-initiate-continue"
        if has_continue:
            return "8-eyes-continue"
        if has_initiate:
            return "8-eyes-initiate"
        if any(label in text for label in
               ("LEVEL SELECT", "RUTH", "SPAIN", "EGYPT", "INDIA",
                "ITALY", "GERMANY")):
            return "8-eyes-level-select"
        if "8 EYES" in text or "PRESS START" in text:
            return "8-eyes-title"
    return None


def _real_panel_geometry(path: Path) -> dict[str, object]:
    image = _image(path)
    if image.size != (1920, 1080):
        raise ValueError("real NES readiness frame is not the exact panel")

    def luma(pixel: tuple[int, int, int]) -> float:
        return 0.2126 * pixel[0] + 0.7152 * pixel[1] + 0.0722 * pixel[2]

    pillar_values = []
    for box in ((0, 160, 240, 920), (1680, 160, 1920, 920)):
        values = [luma(pixel) for pixel in image.crop(box).getdata()]
        mean = sum(values) / len(values)
        fraction = sum(value > 12.0 for value in values) / len(values)
        if mean > 2.0 or fraction > 0.002:
            raise ValueError("real NES readiness has nonblack outer pillars")
        pillar_values.append((mean, fraction))

    def material(box: tuple[int, int, int, int]) -> float:
        pixels = image.crop(box).getdata()
        values = [luma(pixel) for pixel in pixels]
        return sum(value > 12.0 for value in values) / len(values)

    top = material((240, 0, 1680, 8))
    bottom = material((240, 1072, 1680, 1080))
    active = material((240, 0, 1680, 1080))
    if top < 0.01 or bottom < 0.01:
        raise ValueError("real NES readiness has a top/bottom bar or clipping")
    if active < 0.03:
        raise ValueError("real NES readiness has no material guest content")
    return {"topEdgeMaterialFraction": round(top, 8),
            "bottomEdgeMaterialFraction": round(bottom, 8),
            "activeMaterialFraction": round(active, 8),
            "fullHeight": True, "aspectPreserved": True}


def _real_frame_change_fraction(left: Path, right: Path) -> float:
    before = _image(left).crop((240, 0, 1680, 1080)).resize(
        (320, 240), Image.Resampling.BILINEAR
    )
    after = _image(right).crop((240, 0, 1680, 1080)).resize(
        (320, 240), Image.Resampling.BILINEAR
    )
    pixels = list(ImageChops.difference(before, after).getdata())
    return sum(max(pixel) >= 12 for pixel in pixels) / len(pixels)


def _verify_real_readiness_pixels(paths: list[Path], title: str,
                                  saved: object) -> dict[str, object]:
    if len(paths) != 8:
        raise ValueError("real NES sustained readiness needs exactly eight frames")
    geometry = [_real_panel_geometry(path) for path in paths]
    fractions = [_real_frame_change_fraction(left, right)
                 for left, right in zip(paths, paths[1:])]
    changed = sum(value >= 0.005 for value in fractions)
    if changed < 5:
        raise ValueError(
            f"real NES readiness is static: changedPairs={changed}/7"
        )
    calculated = {"title": title, "frameCount": 8,
                  "changedPairs": changed, "requiredChangedPairs": 5,
                  "changeFractions": [round(value, 8) for value in fractions],
                  "titleMenuAbsent": True, "sustainedMaterialMotion": True}
    if not isinstance(saved, dict) or any(saved.get(key) != value
                                          for key, value in calculated.items()):
        raise ValueError("real NES saved readiness summary differs from pixels")
    saved_frames = saved.get("frames")
    if (not isinstance(saved_frames, list) or len(saved_frames) != 8 or
            [Path(str(item.get("path", ""))).name for item in saved_frames
             if isinstance(item, dict)] != [path.name for path in paths]):
        raise ValueError("real NES saved readiness frame order differs")
    calculated["geometry"] = geometry
    return calculated


def verify_real_readiness(roles: dict[str, Path], identity: dict[str, object],
                          title: str,
                          saved_recomputed: object = None) -> dict[str, object]:
    """Recompute timing, HEALTH identity and physical activation from raw files."""
    required = {"gameplay-readiness-report", "controller-input-trace", "logcat"}
    if not required.issubset(roles):
        raise ValueError("real-title readiness artifacts are incomplete")
    report = json.loads(roles["gameplay-readiness-report"].read_text(
        encoding="utf-8"))
    if (not isinstance(report, dict) or report.get("schemaVersion") != 2 or
            report.get("title") != title or report.get("saveStatePreserved") is not True):
        raise ValueError("real-title readiness report schema/identity mismatch")
    attempts = report.get("attempts")
    actions = report.get("actions")
    if not isinstance(attempts, list) or not attempts or not isinstance(actions, list):
        raise ValueError("real-title readiness attempts/actions are malformed")
    raw_health = _real_health_records(
        roles["logcat"].read_text(encoding="utf-8", errors="replace")
    )
    accepted: list[dict[str, object]] = []
    recognized: dict[int, tuple[str, int]] = {}
    for attempt in attempts:
        if not isinstance(attempt, dict):
            raise ValueError("real-title readiness attempt is malformed")
        sequence = attempt.get("sequence")
        samples = attempt.get("samples")
        states = attempt.get("states")
        if (not isinstance(sequence, int) or not isinstance(samples, list) or
                not samples or not isinstance(states, list) or
                len(states) != len(samples)):
            raise ValueError("real-title readiness samples are malformed")
        timestamps = []
        for index, (sample, state) in enumerate(zip(samples, states)):
            if not isinstance(sample, dict) or sample.get("state") != state:
                raise ValueError("real-title saved sample state is inconsistent")
            stamp = sample.get("hostMonotonicNs")
            relative = Path(str(sample.get("path", ""))).name
            role = f"gameplay-readiness-attempt-{sequence:02d}-{index:02d}"
            if not isinstance(stamp, int) or stamp <= 0 or role not in roles or \
                    roles[role].name != relative:
                raise ValueError("real-title readiness frame/timestamp is not bound")
            if _real_menu_state_from_pixels(roles[role], title) != state:
                raise ValueError("real-title readiness menu state differs from pixels")
            timestamps.append(stamp)
        if timestamps != sorted(set(timestamps)):
            raise ValueError("real-title readiness timestamps are not strictly monotonic")
        elapsed = timestamps[-1] - timestamps[0]
        if attempt.get("elapsedNs") != elapsed:
            raise ValueError("real-title readiness elapsed time is forged")
        visible = [(index, state) for index, state in enumerate(states)
                   if state is not None]
        if visible:
            if len(visible) != 1 or visible[0][0] != len(states) - 1:
                raise ValueError("real-title menu did not abort its probe immediately")
            recognized[sequence] = (str(visible[0][1]), timestamps[-1])
            continue
        if len(samples) == 8:
            accepted.append(attempt)
    if len(accepted) != 1:
        raise ValueError("real-title readiness lacks one unique sustained attempt")
    success = accepted[0]
    success_sequence = int(success["sequence"])
    if int(success["elapsedNs"]) <= REAL_READINESS_MIN_NS:
        raise ValueError("real-title readiness did not exceed 19 seconds")
    success_paths = [roles[f"gameplay-readiness-attempt-"
                           f"{int(success['sequence']):02d}-{index:02d}"]
                     for index in range(len(success["samples"]))]
    pixel_proof = _verify_real_readiness_pixels(
        success_paths, title, report.get("gameplay")
    )
    if saved_recomputed is not None:
        _verify_real_readiness_pixels(success_paths, title, saved_recomputed)
    baseline = success.get("healthBaseline")
    windows = success.get("healthWindows")
    if not isinstance(baseline, dict) or not isinstance(windows, list) or len(windows) < 3:
        raise ValueError("real-title readiness HEALTH evidence is incomplete")
    pid = int(baseline.get("pid", -1))
    generator = int(baseline.get("generator", -1))
    baseline_end = int(baseline.get("window_end_ns", -1))
    if pid != int(identity.get("pid", -2)):
        raise ValueError("real-title readiness baseline PID mismatches title identity")
    raw_baselines = [row for row in raw_health
                     if int(row["window_end_ns"]) == baseline_end and
                     int(row["pid"]) == pid and int(row["generator"]) == generator]
    if len(raw_baselines) != 1 or raw_baselines[0] != baseline:
        raise ValueError("real-title readiness baseline is stale/forged")
    final_end = int(windows[-1].get("window_end_ns", -1))
    raw_interval = [row for row in raw_health
                    if baseline_end < int(row["window_end_ns"]) <= final_end]
    if raw_interval != windows:
        raise ValueError("real-title readiness HEALTH interval differs from raw log")
    if any(int(row.get("pid", -1)) != pid or
           int(row.get("generator", -1)) != generator or
           int(row.get("window_promoted", 0)) <= 0 for row in windows):
        raise ValueError("real-title readiness HEALTH crossed identity or stopped")

    action_sources = dict(recognized)
    for attempt in attempts:
        sequence = int(attempt["sequence"])
        if sequence == success_sequence or sequence in action_sources:
            continue
        group = [item for item in actions
                 if isinstance(item, dict) and item.get("attemptSequence") == sequence]
        if group and {item.get("sourceState") for item in group} == {"static-gameplay"}:
            action_sources[sequence] = (
                "static-gameplay", int(attempt["samples"][-1]["hostMonotonicNs"])
            )
    expected_actions: list[tuple[tuple[int, int, int],
                                 list[tuple[int, int, int, int]]]] = []
    action_cursor = 0
    for sequence, (state, recognized_ns) in sorted(action_sources.items()):
        expected = _expected_real_activation(title, state)
        group = [(global_index, item) for global_index, item in enumerate(actions)
                 if isinstance(item, dict) and item.get("attemptSequence") == sequence]
        if len(group) != len(expected):
            raise ValueError("real-title menu lacks its exact activation action")
        for index, ((global_index, item), event) in enumerate(zip(group, expected)):
            kernel = item.get("kernelEvent")
            expected_label = f"real-nes-activate-{sequence:02d}"
            if (not str(item.get("label", "")).startswith(expected_label) or
                    item.get("sourceState") != state or
                    item.get("recognizedFrameHostMonotonicNs") != recognized_ns or
                    not isinstance(item.get("hostMonotonicNs"), int) or
                    int(item["hostMonotonicNs"]) < recognized_ns or
                    (index == 0 and int(item["hostMonotonicNs"]) - recognized_ns >
                     2_000_000_000) or
                    not isinstance(kernel, dict) or
                    (kernel.get("type"), kernel.get("code"), kernel.get("value")) != event):
                raise ValueError("real-title activation chronology/code is forged")
            trace_role = f"gameplay-readiness-action-{global_index:02d}"
            if (trace_role not in roles or
                    roles[trace_role].name != Path(str(item.get("actionTracePath", ""))).name):
                raise ValueError("real-title activation trace is not artifact-bound")
            action_timed = _kernel_timed_events(roles[trace_role].read_text(
                encoding="utf-8", errors="replace"))
            exact_pair = [event, (event[0], event[1], 0)]
            if [row[:3] for row in action_timed] != exact_pair:
                raise ValueError("real-title activation-specific raw trace is wrong")
            expected_actions.append((event, action_timed))
            action_cursor += 1
    if action_cursor != len(actions):
        raise ValueError("real-title readiness contains unbound activation actions")
    continuous_timed = _kernel_timed_events(roles["controller-input-trace"].read_text(
        encoding="utf-8", errors="replace"))
    cursor = 0
    for _event, action_timed in expected_actions:
        match = next((index for index in range(cursor, len(continuous_timed) - 1)
                      if continuous_timed[index:index + 2] == action_timed), None)
        if match is None:
            raise ValueError(
                "real-title activation-specific edges are absent from continuous raw trace"
            )
        cursor = match + 2
    return {"elapsedNs": int(success["elapsedNs"]), "pid": pid,
            "generator": generator, "healthWindowCount": len(windows),
            "activationCount": len(expected_actions),
            "pixelProof": pixel_proof, "passed": True}


def analyze_tier_input_schedule(path: Path, trace_text: str,
                                expected_node: str) -> dict[str, object]:
    schedule = json.loads(path.read_text(encoding="utf-8"))
    if set(schedule) != {
            "schemaVersion", "tiers", "directSelections", "proofResets", "source",
            "noClockOverride"}:
        raise ValueError("NES tier schedule has an unexpected schema")
    tiers = [60, 50, 40, 30, 40, 50, 60]
    if (schedule.get("schemaVersion") != 1 or schedule.get("tiers") != tiers or
            schedule.get("source") != "physical Odin Controller Select+direction" or
            schedule.get("noClockOverride") is not True):
        raise ValueError("NES tier schedule is not the exact physical campaign")
    expected = {
        60: (17, -1, "Select+Up"), 50: (16, 1, "Select+Right"),
        40: (17, 1, "Select+Down"), 30: (16, -1, "Select+Left"),
    }
    selections = schedule.get("directSelections")
    if not isinstance(selections, list) or len(selections) != 7:
        raise ValueError("NES tier schedule must contain seven direct selections")
    prior_end = 0
    requested: list[tuple[int, int]] = []
    for item, tier in zip(selections, tiers):
        if not isinstance(item, dict) or set(item) != {
                "tier", "combo", "hostStartNs", "hostEndNs",
                "deviceStartMonotonicNs", "deviceEndMonotonicNs",
                "physicalEventNode"}:
            raise ValueError("NES tier selection has an unexpected schema")
        axis, value, combo = expected[tier]
        start, end = item.get("hostStartNs"), item.get("hostEndNs")
        device_start = item.get("deviceStartMonotonicNs")
        device_end = item.get("deviceEndMonotonicNs")
        if (item.get("tier") != tier or item.get("combo") != combo or
                item.get("physicalEventNode") != expected_node or
                not isinstance(start, int) or not isinstance(end, int) or
                not isinstance(device_start, int) or
                not isinstance(device_end, int) or
                start <= prior_end or end <= start or
                device_start <= 0 or device_end <= device_start or
                device_end - device_start > 500_000_000):
            raise ValueError("NES tier selection identity/range is invalid")
        prior_end = end
        requested.append((axis, value))

    relevant = [event for event in _kernel_timed_events(trace_text)
                if (event[0] == 1 and event[1] == 314) or
                (event[0] == 3 and event[1] in (16, 17))]
    cursor = 0
    for selection_index, (axis, value) in enumerate(requested):
        sequence = [(3, axis, value), (1, 314, 1), (1, 314, 0), (3, axis, 0)]
        match = next((index for index in range(cursor, len(relevant) - 3)
                      if [event[:3] for event in relevant[index:index + 4]] == sequence),
                     None)
        if match is None:
            raise ValueError(
                "NES raw kernel trace lacks the ordered direct tier chord sequence"
            )
        # The per-injection raw trace and continuous trace see the same evdev
        # timestamps. Bind every declared selection to those exact monotonic
        # edge times rather than accepting an earlier balanced chord sequence.
        selection = selections[selection_index]
        observed_start = relevant[match][3]
        observed_end = relevant[match + 3][3]
        if (abs(observed_start - selection["deviceStartMonotonicNs"]) > 1_000_000 or
                abs(observed_end - selection["deviceEndMonotonicNs"]) > 1_000_000):
            raise ValueError(
                "NES tier schedule monotonic bounds do not bind raw chord edges"
            )
        cursor = match + 4
    resets = schedule.get("proofResets")
    if not isinstance(resets, list) or len(resets) != 7:
        raise ValueError("NES tier schedule must contain seven proof resets")
    previous_enabled = -1
    previous_baseline = -1
    for reset, tier in zip(resets, tiers):
        if not isinstance(reset, dict) or set(reset) != {
                "tier", "pid", "generator", "disabledLineIndex",
                "enabledLineIndex", "baselineWindowEndNs"}:
            raise ValueError("NES tier proof reset has an unexpected schema")
        disabled = reset.get("disabledLineIndex")
        enabled = reset.get("enabledLineIndex")
        baseline = reset.get("baselineWindowEndNs")
        if (reset.get("tier") != tier or
                not isinstance(reset.get("pid"), int) or reset["pid"] <= 0 or
                not isinstance(reset.get("generator"), int) or
                reset["generator"] <= 0 or
                not isinstance(disabled, int) or disabled <= previous_enabled or
                not isinstance(enabled, int) or enabled <= disabled or
                not isinstance(baseline, int) or baseline <= previous_baseline):
            raise ValueError("NES tier proof reset identity/order is invalid")
        previous_enabled = enabled
        previous_baseline = baseline
    return {"tiers": tiers, "directSelections": len(selections),
            "selections": selections,
            "proofResets": resets,
            "physicalEventNode": expected_node, "noClockOverride": True,
            "kernelChordSequenceProven": True}


def analyze_tier_proof_reset_log(schedule: dict[str, object], log_text: str,
                                 expected_pid: int) -> dict[str, object]:
    resets = schedule.get("proofResets")
    if not isinstance(resets, list) or len(resets) != 7:
        raise ValueError("NES tier proof reset campaign is absent")
    events = frame_gen.framegen_proof_state_events(log_text)
    records = []
    for line_index, line in enumerate(log_text.splitlines()):
        health = frame_gen.HEALTH.search(line)
        if health is None:
            continue
        pid = frame_gen.framegen_line_pid(line)
        if pid is None:
            raise ValueError("NES frame-generation HEALTH lacks strict PID identity")
        record = {key: value if key in ("role", "proof_contract") else int(value)
                  for key, value in health.groupdict().items()}
        record.update({"pid": pid, "line_index": line_index})
        records.append(record)
    generator_ids = {int(reset["generator"]) for reset in resets}
    if len(generator_ids) != 1 or any(int(reset["pid"]) != expected_pid
                                      for reset in resets):
        raise ValueError("NES tier proof resets mix PID/generator identity")
    generator = next(iter(generator_ids))
    first_disabled = int(resets[0]["disabledLineIndex"])
    last_enabled = int(resets[-1]["enabledLineIndex"])
    campaign_events = [event for event in events
                       if event["pid"] == expected_pid and
                       event["generator"] == generator and
                       first_disabled <= int(event["lineIndex"]) <= last_enabled]
    if len(campaign_events) != 14:
        raise ValueError("NES tier proof reset campaign has missing/extra markers")
    for index, reset in enumerate(resets):
        disabled, enabled = campaign_events[index * 2:index * 2 + 2]
        if (int(disabled["lineIndex"]) != reset["disabledLineIndex"] or
                disabled["enabled"] is not False or
                int(enabled["lineIndex"]) != reset["enabledLineIndex"] or
                enabled["enabled"] is not True):
            raise ValueError("NES tier proof reset markers are reordered or reused")
        following = [record for record in records
                     if record["pid"] == expected_pid and
                     record["generator"] == generator and
                     record["role"] == "primary" and
                     int(record["display_id"]) == 0 and
                     int(record["line_index"]) > int(enabled["lineIndex"])]
        if (not following or
                int(following[0]["window_end_ns"]) !=
                int(reset["baselineWindowEndNs"])):
            raise ValueError("NES tier proof reset does not bind first HEALTH baseline")
        if any(int(following[0][key]) != 0
               for key in frame_gen.RESET_COUNTER_FIELDS):
            raise ValueError("NES tier proof reset baseline counters are nonzero")
    return {"resets": 7, "pid": expected_pid, "generator": generator,
            "firstDisabledLineIndex": first_disabled,
            "lastEnabledLineIndex": last_enabled,
            "allBaselinesZero": True}


def _parse_single_key_pair(raw: str, key_code: int) -> dict[str, object]:
    edges: list[tuple[int, float]] = []
    for line in raw.splitlines():
        stamp = re.search(r"\[\s*(\d+(?:\.\d+)?)\]", line)
        event = re.search(
            rf"\b0001\s+{key_code:04x}\s+([0-9a-f]{{8}})\b", line, re.I
        )
        if stamp and event:
            edges.append((int(event.group(1), 16), float(stamp.group(1))))
    if (len(edges) != 2 or [value for value, _ in edges] != [1, 0] or
            edges[1][1] <= edges[0][1]):
        raise ValueError("NES device input trace is not one exact key pair")
    return {"downKernelSeconds": edges[0][1],
            "upKernelSeconds": edges[1][1],
            "holdMs": round((edges[1][1] - edges[0][1]) * 1000.0, 3)}


def analyze_device_clock_input(path: Path, *, action: str, key_code: int,
                               expected_node: str) -> dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if set(data) != {"schemaVersion", "eventNode", "action", "keyCode",
                    "uptimeBeforeSeconds", "uptimeAfterSeconds",
                    "rawKernelTrace"}:
        raise ValueError("NES device input artifact has an unexpected schema")
    before, after = data.get("uptimeBeforeSeconds"), data.get("uptimeAfterSeconds")
    if (data.get("schemaVersion") != 1 or data.get("eventNode") != expected_node or
            data.get("action") != action or data.get("keyCode") != key_code or
            not isinstance(before, (int, float)) or
            not isinstance(after, (int, float)) or before <= 0 or after <= before):
        raise ValueError("NES device input artifact identity/clock is invalid")
    pair = _parse_single_key_pair(str(data.get("rawKernelTrace", "")), key_code)
    # getevent timestamps are CLOCK_MONOTONIC on this userspace while
    # /proc/uptime/Winscope are BOOTTIME/elapsed-realtime. Their absolute
    # epochs diverge by cumulative suspend, so evdev proves edge order/duration
    # only; the same-shell uptime reads conservatively bracket the video clock.
    span = after - before
    if action == "launch-a":
        if not 40 <= pair["holdMs"] <= 100 or not 0.04 <= span <= 0.20:
            raise ValueError("NES launch input is not one bounded physical A tap")
        origin = int(before * 1_000_000_000)
    else:
        if not 1100 <= pair["holdMs"] <= 1300 or not 1.10 <= span <= 1.40:
            raise ValueError("NES Stop input is not one bounded physical hold")
        origin = int(before * 1_000_000_000) + 1_000_000_000
    return {"originElapsedNs": origin, "uptimeBeforeSeconds": before,
            "uptimeAfterSeconds": after, "kernelEdges": pair,
            "eventNode": expected_node, "action": action}


def verify_video_frame_binding(video_path: Path, frames: list[TimedImage],
                               origin_ns: int, *, launch: bool) -> list[int]:
    video = video_path.read_bytes()
    if len(video) < 64 or b"ftyp" not in video[:64]:
        raise ValueError("NES visible evidence is not an MP4 container")
    timestamps = return_video.parse_winscope_frame_timestamps(video)
    first, last = return_video.frame_window(
        timestamps, origin_ns, before_ms=300, after_ms=650,
    )
    expected_indexes = list(range(first, last + 1))
    if ([frame.index for frame in frames] != expected_indexes or
            [frame.elapsed_ns for frame in frames] !=
            [timestamps[index] for index in expected_indexes]):
        raise ValueError("NES decoded frame index/timestamps do not bind the MP4")
    ffmpeg = Path("/opt/homebrew/bin/ffmpeg")
    if not ffmpeg.is_file():
        raise ValueError("ffmpeg is required to independently decode NES evidence")
    with tempfile.TemporaryDirectory(prefix="emufusion-nes-video-") as directory:
        pattern = Path(directory) / "%06d.png"
        decoded = subprocess.run(
            [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-i",
             str(video_path), "-map", "0:v:0", "-vf",
             f"select=between(n\\,{first}\\,{last})", "-fps_mode", "passthrough",
             "-start_number", "0", str(pattern)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            timeout=60.0,
        )
        paths = sorted(Path(directory).glob("*.png"))
        if decoded.returncode != 0 or len(paths) != len(frames):
            raise ValueError("NES MP4 cannot independently reproduce its bound frames")
        for actual, declared in zip(paths, frames):
            left, right = _image(actual), _image(declared.path)
            if left.size != right.size or ImageChops.difference(left, right).getbbox():
                raise ValueError("NES bound PNG is not the exact decoded MP4 frame")
    return timestamps


def verify_manifest(path: Path) -> dict[str, object]:
    root = path.resolve().parent
    data = json.loads(path.read_text(encoding="utf-8"))
    errors: list[str] = []
    if data.get("schemaVersion") != SCHEMA_VERSION or data.get("profile") != PROFILE:
        errors.append("unsupported NES qualification schema/profile")
    identity = data.get("identity") or {}
    for key in ("apkSha256", "installedApkSha256", "romSha256", "coreArtifactSha256"):
        if not SHA256.fullmatch(str(identity.get(key, ""))):
            errors.append(f"identity.{key} is not a lowercase SHA-256")
    if identity.get("apkSha256") != identity.get("installedApkSha256"):
        errors.append("installed APK differs from the qualification candidate")
    if identity.get("engine") != "mesen" or identity.get("system") != "nes":
        errors.append("qualification identity is not exact Mesen/NES")
    if identity.get("gameTitle") != "Lucent Callback Test":
        errors.append("qualification identity is not the exact fixture title")
    if not isinstance(identity.get("pid"), int) or identity.get("pid", 0) <= 0:
        errors.append("qualification identity has no exact package PID")
    artifacts = data.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        errors.append("artifact inventory is empty")
        artifacts = []
    role_paths: dict[str, Path] = {}
    for artifact in artifacts:
        role = str(artifact.get("role", ""))
        relative = Path(str(artifact.get("path", "")))
        if (not role or role in role_paths or relative.is_absolute() or
                ".." in relative.parts):
            errors.append(f"invalid or duplicate artifact: {role!r}/{relative}")
            continue
        target = (root / relative).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            errors.append(f"artifact escapes evidence root: {relative}")
            continue
        if not target.is_file() or target.is_symlink():
            errors.append(f"artifact is absent or unsafe: {relative}")
            continue
        if target.stat().st_size != artifact.get("bytes"):
            errors.append(f"artifact byte count differs: {relative}")
        if sha256_file(target) != artifact.get("sha256"):
            errors.append(f"artifact digest differs: {relative}")
        role_paths[role] = target
    framegen_segments = [*(f"steady-{tier}" for tier in STEADY_TIERS),
                         *(f"transition-{left}-{right}"
                           for left, right in TRANSITIONS)]
    required_roles = {
        "candidate-apk", "qualification-rom", "core-artifact",
        "launch-video", "launch-input-trace", "launch-menu-reference",
        "geometry", "motion-before",
        "motion-after", "control-neutral", "resume-before", "resume-after",
        "cheat-before", "cheat-enabled", "cheat-disabled", "cheat-initial",
        "cheat-panel",
        "logcat",
        "stop-video", "stop-input-trace", "stop-menu-reference",
        "stop-menu-first", "stop-menu-interactive", "stop-menu-selection",
        "controller-description", "controller-keylayout", "controller-settings",
        "controller-input-trace", "framegen-tier-input-schedule",
        "framegen-log",
        *(f"control-{name.lower()}" for name in CONTROL_NAMES),
        *(f"framegen-{segment}-{kind}" for segment in framegen_segments
          for kind in ("qualification", "latency", "report")),
    }
    dynamic = re.compile(r"^(?:launch|stop)-frame-\d{6}$")
    allowed_roles = required_roles | {role for role in role_paths if dynamic.fullmatch(role)}
    extra = sorted(set(role_paths) - allowed_roles)
    if extra:
        errors.append("unexpected stale/unbound artifacts: " + ", ".join(extra))
    missing = sorted(required_roles - set(role_paths))
    if missing:
        errors.append("missing required artifacts: " + ", ".join(missing))

    def bound(role: str) -> Path:
        if role not in role_paths:
            raise ValueError(f"missing artifact role {role}")
        return role_paths[role]

    # Identity hashes are independently tied to raw APK/ROM/core artifacts.
    for key, role in (("apkSha256", "candidate-apk"),
                      ("romSha256", "qualification-rom"),
                      ("coreArtifactSha256", "core-artifact")):
        try:
            if sha256_file(bound(role)) != identity.get(key):
                errors.append(f"identity.{key} does not bind {role}")
        except (OSError, ValueError) as failure:
            errors.append(str(failure))
    try:
        with zipfile.ZipFile(bound("candidate-apk")) as archive:
            database = json.loads(
                archive.read("assets/cheats/cheat-database.json").decode("utf-8")
            )
            packaged_core = archive.read(
                "lib/arm64-v8a/liblucent_core_mesen.so"
            )
        if hashlib.sha256(packaged_core).hexdigest() != identity.get(
                "coreArtifactSha256") or packaged_core != bound(
                    "core-artifact").read_bytes():
            errors.append("candidate APK Mesen core differs from core-artifact")
        matches = []
        for game in database.get("games", []):
            if game.get("system") == "nes" and game.get("title") == "Lucent Callback Test":
                matches.extend(cheat for cheat in game.get("cheats", [])
                               if cheat.get("id") == "qualification-red-border")
        if len(matches) != 1 or matches[0].get("code") != "6000:3F" or \
                identity.get("romSha256") not in str(matches[0].get("description", "")):
            errors.append("candidate APK lacks the exact-ROM qualification cheat row")
    except (OSError, KeyError, ValueError, zipfile.BadZipFile,
            json.JSONDecodeError) as failure:
        errors.append(f"candidate APK cheat catalog is not auditable: {failure}")

    measurements = data.get("measurements")
    if not isinstance(measurements, dict):
        measurements = {}
        errors.append("NES qualification has no raw measurement bindings")

    def timed_frames(section: str) -> list[TimedImage]:
        value = measurements.get(section)
        if not isinstance(value, dict) or not isinstance(value.get("frames"), list):
            raise ValueError(f"NES {section} measurement has no frame index")
        result = []
        seen: set[str] = set()
        for item in value["frames"]:
            if not isinstance(item, dict):
                raise ValueError(f"NES {section} frame record is invalid")
            role = str(item.get("role", ""))
            if role in seen or not re.fullmatch(fr"{section}-frame-\d{{6}}", role):
                raise ValueError(f"NES {section} frame role is invalid or duplicated")
            seen.add(role)
            result.append(TimedImage(int(item["index"]), int(item["elapsedNs"]),
                                     bound(role)))
        inventory = {role for role in role_paths
                     if re.fullmatch(fr"{section}-frame-\d{{6}}", role)}
        if seen != inventory:
            raise ValueError(f"NES {section} frame index does not exactly close inventory")
        return result

    recomputed: dict[str, object] = {}
    log_text = ""
    controller = measurements.get("controller") or {}
    try:
        log_text = bound("logcat").read_text(encoding="utf-8", errors="replace")
        log_capture = measurements.get("logcatCapture") or {}
        expected_pid = identity.get("pid")
        if (log_capture.get("pid") != expected_pid or
                log_capture.get("arguments") !=
                ["logcat", "--pid", str(expected_pid), "-v", "threadtime"]):
            raise ValueError("NES normative log is not declared PID-bound")
        marker_lines = [line for line in log_text.splitlines()
                        if any(marker in line for marker in (
                            "engine=mesen system=nes", "audio-pcm-signal",
                            "Quick Resume restored"))]
        if not marker_lines or any(
                (match := re.match(r"^\S+\s+\S+\s+(\d+)\s+\d+\s", line)) is None or
                int(match.group(1)) != expected_pid for line in marker_lines):
            raise ValueError("NES normative log contains unbound/foreign-PID markers")
        recomputed["geometry"] = analyze_geometry(bound("geometry"))
        motion_spec = measurements.get("motion") or {}
        recomputed["motion"] = analyze_motion(
            bound("motion-before"), bound("motion-after"), int(motion_spec["spanMs"])
        )
        recomputed["controls"] = analyze_controls(
            bound("control-neutral"),
            {name: bound(f"control-{name.lower()}") for name in CONTROL_NAMES},
        )
        recomputed["resume"] = analyze_resume(
            bound("resume-before"), bound("resume-after"), log_text
        )
        recomputed["audio"] = analyze_audio(log_text, require_tone=True)
        recomputed["cheat"] = analyze_cheat(
            bound("cheat-before"), bound("cheat-enabled"),
            bound("cheat-disabled"), log_text,
        )
        initial = _image(bound("cheat-initial"))
        if initial.size != (EXPECTED_WIDTH, EXPECTED_HEIGHT):
            raise ValueError("NES initial cheat-state frame has incompatible dimensions")
        initial_rgb = _mean_rgb(initial.crop((
            EXPECTED_LEFT + 80, 0,
            EXPECTED_LEFT + EXPECTED_ACTIVE_WIDTH - 80, 24,
        )))
        initial_enabled = (initial_rgb[0] > initial_rgb[1] + 60 and
                           initial_rgb[0] > initial_rgb[2] + 60)
        cheat_spec = measurements.get("cheat") or {}
        if cheat_spec.get("initialEnabled") is not initial_enabled:
            raise ValueError("NES persisted cheat normalization summary is not raw-bound")
        recomputed["cheatPanel"] = analyze_cheat_panel(
            bound("cheat-panel"), log_text
        )
        recomputed["cheat"]["initialEnabled"] = initial_enabled
        launch_spec = measurements.get("launch") or {}
        launch_frames = timed_frames("launch")
        launch_input = analyze_device_clock_input(
            bound("launch-input-trace"), action="launch-a", key_code=304,
            expected_node=str(controller.get("eventNode", "")),
        )
        if int(launch_spec.get("inputLowerBoundElapsedNs", -1)) != int(
                launch_input["originElapsedNs"]):
            raise ValueError("NES launch summary clock is not raw-bound")
        verify_video_frame_binding(
            bound("launch-video"), launch_frames,
            int(launch_input["originElapsedNs"]), launch=True,
        )
        menu_reference = bound("launch-menu-reference")

        def is_menu(frame_path: Path) -> bool:
            frame = _image(frame_path)
            reference = _image(menu_reference).resize(
                frame.size, Image.Resampling.BILINEAR
            )
            difference = ImageChops.difference(frame, reference)
            return max(ImageStat.Stat(difference).mean[:3]) < 65.0

        def is_guest(frame_path: Path) -> bool:
            try:
                analyze_geometry(frame_path, allow_video_scale=True)
                return True
            except ValueError:
                return False

        recomputed["launch"] = evaluate_launch_video(
            launch_frames, int(launch_spec["inputLowerBoundElapsedNs"]),
            is_menu, is_guest,
        )
        stop_spec = measurements.get("stop") or {}
        stop_frames = timed_frames("stop")
        stop_input = analyze_device_clock_input(
            bound("stop-input-trace"), action="held-stop", key_code=314,
            expected_node=str(controller.get("eventNode", "")),
        )
        if int(stop_spec.get("thresholdElapsedNs", -1)) != int(
                stop_input["originElapsedNs"]):
            raise ValueError("NES Stop summary clock is not raw-bound")
        verify_video_frame_binding(
            bound("stop-video"), stop_frames,
            int(stop_input["originElapsedNs"]), launch=False,
        )
        recomputed["stop"] = evaluate_stop_video(
            stop_frames, int(stop_input["originElapsedNs"]),
            bound("stop-menu-reference"),
        )
        first_menu = _image(bound("stop-menu-first")).resize((320, 180))
        interactive = _image(bound("stop-menu-interactive")).resize((320, 180))
        input_changed = sum(max(pixel) >= 10 for pixel in ImageChops.difference(
            first_menu, interactive).getdata())
        if input_changed < 750 or input_changed != int(
                stop_spec.get("immediateInputChangedPixels", -1)):
            raise ValueError("NES returned library lacks bound immediate D-pad response")
        selection = str(stop_spec.get("selectionOcr", ""))
        if re.sub(r"[^a-z0-9]+", "", selection.lower()).find(
                "lucentcallbacktest") < 0:
            raise ValueError("NES returned library selection is not the fixture title")
        recomputed["stop"]["immediateInputChangedPixels"] = input_changed
        recomputed["stop"]["selectionOcr"] = selection
    except (KeyError, TypeError, ValueError, OSError) as failure:
        errors.append(f"raw NES semantic verification failed: {failure}")

    raw_keylayout_sha = (sha256_file(role_paths["controller-keylayout"])
                         if "controller-keylayout" in role_paths else None)
    if (controller.get("flip_button_layout") != "0" or
            controller.get("no_create_gamepad_button_layout") != "0" or
            controller.get("style") != "Odin Style" or
            not re.fullmatch(r"/dev/input/event\d+",
                             str(controller.get("eventNode", ""))) or
            controller.get("name") != "Odin Controller" or
            controller.get("vid") != 0x2020 or controller.get("pid") != 0x0111 or
            controller.get("keylayoutPath") !=
            "/system/usr/keylayout/Vendor_2020_Product_0111.kl" or
            controller.get("keylayoutSha256") != raw_keylayout_sha or
            raw_keylayout_sha != EXPECTED_THOR_KEYLAYOUT_SHA256):
        errors.append("NES controller identity/settings/keylayout binding is incomplete")
    try:
        description = bound("controller-description").read_text(
            encoding="utf-8", errors="replace")
        settings_raw = json.loads(bound("controller-settings").read_text(encoding="utf-8"))
        trace_text = bound("controller-input-trace").read_text(
            encoding="utf-8", errors="replace")
        trace = analyze_kernel_input_trace(trace_text)
        schedule = analyze_tier_input_schedule(
            bound("framegen-tier-input-schedule"), trace_text,
            str(controller.get("eventNode", "")),
        )
        if (controller.get("eventNode") not in description or
                'Name="Odin Controller"' not in description or
                not re.search(r"Vendor=2020 Product=0111", description, re.I) or
                settings_raw.get("flip_button_layout") != "0" or
                settings_raw.get("no_create_gamepad_button_layout") != "0" or
                settings_raw.get("style") != "Odin Style" or
                not trace.get("noRepeatsOrStuckState")):
            raise ValueError("controller raw artifacts do not bind the selected profile")
        recomputed["controllerInput"] = trace
        recomputed["tierInputSchedule"] = schedule
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as failure:
        errors.append(f"NES controller raw binding failed: {failure}")

    framegen_results = {}
    try:
        framegen_log = bound("framegen-log")
        framegen_log_text = framegen_log.read_text(
            encoding="utf-8", errors="replace"
        )
        if not log_text.startswith(framegen_log_text):
            raise ValueError(
                "framegen log is not an exact prefix of the PID-bound session log"
            )
        recomputed["tierProofResets"] = analyze_tier_proof_reset_log(
            recomputed["tierInputSchedule"], framegen_log_text,
            int(identity.get("pid", 0)),
        )
        for segment_name in framegen_segments:
            qualification = bound(f"framegen-{segment_name}-qualification")
            latency = bound(f"framegen-{segment_name}-latency")
            saved_report = json.loads(
                bound(f"framegen-{segment_name}-report").read_text(encoding="utf-8")
            )
            qualification_json = json.loads(qualification.read_text(encoding="utf-8"))
            segments = qualification_json.get("segments") or []
            if len(segments) != 1:
                raise ValueError(f"{segment_name} qualification must bind one segment")
            segment_id = segments[0].get("segmentId")
            expected_kind = "steady" if segment_name.startswith("steady-") else "transition"
            if segments[0].get("kind") != expected_kind:
                raise ValueError(f"{segment_name} has the wrong segment kind")
            if expected_kind == "steady":
                steady_tier = int(segment_name.split("-")[1])
                if segments[0].get("expectedLockedFps") != steady_tier:
                    raise ValueError(f"{segment_name} has the wrong steady tier")
                first_occurrence = {60: 0, 50: 1, 40: 2, 30: 3}[steady_tier]
                selection = recomputed["tierInputSchedule"]["selections"][
                    first_occurrence
                ]
                expected_reset = recomputed["tierInputSchedule"]["proofResets"][
                    first_occurrence
                ]
                if int(selection["deviceEndMonotonicNs"]) > int(
                        segments[0].get("startWindowEndNs", 0)):
                    raise ValueError(
                        f"{segment_name} begins before its physical direct selection"
                    )
            else:
                _label, left, right = segment_name.split("-")
                if (segments[0].get("expectedFromFps"),
                    segments[0].get("expectedToFps")) != (int(left), int(right)):
                    raise ValueError(f"{segment_name} has the wrong transition tiers")
                transition_index = TRANSITIONS.index((int(left), int(right)))
                selection = recomputed["tierInputSchedule"]["selections"][
                    transition_index + 1
                ]
                expected_reset = recomputed["tierInputSchedule"]["proofResets"][
                    transition_index + 1
                ]
                if not (int(segments[0].get("startWindowEndNs", 0)) <=
                        int(selection["deviceStartMonotonicNs"]) <
                        int(selection["deviceEndMonotonicNs"]) <=
                        int(segments[0].get("proofBaselineWindowEndNs", 0))):
                    raise ValueError(
                        f"{segment_name} is not chronologically bound to its physical chord"
                    )
            segment_reset = segments[0].get("proofReset")
            if segment_reset != {key: expected_reset[key] for key in (
                    "pid", "generator", "disabledLineIndex",
                    "enabledLineIndex", "baselineWindowEndNs")}:
                raise ValueError(
                    f"{segment_name} is bound to the wrong tier proof reset"
                )
            calculated = frame_gen.verify(
                framegen_log, latency, role="primary", display_id=0,
                qualification_path=qualification, segment_id=segment_id,
            )
            validate_calibration_report(calculated, saved_report, segment_name)
            q_identity = qualification_json.get("identity") or {}
            if (q_identity.get("systemId") != "nes" or
                    q_identity.get("coreId") != "mesen" or
                    q_identity.get("romSha256") != identity.get("romSha256") or
                    q_identity.get("coreSha256") != identity.get("coreArtifactSha256") or
                    q_identity.get("apkSha256") != identity.get("apkSha256") or
                    q_identity.get("pid") != identity.get("pid") or
                    q_identity.get("packageName") != "com.thorium.preview"):
                raise ValueError(f"{segment_name} frame-generation identity mismatch")
            framegen_results[segment_name] = calculated
        framegen_measurement = (data.get("measurements") or {}).get(
            "frameGeneration"
        )
        content_quality_passed = all(
            bool(result["passed"]) for result in framegen_results.values()
        )
        expected_measurement = {
            "calibrationOnly": True,
            "contentQualificationEligible": False,
            "contentQualityPassed": content_quality_passed,
            "segmentCount": len(framegen_segments),
        }
        if framegen_measurement != expected_measurement:
            raise ValueError(
                "fixture frame-generation calibration role/summary mismatch"
            )
    except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as failure:
        errors.append(f"frame-generation campaign verification failed: {failure}")

    return {"passed": not errors, "errors": errors, "identity": identity,
            "artifactCount": len(artifacts), "artifactRoles": sorted(role_paths),
            "recomputed": recomputed, "frameGeneration": framegen_results}


def verify_real_title_manifest(path: Path,
                               expected_title: str) -> dict[str, object]:
    """Recompute the unchanged full frame-generation gate for one real title."""
    errors: list[str] = []
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as failure:
        return {"passed": False, "errors": [f"invalid real-title manifest: {failure}"]}
    root = path.resolve().parent
    identity = document.get("identity") if isinstance(document, dict) else None
    if (not isinstance(document, dict) or document.get("schemaVersion") != 1 or
            document.get("profile") != REAL_GAME_PROFILE or
            not isinstance(identity, dict) or identity.get("title") != expected_title):
        errors.append("real-title manifest identity/profile mismatch")
        identity = identity if isinstance(identity, dict) else {}
    roles: dict[str, Path] = {}
    artifacts = document.get("artifacts") if isinstance(document, dict) else None
    if not isinstance(artifacts, list):
        artifacts = []
        errors.append("real-title manifest has no artifact inventory")
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            errors.append("real-title manifest has malformed artifact")
            continue
        role, relative = artifact.get("role"), artifact.get("path")
        if (not isinstance(role, str) or role in roles or
                not isinstance(relative, str) or Path(relative).name != relative):
            errors.append("real-title manifest has unsafe/duplicate artifact")
            continue
        target = (root / relative).resolve()
        if (target.parent != root or not target.is_file() or target.is_symlink() or
                target.stat().st_size != artifact.get("bytes") or
                sha256_file(target) != artifact.get("sha256")):
            errors.append(f"real-title artifact binding failed: {role}")
            continue
        roles[role] = target
    required = {"framegen-log", "framegen-latency",
                "framegen-qualification", "framegen-report",
                "gameplay-readiness-report", "controller-input-trace", "logcat"}
    if not required.issubset(roles):
        errors.append("real-title frame-generation artifacts are incomplete")
    readiness = None
    try:
        readiness = verify_real_readiness(
            roles, identity, expected_title,
            (document.get("recomputed") or {}).get("gameplayReadiness"),
        )
    except (KeyError, OSError, TypeError, ValueError,
            json.JSONDecodeError) as failure:
        errors.append(f"real-title readiness verification failed: {failure}")
    try:
        qualification = json.loads(
            roles["framegen-qualification"].read_text(encoding="utf-8")
        )
        segments = qualification.get("segments") or []
        if len(segments) != 1 or not isinstance(segments[0].get("segmentId"), str):
            raise ValueError("real-title qualification must bind one segment")
        calculated = frame_gen.verify(
            roles["framegen-log"], roles["framegen-latency"],
            role="primary", display_id=0,
            qualification_path=roles["framegen-qualification"],
            segment_id=segments[0]["segmentId"],
        )
        saved = json.loads(roles["framegen-report"].read_text(encoding="utf-8"))
        if not calculated.get("passed") or not saved.get("passed"):
            raise ValueError("real-title full frame-generation verifier did not pass")
        if any(saved.get(key) != value for key, value in calculated.items()):
            raise ValueError("real-title saved frame-generation report differs")
        q_identity = qualification.get("identity") or {}
        if (q_identity.get("systemId") != "nes" or
                q_identity.get("coreId") != "mesen" or
                q_identity.get("romSha256") != identity.get("romSha256") or
                q_identity.get("coreSha256") != identity.get("coreSha256") or
                q_identity.get("apkSha256") != identity.get("apkSha256") or
                q_identity.get("pid") != identity.get("pid")):
            raise ValueError("real-title frame-generation identity mismatch")
    except (KeyError, OSError, TypeError, ValueError,
            json.JSONDecodeError) as failure:
        errors.append(f"real-title frame-generation verification failed: {failure}")
        calculated = None
    return {"passed": not errors, "errors": errors, "title": expected_title,
            "readiness": readiness, "frameGeneration": calculated}


def verify_real_game_closure(path: Path) -> dict[str, object]:
    """Require exact, hash-bound full verifier passes for all three real games."""
    errors: list[str] = []
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as failure:
        return {"passed": False, "errors": [f"invalid real-game closure: {failure}"]}
    root = path.resolve().parent
    games = document.get("games") if isinstance(document, dict) else None
    if (not isinstance(document, dict) or document.get("schemaVersion") != 1 or
            document.get("profile") != REAL_GAME_CLOSURE_PROFILE or
            not isinstance(games, list)):
        return {"passed": False, "errors": ["real-game closure schema/profile mismatch"]}
    titles = [game.get("title") for game in games if isinstance(game, dict)]
    if len(games) != len(REAL_GAME_TITLES) or set(titles) != set(REAL_GAME_TITLES):
        errors.append("real-game closure is missing or duplicating required titles")
    results: dict[str, object] = {}
    for game in games:
        if not isinstance(game, dict) or game.get("title") not in REAL_GAME_TITLES:
            continue
        title = str(game["title"])
        relative = game.get("manifest")
        if not isinstance(relative, str) or Path(relative).name != relative:
            errors.append(f"real-game closure has unsafe manifest for {title}")
            continue
        child = (root / relative).resolve()
        if (child.parent != root or not child.is_file() or child.is_symlink() or
                sha256_file(child) != game.get("sha256")):
            errors.append(f"real-game closure manifest binding failed for {title}")
            continue
        result = verify_real_title_manifest(child, title)
        results[title] = result
        if not result["passed"]:
            errors.append(f"real-game qualification failed for {title}")
    if set(results) != set(REAL_GAME_TITLES):
        errors.append("real-game closure did not verify every required title")
    return {"passed": not errors, "errors": errors, "games": results}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    result = verify_manifest(args.manifest)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
