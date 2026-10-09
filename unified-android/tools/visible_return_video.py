#!/usr/bin/env python3
"""Device-clocked visible-return video evidence.

ADB ``screencap`` is a request/encode/transfer operation, not a camera.  A
single full-resolution capture can take longer than EmuFusion's entire 500 ms
return budget and therefore cannot sample that budget densely.  Android's
``screenrecord`` instead receives composed frames continuously from a virtual
display.  Current AOSP stores the monotonic presentation time of every encoded
frame in a Winscope metadata sample in the MP4.  This module parses that sample
without trusting MP4 playback time or host/ADB timing.

The Stop injector brackets its DOWN edge with ``/proc/uptime`` on the device.
The pre-edge value is deliberately used as the threshold origin: because DOWN
can only occur *after* that read, the resulting visible latency is an upper
bound.  Command overhead can make a result slower, never make a slow return
pass.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence


WINSC0PE_V2_MAGIC = b"#VV1NSC0PET1ME2#"
MAX_EVIDENCE_FRAMES = 20_000


@dataclass(frozen=True)
class TimedFrame:
    index: int
    elapsed_ns: int
    path: Path


def parse_uptime_seconds(value: str) -> float:
    """Parse the first field of ``/proc/uptime`` and reject ambiguity."""
    fields = value.strip().split()
    if len(fields) < 2:
        raise ValueError("device uptime sample needs uptime and idle fields")
    try:
        result = float(fields[0])
    except ValueError as error:
        raise ValueError("device uptime sample is not numeric") from error
    if not math.isfinite(result) or result <= 0:
        raise ValueError("device uptime sample must be finite and positive")
    return result


def parse_winscope_frame_timestamps(mp4: bytes) -> list[int]:
    """Return v2 frame timestamps in Android elapsed-realtime nanoseconds.

    The metadata payload is an ``application/octet-stream`` MP4 sample.  AOSP
    gives it a fixed magic prefix, so locating the payload directly avoids an
    ffmpeg-version-dependent data-track demux.  Every size and chronology check
    fails closed before any value is used as timing evidence.
    """
    positions = []
    offset = 0
    while True:
        found = mp4.find(WINSC0PE_V2_MAGIC, offset)
        if found < 0:
            break
        positions.append(found)
        offset = found + 1
    if len(positions) != 1:
        raise ValueError(
            "screen recording needs exactly one Winscope v2 metadata sample; "
            f"found {len(positions)}"
        )
    cursor = positions[0] + len(WINSC0PE_V2_MAGIC)
    header_size = 4 + 8 + 4
    if cursor + header_size > len(mp4):
        raise ValueError("truncated Winscope v2 metadata header")
    version, _realtime_to_elapsed_ns, count = struct.unpack_from(
        "<IqI", mp4, cursor
    )
    if version != 2:
        raise ValueError(f"unsupported Winscope metadata version {version}")
    if count < 2 or count > MAX_EVIDENCE_FRAMES:
        raise ValueError(f"unsafe Winscope frame count {count}")
    cursor += header_size
    end = cursor + count * 8
    if end > len(mp4):
        raise ValueError("truncated Winscope v2 frame timestamp array")
    timestamps = list(struct.unpack_from(f"<{count}Q", mp4, cursor))
    if any(right <= left for left, right in zip(timestamps, timestamps[1:])):
        raise ValueError("Winscope frame timestamps are not strictly increasing")
    return timestamps


def frame_window(timestamps: Sequence[int], threshold_ns: int,
                 before_ms: int = 300, after_ms: int = 650) -> tuple[int, int]:
    """Return an inclusive encoded-frame range around the Stop threshold."""
    if threshold_ns <= 0 or not timestamps:
        raise ValueError("a positive threshold and frame timestamps are required")
    start_ns = threshold_ns - before_ms * 1_000_000
    end_ns = threshold_ns + after_ms * 1_000_000
    selected = [index for index, timestamp in enumerate(timestamps)
                if start_ns <= timestamp <= end_ns]
    if not selected:
        raise ValueError("screen recording has no frames around the Stop threshold")
    return selected[0], selected[-1]


def evaluate_visible_return(
        frames: Sequence[TimedFrame], threshold_lower_bound_ns: int,
        is_restored_menu: Callable[[Path], bool], max_latency_ms: int = 500,
        maximum_frame_gap_ms: int = 100) -> dict[str, object]:
    """Find the first visibly restored menu and enforce a conservative bound.

    ``threshold_lower_bound_ns`` is the device uptime sampled immediately
    before Stop DOWN plus the one-second hold threshold.  It is never adjusted
    toward the observed menu.  The selected frame's SurfaceFlinger-derived
    elapsed timestamp therefore yields an upper bound on visible latency.
    """
    if threshold_lower_bound_ns <= 0:
        raise ValueError("Stop threshold lower bound must be positive")
    ordered = sorted(frames, key=lambda frame: frame.elapsed_ns)
    if list(frames) != ordered:
        raise ValueError("decoded return frames are not chronological")
    if len({frame.index for frame in frames}) != len(frames):
        raise ValueError("decoded return frames contain duplicate indices")
    before = [frame for frame in frames
              if frame.elapsed_ns <= threshold_lower_bound_ns]
    if not before:
        raise ValueError("recording did not prove it was active before Stop threshold")
    relevant = [frame for frame in frames
                if threshold_lower_bound_ns <= frame.elapsed_ns <=
                threshold_lower_bound_ns + max_latency_ms * 1_000_000]
    if not relevant:
        raise ValueError("recording did not sample the visible return budget")
    # A variable-frame-rate recording can legitimately omit unchanged frames,
    # but a long hole spanning the transition makes the first-menu timestamp
    # unknowable.  Reject rather than interpolate across it.
    chronology = [before[-1], *relevant]
    largest_gap_ns = max(
        (right.elapsed_ns - left.elapsed_ns
         for left, right in zip(chronology, chronology[1:])), default=0
    )
    if largest_gap_ns > maximum_frame_gap_ms * 1_000_000:
        raise ValueError(
            "visible-return video cadence is too sparse: "
            f"largest gap {largest_gap_ns / 1_000_000:.3f} ms"
        )
    restored = next((frame for frame in relevant
                     if is_restored_menu(frame.path)), None)
    if restored is None:
        after_budget = [frame for frame in frames if frame.elapsed_ns >=
                        threshold_lower_bound_ns + max_latency_ms * 1_000_000]
        if not after_budget:
            raise ValueError(
                "recording ended before it could disprove a return within the budget"
            )
        raise ValueError(
            f"prior menu was not visibly restored within {max_latency_ms} ms"
        )
    # Ceiling preserves the upper-bound nature at sub-millisecond precision.
    latency_ms = math.ceil(
        (restored.elapsed_ns - threshold_lower_bound_ns) / 1_000_000
    )
    if latency_ms < 0 or latency_ms > max_latency_ms:
        raise ValueError(
            f"visible return exceeded {max_latency_ms} ms: {latency_ms} ms"
        )
    return {
        "method": "screenrecord-winscope-v2-device-clock-upper-bound",
        "thresholdLowerBoundElapsedNs": threshold_lower_bound_ns,
        "firstMenuFrameIndex": restored.index,
        "firstMenuElapsedNs": restored.elapsed_ns,
        "visibleReturnLatencyUpperBoundMs": latency_ms,
        "largestSampleGapMs": round(largest_gap_ns / 1_000_000, 3),
        "frameCount": len(frames),
    }
