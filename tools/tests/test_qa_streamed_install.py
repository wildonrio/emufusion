"""Keep QA APK replacements off Android's failed incremental-install path.

Evaluate the actual install-call expressions, without connecting to a device.
This verifies command selection, not preservation of private app data by Android.
"""
import ast
import hashlib
from pathlib import Path
import re
import subprocess
import tempfile
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[2]
RUNNERS = ROOT / "unified-android/tools"
EXPECTED = {
    "run_phase1a_activity_qa.py",
    "run_phase2_activity_qa.py",
    "run_runtime_acceptance_qa.py",
    "run_library_a_button_qa.py",
    "run_phase1_physical_library_qa.py",
}


class StreamedInstallTest(unittest.TestCase):
    def test_all_runner_install_calls_execute_with_explicit_streamed_replacement(self):
        found = set()
        for path in sorted(RUNNERS.glob("run_*qa.py")):
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = (node.func.attr if isinstance(node.func, ast.Attribute)
                        else node.func.id if isinstance(node.func, ast.Name) else "")
                if name != "adb" or not any(
                        isinstance(arg, ast.Constant) and arg.value == "install"
                        for arg in node.args):
                    continue
                found.add(path.name)
                with self.subTest(runner=path.name, line=node.lineno):
                    calls = []
                    capture = lambda *args, **kwargs: calls.append((args, kwargs))
                    # These are literal QA installer expressions, not module
                    # imports/main(): no build, permission grant or ADB runs.
                    namespace = {
                        "adb": capture, "qa": SimpleNamespace(adb=capture),
                        "adb_path": Path("/fake/adb"), "serial": "test-device",
                        "apk": Path("/candidate with spaces.apk"),
                        "args": SimpleNamespace(adb=Path("/fake/adb"), serial="test-device"),
                    }
                    eval(compile(ast.Expression(node), str(path), "eval"), namespace)
                    self.assertEqual(len(calls), 1)
                    arguments, options = calls[0]
                    install = arguments[arguments.index("install"):]
                    self.assertEqual(install.count("--no-incremental"), 1)
                    self.assertIn("-r", install)
                    self.assertNotIn("--incremental", install)
                    self.assertNotIn("-g", install)
                    self.assertEqual(install[-1], "/candidate with spaces.apk")
                    self.assertNotEqual(options.get("check"), False)
                    if path.name == "run_runtime_acceptance_qa.py":
                        self.assertNotIn("-d", install)
        self.assertEqual(found, EXPECTED)


class ExactInstallVerificationTest(unittest.TestCase):
    def execute(self, *, package_present=True, wrong_payload=False,
                read_failed=False, perform_install=True, wrong_expected=False,
                before_present=True, before_identity=None, after_identity=None,
                final_present=True, final_path=None, install_failure=False,
                final_identity=None, before_path=None):
        path = RUNNERS / "run_runtime_acceptance_qa.py"
        tree = ast.parse(path.read_text(), filename=str(path))
        function = next(node for node in tree.body
                        if isinstance(node, ast.FunctionDef) and node.name == "exact_install")
        calls = []
        reads = []
        payload = b"isolated fake APK payload"
        original = "    userId=10205\n      firstInstallTime=2026-09-09 00:10:20\n"
        before_identity = original if before_identity is None else before_identity
        after_identity = original if after_identity is None else after_identity
        path_reads = 0
        identity_reads = 0

        def fake_adb(adb, serial, *args):
            nonlocal path_reads, identity_reads
            calls.append(args)
            if args[0] == "install":
                if install_failure:
                    raise RuntimeError("reported installer failure")
                return SimpleNamespace(stdout="Success\n")
            if args == ("shell", "pm", "path", "com.thorium.preview"):
                path_reads += 1
                present = (before_present if path_reads == 1 else
                           package_present if path_reads == 2 else final_present)
                name = (before_path if path_reads == 1 and before_path else
                        final_path if path_reads == 3 and final_path else "/data/app/test/base.apk")
                return SimpleNamespace(stdout=f"package:{name}\n" if present else "")
            self.assertEqual(args, ("shell", "dumpsys", "package", "com.thorium.preview"))
            identity_reads += 1
            return SimpleNamespace(stdout=(before_identity if identity_reads == 1 else
                final_identity if identity_reads == 3 and final_identity is not None else after_identity))

        def fake_read(command, *, stdout, stderr):
            reads.append(command)
            self.assertEqual(command, ["/fake/adb", "-s", "test-device", "exec-out", "cat",
                                       "/data/app/test/base.apk"])
            stdout.write(b"wrong payload" if wrong_payload else payload)
            return SimpleNamespace(returncode=1 if read_failed else 0)

        namespace = {
            "Path": Path, "PACKAGE": "com.thorium.preview", "qa": SimpleNamespace(adb=fake_adb),
            "subprocess": SimpleNamespace(run=fake_read, PIPE=subprocess.PIPE),
            "sha256_file": lambda target: hashlib.sha256(target.read_bytes()).hexdigest(),
            "re": re,
        }
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"), namespace)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            apk = output / "candidate.apk"
            apk.write_bytes(payload)
            expected = "0" * 64 if wrong_expected else hashlib.sha256(payload).hexdigest()
            error = None
            result = None
            try:
                result = namespace["exact_install"](Path("/fake/adb"), "test-device", apk,
                                                      expected, output, perform_install)
            except RuntimeError as exception:
                error = str(exception)
            if calls:
                self.assertTrue((output / "package-before-path.txt").exists())
        # No uninstall/clear/permission grant/retry is possible in this verifier.
        self.assertTrue(all(call[0] in {"install", "shell"} for call in calls))
        self.assertLessEqual(sum(call[0] == "install" for call in calls), 1)
        return result, error, calls, reads

    def test_reported_success_with_disappearing_package_fails_without_retry(self):
        result, error, calls, reads = self.execute(package_present=False)
        self.assertIsNone(result)
        self.assertIn("path was not found", error)
        self.assertEqual(next(call for call in calls if call[0] == "install")[:3],
                         ("install", "--no-incremental", "-r"))
        self.assertEqual(reads, [])

    def test_missing_existing_package_never_attempts_a_fresh_install(self):
        result, error, calls, reads = self.execute(before_present=False)
        self.assertIsNone(result)
        self.assertIn("path was not found", error)
        self.assertFalse(any(call[0] == "install" for call in calls))
        self.assertEqual(reads, [])

    def test_ambiguous_existing_package_stops_before_install(self):
        result, error, calls, reads = self.execute(before_path=(
            "/data/app/one/base.apk\npackage:/data/app/two/base.apk"))
        self.assertIsNone(result)
        self.assertIn("ambiguous", error)
        self.assertFalse(any(call[0] == "install" for call in calls))
        self.assertEqual(reads, [])

    def test_missing_or_ambiguous_identity_stops_before_install(self):
        for report in ("", "userId=10205\n", "firstInstallTime=today\n",
                       "userId=10205\nfirstInstallTime=\n",
                       "userId=10205\nuserId=10206\nfirstInstallTime=today\n",
                       "userId=10205\nfirstInstallTime=today\nfirstInstallTime=yesterday\n"):
            with self.subTest(report=report):
                result, error, calls, reads = self.execute(before_identity=report)
                self.assertIsNone(result)
                self.assertIn("cannot establish", error)
                self.assertFalse(any(call[0] == "install" for call in calls))
                self.assertEqual(reads, [])

    def test_new_uid_or_first_install_time_rejects_apparent_success(self):
        for report in (
                "userId=10206\nfirstInstallTime=2026-09-09 00:10:20\n",
                "userId=10205\nfirstInstallTime=2026-09-11 14:03:15\n",
                "userId=10206\nfirstInstallTime=2026-09-11 14:03:15\n"):
            with self.subTest(report=report):
                result, error, calls, reads = self.execute(after_identity=report)
                self.assertIsNone(result)
                self.assertIn("identity changed", error)
                self.assertEqual(sum(call[0] == "install" for call in calls), 1)
                self.assertEqual(reads, [])

    def test_missing_identity_after_success_does_not_retry(self):
        result, error, calls, reads = self.execute(after_identity="")
        self.assertIsNone(result)
        self.assertIn("cannot establish", error)
        self.assertEqual(sum(call[0] == "install" for call in calls), 1)
        self.assertEqual(reads, [])

    def test_changed_last_update_time_is_an_ordinary_replacement(self):
        result, error, _, _ = self.execute(after_identity=(
            "userId=10205\nfirstInstallTime=2026-09-09 00:10:20\n"
            "lastUpdateTime=2026-09-11 14:03:15\n"))
        self.assertIsNone(error)
        self.assertEqual(result["packageIdentityBefore"], result["packageIdentityAfter"])
        self.assertFalse(result["privateDataRetentionVerified"])

    def test_installer_failure_does_not_retry(self):
        result, error, calls, reads = self.execute(install_failure=True)
        self.assertIsNone(result)
        self.assertIn("installer failure", error)
        self.assertEqual(sum(call[0] == "install" for call in calls), 1)
        self.assertEqual(reads, [])

    def test_android16_app_id_preserves_exact_identity_verification(self):
        report = "appId=10205\nfirstInstallTime=2026-09-09 00:10:20\n"
        result, error, _, reads = self.execute(before_identity=report, after_identity=report)
        self.assertIsNone(error)
        self.assertEqual(result["packageIdentityAfter"]["uid"], 10205)
        self.assertEqual(len(reads), 1)
        _, error, calls, _ = self.execute(before_identity="userId=10206\n" + report)
        self.assertIn("cannot establish", error)
        self.assertFalse(any(call[0] == "install" for call in calls))

    def test_package_loss_during_apk_read_is_not_success(self):
        result, error, calls, reads = self.execute(final_present=False)
        self.assertIsNone(result)
        self.assertIn("path was not found", error)
        self.assertEqual(sum(call[0] == "install" for call in calls), 1)
        self.assertEqual(len(reads), 1)

    def test_package_replaced_during_apk_read_is_not_success(self):
        result, error, _, reads = self.execute(final_path="/data/app/replaced/base.apk")
        self.assertIsNone(result)
        self.assertIn("changed during APK verification", error)
        self.assertEqual(len(reads), 1)

    def test_identity_reset_during_apk_read_is_not_success(self):
        result, error, _, reads = self.execute(final_identity=(
            "userId=10206\nfirstInstallTime=2026-09-11 14:03:15\n"))
        self.assertIsNone(result)
        self.assertIn("changed during APK verification", error)
        self.assertEqual(len(reads), 1)

    def test_installed_payload_must_match_candidate(self):
        result, error, _, _ = self.execute(wrong_payload=True)
        self.assertIsNone(result)
        self.assertIn("differs from candidate", error)

    def test_unreadable_installed_apk_is_not_success(self):
        result, error, _, _ = self.execute(read_failed=True)
        self.assertIsNone(result)
        self.assertIn("cannot read installed", error)

    def test_verified_install_reports_both_hashes(self):
        result, error, _, _ = self.execute()
        self.assertIsNone(error)
        self.assertEqual(result["installedSha256"], result["candidateSha256"])
        self.assertTrue(result["replacementInstallPerformed"])

    def test_skip_install_still_verifies_without_mutation(self):
        result, error, calls, reads = self.execute(perform_install=False)
        self.assertIsNone(error)
        self.assertFalse(result["replacementInstallPerformed"])
        self.assertFalse(any(call[0] == "install" for call in calls))
        self.assertEqual(len(reads), 1)

    def test_wrong_local_candidate_stops_before_adb(self):
        result, error, calls, reads = self.execute(wrong_expected=True)
        self.assertIsNone(result)
        self.assertIn("candidate SHA mismatch", error)
        self.assertEqual(calls, [])
        self.assertEqual(reads, [])


if __name__ == "__main__":
    unittest.main()
