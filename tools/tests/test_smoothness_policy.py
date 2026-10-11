"""Stutter-free core options: Dolphin hybrid ubershaders, Azahar disk shader cache."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
POLICY = (ROOT / 'unified-android/src/com/thorium/preview/game/SmoothnessPolicy.java').read_text()
LAUNCH = (ROOT / 'unified-android/src/com/thorium/preview/game/WidescreenHackPolicy.java').read_text()


class SmoothnessPolicyTest(unittest.TestCase):
    def test_options(self):
        self.assertIn('out.put("dolphin_shader_compilation_mode", "async-ubershaders");', POLICY)
        self.assertIn('out.put("citra_use_disk_shader_cache", "enabled");', POLICY)

    def test_merged_after_resolution(self):
        resolution = LAUNCH.index('RenderResolutionPolicy.coreOptionOverrides(context, engine)')
        smooth = LAUNCH.index('SmoothnessPolicy.coreOptionOverrides(engine)')
        self.assertLess(resolution, smooth)

    def test_values_exist_in_the_shipped_cores(self):
        for core, value in (('dolphin_libretro.so', b'async-ubershaders'),
                            ('azahar_libretro.so', b'citra_use_disk_shader_cache')):
            path = ROOT / 'engines/build/arm64-v8a' / core
            if not path.exists():
                self.skipTest('local-only core binary absent')
            self.assertIn(value, path.read_bytes())


if __name__ == '__main__':
    unittest.main()
