import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[2] / 'unified-android/tools'
sys.path.insert(0, str(TOOLS))
SPEC = importlib.util.spec_from_file_location('rife_cleanup', TOOLS / 'cleanup_retired_rife_objects.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class RetiredRifeObjectsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.app = Path(tmp.name).resolve() / 'app'
        self.app.mkdir()
        self.old = self.config('old', M.CUTOFF - 400)
        self.new = self.config('new', M.CUTOFF - 200)
        mock = patch.object(M.subprocess, 'check_output', return_value='ELF, with debug_info, not stripped')
        mock.start()
        self.addCleanup(mock.stop)

    def config(self, name, when):
        abi = self.app / '.cxx/Debug' / name / 'arm64-v8a'
        abi.mkdir(parents=True)
        for file in ('CMakeCache.txt', 'build.ninja', 'unit.o', 'libunit.a', 'source.cpp'):
            path = abi / file
            path.write_text(file)
            os.utime(path, (when, when))
        so = self.app / 'build/intermediates/cxx/Debug' / name / 'obj/arm64-v8a/librife_benchmark.so'
        so.parent.mkdir(parents=True)
        so.write_text('ELF')
        return abi

    def test_only_old_objects_selected_and_libraries_retained(self):
        plan, retained = M.select(self.app)
        self.assertEqual([p for p, _ in plan], [self.old / 'unit.o'])
        self.assertIn(self.old / 'libunit.a', retained)
        self.assertTrue(any(p.name == 'librife_benchmark.so' for p in retained))
        self.assertNotIn(self.old / 'source.cpp', [p for p, _ in plan])

    def test_open_benchmark_refused(self):
        with self.assertRaises(RuntimeError):
            M.select(self.app, opened=[str(self.old / 'build.ninja')])

    def test_tracked_object_refused(self):
        with self.assertRaises(RuntimeError):
            M.select(self.app, tracked=[str(self.old / 'unit.o')])

    def test_recent_object_skips_whole_configuration(self):
        os.utime(self.old / 'unit.o', (M.CUTOFF + 1, M.CUTOFF + 1))
        self.assertEqual(M.select(self.app)[0], [])

    def test_missing_final_library_keeps_objects(self):
        for p in (self.app / 'build/intermediates/cxx/Debug/old').rglob('*.so'):
            p.unlink()
        self.assertEqual(M.select(self.app)[0], [])

    def test_symlink_refused(self):
        p = self.old / 'unit.o'
        p.unlink()
        p.symlink_to(self.new / 'unit.o')
        with self.assertRaises(RuntimeError):
            M.select(self.app)

    def test_stripped_final_library_refused(self):
        with patch.object(M.subprocess, 'check_output', return_value='ELF, stripped'):
            with self.assertRaises(RuntimeError):
                M.select(self.app)

    def test_static_archive_scope_keeps_newest_cache_and_symbols(self):
        plan, retained = M.static_archive_plan(self.app)
        self.assertEqual([p for p, _ in plan], [self.old / 'libunit.a'])
        self.assertTrue(any(p.name == 'librife_benchmark.so' for p in retained))
        self.assertNotIn(self.old / 'source.cpp', [p for p, _ in plan])
        self.assertTrue((self.new / 'libunit.a').exists())

    def test_static_archive_tracked_or_existing_output_refused(self):
        with self.assertRaises(RuntimeError):
            M.static_archive_plan(self.app, tracked=[str(self.old / 'libunit.a')])
        for suffix in ('.gz', '.gz.partial'):
            output = self.old / ('libunit.a' + suffix)
            output.touch()
            with self.assertRaises(RuntimeError):
                M.static_archive_plan(self.app)
            output.unlink()

    def test_static_archive_roundtrip_and_repeat_selection(self):
        import gzip
        plan, retained = M.static_archive_plan(self.app)
        path, meta = plan[0]
        original = path.read_bytes()
        with tempfile.TemporaryFile(mode='w+') as receipt:
            M.archive(path, meta, receipt, lambda: set())
        self.assertFalse(path.exists())
        self.assertEqual(gzip.decompress(path.with_suffix('.a.gz').read_bytes()), original)
        self.assertEqual(M.static_archive_plan(self.app)[0], [])
        self.assertTrue(all(p.exists() for p in retained))
        self.assertTrue((self.new / 'libunit.a').exists())

    def test_static_archive_open_and_recent_inputs_protected(self):
        with self.assertRaises(RuntimeError):
            M.static_archive_plan(self.app, opened=[str(self.old / 'build.ninja')])
        os.utime(self.old / 'libunit.a', (M.CUTOFF + 1, M.CUTOFF + 1))
        self.assertEqual(M.static_archive_plan(self.app)[0], [])


if __name__ == '__main__':
    unittest.main()
