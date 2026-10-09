import importlib.util
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("retention", ROOT / "unified-android/tools/prune_build_apks.py")
RETENTION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RETENTION)


class RetentionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.now = 100 * 86400
        self.policy = dict(keep_per_flavor=1, minimum_age_days=7, pinned_sha256={})

    def apk(self, number, age=10, flavor="-lsfg-framegen-qualification", version="3.2.16"):
        digest = f"{number:064x}"
        path = self.root / f"lucent-{version}{flavor}-{digest}.apk"
        path.write_bytes(b"fixture")
        os.utime(path, (self.now - age * 86400,) * 2)
        return path

    def selected(self, opened=()):
        return [p for p, _, _ in RETENTION.select(self.root, self.policy, self.now, opened)]

    def test_keeps_newest_per_flavor(self):
        old = self.apk(1, 20)
        self.apk(2, 10)
        self.apk(3, 30, "-phase3-qualification")
        self.assertEqual(self.selected(), [old])

    def test_preserves_recent_beyond_count(self):
        self.apk(1, 3)
        self.apk(2, 2)
        self.assertEqual(self.selected(), [])

    def test_pin_preserves_old_rollback(self):
        self.apk(1, 20)
        self.apk(2, 10)
        self.policy["pinned_sha256"][f"{1:064x}"] = "rollback"
        self.assertEqual(self.selected(), [])

    def test_open_file_preserved(self):
        old = self.apk(1, 20)
        self.apk(2, 10)
        self.assertEqual(self.selected({str(old)}), [])

    def test_mutable_unknown_files_and_subdirectories_untouched(self):
        self.apk(2)
        for name in ("lucent-3.2.16.apk", "rom.nsp", "state.bin", "libcore.so", "data.json"):
            (self.root / name).write_bytes(b"keep")
        (self.root / "work").mkdir()
        (self.root / "work/a.apk").write_bytes(b"keep")
        self.assertEqual(self.selected(), [])

    def test_symlink_not_followed(self):
        old = self.apk(1, 20)
        target = self.root / "outside"
        old.rename(target)
        old.symlink_to(target)
        self.apk(2, 10)
        self.assertEqual(self.selected(), [])

    def test_versions_share_retention_bucket(self):
        old = self.apk(1, 20, version="3.2.15")
        self.apk(2, 10)
        self.assertEqual(self.selected(), [old])

    def test_changed_file_rejected(self):
        path = self.apk(1)
        meta = path.stat()
        self.assertTrue(RETENTION.unchanged(path, meta))
        path.write_bytes(b"changed")
        self.assertFalse(RETENTION.unchanged(path, meta))

    def test_unsafe_policy_rejected(self):
        for key, value in (("keep_per_flavor", 0), ("minimum_age_days", 0),
                           ("pinned_sha256", {"bad": "bad"})):
            with self.subTest(key=key):
                saved = self.policy[key]
                self.policy[key] = value
                with self.assertRaises(ValueError):
                    self.selected()
                self.policy[key] = saved

    def test_diagnostic_scope_and_age(self):
        old = self.root / "emufusion-old-trial.apk"
        old.write_bytes(b"old")
        os.utime(old, (self.now - 30 * 86400,) * 2)
        for name in ("unsigned.apk", "source.cpp", "lib.unstripped.so", "game.apk", "savedata.bin"):
            (self.root / name).write_bytes(b"keep")
        candidates = RETENTION.retired_diagnostics([self.root], self.now, set())
        self.assertEqual([p for p, _, _ in candidates], [old])
        self.assertEqual(RETENTION.retired_diagnostics([self.root], self.now, {str(old)}), [])

    def test_diagnostic_symlink_root_rejected(self):
        alias = self.root / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(RuntimeError):
            RETENTION.retired_diagnostics([alias], self.now, set())

    def test_nested_diagnostic_names_only_and_symlinks_not_followed(self):
        nested = self.root / "old-test"
        nested.mkdir()
        old = nested / "installed-base.apk"
        old.write_bytes(b"obsolete")
        os.utime(old, (self.now - 30 * 86400,) * 2)
        unknown = nested / "unknown.apk"
        unknown.write_bytes(b"keep")
        os.utime(unknown, (1, 1))
        (self.root / "emufusion-linked.apk").symlink_to(old)
        (self.root / "linked-directory").symlink_to(nested, target_is_directory=True)
        candidates = RETENTION.retired_diagnostics([self.root], self.now, set())
        self.assertEqual([p for p, _, _ in candidates], [old])

    def orphan(self, name="emufusion-old.apk.idsig", age=2):
        path = self.root / name
        path.write_bytes(b"disposable signature")
        os.utime(path, (self.now - age * 86400,) * 2)
        return path

    def orphans(self, opened=(), pins=()):
        return [p for p, _, _ in RETENTION.orphan_signatures(
            [self.root], self.now, opened, pins)]

    def test_stale_orphan_signature_selected(self):
        path = self.orphan()
        self.assertEqual(self.orphans(), [path])

    def test_live_apk_and_broken_symlink_preserve_signature(self):
        path = self.orphan()
        apk = path.with_suffix("")
        apk.write_bytes(b"keep")
        self.assertEqual(self.orphans(), [])
        apk.unlink()
        apk.symlink_to(self.root / "missing")
        self.assertEqual(self.orphans(), [])

    def test_orphan_age_open_and_unknown_name_guards(self):
        path = self.orphan()
        self.orphan("emufusion-new.apk.idsig", age=0)
        self.orphan("game.apk.idsig")
        self.assertEqual(self.orphans(opened={str(path)}), [])
        self.assertEqual(self.orphans(opened={str(path.with_suffix(''))}), [])

    def test_orphan_hash_pin_and_symlink_guards(self):
        digest = "a" * 64
        path = self.orphan(f"lucent-3.2.16-test-{digest}.apk.idsig")
        self.assertEqual(self.orphans(pins={digest}), [])
        target = self.root / "retained"
        path.rename(target)
        path.symlink_to(target)
        self.assertEqual(self.orphans(), [])


class RetentionExecutionTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.project = self.root / "unified-android"
        self.build = self.project / "build"
        self.build.mkdir(parents=True)
        self.policy = dict(keep_per_flavor=1, minimum_age_days=7, pinned_sha256={})
        (self.root / "release-manifest.json").write_text("{}")
        self.old = self.apk(b"old", 1)
        self.new = self.apk(b"new", 2)

    def apk(self, contents, timestamp):
        digest = RETENTION.hashlib.sha256(contents).hexdigest()
        path = self.build / f"lucent-3.2.16-test-{digest}.apk"
        path.write_bytes(contents)
        os.utime(path, (timestamp, timestamp))
        return path

    def run_cleanup(self, *args, tracked=b""):
        (self.project / "build-retention.json").write_text(json.dumps(self.policy))
        with (mock.patch.object(RETENTION, "PROJECT", self.project),
              mock.patch.object(RETENTION, "open_paths", return_value=set()),
              mock.patch.object(RETENTION.subprocess, "check_output", return_value=tracked),
              mock.patch.object(RETENTION.sys, "argv", ["prune", *args]),
              contextlib.redirect_stderr(io.StringIO()),
              contextlib.redirect_stdout(io.StringIO())):
            RETENTION.main()

    def test_dry_run_never_deletes(self):
        self.run_cleanup()
        self.assertTrue(self.old.exists())
        self.assertFalse((self.build / ".lucent-build-lock").exists())

    def test_apply_deletes_old_and_records_hash(self):
        self.run_cleanup("--apply")
        self.assertFalse(self.old.exists())
        self.assertTrue(self.new.exists())
        receipt, = (self.build / "retention-receipts").glob("*.jsonl")
        records = [json.loads(line) for line in receipt.read_text().splitlines()]
        self.assertEqual(records[-1]["files"], 1)
        self.assertEqual(records[0]["sha256"], RETENTION.hashlib.sha256(b"old").hexdigest())

    def test_tracked_file_never_deleted(self):
        tracked = str(self.old.relative_to(self.root)).encode() + b"\0"
        with self.assertRaises(RuntimeError):
            self.run_cleanup("--apply", tracked=tracked)
        self.assertTrue(self.old.exists())

    def test_existing_lock_never_stolen(self):
        lock = self.build / ".lucent-build-lock"
        lock.mkdir()
        with self.assertRaises(FileExistsError):
            self.run_cleanup("--apply")
        self.assertTrue(lock.exists())
        self.assertTrue(self.old.exists())

    def test_incorrect_hash_never_deleted(self):
        self.old.write_bytes(b"changed content")
        os.utime(self.old, (1, 1))
        with self.assertRaises(RuntimeError):
            self.run_cleanup("--apply")
        self.assertTrue(self.old.exists())

    def test_manifest_release_protected(self):
        digest = RETENTION.sha256(self.old)
        (self.root / "release-manifest.json").write_text(json.dumps(dict(companionSha256=digest)))
        self.run_cleanup("--apply")
        self.assertTrue(self.old.exists())

    def test_owning_build_lock_supported(self):
        lock = self.build / ".lucent-build-lock"
        lock.mkdir()
        (lock / "pid").write_text(str(os.getppid()))
        self.run_cleanup("--apply", "--build-lock-owner", str(os.getppid()))
        self.assertFalse(self.old.exists())
        self.assertTrue(lock.exists())

    def test_wrong_lock_owner_refused(self):
        lock = self.build / ".lucent-build-lock"
        lock.mkdir()
        (lock / "pid").write_text("0")
        with self.assertRaises(RuntimeError):
            self.run_cleanup("--apply", "--build-lock-owner", str(os.getppid()))
        self.assertTrue(self.old.exists())

    def test_build_subfolder_diagnostic_retired_with_receipt(self):
        nested = self.build / "retired-trial"
        nested.mkdir()
        diagnostic = nested / "installed-base.apk"
        diagnostic.write_bytes(b"retired")
        os.utime(diagnostic, (1, 1))
        evidence = nested / "results.json"
        evidence.write_text("{}")
        self.run_cleanup("--apply", "--retired-diagnostics")
        self.assertFalse(diagnostic.exists())
        self.assertTrue(evidence.exists())
        receipt, = (self.build / "retention-receipts").glob("*.jsonl")
        records = [json.loads(line) for line in receipt.read_text().splitlines()]
        self.assertTrue(any(r.get("path") == str(diagnostic) and
                            r["event"] == "unlinked" for r in records))

    def test_build_subfolder_diagnostic_pin_protects_actual_hash(self):
        nested = self.build / "retired-trial"
        nested.mkdir()
        diagnostic = nested / "installed-base.apk"
        diagnostic.write_bytes(b"retained baseline")
        os.utime(diagnostic, (1, 1))
        self.policy["pinned_sha256"][RETENTION.sha256(diagnostic)] = "current baseline"
        self.run_cleanup("--apply", "--retired-diagnostics")
        self.assertTrue(diagnostic.exists())

    def test_build_runs_diagnostic_retention_automatically(self):
        script = (ROOT / "unified-android/build.sh").read_text()
        self.assertIn('prune_build_apks.py" --apply --retired-diagnostics', script)

    def test_build_prunes_after_verified_publication_and_before_return(self):
        script = (ROOT / "unified-android/build.sh").read_text()
        cleanup = script.rindex('prune_build_apks.py" --apply --retired-diagnostics')
        self.assertGreater(cleanup, script.index('ln "$IMMUTABLE_TEMP" "$IMMUTABLE_OUTPUT"'))
        self.assertLess(cleanup, script.rindex('printf \'%s\\n\' "$IMMUTABLE_OUTPUT"'))
        self.assertEqual(script.count('prune_build_apks.py" --apply --retired-diagnostics'), 2)

    def test_orphan_signature_deleted_with_receipt_only_on_apply(self):
        sidecar = self.build / "lucent-3.0.0.apk.idsig"
        sidecar.write_bytes(b"signature without APK")
        os.utime(sidecar, (1, 1))
        self.run_cleanup("--retired-diagnostics")
        self.assertTrue(sidecar.exists())
        self.run_cleanup("--apply", "--retired-diagnostics")
        self.assertFalse(sidecar.exists())

    def test_tracked_orphan_signature_preserved(self):
        sidecar = self.build / "emufusion-closed.apk.idsig"
        sidecar.write_bytes(b"tracked signature")
        os.utime(sidecar, (1, 1))
        tracked = str(sidecar.relative_to(self.root)).encode() + b"\0"
        with self.assertRaises(RuntimeError):
            self.run_cleanup("--apply", "--retired-diagnostics", tracked=tracked)
        self.assertTrue(sidecar.exists())

    def closed_trial(self):
        folder = self.root / "docs/qa/closed-trial"
        folder.mkdir(parents=True)
        apk = folder / "emufusion-closed.apk"
        apk.write_bytes(b"closed diagnostic")
        sidecar = Path(str(apk) + ".idsig")
        sidecar.write_bytes(b"signature")
        (folder / "native-symbols.so").write_bytes(b"keep")
        relative = str(apk.relative_to(self.root))
        self.policy["retired_diagnostic_apks"] = {
            relative: dict(sha256=RETENTION.sha256(apk), reason="Test completed")}
        return apk, sidecar, relative

    def test_explicit_closed_trial_retires_before_age_limit_and_is_idempotent(self):
        apk, sidecar, _ = self.closed_trial()
        self.run_cleanup("--apply", "--retired-diagnostics")
        self.assertFalse(apk.exists())
        self.assertFalse(sidecar.exists())
        self.assertTrue((apk.parent / "native-symbols.so").exists())
        self.run_cleanup("--apply", "--retired-diagnostics")

    def test_closed_trial_dry_run_preserves_files(self):
        apk, sidecar, _ = self.closed_trial()
        self.run_cleanup("--retired-diagnostics")
        self.assertTrue(apk.exists())
        self.assertTrue(sidecar.exists())

    def test_closed_trial_pin_wins_including_sidecar(self):
        apk, sidecar, _ = self.closed_trial()
        self.policy["pinned_sha256"][RETENTION.sha256(apk)] = "Still installed"
        self.run_cleanup("--apply", "--retired-diagnostics")
        self.assertTrue(apk.exists())
        self.assertTrue(sidecar.exists())

    def test_custom_named_trial_requires_explicit_path_and_hash(self):
        apk, sidecar, relative = self.closed_trial()
        custom = apk.with_name("flow-export.apk")
        custom_sidecar = Path(str(custom) + ".idsig")
        apk.rename(custom)
        sidecar.rename(custom_sidecar)
        # Age alone must never retire custom names or their signing sidecars.
        os.utime(custom, (1, 1))
        os.utime(custom_sidecar, (1, 1))
        self.run_cleanup("--apply", "--retired-diagnostics")
        self.assertTrue(custom.exists())
        self.assertTrue(custom_sidecar.exists())
        entry = self.policy["retired_diagnostic_apks"].pop(relative)
        self.policy["retired_diagnostic_apks"][str(custom.relative_to(self.root))] = entry
        self.run_cleanup("--apply", "--retired-diagnostics")
        self.assertFalse(custom.exists())
        self.assertFalse(custom_sidecar.exists())
        self.assertTrue((custom.parent / "native-symbols.so").exists())

    def test_custom_named_trial_pin_still_wins(self):
        apk, sidecar, relative = self.closed_trial()
        custom = apk.with_name("capture.apk")
        apk.rename(custom)
        sidecar.rename(Path(str(custom) + ".idsig"))
        entry = self.policy["retired_diagnostic_apks"].pop(relative)
        self.policy["retired_diagnostic_apks"][str(custom.relative_to(self.root))] = entry
        self.policy["pinned_sha256"][entry["sha256"]] = "Required rollback"
        self.run_cleanup("--apply", "--retired-diagnostics")
        self.assertTrue(custom.exists())
        self.assertTrue(Path(str(custom) + ".idsig").exists())

    def test_closed_trial_hash_mismatch_preserves_apk_and_sidecar(self):
        apk, sidecar, _ = self.closed_trial()
        apk.write_bytes(b"different build")
        with self.assertRaises(RuntimeError):
            self.run_cleanup("--apply", "--retired-diagnostics")
        self.assertTrue(apk.exists())
        self.assertTrue(sidecar.exists())

    def test_closed_trial_rejects_path_escape_unknown_name_and_invalid_hash(self):
        apk, _, relative = self.closed_trial()
        valid = self.policy["retired_diagnostic_apks"][relative]
        for path, entry in (("../outside.apk", valid), (str(apk), valid),
                            ("source/emufusion-closed.apk", valid),
                            ("docs/qa/game.rom", valid),
                            (relative, dict(sha256="bad", reason="closed"))):
            self.policy["retired_diagnostic_apks"] = {path: entry}
            with self.subTest(path=path, entry=entry), self.assertRaises(ValueError):
                self.run_cleanup("--apply", "--retired-diagnostics")
        self.assertTrue(apk.exists())

    def test_closed_trial_symlink_refused(self):
        apk, _, _ = self.closed_trial()
        target = apk.with_suffix(".saved")
        apk.rename(target)
        apk.symlink_to(target)
        with self.assertRaises(RuntimeError):
            self.run_cleanup("--apply", "--retired-diagnostics")
        self.assertTrue(target.exists())

    def test_closed_trial_open_sidecar_preserves_pair(self):
        apk, sidecar, _ = self.closed_trial()
        self.assertEqual(RETENTION.completed_diagnostics(
            self.root, [self.root / "docs/qa"], self.policy, {str(sidecar)}), [])

    def test_closed_old_trial_is_not_deleted_twice(self):
        apk, sidecar, _ = self.closed_trial()
        os.utime(apk, (1, 1))
        self.run_cleanup("--apply", "--retired-diagnostics")
        self.assertFalse(apk.exists())
        self.assertFalse(sidecar.exists())


if __name__ == "__main__":
    unittest.main()
