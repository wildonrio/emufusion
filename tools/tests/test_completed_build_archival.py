"""Safety checks for lossless archival of completed PS2 compiler outputs."""
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

TOOLS = Path(__file__).resolve().parents[2] / 'unified-android/tools'
sys.path.insert(0, str(TOOLS))
SPEC = importlib.util.spec_from_file_location(
    'completed_archival', TOOLS / 'archive_retired_ps3_intermediates.py')
ARCHIVE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ARCHIVE)
sys.path.pop(0)


class CompletedBuildArchivalTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()

    def fixture(self, trial=0):
        name, core = ARCHIVE.COMPLETED_PS2[trial]
        folder = self.root / name
        out = folder / 'work' / core / 'out'
        out.mkdir(parents=True)
        path = out / 'libstatic.a'
        path.write_bytes(b'exact recoverable contents\0' * 400)
        return folder, out, path

    def selected(self, opened=()):
        return [p for p, _ in ARCHIVE.completed_ps2_archives(self.root, opened)]

    def test_exact_three_roots_and_static_archives_only(self):
        expected = []
        for i in range(3):
            folder, out, path = self.fixture(i)
            expected.append(path)
            for name in ('core.so', 'core.unstripped.so', 'source.cpp', 'savedata.bin'):
                (out / name).write_bytes(b'preserve')
            (folder / 'outside-output.a').write_bytes(b'preserve')
        unknown = self.root / 'armsx2-current/work/out'
        unknown.mkdir(parents=True)
        (unknown / 'current.a').write_bytes(b'preserve')
        self.assertEqual(self.selected(), sorted(expected))

    def test_any_open_file_in_trial_preserves_its_archives(self):
        folder, _, _ = self.fixture()
        self.assertEqual(self.selected({str(folder / 'arm64-v8a/core.so')}), [])

    def test_symlink_output_root_rejected(self):
        _, out, _ = self.fixture()
        moved = out.with_name('retained')
        out.rename(moved)
        out.symlink_to(moved, target_is_directory=True)
        with self.assertRaises(RuntimeError):
            self.selected()

    def test_symlink_archive_preserved_without_following(self):
        _, _, path = self.fixture()
        saved = path.with_suffix('.saved')
        path.rename(saved)
        path.symlink_to(saved)
        self.assertEqual(self.selected(), [])
        self.assertTrue(path.is_symlink())
        self.assertTrue(saved.exists())

    def archive(self, path, opened=lambda: set(), meta=None):
        with (self.root / 'receipt.jsonl').open('w') as receipt:
            return ARCHIVE.archive(path, meta or path.lstat(), receipt, opened)

    def test_byte_exact_recovery_receipt_and_idempotent_selection(self):
        _, _, path = self.fixture()
        original = path.read_bytes()
        self.assertGreater(self.archive(path), 0)
        self.assertFalse(path.exists())
        self.assertEqual(gzip.decompress(path.with_suffix('.a.gz').read_bytes()), original)
        records = [json.loads(line) for line in
                   (self.root / 'receipt.jsonl').read_text().splitlines()]
        self.assertEqual(records[0]['sha256'], hashlib.sha256(original).hexdigest())
        self.assertEqual(records[1]['event'], 'removed_uncompressed_copy')
        self.assertEqual(self.selected(), [])

    def test_changed_input_is_not_removed(self):
        _, _, path = self.fixture()
        before = path.lstat()
        path.write_bytes(b'changed')
        with self.assertRaises(RuntimeError):
            self.archive(path, meta=before)
        self.assertEqual(path.read_bytes(), b'changed')

    def test_archive_collision_preserves_both_files(self):
        _, _, path = self.fixture()
        target = path.with_suffix('.a.gz')
        target.write_bytes(b'prior archive')
        with self.assertRaises(RuntimeError):
            self.archive(path)
        self.assertTrue(path.exists())
        self.assertEqual(target.read_bytes(), b'prior archive')

    def test_opened_during_compression_does_not_remove_original(self):
        _, _, path = self.fixture()
        with self.assertRaises(RuntimeError):
            self.archive(path, opened=lambda: {str(path)})
        self.assertTrue(path.exists())
        self.assertFalse(path.with_suffix('.a.gz').exists())


class CompletedPs2SymbolsTest(unittest.TestCase):
    setUp = CompletedBuildArchivalTest.setUp
    fixture = CompletedBuildArchivalTest.fixture
    archive = CompletedBuildArchivalTest.archive

    def symbols(self, index=0):
        folder, out, _ = self.fixture(index)
        debug = out / 'pcsx2-libretro/armsx2_libretro.so'
        debug.parent.mkdir()
        debug.write_bytes(b'ELF with recoverable debugging symbols' * 1000)
        core = ARCHIVE.COMPLETED_PS2[index][1]
        runtime = folder / 'arm64-v8a' / (
            'armsx2_16k_libretro.so' if '_16k-' in core else 'armsx2_libretro.so')
        runtime.parent.mkdir()
        runtime.write_bytes(b'runnable core')
        return folder, debug, runtime

    def selected_symbols(self, opened=()):
        return [p for p, _ in ARCHIVE.completed_ps2_symbols(self.root, opened)]

    def test_only_exact_debug_outputs_and_runtime_kept(self):
        rows = [self.symbols(i) for i in range(3)]
        self.assertEqual(self.selected_symbols(), [debug for _, debug, _ in rows])
        for folder, debug, runtime in rows:
            original = debug.read_bytes()
            self.archive(debug)
            self.assertEqual(gzip.decompress(debug.with_suffix('.so.gz').read_bytes()), original)
            self.assertEqual(runtime.read_bytes(), b'runnable core')
            self.assertTrue((folder / 'work').exists())
        self.assertEqual(self.selected_symbols(), [])

    def test_open_trial_preserves_debug_output(self):
        _, _, runtime = self.symbols()
        self.assertEqual(self.selected_symbols({str(runtime)}), [])

    def test_missing_runtime_refuses_archival(self):
        _, debug, runtime = self.symbols()
        runtime.unlink()
        with self.assertRaises(RuntimeError):
            self.selected_symbols()
        self.assertTrue(debug.exists())

    def test_debug_symlink_refused(self):
        _, debug, runtime = self.symbols()
        debug.unlink()
        debug.symlink_to(runtime)
        with self.assertRaises(RuntimeError):
            self.selected_symbols()

    def test_runtime_symlink_or_hardlink_refused(self):
        _, debug, runtime = self.symbols()
        runtime.unlink()
        runtime.symlink_to(debug)
        with self.assertRaises(RuntimeError):
            self.selected_symbols()
        runtime.unlink()
        os.link(debug, runtime)
        with self.assertRaises(RuntimeError):
            self.selected_symbols()

    def test_unknown_trial_not_selected(self):
        folder = self.root / 'armsx2-new-active/work/out/pcsx2-libretro'
        folder.mkdir(parents=True)
        (folder / 'armsx2_libretro.so').write_bytes(b'active debug')
        self.assertEqual(self.selected_symbols(), [])


class CompletedSwitchSymbolsTest(unittest.TestCase):
    setUp = CompletedBuildArchivalTest.setUp
    archive = CompletedBuildArchivalTest.archive

    def test_closed_start_failure_symbols_recoverable_runtime_untouched(self):
        folder = self.root / 'android-portability-2026-10-04-start-failure'
        folder.mkdir()
        debug = folder / 'libeden-unstripped.so'
        original = b'debug symbols' * 100
        debug.write_bytes(original)
        runtime = folder / 'liblucent_native_adapter_eden.so'
        runtime.write_bytes(b'runnable')
        rows = ARCHIVE.completed_switch_archives(self.root)
        self.assertEqual([path for path, _ in rows], [debug])
        self.assertEqual(ARCHIVE.completed_switch_archives(self.root, {str(runtime)}), [])
        self.archive(debug)
        self.assertEqual(gzip.decompress(debug.with_suffix('.so.gz').read_bytes()), original)
        self.assertEqual(runtime.read_bytes(), b'runnable')
        self.assertEqual(ARCHIVE.completed_switch_archives(self.root), [])


if __name__ == '__main__':
    unittest.main()
