"""Static overlays are on by default for 3-D sources and off for pixel art (3.2.161).

A pixel unchanged for 60 real frames is shown unwarped; the QA setting can force a count for every
source or turn it off."""
from pathlib import Path
import unittest

GAME = Path(__file__).resolve().parents[2] / 'unified-android/src/com/thorium/preview/game'


class StaticOverlayDefaultTest(unittest.TestCase):
    def test_default_is_by_kind_of_source(self):
        switch = (GAME / 'TimelineSchedulerSwitch.java').read_text()
        self.assertIn('private static volatile int staticOverlayFrames = -1;', switch)
        self.assertIn('context.getContentResolver(), STATIC_OVERLAY_GLOBAL, -1);', switch)
        self.assertIn('static final int STATIC_OVERLAY_3D_FRAMES = 60;', switch)
        self.assertIn('if (frames >= 0) return frames;', switch)
        self.assertIn('return discrete ? 0 : STATIC_OVERLAY_3D_FRAMES;', switch)

    def test_generator_asks_with_the_source_kind(self):
        generator = (GAME / 'DisplayFrameGenerator.java').read_text()
        self.assertIn('TimelineSchedulerSwitch.staticOverlayFrames(discreteContent));', generator)
        self.assertNotIn('TimelineSchedulerSwitch.staticOverlayFrames());', generator)


if __name__ == '__main__':
    unittest.main()
