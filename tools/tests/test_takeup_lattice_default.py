"""The take-up lattice stays off unless QA turns it on (Thor, 2026-10-27)."""
from pathlib import Path
import re
import unittest

SOURCE = (Path(__file__).resolve().parents[2] /
          'unified-android/src/com/thorium/preview/game/TimelineSchedulerSwitch.java')


class TakeUpLatticeDefaultTest(unittest.TestCase):
    def test_lattice_is_opt_in(self):
        text = SOURCE.read_text()
        # 3.2.112-3.2.116 took pairs up on the lattice by default; on the Thor
        # paced 2-D cores then dropped real images (two-scan holds by the
        # hundred every 30 s), so pairs are taken up on arrival again.
        self.assertIn('private static volatile boolean takeUpLattice;', text)
        self.assertRegex(text, r'boolean lattice = false;\s+try \{\s+if \(context != null\) '
                               r'lattice = Settings\.Global\.getInt\(\s+context\.getContentResolver\(\), '
                               r'TAKEUP_LATTICE_GLOBAL, 0\) != 0;')
        self.assertIsNone(re.search(r'TAKEUP_LATTICE_GLOBAL, 1\)', text))


if __name__ == '__main__':
    unittest.main()
