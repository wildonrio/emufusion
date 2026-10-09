import gzip
import importlib.util
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / 'unified-android/tools'
with mock.patch.object(sys, 'path', [str(TOOLS), *sys.path]):
    spec = importlib.util.spec_from_file_location('archive_retired', TOOLS / 'archive_retired_ps3_intermediates.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)


class RetiredArchiveTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.now = 100 * 86400

    def fixture(self, name='aps3e-old-test-2026-09-09', age=30):
        folder = self.root / name
        folder.mkdir()
        path = folder / 'librpcs3_emu.trace.a'
        path.write_bytes(b'!<arch>\n' + b'test object data' * 1000)
        os.utime(path, (self.now - age * 86400,) * 2)
        return path

    def test_exact_scope_excludes_normal_recent_and_other_engines(self):
        old = self.fixture()
        self.fixture('aps3e-wrapper-sync-clean-linked-2026-09-09')
        self.fixture('aps3e-recent-2026-09-08', age=1)
        self.fixture('dolphin-old-2026-09-09')
        (old.parent / 'libcore.unstripped.so').write_bytes(b'symbols')
        self.assertEqual([p for p, _ in module.select(self.root, self.now)], [old])
        self.assertEqual(module.select(self.root, self.now, {str(old)}), [])

    def test_symlink_folder_and_file_not_selected(self):
        path = self.fixture()
        target = path.with_name('keep.a')
        path.rename(target)
        path.symlink_to(target)
        (self.root / 'aps3e-alias-2026-09-09').symlink_to(path.parent, target_is_directory=True)
        self.assertEqual(module.select(self.root, self.now), [])

    def test_symbols_opt_in_exact_scope_and_active_baseline_preserved(self):
        old = self.fixture()
        baseline = self.fixture('aps3e-wrapper-sync-clean-linked-2026-09-09')
        symbols = old.with_name('liblucent_native_adapter_aps3e.trace.unstripped.so')
        for folder in (old.parent, baseline.parent):
            for name in (symbols.name, 'liblucent_native_adapter_aps3e.trace.so',
                         'other.unstripped.so'):
                path = folder / name
                path.write_bytes(b'preserve exact symbols or runnable library')
                os.utime(path, (self.now - 30 * 86400,) * 2)
        self.assertEqual([p for p, _ in module.select(self.root, self.now)], [old])
        self.assertEqual([p for p, _ in module.select(
            self.root, self.now, retired_symbols=True)], [old, symbols])
        self.assertEqual(module.select(self.root, self.now,
            {str(old.with_name('liblucent_native_adapter_aps3e.trace.so'))}, True), [])

    def test_recent_or_symlinked_symbols_preserved(self):
        old = self.fixture()
        symbols = old.with_name('liblucent_native_adapter_aps3e.trace.unstripped.so')
        symbols.write_bytes(b'recent')
        os.utime(symbols, (self.now - 86400,) * 2)
        self.assertEqual([p for p, _ in module.select(
            self.root, self.now, retired_symbols=True)], [old])
        symbols.unlink()
        symbols.symlink_to(old)
        self.assertEqual([p for p, _ in module.select(
            self.root, self.now, retired_symbols=True)], [old])

    def run_archive(self, path, meta=None, opened=lambda: set()):
        with (self.root / 'receipt.jsonl').open('w') as receipt:
            return module.archive(path, meta or path.stat(), receipt, opened)

    def test_switch_retirement_is_opt_in_and_exact_allowlist(self):
        selected = []
        for name in ('eden-clock-recovery-2026-09-09',
                     'eden-multiplayer-2026-09-07',
                     'eden-unknown-2026-09-09', 'eden-clock-recovery-2026-10-06'):
            folder = self.root / name
            folder.mkdir()
            for filename in ('libcore.a', 'libvideo_core.a', 'libeden.unstripped.so',
                             'liblucent_native_adapter_eden.so', 'source.cpp', 'save.bin'):
                path = folder / filename
                path.write_bytes(b'preserve unless explicitly archived')
                os.utime(path, (self.now - 30 * 86400,) * 2)
                if name in module.RETIRED_SWITCH and filename in (
                        'libcore.a', 'libvideo_core.a', 'libeden.unstripped.so'):
                    selected.append(path)
        self.assertEqual(module.select(self.root, self.now), [])
        self.assertEqual([p for p, _ in module.select(
            self.root, self.now, retired_switch=True)], selected)

    def test_switch_open_candidate_recent_file_and_symlink_preserved(self):
        folder = self.root / 'eden-clock-recovery-2026-09-09'
        folder.mkdir()
        old = folder / 'libcore.a'
        old.write_bytes(b'old')
        os.utime(old, (self.now - 30 * 86400,) * 2)
        recent = folder / 'libvideo_core.a'
        recent.write_bytes(b'recent')
        os.utime(recent, (self.now - 86400,) * 2)
        (folder / 'libeden.unstripped.so').symlink_to(old)
        self.assertEqual([p for p, _ in module.select(
            self.root, self.now, retired_switch=True)], [old])
        self.assertEqual(module.select(self.root, self.now,
            {str(folder / 'liblucent_native_adapter_eden.so')}, retired_switch=True), [])
        alias = self.root / 'eden-coupled-clock-2026-09-09'
        alias.symlink_to(folder, target_is_directory=True)
        self.assertEqual([p for p, _ in module.select(
            self.root, self.now, retired_switch=True)], [old])

    def test_archive_roundtrip_and_retirement(self):
        path = self.fixture()
        original = path.read_bytes()
        self.assertGreater(self.run_archive(path), 0)
        self.assertFalse(path.exists())
        with gzip.open(str(path) + '.gz', 'rb') as source:
            self.assertEqual(source.read(), original)
        self.assertIn(module.hashlib.sha256(original).hexdigest(), (self.root / 'receipt.jsonl').read_text())

    def test_completed_switch_archives_only_exact_five_outputs(self):
        expected = []
        for relative in module.COMPLETED_SWITCH_OUTPUTS:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'closed diagnostic symbols')
            expected.append(path)
            for name in ('liblucent_native_adapter_eden.so', 'source.cpp', 'save.bin'):
                (path.parent / name).write_bytes(b'keep')
        unrelated = self.root / 'android-portability-2026-10-07-switch-current'
        unrelated.mkdir()
        (unrelated / 'libeden-unstripped.so').write_bytes(b'keep active symbols')
        self.assertEqual([p for p, _ in module.completed_switch_archives(self.root)], expected)
        opened = {str(expected[-1].with_name('runtime.log'))}
        # An open handheld/r2 trial protects both handheld outputs, not the
        # independently closed load/start-failure trials.
        self.assertEqual([p for p, _ in module.completed_switch_archives(self.root, opened)], expected[:3])

    def test_completed_switch_symlink_refused_and_missing_output_skipped(self):
        path = self.root / module.COMPLETED_SWITCH_OUTPUTS[0]
        path.parent.mkdir(parents=True)
        self.assertEqual(module.completed_switch_archives(self.root), [])
        path.symlink_to(self.root / 'missing.a')
        with self.assertRaises(RuntimeError):
            module.completed_switch_archives(self.root)
        path.unlink()
        path.parent.rmdir()
        real = self.root / 'actual-trial'
        real.mkdir()
        (real / path.name).write_bytes(b'keep')
        path.parent.symlink_to(real, target_is_directory=True)
        with self.assertRaises(RuntimeError):
            module.completed_switch_archives(self.root)

    def test_existing_archive_never_overwritten(self):
        path = self.fixture()
        archive = Path(str(path) + '.gz')
        archive.write_bytes(b'keep')
        with self.assertRaises(RuntimeError):
            self.run_archive(path)
        self.assertTrue(path.exists())
        self.assertEqual(archive.read_bytes(), b'keep')

    def test_completed_cemu_exact_copies_only_and_open_trial_protected(self):
        expected = []
        for relative in module.COMPLETED_CEMU_SYMBOLS:
            path = self.root / relative
            path.parent.mkdir(parents=True)
            path.write_bytes(b'historical symbols')
            expected.append(path)
            for name in ('liblucent_native_adapter_cemu.so', 'source.cpp', 'save.bin'):
                (path.parent / name).write_bytes(b'preserve')
        other = self.root / 'android-portability-2026-10-07-native-stick-clicks'
        other.mkdir()
        (other / 'linked-before.so').write_bytes(b'preserve active work')
        self.assertEqual([p for p, _ in module.completed_cemu_symbols(self.root)], expected)
        self.assertEqual([p for p, _ in module.completed_cemu_symbols(
            self.root, {str(expected[0].with_name('runtime.log'))})], expected[1:])

    def test_completed_cemu_lossless_recovery_and_repeat_is_noop(self):
        path = self.root / module.COMPLETED_CEMU_SYMBOLS[0]
        path.parent.mkdir(parents=True)
        original = b'ELF debug information' * 1000
        path.write_bytes(original)
        self.run_archive(path)
        self.assertEqual(gzip.decompress(Path(str(path) + '.gz').read_bytes()), original)
        self.assertEqual(module.completed_cemu_symbols(self.root), [])

    def test_completed_cemu_rejects_symlink_and_skips_missing(self):
        self.assertEqual(module.completed_cemu_symbols(self.root), [])
        path = self.root / module.COMPLETED_CEMU_SYMBOLS[0]
        path.parent.mkdir(parents=True)
        target = self.root / 'keep.so'
        target.write_bytes(b'keep')
        path.symlink_to(target)
        with self.assertRaises(RuntimeError):
            module.completed_cemu_symbols(self.root)
        self.assertEqual(target.read_bytes(), b'keep')

    def test_changed_input_preserved(self):
        path = self.fixture()
        previous = path.stat()
        path.write_bytes(b'changed')
        with self.assertRaises(RuntimeError):
            self.run_archive(path, previous)
        self.assertTrue(path.exists())

    def test_newly_opened_input_preserved(self):
        path = self.fixture()
        with self.assertRaises(RuntimeError):
            self.run_archive(path, opened=lambda: {str(path)})
        self.assertTrue(path.exists())

    def test_newly_opened_sibling_preserves_candidate(self):
        path = self.fixture()
        with self.assertRaises(RuntimeError):
            self.run_archive(path, opened=lambda: {str(path.with_name('running.so'))})
        self.assertTrue(path.exists())

    def test_failed_roundtrip_never_removes_original(self):
        path = self.fixture()
        with mock.patch.object(module.gzip, 'open', return_value=io.BytesIO(b'corrupt')):
            with self.assertRaises(RuntimeError):
                self.run_archive(path)
        self.assertTrue(path.exists())
        self.assertFalse(Path(str(path) + '.gz').exists())


if __name__ == '__main__':
    unittest.main()
