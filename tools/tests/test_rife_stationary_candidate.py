import sys
from pathlib import Path
import unittest
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evaluate_rife_stationary_candidate import preserve_agreeing_neighborhoods


class StationaryCandidateTest(unittest.TestCase):
    def test_motion_guard_and_ambiguous_midpoint(self):
        a = np.zeros((7, 7, 3)); b = a.copy(); b[3, 3] = 255
        g = np.full_like(a, 10)
        output, selected = preserve_agreeing_neighborhoods(a, b, g, 1)
        self.assertFalse(selected[2:5, 2:5].any())
        self.assertTrue(selected[0, 0])
        self.assertEqual(output[0, 0, 0], 0)
        self.assertEqual(output[3, 3, 0], 10)
        # Same endpoints do not establish a stationary middle: explicitly
        # demonstrate the failure rather than treating consensus as proof.
        reference = a.copy(); reference[3, 3] = 255
        output, _ = preserve_agreeing_neighborhoods(a, a, reference, 1)
        self.assertFalse(np.array_equal(output, reference))
