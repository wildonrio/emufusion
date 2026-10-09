"""A reused PS2 library must belong to the locked timing source and page variant."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('ps2_identity', ROOT/'engines/tools/armsx2_build_identity.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class Ps2BuildIdentityTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root/'engines/patches').mkdir(parents=True)
        self.patch = self.root/'engines/patches/clock.patch'
        self.patch.write_bytes(b'new frame clock')
        self.lock = self.root/'engines/armsx2-source-lock.json'
        self.lock.write_text(json.dumps(dict(patches=[dict(
            path='engines/patches/clock.patch', sha256=MODULE.sha256(self.patch))])))
        (self.root/'engines/build_core.sh').write_text('# locked recipe\n')
        self.core = self.root/'armsx2_libretro.so'
        self.core.write_bytes(b'compiled clock fix')
        self.snapshot = dict(sourceInputs=MODULE.source_inputs(self.root), hostPageSize=4096,
            recipeSha256=MODULE.sha256(self.root/'engines/build_core.sh'))

    def receipt(self):
        data = MODULE.make_receipt(self.root, self.core, 4096, self.snapshot)
        MODULE.receipt_path(self.core).write_text(json.dumps(data))

    def test_current_core_and_source_pass(self):
        self.receipt()
        MODULE.verify(self.root, self.core, 4096)

    def test_old_core_without_receipt_fails(self):
        with self.assertRaisesRegex(ValueError, 'identity missing'):
            MODULE.verify(self.root, self.core, 4096)

    def test_binary_or_page_variant_mismatch_fails(self):
        self.receipt()
        with self.assertRaisesRegex(ValueError, 'cached core'):
            MODULE.verify(self.root, self.core, 16384)
        self.core.write_bytes(b'old core copied onto new filename')
        with self.assertRaisesRegex(ValueError, 'cached core'):
            MODULE.verify(self.root, self.core, 4096)

    def test_lock_update_invalidates_cache_and_inflight_build(self):
        self.receipt()
        data = json.loads(self.lock.read_text())
        data['newRevision'] = 2
        self.lock.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'cached core'):
            MODULE.verify(self.root, self.core, 4096)
        with self.assertRaisesRegex(ValueError, 'sources changed'):
            MODULE.make_receipt(self.root, self.core, 4096, self.snapshot)

    def test_modified_patch_cannot_be_stamped_current(self):
        self.patch.write_bytes(b'old timing')
        with self.assertRaisesRegex(ValueError, 'patch differs'):
            MODULE.source_inputs(self.root)

    def test_recipe_change_during_build_rejects_receipt(self):
        (self.root/'engines/build_core.sh').write_text('# concurrent edit\n')
        with self.assertRaisesRegex(ValueError, 'recipe changed'):
            MODULE.make_receipt(self.root, self.core, 4096, self.snapshot)

    def test_apk_path_checks_both_page_variants_even_on_reuse(self):
        script = (ROOT/'unified-android/build.sh').read_text()
        self.assertIn('armsx2_build_identity.py" verify', script)
        self.assertIn('--root "$ROOT_DIR" --pages 4096', script)
        self.assertIn('--root "$ROOT_DIR" --pages 16384', script)
        self.assertLess(script.index('armsx2_build_identity.py" verify'),
                        script.index('THEME_ARCHIVE='))


if __name__ == '__main__':
    unittest.main()
