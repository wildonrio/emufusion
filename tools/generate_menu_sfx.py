#!/usr/bin/env python3
"""Generate EmuFusion's menu sound effects as small 16-bit PCM WAV assets.

The four blips are deliberately plain: a sine with a little second and third
harmonic for warmth, a raised-cosine attack so nothing clicks, and an
exponential decay that is forced to silence at the last sample so the file ends
on a true zero crossing. Every voice is short (< 120 ms) and quiet, because a
launcher makes these sounds hundreds of times in a session and anything bright
or long becomes fatiguing immediately.

Pitch, not volume, is what distinguishes them: moving is the highest and
shortest, confirming rises, going back falls, and the denial blip sits lowest
and is the only one that repeats. Run with no arguments to rewrite the assets
in android-companion/res/raw/ (build.sh copies that directory into the APK).
"""

from __future__ import annotations

import argparse
import math
import struct
import wave
from pathlib import Path

SAMPLE_RATE = 44_100
# Bounds the QA test asserts, and the reason for them: anything longer stops
# feeling like part of the key press, and anything louder competes with the
# preview video that is usually playing underneath.
MAX_DURATION_SECONDS = 0.120
MAX_PEAK = 0.30

# name -> (segments, peak amplitude)
# Each segment is (start_hz, end_hz, seconds, gap_seconds_after).
VOICES: dict[str, tuple[tuple[tuple[float, float, float, float], ...], float]] = {
    # Selection move: a single soft high tick, the most frequently heard sound
    # and therefore the quietest and shortest.
    "move": (((1_046.50, 1_046.50, 0.045, 0.0),), 0.14),
    # Confirm: a rising minor third, read as "forward".
    "confirm": (((659.25, 659.25, 0.040, 0.0),
                 (987.77, 987.77, 0.062, 0.0)), 0.20),
    # Back: the same interval falling, read as "undo".
    "back": (((622.25, 622.25, 0.038, 0.0),
              (440.00, 440.00, 0.058, 0.0)), 0.17),
    # Denied: two low blips. Repetition, not loudness, carries the "no".
    "error": (((311.13, 311.13, 0.034, 0.018),
               (311.13, 293.66, 0.050, 0.0)), 0.19),
}

ATTACK_SECONDS = 0.006
RELEASE_SECONDS = 0.010
# Mild harmonic content: a pure sine sounds thin on handheld speakers, and a
# real triangle is too bright at these frequencies.
HARMONICS = ((1.0, 1.0), (2.0, 0.16), (3.0, 0.06))


def envelope(index: int, total: int) -> float:
    """Raised-cosine attack, exponential decay, forced zero at the end."""
    if total <= 1:
        return 0.0
    position = index / (total - 1)
    attack_samples = max(1, int(ATTACK_SECONDS * SAMPLE_RATE))
    if index < attack_samples:
        gain = 0.5 - 0.5 * math.cos(math.pi * index / attack_samples)
    else:
        gain = 1.0
    gain *= math.exp(-3.6 * position)
    release_samples = max(1, int(RELEASE_SECONDS * SAMPLE_RATE))
    remaining = total - 1 - index
    if remaining < release_samples:
        gain *= remaining / release_samples
    return gain


def render(segments: tuple[tuple[float, float, float, float], ...],
           peak: float) -> list[float]:
    samples: list[float] = []
    phase = 0.0
    for start_hz, end_hz, seconds, gap_seconds in segments:
        count = int(seconds * SAMPLE_RATE)
        for index in range(count):
            progress = index / max(1, count - 1)
            frequency = start_hz + (end_hz - start_hz) * progress
            phase += 2.0 * math.pi * frequency / SAMPLE_RATE
            value = sum(level * math.sin(multiple * phase)
                        for multiple, level in HARMONICS)
            normalizer = sum(level for _, level in HARMONICS)
            samples.append(value / normalizer * envelope(index, count))
        samples.extend([0.0] * int(gap_seconds * SAMPLE_RATE))
    while samples and samples[-1] == 0.0 and len(samples) > 1:
        samples.pop()
    loudest = max((abs(value) for value in samples), default=0.0)
    if loudest > 0.0:
        samples = [value / loudest * peak for value in samples]
    return samples


def write_wav(path: Path, samples: list[float]) -> None:
    frames = b"".join(
        struct.pack("<h", max(-32_768, min(32_767, int(round(value * 32_767)))))
        for value in samples)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(SAMPLE_RATE)
        output.writeframes(frames)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=root / "android-companion" / "res" / "raw",
                        help="directory that build.sh copies into res/raw")
    arguments = parser.parse_args()
    arguments.output.mkdir(parents=True, exist_ok=True)
    for name, (segments, peak) in VOICES.items():
        samples = render(segments, peak)
        duration = len(samples) / SAMPLE_RATE
        if duration > MAX_DURATION_SECONDS:
            raise SystemExit(f"{name} is {duration:.3f}s, over the UI budget")
        if peak > MAX_PEAK:
            raise SystemExit(f"{name} peaks at {peak}, louder than the budget")
        path = arguments.output / f"lucent_sfx_{name}.wav"
        write_wav(path, samples)
        print(f"{path.name}  {duration * 1000:.0f} ms  peak {peak:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
