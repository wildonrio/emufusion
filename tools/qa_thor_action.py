"""Execute a bounded Thor QA action only inside a live OLED test window.

No signal-based process probe: Android shell cannot signal the app UID. The
caller must observe the screen first and reserve enough time for the whole batch.
Sleep/release-only emergency cleanup should not use this admission gate.
"""
import argparse
from pathlib import Path
import re
import shlex
import subprocess

from qa_thor_lid_check import lid_state

ADB = '/Users/tyleryoung/.codex/tools/android-platform-tools/adb'
SERIAL = '427c87b2'


def guarded_command(guard, command, pid=0, reserve=15):
    if not re.fullmatch(r'/data/local/tmp/emufusion-oled-[A-Za-z0-9]+', guard):
        raise ValueError('invalid OLED guard directory')
    if not command or pid < 0 or not 5 <= reserve <= 240:
        raise ValueError('invalid action bounds')
    prefix = [
        'set -eu',
        f'test ! -e {shlex.quote(guard + "/cancel")}',
        f'qa_deadline=$(sed -n "s/^armed device deadline=//p" {shlex.quote(guard + "/log")})',
        'case "$qa_deadline" in ""|*[!0-9]*) exit 3;; esac',
        f'test "$(( $(date +%s) + {reserve} ))" -lt "$qa_deadline"',
        # Match the exact device-side guard command, not this command's text.
        'ps -A -o ARGS | awk -v script=' + shlex.quote(guard + '/timeout.sh') +
        " '($1 == \"sh\" && $2 == script) {found=1} END {exit !found}'",
    ]
    if pid:
        prefix.extend([
            f'test "$(pidof com.thorium.preview)" = {pid}',
            "dumpsys power | grep 'mWakefulness=Awake' >/dev/null",
        ])
    prefix.append('sh -c ' + shlex.quote(command))
    return '\n'.join(prefix)


def execute(root, command, pid=0, reserve=15, runner=subprocess.run):
    root = Path(root).resolve()
    if (root / 'watchdog-ended').exists() or (root / 'stop-test').exists():
        raise RuntimeError('OLED test already ended; no action executed')
    guard = (root / 'device-guard-dir.txt').read_text().strip()
    remote = guarded_command(guard, command, pid, reserve)
    snapshot = runner([ADB, '-s', SERIAL, 'shell', 'dumpsys input'],
                      text=True, capture_output=True, check=True, timeout=10)
    if lid_state(snapshot.stdout) != 'open':
        raise RuntimeError('Thor lid is closed/unknown; no action executed')
    return runner([ADB, '-s', SERIAL, 'shell', remote], text=True,
                  capture_output=True, check=True, timeout=reserve + 10)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True)
    parser.add_argument('--pid', type=int, default=0)
    parser.add_argument('--reserve', type=int, default=15)
    parser.add_argument('command')
    args = parser.parse_args()
    result = execute(args.root, args.command, args.pid, args.reserve)
    print(result.stdout, end='')
    print(result.stderr, end='')
