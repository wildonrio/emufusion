"""Full-header regression: real atomics, refcounts, queues and wait implementation."""
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools.tests import aps3e_locked_source as locked

ROOT = Path(__file__).resolve().parents[2]
QA = ROOT / 'docs/qa/android-portability-2026-10-06-ps3-wide-pointer'
PATCH = ROOT / 'engines/patches/aps3e-android-full-address-atomic-ptr.patch'
PREPARE = None
if (QA / 'prepare.py').is_file():
    spec = importlib.util.spec_from_file_location('wide_prepare', QA / 'prepare.py')
    PREPARE = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(PREPARE)


class WidePointerTests(unittest.TestCase):
    @unittest.skipUnless((QA / 'wide-pointer.patch').is_file(),
                         'archived tested candidate patch absent: ' + str(QA / 'wide-pointer.patch'))
    def test_normal_build_patch_is_the_archived_tested_candidate(self):
        self.assertEqual(PATCH.read_bytes(), (QA / 'wide-pointer.patch').read_bytes())

    def test_normal_build_records_the_exact_tested_full_address_patch(self):
        patch = PATCH
        lock = json.loads((ROOT / 'engines/aps3e-source-lock.json').read_text())
        paths = [p['path'] for p in lock['patches']]
        name = str(patch.relative_to(ROOT))
        self.assertEqual(paths.count(name), 1)
        self.assertLess(paths.index('engines/patches/aps3e-android-tagged-atomic-ptr.patch'),
                        paths.index(name))
        entry = lock['patches'][paths.index(name)]
        self.assertEqual(entry['sha256'], hashlib.sha256(patch.read_bytes()).hexdigest())
        self.assertEqual(entry['bytes'], patch.stat().st_size)
        build = lock['latestPortabilityRebuild']
        self.assertEqual(build['compileProfile']['coreTranslationUnits'], 467)
        self.assertFalse(build['deviceQualified'])
        self.assertFalse(build['traceEnabled'])
        self.assertIn('ICO still stalls', build['limitations'])

    @unittest.skipUnless(PREPARE is not None and locked.available(),
                         'closed diagnostic or pinned aPS3e archive absent')
    def test_patch_roundtrip_matches_actual_candidate_headers(self):
        # The headers as the patch finds them: the pinned archive with the
        # earlier locked patches, byte for byte the diagnostic's pinned inputs.
        source = locked.state_before(str(PATCH.relative_to(ROOT)), extra=tuple(
            'app/src/main/cpp/rpcs3/' + name for name in PREPARE.HASHES)) / 'app/src/main/cpp/rpcs3'
        for name, expected in PREPARE.HASHES.items():
            self.assertEqual(hashlib.sha256((source / name).read_bytes()).hexdigest(), expected, name)
        with tempfile.TemporaryDirectory(prefix='aps3e-wide-roundtrip-') as temp:
            root = Path(temp)
            prefix = root / 'app/src/main/cpp/rpcs3'
            for name in PREPARE.HASHES:
                original = (source / name).read_bytes()
                path = prefix / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(original)
            subprocess.run(['git', 'apply', '--unsafe-paths', str(PATCH)], cwd=root, check=True)
            for name in PREPARE.HASHES:
                self.assertEqual((prefix / name).read_text(),
                    PREPARE.transform(name, (source / name).read_text()))
            subprocess.run(['git', 'apply', '--unsafe-paths', '--reverse', str(PATCH)], cwd=root, check=True)
            for name in PREPARE.HASHES:
                self.assertEqual((prefix / name).read_bytes(), (source / name).read_bytes())

    def test_actual_headers_old_failure_wide_pass_nonandroid_regression(self):
        if not (QA / 'pointer_test.cpp').is_file():
            self.skipTest('local-only input absent: ' + str(QA / 'pointer_test.cpp'))
        spec = importlib.util.spec_from_file_location('wide_build_test', QA / 'build_test.py')
        module = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(QA))
        try: spec.loader.exec_module(module)
        finally: sys.path.pop(0)
        with tempfile.TemporaryDirectory(prefix='aps3e-wide-headers-') as temp:
            for variant, code in [('old', 3), ('wide', 0), ('nonandroid', 0)]:
                with self.subTest(variant=variant):
                    binary = module.build(Path(temp) / variant, variant)
                    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=60,
                        env=dict(os.environ, ASAN_OPTIONS='halt_on_error=1', UBSAN_OPTIONS='halt_on_error=1'))
                    self.assertEqual(result.returncode, code, result.stderr)
                    self.assertIn('old-codec-rejected' if code else 'tests passed', result.stdout)
                    self.assertEqual(result.stderr, '')


if __name__ == '__main__': unittest.main()
