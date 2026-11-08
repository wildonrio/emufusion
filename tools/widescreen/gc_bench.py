#!/usr/bin/env python3
"""gc_bench.py GAME OUT MODE SCRIPT: run a GameCube game in the Mac dolphin-emu-nogui bench (dolphin_mac_bench.sh), narrow or wide, with pad input from a
script, keeping every Nth frame at its display aspect.

MODE: narrow (4:3, no widening) or wide (Dolphin's widescreen hack, 16:9, 2D drawn 0.75 wide as the app does on the Thor).
SCRIPT steps: wait:SECONDS, press:BUTTON[:SECONDS] (A B X Y Z START D_UP D_DOWN D_LEFT D_RIGHT), stick:X,Y:SECONDS (0..1).
Frames land in OUT/user/Dump/Frames.
"""
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

DOLPHIN = Path(os.environ.get('DOLPHIN_MAC_BENCH', Path.home() / '.cache/emufusion-widescreen/host-build/dolphin-mac')) / 'build-mac/Binaries/dolphin-emu-nogui'
EVERY = os.environ.get('GC_BENCH_EVERY', '15')


def configure(user, wide):
    config = user / 'Config'
    config.mkdir(parents=True, exist_ok=True)
    (user / 'Pipes').mkdir(exist_ok=True)
    (config / 'Dolphin.ini').write_text(
        '[Core]\nSIDevice0 = 6\nSkipIPL = True\nGFXBackend = Metal\n'
        '[DSP]\nBackend = No Audio Output\n'
        '[Movie]\nDumpFrames = True\n'
        '[Interface]\nConfirmStop = False\nShowActiveTitle = False\n'
        '[Analytics]\nPermissionAsked = True\nEnabled = False\n')
    (config / 'GFX.ini').write_text(
        '[Settings]\n'
        f'wideScreenHack = {"True" if wide else "False"}\n'
        f'AspectRatio = {1 if wide else 2}\n'
        'InternalResolution = 2\nDumpFramesAsImages = True\nFrameDumpsResolutionType = 1\n'
        'ShowFPS = False\nShowNetPlayPing = False\nOverlayStats = False\n')
    buttons = ['A', 'B', 'X', 'Y', 'Z', 'START']
    lines = ['[GCPad1]', 'Device = Pipe/0/pad']
    lines += [f'Buttons/{"Start" if b == "START" else b} = `Button {b}`' for b in buttons]
    lines += ['D-Pad/Up = `Button D_UP`', 'D-Pad/Down = `Button D_DOWN`', 'D-Pad/Left = `Button D_LEFT`', 'D-Pad/Right = `Button D_RIGHT`',
              'Main Stick/Up = `Axis MAIN Y -`', 'Main Stick/Down = `Axis MAIN Y +`',
              'Main Stick/Left = `Axis MAIN X -`', 'Main Stick/Right = `Axis MAIN X +`']
    (config / 'GCPadNew.ini').write_text('\n'.join(lines) + '\n')
    pipe = user / 'Pipes/pad'
    if not pipe.exists():
        os.mkfifo(pipe)
    return pipe


def main():
    game, out, mode, script = sys.argv[1], Path(sys.argv[2]), sys.argv[3], sys.argv[4]
    wide = mode == 'wide'
    user = out / 'user'
    if (user / 'Dump').exists():
        shutil.rmtree(user / 'Dump')
    pipe = configure(user, wide)
    env = dict(os.environ, EMUFUSION_WS_2D='0.75' if wide else '1', EMUFUSION_DUMP_EVERY=EVERY)
    log = open(out / 'dolphin.log', 'w')
    process = subprocess.Popen([str(DOLPHIN), '-u', str(user), '-p', 'headless', '-v', 'Metal', '-e', game],
                               stdout=log, stderr=subprocess.STDOUT, env=env)
    try:
        # Dolphin opens the pipe for reading when its controllers start; this blocks until then.
        fd = os.open(pipe, os.O_WRONLY)
        writer = os.fdopen(fd, 'w', buffering=1)
        for step in script.split():
            kind, _, rest = step.partition(':')
            if process.poll() is not None:
                break
            if kind == 'wait':
                time.sleep(float(rest))
            elif kind == 'press':
                name, _, seconds = rest.partition(':')
                writer.write(f'PRESS {name}\n')
                time.sleep(float(seconds or 0.2))
                writer.write(f'RELEASE {name}\n')
                time.sleep(0.1)
            elif kind == 'stick':
                where, _, seconds = rest.partition(':')
                x, y = where.split(',')
                writer.write(f'SET MAIN {x} {y}\n')
                time.sleep(float(seconds))
                writer.write('SET MAIN 0.5 0.5\n')
        writer.close()
    finally:
        process.terminate()
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
    frames = sorted((user / 'Dump/Frames').glob('*.png')) if (user / 'Dump/Frames').exists() else []
    print(mode, 'frames', len(frames), 'exit', process.returncode)


if __name__ == '__main__':
    main()
