"""The next APK must not pair a stale Wii U binary with today's source lock."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('cemu_build_identity', ROOT / 'engines/tools/cemu_build_identity.py')
IDENTITY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(IDENTITY)


class CemuBuildIdentityTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / 'engines').mkdir()
        self.source = self.root / 'engine.cpp'
        self.source.write_text('current source')
        self.core = self.root / 'liblucent_native_adapter_cemu.so'
        self.core.write_bytes(b'configured native output')
        self.lock = dict(patches=[dict(path='engine.cpp', sha256=IDENTITY.sha256(self.source))],
                         artifact=dict(sha256=IDENTITY.sha256(self.core)))
        self.receipt = dict(schemaVersion=1, sha256=IDENTITY.sha256(self.core),
                            sourceHashes={str(self.source): IDENTITY.sha256(self.source)})
        self.save()

    def save(self):
        (self.root / 'engines/cemu-source-lock.json').write_text(json.dumps(self.lock))
        self.core.with_suffix('.so.build.json').write_text(json.dumps(self.receipt))

    def test_matching_configured_output(self):
        IDENTITY.verify(self.root, self.core)

    def test_missing_receipt(self):
        self.core.with_suffix('.so.build.json').unlink()
        with self.assertRaisesRegex(ValueError, 'identity missing'):
            IDENTITY.verify(self.root, self.core)

    def test_old_binary_even_if_lock_matches(self):
        self.core.write_bytes(b'old native output')
        self.lock['artifact']['sha256'] = IDENTITY.sha256(self.core)
        self.save()
        with self.assertRaisesRegex(ValueError, 'does not match'):
            IDENTITY.verify(self.root, self.core)

    def test_changed_source_not_hidden_by_updated_source_lock(self):
        self.source.write_text('new pause fix')
        self.lock['patches'][0]['sha256'] = IDENTITY.sha256(self.source)
        self.save()
        with self.assertRaisesRegex(ValueError, 'predates'):
            IDENTITY.verify(self.root, self.core)

    def test_unrecorded_source_edit(self):
        self.source.write_text('changed by another agent')
        with self.assertRaisesRegex(ValueError, 'source differs'):
            IDENTITY.verify(self.root, self.core)

    def test_omitted_locked_source_is_rejected(self):
        self.receipt['sourceHashes'] = {}
        self.save()
        with self.assertRaisesRegex(ValueError, 'predates'):
            IDENTITY.verify(self.root, self.core)

    def test_external_tree_location_used(self):
        self.lock['patches'][0].update(pathIsRelativeTo=str(self.root))
        self.save()
        IDENTITY.verify(self.root, self.core)

    def test_rejects_empty_and_duplicate_input_sets(self):
        for patches in ([], self.lock['patches'] * 2):
            with self.subTest(patches=patches):
                self.lock['patches'] = patches
                self.save()
                with self.assertRaises(ValueError):
                    IDENTITY.verify(self.root, self.core)

    def test_build_checks_identity_before_assembly(self):
        build = (ROOT / 'unified-android/build.sh').read_text()
        guard = build.index('engines/tools/cemu_build_identity.py')
        self.assertLess(guard, build.index('fetch_dependency()'))
        self.assertIn('if [ "$INCLUDE_PHASE3_CEMU" = 1 ]; then', build[:guard])


if __name__ == '__main__':
    unittest.main()
