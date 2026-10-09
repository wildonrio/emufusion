import sys
from pathlib import Path
import unittest
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from evaluate_rife_patch_motion import box_mean,synthesize,sample_cubic,match


class PatchMotionTest(unittest.TestCase):
    def test_consensus_does_not_move_static_overlay(self):
        left=np.random.default_rng(9).integers(0,256,(32,48,3)).astype(float)
        right=np.roll(left,2,axis=1)
        overlay=np.random.default_rng(10).integers(0,256,(8,8,3))
        left[10:18,20:28]=overlay;right[10:18,20:28]=overlay
        flow,confidence=match(left,right,consensus=True)
        self.assertTrue(confidence[13,23])
        np.testing.assert_array_equal(flow[13,23],[0,0])

    def test_cubic_preserves_integer_samples_and_bounds(self):
        image=np.random.default_rng(2).integers(0,256,(8,8,3)).astype(float)
        y,x=np.mgrid[:8,:8]
        np.testing.assert_array_equal(sample_cubic(image,x,y),image)
        result=sample_cubic(image,x+.5,y+.5)
        self.assertTrue(np.isfinite(result).all())
        self.assertGreaterEqual(result.min(),0)
        self.assertLessEqual(result.max(),255)
    def test_box_mean(self):
        values=np.arange(25,dtype=float).reshape(5,5)
        result=box_mean(values,1)
        self.assertEqual(result.shape,values.shape)
        self.assertAlmostEqual(result[2,2],values[1:4,1:4].mean())

    def test_known_translation_has_true_midpoint(self):
        left=np.random.default_rng(1).integers(0,256,(24,32,3)).astype(float)
        right=np.roll(left,2,axis=1)
        candidate,mask=synthesize(left,right,np.zeros_like(left))
        self.assertGreater(mask.sum(),100)
        expected=np.roll(left,1,axis=1)
        np.testing.assert_allclose(candidate[mask],expected[mask])

    def test_ambiguous_flat_region_does_not_invent_motion(self):
        left=np.zeros((12,12,3));generated=left+12
        candidate,mask=synthesize(left,left,generated)
        self.assertFalse(mask.any())
        np.testing.assert_array_equal(candidate,generated)


if __name__=='__main__':unittest.main()
