"""Exercise trial byte preservation and rollback entirely against fake commands."""

import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[2]
TRIAL = ROOT / "tools/qa_ps3_config_trial.sh"
RESTORE = ROOT / "tools/qa_ps3_config_restore_device.sh"
CONFIG = "app_engine-system/aps3e/config/config.yml"
BACKUP = "cache/qa-ps3-config-Ab1234"
FAKE_COMMAND = r'''#!/usr/bin/env python3
import os, pathlib, shutil, sys
root = pathlib.Path(os.environ["FAKE_DEVICE"])
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
if name == "date":
    counter = root / "clock"
    now = int(counter.read_text()) if counter.exists() else 0
    counter.write_text(str(now + 601))
    print(now)
    sys.exit(0)
if name == "run-as":
    args = ["shell", "run-as"] + args
elif name in ("am", "input"):
    args = ["shell", name] + args
else:
    assert args[:2] == ["-s", "427c87b2"], args
    args = args[2:]
with (root / "calls").open("a") as log:
    log.write(repr(args) + "\n")
if args[0] == "push":
    destination = root / args[2].lstrip("/")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(args[1], destination)
elif args[0] == "shell" and len(args) == 2:
    if args[1].startswith("if pidof"):
        sys.exit(1 if os.environ.get("FAKE_BUSY") else 0)
    assert args[1].startswith("nohup sh "), args
    shutil.copyfile(root / "cache/qa-ps3-config-Ab1234/config-candidate.yml",
                    root / "app_engine-system/aps3e/config/config.yml")
    (root / "cache/qa-ps3-config-Ab1234/armed").touch()
elif args[1:3] == ["am", "force-stop"] or args[1:3] == ["input", "keyevent"]:
    pass
else:
    assert args[1:3] == ["run-as", "com.thorium.preview"], args
    cmd = args[3:]
    def path(value):
        return root / value.lstrip("/")
    if cmd[0] == "mktemp":
        path("cache/qa-ps3-config-Ab1234").mkdir(parents=True)
        print("cache/qa-ps3-config-Ab1234")
    elif cmd[0] == "cp":
        if os.environ.get("FAKE_APPLY_FAIL") and cmd[1].endswith("qa_ps3_config_candidate.yml"):
            sys.exit(1)
        if os.environ.get("FAKE_RESTORE_FAIL") and cmd[1].endswith("/config-before.yml"):
            sys.exit(1)
        path(cmd[2]).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path(cmd[1]), path(cmd[2]))
    elif cmd[0] == "cat":
        sys.stdout.buffer.write(path(cmd[1]).read_bytes())
    elif cmd[0] == "test":
        sys.exit(0 if path(cmd[2]).is_file() else 1)
    elif cmd[0] == "touch":
        path(cmd[1]).touch()
        if cmd[1].endswith("/restore-request") and not os.environ.get("FAKE_RESTORE_FAIL"):
            shutil.copyfile(root / "cache/qa-ps3-config-Ab1234/config-before.yml",
                            root / "app_engine-system/aps3e/config/config.yml")
            (root / "cache/qa-ps3-config-Ab1234/restored").touch()
    elif cmd[0] == "cmp":
        sys.exit(0 if path(cmd[1]).read_bytes() == path(cmd[2]).read_bytes() else 1)
    else:
        raise AssertionError(cmd)
'''


class Ps3ConfigTrialTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.evidence = self.base / "evidence"
        self.evidence.mkdir()
        self.device = self.base / "device"
        (self.device / CONFIG).parent.mkdir(parents=True)
        self.bin = self.base / "bin"
        self.bin.mkdir()
        for name in ("adb", "run-as", "date", "am", "input"):
            command = self.bin / name
            command.write_text(FAKE_COMMAND)
            command.chmod(0o755)
        self.guard = self.base / "guard.sh"
        self.guard.write_text("#!/bin/sh\nexit 0\n")
        self.env = dict(os.environ, FAKE_DEVICE=str(self.device),
                        PS3_TRIAL_ADB=str(self.bin / "adb"),
                        PS3_TRIAL_OLED_GUARD=str(self.guard),
                        PATH=str(self.bin) + os.pathsep + os.environ["PATH"])
        self.original = b"Core:\n  Accurate SPU DMA: false\n  Accurate SPU Reservations: true"
        self.prepare(self.original)

    def prepare(self, original, candidate=None):
        self.original = original
        (self.device / CONFIG).write_bytes(original)
        (self.evidence / "config-before.yml").write_bytes(original)
        (self.evidence / "config-candidate.yml").write_bytes(
            candidate if candidate is not None else original.replace(
                b"Accurate SPU DMA: false", b"Accurate SPU DMA: true"))

    def run_trial(self):
        return subprocess.run(["sh", str(TRIAL), str(self.evidence)], env=self.env,
                              capture_output=True, timeout=15)

    def assert_restored(self):
        self.assertEqual((self.device / CONFIG).read_bytes(), self.original)
        self.assertEqual((self.evidence / "config-restored.yml").read_bytes(), self.original)
        self.assertTrue((self.device / BACKUP / "restored").is_file())

    def test_exact_round_trip_without_final_newline(self):
        result = self.run_trial()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_restored()
        self.assertEqual((self.device / BACKUP / "config-before.yml").read_bytes(), self.original)
        self.assertTrue((self.evidence / "trial-ready").is_file())

    def test_crlf_is_preserved(self):
        self.prepare(self.original.replace(b"\n", b"\r\n") + b"\r\n")
        self.assertEqual(self.run_trial().returncode, 0)
        self.assert_restored()

    def test_reject_extra_change_before_any_device_command(self):
        candidate = self.original.replace(b"DMA: false", b"DMA: true") + b"\n"
        self.prepare(self.original, candidate)
        self.assertNotEqual(self.run_trial().returncode, 0)
        self.assertFalse((self.device / "calls").exists())

    def test_reject_duplicate_key_before_any_device_command(self):
        self.prepare(self.original + b"\n  Accurate SPU DMA: false")
        self.assertNotEqual(self.run_trial().returncode, 0)
        self.assertFalse((self.device / "calls").exists())

    def test_reject_already_enabled_before_any_device_command(self):
        self.prepare(self.original.replace(b"DMA: false", b"DMA: true"))
        self.assertNotEqual(self.run_trial().returncode, 0)
        self.assertFalse((self.device / "calls").exists())

    def test_running_app_rejected_without_backup_or_mutation(self):
        self.env["FAKE_BUSY"] = "1"
        self.assertNotEqual(self.run_trial().returncode, 0)
        self.assertEqual((self.device / CONFIG).read_bytes(), self.original)
        self.assertFalse((self.device / BACKUP).exists())

    def test_apply_failure_restores_original(self):
        self.env["FAKE_APPLY_FAIL"] = "1"
        self.assertNotEqual(self.run_trial().returncode, 0)
        self.assertEqual((self.device / CONFIG).read_bytes(), self.original)
        self.assertEqual((self.evidence / "config-restored.yml").read_bytes(), self.original)
        self.assertFalse((self.device / BACKUP / "armed").exists())

    def test_host_restore_failure_does_not_cancel_detached_restore(self):
        self.env["FAKE_RESTORE_FAIL"] = "1"
        self.assertNotEqual(self.run_trial().returncode, 0)
        self.assertTrue((self.device / BACKUP / "armed").is_file())
        self.assertFalse((self.device / BACKUP / "restored").exists())
        # Run the actual detached script with fake time/commands after host loss.
        del self.env["FAKE_RESTORE_FAIL"]
        result = subprocess.run(["sh", str(RESTORE), BACKUP], env=self.env,
                                capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.device / CONFIG).read_bytes(), self.original)
        self.assertTrue((self.device / BACKUP / "restored").is_file())

    def test_detached_owner_applies_then_restores_without_host(self):
        backup = self.device / BACKUP
        backup.mkdir(parents=True)
        (backup / "config-before.yml").write_bytes(self.original)
        (backup / "config-candidate.yml").write_bytes(
            (self.evidence / "config-candidate.yml").read_bytes())
        result = subprocess.run(["sh", str(RESTORE), BACKUP], env=self.env,
                                capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.device / CONFIG).read_bytes(), self.original)
        self.assertTrue((backup / "armed").is_file())
        self.assertTrue((backup / "restored").is_file())
        calls = (self.device / "calls").read_text()
        self.assertLess(calls.index("config-candidate.yml', 'app_engine-system"),
                        calls.index("config-before.yml', 'app_engine-system"))

    def test_signals_restore_original(self):
        self.guard.write_text("#!/bin/sh\ntrap 'exit 0' HUP INT TERM\nwhile :; do sleep 0.05; done\n")
        for sig in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
            with self.subTest(signal=sig):
                for name in ("trial-ready", "config-applied.yml", "config-restored.yml"):
                    (self.evidence / name).unlink(missing_ok=True)
                backup = self.device / BACKUP
                if backup.exists():
                    for entry in backup.iterdir():
                        entry.unlink()
                    backup.rmdir()
                process = subprocess.Popen(["sh", str(TRIAL), str(self.evidence)],
                                           env=self.env, stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE)
                try:
                    deadline = time.monotonic() + 10
                    while not (self.evidence / "trial-ready").exists():
                        if process.poll() is not None or time.monotonic() > deadline:
                            self.fail("Trial did not reach fake ready state")
                        time.sleep(0.01)
                    process.send_signal(sig)
                    _, stderr = process.communicate(timeout=5)
                    self.assertEqual(process.returncode, 128 + sig, stderr)
                    self.assert_restored()
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.communicate()


if __name__ == "__main__":
    unittest.main()
