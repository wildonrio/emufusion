#!/usr/bin/env python3
"""Prove widening never stretches: a pixel's shape must be the same narrow and wide on every engine.

The Widescreen Hack adds columns. A pixel's width over its height is the picture's aspect divided by
its width over its height, and that must not change when a game widens. Run after any engine change.

usage: par_check.py
"""
import os
import re
import subprocess
from pathlib import Path

HOME = Path(os.path.expanduser('~/.cache/emufusion-widescreen'))
BUILD = HOME / 'host-build'
TOOL = Path(__file__).with_name('retro_play.py')
# Engine, ROM, option name and value that widen it to 16:9, frames to run.
CASES = [
    ('snes bsnes-hd', BUILD / 'bsnes-hd/bsnes/out/bsnes_hd_beta_libretro.dylib', 'snes/Super Mario World.sfc', 'emufusion_ws_width', '348'),
    ('megadrive blastem H40', BUILD / 'blastem/blastem_libretro.so', 'megadrive/Sonic & Knuckles.gen', 'emufusion_ws_aspect', '1778'),
    ('megadrive blastem H32', BUILD / 'blastem/blastem_libretro.so', 'megadrive/Monster World IV.md', 'emufusion_ws_aspect', '1778'),
    ('gamegear gearsystem', BUILD / 'gearsystem/platforms/libretro/gearsystem_libretro.dylib', 'gamegear/Sonic the Hedgehog.gg', 'emufusion_ws_aspect', '1778'),
    ('nes mesen', BUILD / 'mesen/Libretro/mesen_libretro.dylib', 'nes/Contra.nes', 'emufusion_ws_aspect', '1778'),
    ('gb sameboy', BUILD / 'sameboy/build/bin/sameboy_libretro.dylib', 'gb/Tetris (USA, Europe).gb', 'emufusion_ws_aspect', '1778'),
    ('gbc sameboy', BUILD / 'sameboy/build/bin/sameboy_libretro.dylib', 'gbc/Wario Land 3.gbc', 'emufusion_ws_aspect', '1778'),
    ('gba mgba', BUILD / 'mgba/build-host/mgba_libretro.dylib', 'gba/Metroid Fusion.gba', 'emufusion_ws_aspect', '1778'),
]


def geometry(core, rom, option, value, out):
    command = ['python3', str(TOOL), str(core), str(HOME / 'roms' / rom), '--out', out,
               '--opt', f'{option}={value}', '--play', 'wait:400 shot:a']
    if 'bsnes' in str(core):
        # Its widening needs the table's options as well as a width.
        command[6:8] = ['--recipe', 'snes/Super Mario World', '--width', value]
    result = subprocess.run(command, capture_output=True, text=True)
    text = result.stdout + result.stderr
    match = re.findall(r'geometry \((\d+), (\d+), ([\d.]+)\)', text)[-1]
    width, height, aspect = int(match[0]), int(match[1]), float(match[2])
    return width, height, aspect or width / height


def main():
    worst = 0.0
    out = '/tmp/claude-501/par-check'
    os.makedirs(out, exist_ok=True)
    for name, core, rom, option, value in CASES:
        narrow = geometry(core, rom, option, '0', out)
        wide = geometry(core, rom, option, value, out)
        shape = lambda g: g[2] / (g[0] / g[1])
        change = abs(shape(wide) / shape(narrow) - 1) * 100
        worst = max(worst, change)
        print(f'{name:24} narrow {narrow[0]}x{narrow[1]} {narrow[2]:.4f}   wide {wide[0]}x{wide[1]} {wide[2]:.4f}'
              f'   pixel shape changes {change:.3f}%')
    print('NO STRETCH' if worst < 0.05 else f'STRETCH FOUND: {worst:.3f}%')
    return 0 if worst < 0.05 else 1


if __name__ == '__main__':
    raise SystemExit(main())
