import sys
from pathlib import Path
import unittest
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evaluate_rife_temporal_stationary import temporal_candidate, quality_scores, runtime_available_candidate


class TemporalStationaryTest(unittest.TestCase):
    def test_missing_lookahead_does_not_copy_endpoints(self):
        source=np.full((9,9,3),42.)
        generated=source+10
        result,mask=runtime_available_candidate(source,source,None,generated)
        self.assertFalse(mask.any())
        np.testing.assert_array_equal(result,generated)

    def test_three_source_guard_uses_lookahead_motion(self):
        source=np.full((9,9,3),42.)
        following=source.copy();following[4,4]=150
        generated=source+10
        result,mask=runtime_available_candidate(source,source,following,generated)
        self.assertFalse(mask[2:7,2:7].any())
        self.assertTrue(mask[0,0])
        np.testing.assert_array_equal(result[2:7,2:7],generated[2:7,2:7])

    def test_restoring_background_is_not_a_motion_pass(self):
        left = np.zeros((9,9,3))
        right = left.copy(); right[4,4] = 100
        reference = left.copy(); reference[4,5] = 100
        report = quality_scores(left,right,reference,left)
        self.assertFalse(report['gate']['useful_midpoint_gate_passed'])
        self.assertFalse(report['gate']['artifact_free_qualified'])

    def test_stable_detail_restored(self):
        source = np.full((9,9,3),42.0)
        generated = source + 5
        result, mask = temporal_candidate(source,source,source,source,generated,2)
        self.assertTrue(mask.all())
        np.testing.assert_array_equal(result,source)
        np.testing.assert_array_equal(generated,source+5)

    def test_equivalent_generated_detail_is_not_overwritten(self):
        source=np.full((9,9,3),199.0)
        generated=source-1
        result,mask=temporal_candidate(source,source,source,source,generated,2)
        self.assertFalse(mask.any())
        np.testing.assert_array_equal(result,generated)

    def test_temporal_disagreement_protects_neighbor_motion(self):
        source = np.zeros((9,9,3))
        previous = source.copy()
        previous[4,4] = 100
        generated = source + 20
        for earlier, later in ((previous,source),(source,previous)):
            result, mask = temporal_candidate(earlier,source,source,later,generated,2)
            self.assertFalse(mask[2:7,2:7].any())
            np.testing.assert_array_equal(result[2:7,2:7],generated[2:7,2:7])
            self.assertTrue(mask[0,0])

    def test_invalid_input(self):
        source = np.zeros((9,9,3))
        with self.assertRaises(ValueError):
            temporal_candidate(source,source,source,source,source,-1)
        with self.assertRaises(ValueError):
            temporal_candidate(source[:2],source,source,source,source,1)


if __name__ == '__main__':
    unittest.main()
