"""Normal PS3 trial exempts generated caches, never firmware/settings/saves."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / 'docs/qa/android-portability-2026-10-06-ps3-wide-integration/runtime_fixture.py'
SPEC = importlib.util.spec_from_file_location('ps3_normal_preservation', PATH)
FIXTURE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FIXTURE)


class PreservationGuardTests(unittest.TestCase):
    def test_only_expected_runtime_cache_changes_are_allowed(self):
        for name in ('app_engine-system/aps3e/cache/generated.bin',
                     'app_engine-system/aps3e/logs/rp3_log.txt',
                     'app_engine-system/aps3e/config/dev_hdd1/caches/BCUS98259_BCUS98259/FIOSCACHE/cache.idx',
                     'app_engine-system/aps3e/config/dev_hdd1/caches/BCUS98259_BCUS98259/FIOSCACHE/cache.dat'):
            self.assertTrue(FIXTURE.allowed_runtime_change(name), name)

    def test_saves_settings_firmware_and_unrecognized_cache_files_stay_protected(self):
        for name in ('files/engine-saves/game.sav', 'files/state-vault/game.bin',
                     'app_engine-system/aps3e/config/config.yml',
                     'app_engine-system/aps3e/config/dev_flash/vsh/etc/version.txt',
                     'app_engine-system/aps3e/config/dev_hdd0/home/00000001/savedata/SAVE/file',
                     'app_engine-system/aps3e/config/dev_hdd1/caches/another-game/cache.dat',
                     'app_engine-system/aps3e/config/dev_hdd1/caches/BCUS98259_BCUS98259/FIOSCACHE/save.dat'):
            self.assertFalse(FIXTURE.allowed_runtime_change(name), name)


if __name__ == '__main__':
    unittest.main()
