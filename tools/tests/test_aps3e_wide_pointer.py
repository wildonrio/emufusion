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

ROOT = Path(__file__).resolve().parents[2]
QA = ROOT / 'docs/qa/android-portability-2026-10-06-ps3-wide-pointer'
spec = importlib.util.spec_from_file_location('wide_prepare', QA / 'prepare.py')
PREPARE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(PREPARE)


class WidePointerTests(unittest.TestCase):
    def test_normal_build_records_the_exact_tested_full_address_patch(self):
        patch = ROOT / 'engines/patches/aps3e-android-full-address-atomic-ptr.patch'
        self.assertEqual(patch.read_bytes(), (QA / 'wide-pointer.patch').read_bytes())
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

    def test_patch_roundtrip_matches_actual_candidate_headers(self):
        with tempfile.TemporaryDirectory(prefix='aps3e-wide-roundtrip-') as temp:
            root = Path(temp)
            prefix = root / 'app/src/main/cpp/rpcs3'
            for name in PREPARE.HASHES:
                original = (PREPARE.SOURCE / name).read_bytes()
                path = prefix / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(original)
            patch = QA / 'wide-pointer.patch'
            subprocess.run(['git', 'apply', '--unsafe-paths', str(patch)], cwd=root, check=True)
            for name in PREPARE.HASHES:
                self.assertEqual((prefix / name).read_text(),
                    PREPARE.transform(name, (PREPARE.SOURCE / name).read_text()))
            subprocess.run(['git', 'apply', '--unsafe-paths', '--reverse', str(patch)], cwd=root, check=True)
            for name in PREPARE.HASHES:
                self.assertEqual((prefix / name).read_bytes(), (PREPARE.SOURCE / name).read_bytes())

    def test_actual_headers_old_failure_wide_pass_nonandroid_regression(self):
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
