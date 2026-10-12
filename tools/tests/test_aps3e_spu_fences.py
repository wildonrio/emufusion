"""Ordering-transform scope and reproducible patch, not a gameplay acceptance test."""
import difflib
import hashlib
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.tests import aps3e_locked_source as locked

ROOT = Path(__file__).resolve().parents[2]
QA = ROOT / 'docs/qa/android-portability-2026-10-06-ps3-spu-fences'
m = None


@unittest.skipUnless((QA / 'prepare.py').is_file() and locked.available(),
                     'closed diagnostic or pinned aPS3e archive absent')
class SpuFencesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The diagnostic was reviewed against SPUThread.cpp as it stands before
        # the SPURS argument-map patch (its docs/qa snapshot is gone); rebuild
        # those exact bytes from the pinned archive and the locked patches.
        global m
        spec = importlib.util.spec_from_file_location('spu_fences', QA / 'prepare.py')
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        m.SOURCE = locked.state_before('engines/patches/aps3e-spurs-thread-argument-map.patch') / \
            'app/src/main/cpp/rpcs3/rpcs3/Emu/Cell/SPUThread.cpp'

    def test_rebuilt_source_is_the_reviewed_input(self):
        self.assertEqual(hashlib.sha256(m.SOURCE.read_bytes()).hexdigest(), m.SOURCE_SHA)

    def test_scope_no_decoder_config_or_hash_predicate_change(self):
        old = m.SOURCE.read_text()
        new = m.transform(old)
        self.assertEqual(new.count('atomic_fence_acquire();'), old.count('atomic_fence_acquire();') + 2)
        self.assertEqual(new.count('rdata_fence()'), 9)
        predicate = 'return compute_rdata_hash32(*vm::get_super_ptr<decltype(rdata)>(addr)) == hash;'
        self.assertEqual(new.count(predicate), old.count(predicate))
        self.assertIn('cmp_rdata(rdata, data) && rdata_fence() && res == new_time', new)
        self.assertIn('return !res && rdata_fence();', new)

    def test_reapply_or_changed_source_is_rejected(self):
        old = m.SOURCE.read_text()
        with self.assertRaises(AssertionError):
            m.transform(m.transform(old))
        with self.assertRaises(AssertionError):
            m.transform(old.replace('if (this_time == res && cmp_rdata(rdata, data))', 'if (false)'))

    def test_patch_forward_reverse_exact(self):
        old = m.SOURCE.read_text()
        new = m.transform(old)
        patch = ''.join(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
            fromfile='a/SPUThread.cpp', tofile='b/SPUThread.cpp'))
        with tempfile.TemporaryDirectory(prefix='spu-fences-roundtrip-') as temp:
            root = Path(temp)
            path = root / 'SPUThread.cpp'
            path.write_text(old)
            for args, expected in (([], new), (['--reverse'], old)):
                subprocess.run(['git', 'apply', '--unsafe-paths', *args], cwd=root,
                    input=patch, text=True, check=True, capture_output=True)
                self.assertEqual(path.read_text(), expected)


if __name__ == '__main__':
    unittest.main()
