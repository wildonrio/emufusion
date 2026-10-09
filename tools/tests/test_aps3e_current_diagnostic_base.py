"""Current diagnostic packaging must preserve the explicitly reviewed app base."""
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    'aps3e_package_current', ROOT / 'engines/diagnostics/package_spurs_trace.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class CurrentDiagnosticBaseTest(unittest.TestCase):
    def test_explicit_current_base_is_returned_without_modification(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            base = root / 'current.apk'
            payload = b'current app with other-agent edits'
            base.write_bytes(payload)
            expected = hashlib.sha256(payload).hexdigest()
            with patch.object(module, 'ROOT', root):
                self.assertEqual(module.select_base(base, expected), (base, expected))
            self.assertEqual(base.read_bytes(), payload)

    def test_partial_override_never_selects_old_base(self):
        for arguments in ((Path('current.apk'), None), (None, 'a' * 64)):
            with self.assertRaisesRegex(ValueError, 'together'):
                module.select_base(*arguments)

    def test_changed_input_and_invalid_hash_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            base = root / 'current.apk'
            base.write_bytes(b'new content')
            with patch.object(module, 'ROOT', root):
                with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                    module.select_base(base, 'a' * 64)
                with self.assertRaisesRegex(ValueError, 'hexadecimal'):
                    module.select_base(base, 'old')

    def test_default_remains_exact_historical_base(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            payload = b'historical base'
            expected = hashlib.sha256(payload).hexdigest()
            base = root / ('unified-android/build/lucent-3.2.16-phase2-phase3-qualification-' + expected + '.apk')
            base.parent.mkdir(parents=True)
            base.write_bytes(payload)
            with patch.object(module, 'ROOT', root), patch.object(module, 'BASE_SHA', expected):
                self.assertEqual(module.select_base(), (base, expected))


if __name__ == '__main__':
    unittest.main()
