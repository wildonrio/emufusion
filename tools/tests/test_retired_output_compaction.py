import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

TOOLS = Path(__file__).resolve().parents[2] / 'unified-android/tools'
sys.path.insert(0, str(TOOLS))
SPEC = importlib.util.spec_from_file_location('compact_outputs', TOOLS / 'compact_retired_build_outputs.py')
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


class CompactionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.folder = self.root / 'runtime-acceptance-qa-2026-08-01'
        self.folder.mkdir()
        self.log = self.folder / 'game-logcat.txt'
        self.log.write_bytes(b'x' * 1024 * 1024)
        os.utime(self.log, (1, 1))

    def selected(self, opened=(), tracked=()):
        return [p for p, _ in MOD.select_logs(self.root, opened, tracked, MOD.CUTOFF + 86400)]

    def test_only_old_exact_log_scope(self):
        for name in ('game.rom', 'notes.txt', 'symbols.so', 'game-logcat-small.txt'):
            (self.folder / name).write_bytes(b'keep')
        self.assertEqual(self.selected(), [self.log])
        os.utime(self.log, (MOD.CUTOFF, MOD.CUTOFF))
        self.assertEqual(self.selected(), [])

    def test_open_trial_tracked_file_existing_archive_and_symlink_protected(self):
        self.assertEqual(self.selected(opened={str(self.folder / 'other-file')}), [])
        self.assertEqual(self.selected(tracked={str(self.log)}), [])
        self.log.with_suffix('.txt.gz').touch()
        self.assertEqual(self.selected(), [])
        self.log.with_suffix('.txt.gz').unlink()
        saved = self.log.with_suffix('.saved')
        self.log.rename(saved)
        self.log.symlink_to(saved)
        self.assertEqual(self.selected(), [])

    def closed_trace(self):
        path = self.root / MOD.CLOSED_TRACES[0]
        path.parent.mkdir()
        path.write_bytes(b'trace\n' * 100)
        for name in ('watchdog-ended', 'stop-test'):
            (path.parent / name).touch()
        return path

    def test_closed_trace_exact_allowlist_and_markers(self):
        path = self.closed_trace()
        (path.parent / 'other.atrace').write_bytes(b'preserve')
        self.assertEqual([p for p, _ in MOD.select_closed_traces(self.root, (), ())], [path])
        (path.parent / 'watchdog-ended').unlink()
        with self.assertRaises(RuntimeError):
            MOD.select_closed_traces(self.root, (), ())
        self.assertTrue(path.exists())

    def test_closed_trace_open_and_tracked_preserved(self):
        path = self.closed_trace()
        self.assertEqual(MOD.select_closed_traces(self.root, {str(path.parent / 'runtime.log')}, ()), [])
        self.assertEqual(MOD.select_closed_traces(self.root, (), {str(path)}), [])

    def test_closed_trace_symlink_rejected(self):
        path = self.closed_trace()
        saved = path.with_suffix('.saved')
        path.rename(saved)
        path.symlink_to(saved)
        with self.assertRaises(RuntimeError):
            MOD.select_closed_traces(self.root, (), ())

    def test_closed_trace_lossless_recovery_and_idempotence(self):
        import gzip
        path = self.closed_trace()
        original = path.read_bytes()
        with tempfile.TemporaryFile(mode='w+') as receipt:
            MOD.archive(path, path.lstat(), receipt, lambda: set())
        self.assertFalse(path.exists())
        self.assertEqual(gzip.decompress(path.with_suffix('.atrace.gz').read_bytes()), original)
        self.assertEqual(MOD.select_closed_traces(self.root, (), ()), [])

    def recovery(self):
        trial = self.root / 'trial'
        decoded = trial / 'decoded/lib/arm64-v8a/libtest.so'
        decoded.parent.mkdir(parents=True)
        decoded.write_bytes(b'library')
        apk = trial / 'manifest-build.apk'
        with zipfile.ZipFile(apk, 'w') as zipped:
            zipped.writestr('lib/arm64-v8a/libtest.so', b'library')
        return trial, decoded, apk

    def ocr_cache(self):
        original = self.folder / 'frame.png'
        cache = self.folder / '.frame.png.ocr-boost.png'
        for path in (original, cache):
            path.write_bytes(MOD.PNG_HEADER + b'test')
            os.utime(path, (1, 1))
        return original, cache

    def caches(self, opened=(), tracked=()):
        return MOD.select_ocr_caches(self.root, opened, tracked, MOD.CUTOFF + 86400)

    def test_ocr_selects_only_old_derivative_with_original(self):
        original, cache = self.ocr_cache()
        self.assertEqual([r[0] for r in self.caches()], [cache])
        self.assertNotIn(original, [r[0] for r in self.caches()])
        original.unlink()
        self.assertEqual(self.caches(), [])

    def test_ocr_open_tracked_recent_invalid_and_symlink_protected(self):
        original, cache = self.ocr_cache()
        self.assertEqual(self.caches(opened={str(original)}), [])
        self.assertEqual(self.caches(tracked={str(cache)}), [])
        os.utime(cache, (MOD.CUTOFF, MOD.CUTOFF))
        self.assertEqual(self.caches(), [])
        os.utime(cache, (1, 1))
        original.write_bytes(b'not a PNG')
        self.assertEqual(self.caches(), [])
        original.unlink()
        original.symlink_to(cache)
        self.assertEqual(self.caches(), [])

    def test_ocr_removal_preserves_source_and_records_recovery(self):
        original, cache = self.ocr_cache()
        row, = self.caches()
        source_hash = MOD.sha256(original)
        with tempfile.TemporaryFile(mode='w+') as receipt:
            self.assertEqual(MOD.remove_ocr_cache(*row, receipt), row[1].st_size)
            receipt.seek(0)
            self.assertIn(source_hash, receipt.read())
        self.assertFalse(cache.exists())
        self.assertEqual(MOD.sha256(original), source_hash)

    def test_ocr_changed_original_refuses_removal(self):
        original, cache = self.ocr_cache()
        row, = self.caches()
        original.write_bytes(b'changed')
        with tempfile.TemporaryFile(mode='w+') as receipt:
            with self.assertRaises(RuntimeError):
                MOD.remove_ocr_cache(*row, receipt)
        self.assertTrue(cache.exists())

    def test_decoded_copy_requires_exact_recoverable_bytes(self):
        trial, decoded, apk = self.recovery()
        with mock.patch.object(MOD, 'RECOVERY_SHA', MOD.sha256(apk)):
            rows = MOD.decoded_libraries(trial, apk, set(), set())
            self.assertEqual([r[0] for r in rows], [decoded])
            decoded.write_bytes(b'changed')
            with self.assertRaises(RuntimeError):
                MOD.decoded_libraries(trial, apk, set(), set())

    def test_decoded_copy_open_tracked_and_wrong_recovery_refused(self):
        trial, decoded, apk = self.recovery()
        with self.assertRaises(RuntimeError):
            MOD.decoded_libraries(trial, apk, set(), set())
        with mock.patch.object(MOD, 'RECOVERY_SHA', MOD.sha256(apk)):
            for opened, tracked in (({str(decoded)}, set()), (set(), {str(decoded)})):
                with self.assertRaises(RuntimeError):
                    MOD.decoded_libraries(trial, apk, opened, tracked)


if __name__ == '__main__':
    unittest.main()
