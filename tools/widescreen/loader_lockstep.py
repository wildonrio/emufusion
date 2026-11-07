#!/usr/bin/env python3
"""Prove a Game Gear loader patch: the same random inputs through a wide run without the patch and one with it.

Every shot's old 160x144 area must match exactly. Both runs get the recipe's other options, including
emufusion_ws_freepc, so the patch cannot shift the game's timing. Do not start from a state saved by a
patched run: its video memory would carry a fault into the reference.

usage: loader_lockstep.py CORE ROM OUT OPTIONS.json START-SCRIPT SEED MOVES
"""
import json
import random
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageChops

HERE = Path(__file__).resolve().parent
core, rom, out, options_path, start, seed, moves = sys.argv[1:8]
options = json.loads(Path(options_path).read_text())
rng = random.Random(int(seed))
script = [start]
for index in range(int(moves)):
    buttons = rng.choice(['RIGHT', 'RIGHT', 'RIGHT,B', 'RIGHT,A', 'LEFT', 'LEFT,B', 'LEFT', 'UP', 'DOWN',
                          'RIGHT,UP', 'LEFT,DOWN', 'UP,LEFT', 'DOWN,RIGHT', 'B', 'A'])
    script += [f'hold:{buttons}:{rng.randint(12, 70)}', f'shot:s{index:03d}']


def run(name, extra):
    folder = Path(out) / name
    folder.mkdir(parents=True, exist_ok=True)
    command = ['python3', str(HERE / 'retro_play.py'), core, rom, '--out', str(folder), '--play', ' '.join(script),
               '--opt', 'emufusion_ws_aspect=1778']
    for key, value in extra.items():
        command += ['--opt', f'{key}={value}']
    subprocess.run(command, capture_output=True, check=True)
    return folder


reference = run('reference', {key: value for key, value in options.items() if key != 'emufusion_ws_patch'})
patched = run('patched', options)
total, bad = 0, []
for index in range(int(moves)):
    a = Image.open(reference / f's{index:03d}.png').convert('RGB')
    b = Image.open(patched / f's{index:03d}.png').convert('RGB')
    side = (b.width - 160) // 2
    box = (side, 0, side + 160, 144)
    diff = ImageChops.difference(a.crop(box), b.crop(box)).convert('L').point(lambda v: 255 if v else 0)
    total += 1
    if diff.getbbox():
        bad.append((index, diff.getbbox()))
print(f'{total} shots, {len(bad)} differ in the old screen area')
print(bad[:12])
sys.exit(1 if bad else 0)
