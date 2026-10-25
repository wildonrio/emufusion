"""Generated frames shed work only for lateness our own shader work causes.

Wind Waker HD (Cemu, Thor, 2026-10-24) shed to work levels 4-5 -- coarser
motion, more visible artifacts -- because every generated frame shown in the
wrong scan counted as our GPU overloading. Most were shown a scan early (the
compositor not holding them), and late ones were no more common than for real
frames (8% generated against 14% real), which carry none of our shader work;
our work peaked at 4.8 of 12.3 ms.
"""
import unittest

from tools.tests.test_first_install_startup import ROOT

GENERATOR = ROOT / 'unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java'


class SharedTimingMissesTest(unittest.TestCase):
    def setUp(self):
        self.source = GENERATOR.read_text()

    def test_only_late_generated_frames_beyond_real_ones_shed(self):
        source = self.source
        self.assertIn('result.actualNs - result.desiredNs >= result.panelPeriodNs / 2L;', source)
        self.assertIn('if (result.actualNs > 0L) recordPhysicalLateness(result.generated(), shownLate);',
                      source)
        branch = source[source.index('if (result.generated()) {\n                    if (shownLate'):][:400]
        self.assertIn('if (shownLate && generatedLateBeyondReal())', branch)
        self.assertIn('failDenseGpuPairOnce(result.pairSequence, "physical-pair-deadline-miss");', branch)
        self.assertIn('++denseGpuSharedTimingMisses;', branch)

    def test_the_comparison_waits_for_evidence_of_both_kinds(self):
        helper = self.source[self.source.index('private boolean generatedLateBeyondReal() {'):][:500]
        self.assertIn('generatedLateFilled < PHYSICAL_LATENESS_WINDOW / 2', helper)
        self.assertIn('realLateFilled < PHYSICAL_LATENESS_WINDOW / 2', helper)
        self.assertIn('>= GENERATED_LATE_EXCESS', helper)
        self.assertIn('private static final double GENERATED_LATE_EXCESS = 0.04;', self.source)

    def test_counters_are_reported(self):
        self.assertIn('" sharedTimingMisses=" + denseGpuSharedTimingMisses +', self.source)


if __name__ == '__main__':
    unittest.main()
