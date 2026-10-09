"""Execute device deadline cleanup with fake Android commands; no real ADB."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
DEVICE = ROOT / "tools/qa_oled_device_timeout.sh"


class OledIdleRestoreTest(unittest.TestCase):
    def run_deadline(self, current, original="60000", bounded="360000"):
        with tempfile.TemporaryDirectory(prefix="oled-idle-test-") as directory:
            work = Path(directory)
            clock = work / "date"
            clock.write_text('#!/bin/sh\nif [ -f "$CLOCK_SEEN" ]; then echo 361; '
                             'else touch "$CLOCK_SEEN"; echo 0; fi\n')
            clock.chmod(0o755)
            dispatcher = work / "dispatch"
            dispatcher.write_text('#!/bin/sh\nname=${0##*/}\n'
                                  'printf "%s %s\\n" "$name" "$*" >> "$CALLS"\n'
                                  'if [ "$name $*" = "settings get system screen_off_timeout" ]; '
                                  'then echo "$CURRENT_IDLE"; fi\n')
            dispatcher.chmod(0o755)
            for command in ("sendevent", "input", "am", "settings"):
                (work / command).symlink_to(dispatcher)
            calls = work / "calls"
            env = dict(os.environ, PATH=str(work) + os.pathsep + os.environ["PATH"],
                       CLOCK_SEEN=str(work / "seen"), CALLS=str(calls), CURRENT_IDLE=current)
            result = subprocess.run(["sh", str(DEVICE), "360",
                                     "/data/local/tmp/emufusion-oled-host-unit-test/cancel",
                                     original, bounded], env=env, capture_output=True, text=True, timeout=5)
            return result, calls.read_text() if calls.exists() else ""

    def test_deadline_blanks_panels_releases_input_and_restores_its_timeout(self):
        result, calls = self.run_deadline("360000")
        self.assertEqual(0, result.returncode, result.stderr)
        for action in ("input keyevent 223", "am force-stop com.thorium.preview",
                       "sendevent /dev/input/event9 1 307 0",
                       "sendevent /dev/input/event9 1 308 0",
                       "sendevent /dev/input/event9 3 0 0",
                       "sendevent /dev/input/event9 3 1 0",
                       "sendevent /dev/input/event9 3 2 0",
                       "sendevent /dev/input/event9 3 5 0",
                       "sendevent /dev/input/event9 3 16 0",
                       "sendevent /dev/input/event9 3 17 0",
                       "settings put system screen_brightness 0",
                       "settings put system screen_off_timeout 60000"):
            self.assertIn(action, calls)

    def test_host_cleanup_releases_all_axes_before_sync_and_sleep(self):
        source = (ROOT / "tools/qa_oled_timeout.sh").read_text()
        cleanup = source[source.index("cleanup() {"):source.index("trap cleanup EXIT")]
        sync = cleanup.index("sendevent /dev/input/event9 0 0 0")
        for axis in (0, 1, 2, 5, 16, 17):
            self.assertLess(cleanup.index(f"sendevent /dev/input/event9 3 {axis} 0"), sync)
        self.assertLess(sync, cleanup.index("input keyevent 223"))

    def test_deadline_preserves_newer_user_timeout(self):
        result, calls = self.run_deadline("90000")
        self.assertEqual(0, result.returncode)
        self.assertNotIn("settings put system screen_off_timeout", calls)

    def test_default_does_not_read_or_change_idle_timeout(self):
        result, calls = self.run_deadline("60000", "", "")
        self.assertEqual(0, result.returncode)
        self.assertNotIn("screen_off_timeout", calls)

    def test_invalid_timeout_is_rejected_before_cleanup_actions(self):
        result, calls = self.run_deadline("360000", "not-a-timeout", "360000")
        self.assertEqual(2, result.returncode)
        self.assertEqual("", calls)


if __name__ == "__main__":
    unittest.main()
