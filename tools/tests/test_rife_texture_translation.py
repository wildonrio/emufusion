import sys
from pathlib import Path
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from qa_rife_texture_translation import render
from evaluate_rife_camera_consensus import correct


class TextureTranslationTest(unittest.TestCase):
    def test_reference_is_not_crossfade(self):
        left=render(0,(3,3),.38);right=render(1,(3,3),.38)
        truth=render(.5,(3,3),.38)
        self.assertGreater(abs(truth-(left+right)/2).mean(),50)

    def test_integer_midpoint_has_exact_independent_truth(self):
        left=render(0,(2,0),.38);right=render(1,(2,0),.38)
        result,mask=correct(left,right,(left+right)/2)
        self.assertGreater(mask.sum(),1000)
        np.testing.assert_allclose(result[mask],render(.5,(2,0),.38)[mask],atol=1e-10)

    def test_fine_texture_loss_is_visible_below_old_severe_threshold(self):
        # Characterization of a known defect, NOT an acceptance expectation.
        # Replace with a quality requirement when reconstruction is improved.
        left=render(0,(3,3),.38);right=render(1,(3,3),.38)
        result,mask=correct(left,right,(left+right)/2)
        mask[:8]=False;mask[-8:]=False;mask[:,:8]=False;mask[:,-8:]=False
        error=abs(result-render(.5,(3,3),.38))[mask]
        self.assertGreater(error.mean(),15)
        self.assertLess(error.max(),40)
