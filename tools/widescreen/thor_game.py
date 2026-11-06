#!/usr/bin/env python3
"""Run one game on the Thor through the widescreen prompts and play it with the real pad.

Uses the app's normal launch intent inside a QA save namespace, taps and swipes the real
touch screen, takes top-panel screenshots, then exits and puts both panels back to sleep.

Script steps (whitespace separated):
  wait:SECONDS         keep playing
  press:NAME[+NAME]    tap pad buttons (south east north west start select l r up down left right)
  hold:NAME[+NAME]:SECONDS
  shot:NAME            top-panel screenshot NAME.png in OUT
  tap:X,Y              touch the top panel
  swipe:X1,Y1,X2,Y2    swipe on the top panel
usage: thor_game.py OUT SYSTEM ENGINE ROM_PATH SCRIPT
"""
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] /
                       'docs/qa/android-portability-2026-10-08-current-build-survey'))
import thor_smoke as smoke

ADB = ['/tmp/claude-501/thor']
LOCK = '/tmp/claude-501/thor.lock'
TOP = '4630946441858561667'
PAD = '/dev/input/event9'
ACTIVITY = 'com.thorium.preview/org.pegasus_frontend.android.MainActivity'
# A QA save namespace; another one starts with no Quick Resume state to restore.
SESSION = os.environ.get('THOR_QA_SESSION', 'qa-7769646573637265656e000000000000')
KEYS = {'south': 304, 'east': 305, 'north': 308, 'west': 307, 'start': 315, 'select': 314,
        'l': 310, 'r': 311, 'up': 544, 'down': 545, 'left': 546, 'right': 547, 'back': 158}


def shell(command, timeout=60):
    return subprocess.run(ADB + ['shell', command], capture_output=True, timeout=timeout,
                          text=True, errors='replace').stdout


def buttons(names, value):
    return '; '.join(f'sendevent {PAD} 1 {KEYS[n]} {value}' for n in names.split('+')) + \
        f'; sendevent {PAD} 0 0 0'


def hold(names, seconds):
    shell(f'{buttons(names, 1)}; sleep {seconds}; {buttons(names, 0)}')


def screen(path):
    path.write_bytes(subprocess.run(ADB + ['exec-out', 'screencap', '-d', TOP, '-p'],
                                    capture_output=True, timeout=60).stdout)


def wait_log(log, pattern, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        match = re.search(pattern, log.read_text(errors='replace'))
        if match:
            return match
        time.sleep(0.5)
    return None


def main():
    out, system, engine, rom, script = Path(sys.argv[1]), *sys.argv[2:6]
    out.mkdir(parents=True, exist_ok=True)
    take_thor()
    shell('settings put global emufusion_qa_widescreen_all 1')
    # The recipe table is cached per app process, so a running app would not see the setting.
    # Wake first and let it settle: the firmware rebuilds the lower display at the upper panel's
    # size if an app's display mode change lands just before a wake (thor-lower-panel-squeeze).
    shell('input keyevent KEYCODE_WAKEUP')
    time.sleep(2)
    shell('am force-stop com.thorium.preview')
    # Set again: whoever had the Thor before may still be clearing its settings just after the lock.
    shell('settings put global emufusion_qa_widescreen_all 1')
    subprocess.run(ADB + ['logcat', '-c'], timeout=30)
    log = out / 'runtime.log'
    logger = subprocess.Popen(ADB + ['logcat', '-v', 'threadtime'], stdout=log.open('wb'),
                              stderr=subprocess.DEVNULL)
    try:
        quoted = rom.replace("'", "'\\''")
        # What the library would pass; without it the file name stands in for the title.
        name = os.environ.get('THOR_GAME_TITLE', '').replace("'", "'\\''")
        title = f" --es title '{name}'" if name else ''
        shell(f"am start -a com.thorium.preview.LAUNCH_INTERNAL_GAME -n {ACTIVITY} --es path '{quoted}' "
              f"--es system {system} --es engine_id {engine} --ez qualification_only true "
              f"--es qualification_session {SESSION}{title}")
        if not wait_log(log, r'Gameplay layer presenting', 120):
            screen(out / 'no-present.png')
            print('NO_PRESENT')
            return 1
        for step in script.split():
            kind, _, rest = step.partition(':')
            if kind == 'wait':
                time.sleep(float(rest))
            elif kind == 'press':
                hold(rest, 0.12)
            elif kind == 'hold':
                names, _, seconds = rest.rpartition(':')
                hold(names, float(seconds))
            elif kind == 'shot':
                screen(out / f'{rest}.png')
            elif kind == 'tap':
                x, y = rest.split(',')
                shell(f'input tap {x} {y}')
            elif kind == 'swipe':
                shell('input swipe ' + rest.replace(',', ' ') + ' 200')
            else:
                raise SystemExit('unknown step ' + step)
    finally:
        leave(log)
        logger.terminate()
        text = log.read_text(errors='replace')
        print('fatal', len(re.findall(r'FATAL EXCEPTION|Fatal signal', text)),
              'anr', len(re.findall(r'ANR in com\.thorium', text)))
        for line in re.findall(r'Widescreen[^\n]*', text)[:12]:
            print(line[:150])
        shell('settings delete global emufusion_qa_widescreen_all')
        release_thor()
    return 0


def take_thor():
    """The frame-generation work shares this device; one user at a time."""
    while True:
        try:
            os.mkdir(LOCK)
            return
        except FileExistsError:
            time.sleep(2)


def release_thor():
    try:
        os.rmdir(LOCK)
    except OSError:
        pass


def leave(log):
    """Pause, tap the pink Exit row, wait for the library, put both panels to sleep."""
    hold('back', 0.12)
    time.sleep(2)
    shot = log.parent / 'pause.png'
    screen(shot)
    spot = smoke.pink_centre(shot)
    if spot:
        shell(f'input tap {spot[0]} {spot[1]}')
        wait_log(log, r'Exit checkpoint finished', 60)
    else:
        print('EXIT_ROW_NOT_FOUND')
    shell('input keyevent KEYCODE_SLEEP')


if __name__ == '__main__':
    sys.exit(main())
