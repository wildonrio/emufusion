#!/usr/bin/env python3
"""Play a whole library on the Mac and measure whether each game's new columns are real.

A column beside the old picture is real if, when the game scrolls, the same pixels arrive in the
old picture. Nothing about the game needs to be known: two frames a few steps apart, the shift
between them found from their middles, and what the side of one held compared with what the
middle of the other shows. A stale or repeated column fails that test, and a game that never
scrolls gives no evidence at all. Sprites and animation cost a little, hence a bar below 100%.

Only a first look: a game that passes still has to be seen before it gets a recipe.

usage: library_triage.py SYSTEM ROM_DIR OUT.json [--jobs N] [--only SUBSTRING]
"""
import argparse
import concurrent.futures
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
BUILD = Path.home() / '.cache/emufusion-widescreen/host-build'
SYSTEMS = {
    'nes': dict(core=BUILD / 'mesen/Libretro/mesen_libretro.dylib', option='emufusion_ws_aspect=1778',
                base=256, buttons='B', suffixes=('.nes',)),
    'gb': dict(core=BUILD / 'sameboy/build/bin/sameboy_libretro.dylib', option='emufusion_ws_aspect=1778',
               base=160, buttons='A', suffixes=('.gb',)),
    'gbc': dict(core=BUILD / 'sameboy/build/bin/sameboy_libretro.dylib', option='emufusion_ws_aspect=1778',
                base=160, buttons='A', suffixes=('.gbc',)),
    'gba': dict(core=BUILD / 'mgba/build-host/mgba_libretro.dylib', option='emufusion_ws_aspect=1778',
                base=240, buttons='A', suffixes=('.gba',)),
}
# Past most title screens without knowing the game, then walk and jump. A START too many pauses a
# game that is already playing, so each way in has a different count.
LEADS = (
    'wait:240 tap:START wait:360 ',
    'wait:300 tap:START wait:200 tap:START wait:400 ',
    'wait:300 tap:START wait:150 tap:A wait:150 tap:START wait:200 tap:A wait:200 tap:A wait:400 ',
    'wait:600 tap:START wait:300 tap:A wait:300 tap:A wait:300 tap:START wait:300 tap:A wait:500 ',
)
STEPS = 72
GAP = 14
MAX_SHIFT = 48
MATCH_MIDDLE = 0.90


def script(lead):
    steps = []
    for index in range(STEPS):
        press = 'hold:RIGHT,A:%d' % GAP if index % 12 == 6 else 'hold:RIGHT,B:%d' % GAP
        steps.append(f'{press} shot:{index:03d}')
    return lead + ' '.join(steps)


def column(pixels, x, height, step=2):
    return [pixels[x, y] for y in range(0, height, step)]


def same_share(left, right):
    return sum(a == b for a, b in zip(left, right)) / len(left)


def shift_between(a, b, base, width, height):
    """The sideways shift taking frame a to frame b, judged from the old picture's columns."""
    start = (width - base) // 2
    probes = range(start + MAX_SHIFT, start + base - MAX_SHIFT, 12)
    columns_a = {x: column(a, x, height, 3) for x in probes}
    best, best_share = 0, 0.0
    for shift in range(-MAX_SHIFT, MAX_SHIFT + 1):
        share = sum(same_share(columns_a[x], column(b, x - shift, height, 3)) for x in probes) / len(columns_a)
        if share > best_share:
            best, best_share = shift, share
    return best, best_share


def score_frames(paths, base):
    """(real, blank, evidence): side columns that later arrive in the picture, blank ones, pairs used."""
    frames = [Image.open(p).convert('RGB') for p in paths]
    if not frames:
        return 0.0, 1.0, 0
    width, height = frames[0].size
    pads = (width - base) // 2
    if pads <= 0:
        return 0.0, 1.0, 0
    pixels = [f.load() for f in frames]
    start, end = pads, pads + base
    real, seen, blank, total = 0.0, 0, 0, 0
    for frame in pixels:
        for x in (pads // 2, width - 1 - pads // 2):
            cells = column(frame, x, height)
            total += 1
            blank += len(set(cells)) == 1 and cells[0] == (0, 0, 0)
    for i in range(0, len(pixels) - 3):
        for gap in (1, 2, 3):
            shift, share = shift_between(pixels[i], pixels[i + gap], base, width, height)
            if share < MATCH_MIDDLE or abs(shift) < 8:
                continue
            # With shift > 0 the world moved left: the right side of frame i is now in the picture.
            xs = range(end + 2, min(end + abs(shift) - 2, width)) if shift > 0 else range(max(start - abs(shift) + 2, 0), start - 2)
            if xs:
                match = 0.0
                for x in xs:
                    match += same_share(column(pixels[i], x, height), column(pixels[i + gap], x - shift, height))
                real += match / len(xs)
                seen += 1
            break
    return (real / seen if seen else 0.0), blank / max(total, 1), seen


def judge(system, rom):
    spec = SYSTEMS[system]
    best = dict(rom=rom.name, real=0.0, blank=1.0, pairs=0)
    for way, lead in enumerate(LEADS):
        out = tempfile.mkdtemp(prefix='ef-triage-')
        try:
            run = subprocess.run(
                ['nice', '-n', '10', sys.executable, str(ROOT / 'tools/widescreen/retro_play.py'), str(spec['core']), str(rom),
                 '--out', out, '--opt', spec['option'], '--play', script(lead)],
                capture_output=True, text=True, timeout=240, cwd=str(ROOT))
            if run.returncode:
                best.setdefault('error', run.stderr.strip().split('\n')[-1][:120])
                continue
            real, blank, pairs = score_frames(sorted(str(p) for p in Path(out).glob('*.png')), spec['base'])
            if pairs > best['pairs']:
                best = dict(rom=rom.name, real=round(real, 3), blank=round(blank, 3), pairs=pairs, way=way)
            if pairs >= 12:
                break
        except subprocess.TimeoutExpired:
            best.setdefault('error', 'timeout')
        except Exception as error:  # A broken ROM must not end a run over a thousand games.
            best.setdefault('error', str(error)[:120])
        finally:
            shutil.rmtree(out, ignore_errors=True)
    return best


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('system', choices=SYSTEMS)
    parser.add_argument('roms')
    parser.add_argument('out')
    parser.add_argument('--jobs', type=int, default=4)
    parser.add_argument('--only', default='')
    args = parser.parse_args()
    suffixes = SYSTEMS[args.system]['suffixes']
    roms = sorted(p for p in Path(args.roms).iterdir() if p.suffix.lower() in suffixes and args.only.lower() in p.name.lower())
    results = {}
    target = Path(args.out)
    if target.exists():
        results = {row['rom']: row for row in json.loads(target.read_text())}
    todo = [rom for rom in roms if rom.name not in results]
    with concurrent.futures.ThreadPoolExecutor(args.jobs) as pool:
        for row in pool.map(lambda rom: judge(args.system, rom), todo):
            results[row['rom']] = row
            target.write_text(json.dumps(sorted(results.values(), key=lambda r: -r.get('real', 0)), indent=1) + '\n')
            print(row, flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
