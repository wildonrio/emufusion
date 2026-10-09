#!/usr/bin/env python3
"""CI entry point for tools/tests (python3 -m unittest discover -s tools/tests).

Some tests read inputs that exist only on the build Mac and are deliberately
not committed: compiled engine trees (engines/build), QA evidence (docs/qa,
.evidence-*), local experiments, build outputs, and sibling source checkouts
such as ~/Code/cemu. On a clean runner a test that errors only because such an
input is missing is reported as skipped, with the missing path; every other
error or failure still fails the run. Locally, where the inputs exist, these
tests run normally.

usage: run_ci_tests.py [unittest discover args, default: -s tools/tests]
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ONLY = ('engines/build/', 'docs/qa/', '/.evidence', 'experiments/',
              'unified-android/build/', 'android-companion/build/', 'dist/',
              '/Code/cemu/', '/Code/eden/', '/Code/rpcs3/')
MISSING = re.compile(r"(?:FileNotFoundError|NotADirectoryError): \[Errno \d+\] "
                     r"No such file or directory: '([^']+)'")


def local_only(path):
    return any(marker in path for marker in LOCAL_ONLY)


def missing_local_input(err):
    """The local-only path whose absence caused this error, if that is all it was."""
    exc, seen = err[1], set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, (FileNotFoundError, NotADirectoryError)):
            name = str(exc.filename or '')
            return name if local_only(name) else None
        if isinstance(exc, ImportError):
            # A module that failed to import is reported by the loader with the
            # original traceback folded into the message.
            found = MISSING.findall(str(exc))
            if found and all(local_only(path) for path in found):
                return found[-1]
            return None
        exc = exc.__cause__ or exc.__context__
    return None


class LocalInputAwareResult(unittest.TextTestResult):
    def addError(self, test, err):
        missing = missing_local_input(err)
        if missing:
            self.addSkip(test, 'local-only input absent: ' + missing)
        else:
            super().addError(test, err)

    def addSubTest(self, test, subtest, err):
        missing = err is not None and not issubclass(err[0], test.failureException) \
            and missing_local_input(err)
        if missing:
            self.addSkip(subtest, 'local-only input absent: ' + missing)
        else:
            super().addSubTest(test, subtest, err)


def main(argv):
    # Like "python3 -m unittest" from the repository root: tests import
    # tools.tests.* helpers, so the root must be importable.
    sys.path.insert(0, str(ROOT))
    args = argv or ['-s', 'tools/tests']
    start = args[args.index('-s') + 1] if '-s' in args else 'tools/tests'
    pattern = args[args.index('-p') + 1] if '-p' in args else 'test*.py'
    suite = unittest.defaultTestLoader.discover(str(ROOT / start), pattern=pattern,
                                                top_level_dir=str(ROOT / start))
    runner = unittest.TextTestRunner(resultclass=LocalInputAwareResult, verbosity=1)
    result = runner.run(suite)
    skipped_local = sum(1 for _, reason in result.skipped if reason.startswith('local-only input absent'))
    print('local-only inputs absent (skipped): %d' % skipped_local)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
