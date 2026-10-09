from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

from tools.qa_thor_battery_check import check_battery

ROOT = Path(__file__).resolve().parents[2]


def snapshot(level=70, temperature=320, scale=100):
    return ("Current Battery Service state:\n  AC powered: false\n"
            "  USB powered: false\n  present: true\n  health: 2\n  status: 3\n"
            f"  level: {level}\n  scale: {scale}\n  temperature: {temperature}\n")


class ThorBatteryCheckTest(unittest.TestCase):
    def test_thresholds_use_percentage_and_tenths_celsius(self):
        for level, temp, scale, expected in ((20, 429, 100, True),
                (19, 320, 100, False), (70, 430, 100, False),
                (2, 500, 100, False), (9, 470, 100, False),
                (40, 320, 200, True), (39, 320, 200, False)):
            with self.subTest(level=level, temp=temp, scale=scale):
                self.assertEqual(expected, check_battery(snapshot(level, temp, scale))[0])

    def test_missing_ambiguous_simulated_or_invalid_telemetry_refused(self):
        good = snapshot()
        for dump in ("", "permission denied", good + "  level: 90\n",
                     good.replace("present: true", "present: false"),
                     good.replace("health: 2", "health: 3"),
                     good.replace("status: 3", "status: 1"),
                     good.replace("scale: 100", "scale: 0"),
                     good.replace("temperature: 320", "temperature: NaN"),
                     good.replace("temperature: 320", "temperature: 0"),
                     good.replace("level: 70", "level: 101"),
                     good.replace("  temperature: 320\n", ""),
                     good + "  (UPDATES STOPPED -- use 'reset' to restart)\n"):
            with self.subTest(dump=dump):
                self.assertFalse(check_battery(dump)[0])

    def test_cable_or_charging_does_not_override_hot_or_low(self):
        for dump in (snapshot(2, 500).replace("USB powered: false", "USB powered: true"),
                     snapshot(9, 320).replace("status: 3", "status: 2")):
            self.assertFalse(check_battery(dump)[0])

    def test_captured_thor_failures_refused_without_adb(self):
        evidence = ROOT / "docs/qa/gles-off-timestamp-gate-2026-09-10"
        for name in ("battery-before-package.txt", "device-after-package.txt"):
            self.assertFalse(check_battery((evidence / name).read_text())[0])

    def test_cli_exit_code(self):
        for dump, code in ((snapshot(), 0), (snapshot(2, 500), 3), ("", 3)):
            result = subprocess.run([sys.executable, str(ROOT / "tools/qa_thor_battery_check.py")],
                                    input=dump, text=True, capture_output=True, timeout=5)
            self.assertEqual(code, result.returncode, result.stderr)

    def test_guard_battery_admission_precedes_all_mutations(self):
        source = (ROOT / "tools/qa_oled_timeout.sh").read_text()
        check = source.index("qa_thor_battery_check.py")
        self.assertLess(source.index("shell dumpsys battery"), check)
        for mutation in ('shell mktemp', '"$adb_bin" -s 427c87b2 push',
                         'shell "nohup', 'shell settings put'):
            self.assertLess(check, source.index(mutation))

    def test_actual_guard_refuses_hot_low_device_before_any_write(self):
        # Execute the real shell guard with a fake ADB transport, never a device.
        with tempfile.TemporaryDirectory(prefix="thor-battery-guard-") as directory:
            work = Path(directory)
            fake = work / "adb"
            fake.write_text('#!/bin/sh\n'
                            'printf "%s\\n" "$*" >> "$QA_CALLS"\n'
                            'case "$*" in\n'
                            '  "-s 427c87b2 shell dumpsys input") '
                            'printf "  Device 5: hall_switch\\n    SwitchValues: 0\\n  Configuration:\\n" ;;\n'
                            '  "-s 427c87b2 shell dumpsys battery") cat "$QA_BATTERY" ;;\n'
                            '  *) exit 97 ;;\n'
                            'esac\n')
            fake.chmod(0o755)
            source = (ROOT / "tools/qa_oled_timeout.sh").read_text()
            source = source.replace(
                'adb_bin=/Users/tyleryoung/.codex/tools/android-platform-tools/adb',
                'adb_bin="' + str(fake) + '"')
            guard = work / "qa_oled_timeout.sh"
            guard.write_text(source)
            for name in ("qa_thor_lid_check.py", "qa_thor_battery_check.py"):
                (work / name).symlink_to(ROOT / "tools" / name)
            battery = work / "battery"
            battery.write_text(snapshot(2, 500))
            calls = work / "calls"
            result = subprocess.run(["sh", str(guard), str(work), "600", "bounded-idle"],
                                    env=dict(os.environ, QA_CALLS=str(calls), QA_BATTERY=str(battery)),
                                    text=True, capture_output=True, timeout=5)
            self.assertEqual(3, result.returncode, result.stderr)
            self.assertEqual(["-s 427c87b2 shell dumpsys input",
                              "-s 427c87b2 shell dumpsys battery"],
                             calls.read_text().splitlines())
            self.assertIn("REFUSED", result.stdout)
            self.assertFalse((work / "watchdog-ended").exists())


if __name__ == "__main__":
    unittest.main()
