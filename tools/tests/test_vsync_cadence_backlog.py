"""A heavy frame drops the display-clock backlog instead of resetting it.

October 10 Thor: Wii at 3x toggled the hardware display tick clock 28 times
in 47 s because VsyncCadence reset (back to the nominal clock and a fresh
warm-up) whenever the core fell four frames behind; each hand-off hitched.
"""
from pathlib import Path
import unittest

CADENCE = (Path(__file__).resolve().parents[2] /
           'unified-android/src/com/thorium/lucent/timing/VsyncCadence.java').read_text()


class VsyncCadenceBacklogTest(unittest.TestCase):
    def test_backlog_is_coalesced_not_reset(self):
        self.assertIn('if (produced - consumed > 4) consumed = produced - 1;', CADENCE)
        self.assertNotIn('if (produced - consumed > 4) reset();', CADENCE)


if __name__ == '__main__':
    unittest.main()
