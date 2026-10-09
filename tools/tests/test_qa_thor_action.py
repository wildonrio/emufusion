"""Offline action-admission regression; never calls real ADB."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import qa_thor_action as action

OPEN = '  Device 1: hall_switch\n    SwitchValues: 00000000\n  Configuration:\n'


class GuardedActionTest(unittest.TestCase):
    def remote_fixture(self, deadline='1000', app_pid='123', guard_live=True,
                       awake=True):
        # Execute the actual generated remote gate against read-only command
        # fixtures; never create /data directories or call Android commands.
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            responses = {
                'sed': deadline,
                'date': '100',
                'ps': 'COMMAND\nsh /data/local/tmp/emufusion-oled-test/timeout.sh 600' if guard_live else 'COMMAND',
                'pidof': app_pid,
                'dumpsys': 'mWakefulness=Awake' if awake else 'mWakefulness=Asleep',
            }
            import shlex
            for name, response in responses.items():
                path = work / name
                path.write_text('#!/bin/sh\nprintf "%s\\n" ' + shlex.quote(response) + '\n')
                path.chmod(0o755)
            return subprocess.run(['sh'], input=action.guarded_command(
                '/data/local/tmp/emufusion-oled-test', 'echo first; echo second', 123, 30),
                env=dict(os.environ, PATH=str(work) + os.pathsep + os.environ['PATH']),
                capture_output=True, text=True, timeout=5)

    def test_remote_accepted_executes_complete_batch(self):
        result = self.remote_fixture()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual('first\nsecond\n', result.stdout)

    def test_remote_rejection_never_executes_second_command_either(self):
        for override in ({'deadline': '120'}, {'deadline': 'bad'},
                         {'app_pid': '456'}, {'guard_live': False}, {'awake': False}):
            with self.subTest(override=override):
                result = self.remote_fixture(**override)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual('', result.stdout)

    def test_remote_script_is_valid_and_groups_all_actions_after_checks(self):
        command = action.guarded_command('/data/local/tmp/emufusion-oled-test',
                                         "echo 'first'; echo second", 123, 30)
        result = subprocess.run(['sh', '-n'], input=command, text=True,
                                capture_output=True, timeout=3)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertNotIn('kill -0', command)
        self.assertIn('pidof com.thorium.preview', command)
        self.assertIn('ps -A -o ARGS', command)
        self.assertIn('mWakefulness=Awake', command)
        self.assertTrue(command.splitlines()[-1].startswith('sh -c '))

    def test_bad_guard_and_bounds_rejected(self):
        for guard, pid, reserve in [('/tmp/anything', 1, 30),
                                    ('/data/local/tmp/emufusion-oled-x;bad', 1, 30),
                                    ('/data/local/tmp/emufusion-oled-test', -1, 30),
                                    ('/data/local/tmp/emufusion-oled-test', 1, 0)]:
            with self.assertRaises(ValueError):
                action.guarded_command(guard, 'echo no', pid, reserve)

    def test_completed_local_guard_never_calls_adb(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'watchdog-ended').touch()
            def forbidden(*args, **kwargs):
                self.fail('called ADB after test end')
            with self.assertRaises(RuntimeError):
                action.execute(root, 'echo no', runner=forbidden)

    def test_closed_lid_rejects_without_action(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'device-guard-dir.txt').write_text('/data/local/tmp/emufusion-oled-test')
            calls = []
            def fake(command, **kwargs):
                calls.append(command)
                return subprocess.CompletedProcess(command, 0, OPEN.replace('00000000', '00000001'), '')
            with self.assertRaises(RuntimeError):
                action.execute(root, 'echo no', runner=fake)
            self.assertEqual(1, len(calls))

    def test_open_lid_uses_exact_serial_and_remote_admission(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'device-guard-dir.txt').write_text('/data/local/tmp/emufusion-oled-test')
            calls = []
            def fake(command, **kwargs):
                calls.append(command)
                return subprocess.CompletedProcess(command, 0, OPEN if len(calls) == 1 else 'done', '')
            result = action.execute(root, 'echo yes', pid=456, runner=fake)
            self.assertEqual('done', result.stdout)
            self.assertEqual(2, len(calls))
            self.assertEqual([action.ADB, '-s', '427c87b2', 'shell'], calls[-1][:4])
            self.assertIn('= 456', calls[-1][-1])


if __name__ == '__main__':
    unittest.main()
