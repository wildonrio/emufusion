"""tools/run_ci_tests.py skips only errors caused by absent local-only inputs."""
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('run_ci_tests', ROOT / 'tools/run_ci_tests.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def err(exc):
    try:
        raise exc
    except BaseException:
        return sys.exc_info()


class RunCiTestsTest(unittest.TestCase):
    def test_missing_local_only_inputs_are_skipped(self):
        for path in ('/home/runner/work/x/x/engines/build/sources/aps3e/a.cpp',
                     '/home/runner/work/x/x/docs/qa/run/finished.json',
                     '/home/runner/work/x/x/.evidence-n64/trace.json',
                     '/home/runner/work/x/x/experiments/rife/model.bin',
                     '/Users/tyleryoung/Code/cemu/Cemu-0.5/src/Cafe/CafeSystem.cpp'):
            error = FileNotFoundError(2, 'No such file or directory', path)
            self.assertEqual(path, runner.missing_local_input(err(error)), path)

    def test_missing_tracked_files_still_fail(self):
        error = FileNotFoundError(2, 'No such file or directory',
                                  '/home/runner/work/x/x/unified-android/src/Missing.java')
        self.assertIsNone(runner.missing_local_input(err(error)))

    def test_chained_missing_input_is_found(self):
        try:
            try:
                raise FileNotFoundError(2, 'No such file or directory', '/r/engines/build/a.so')
            except FileNotFoundError as cause:
                raise RuntimeError('probe failed') from cause
        except RuntimeError:
            info = sys.exc_info()
        self.assertEqual('/r/engines/build/a.so', runner.missing_local_input(info))

    def test_module_import_failures(self):
        local = ImportError("Failed to import test module: t\nTraceback...\n"
                            "FileNotFoundError: [Errno 2] No such file or directory: '/r/docs/qa/x.json'\n")
        self.assertEqual('/r/docs/qa/x.json', runner.missing_local_input(err(local)))
        dependency = ImportError("Failed to import test module: t\nModuleNotFoundError: No module named 'numpy'")
        self.assertIsNone(runner.missing_local_input(err(dependency)))

    def test_assertion_failures_are_never_skipped(self):
        self.assertIsNone(runner.missing_local_input(err(AssertionError('engines/build/x'))))


if __name__ == '__main__':
    unittest.main()
