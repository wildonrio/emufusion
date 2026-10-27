"""The arrival phase lock is a QA opt-in: on the Thor it bought no smoothness (2026-10-27)."""
from pathlib import Path
import unittest

from tools.tests.test_framegen_startup_fallback import method

GAME = Path(__file__).resolve().parents[2] / 'unified-android/src/com/thorium/preview/game'


class ArrivalPhaseLockTest(unittest.TestCase):
    def test_arrival_pacing_keeps_the_lattice_only_when_qa_asks(self):
        body = method((GAME / 'DisplayFrameGenerator.java').read_text(),
                      '    private PhysicalPresentationDeadline phaseLockedTimelineDeadline(')
        self.assertIn('if (timeline.arrivalPacing() && !TimelineSchedulerSwitch.arrivalPhaseLock()) '
                      'return deadline;', body)
        self.assertNotIn('if (timeline.arrivalPacing()) return deadline;', body)
        # One-scan outputs (60 -> 120) have no lattice to keep.
        self.assertIn('if (scans <= 1 ||', body)

    def test_switch_defaults_off(self):
        text = (GAME / 'TimelineSchedulerSwitch.java').read_text()
        self.assertIn('"emufusion_framegen_arrival_phase_lock"', text)
        self.assertIn('private static volatile boolean arrivalPhaseLock;', text)
        self.assertIn('ARRIVAL_PHASE_LOCK_GLOBAL, 0) != 0;', text)


if __name__ == '__main__':
    unittest.main()
