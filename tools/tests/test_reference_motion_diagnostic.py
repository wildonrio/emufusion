import sys
from pathlib import Path
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from diagnose_reference_motion import diagnose


class ReferenceMotionDiagnosticTest(unittest.TestCase):
    def test_uniform_and_quantized_motion_remain_distinct(self):
        left=np.random.default_rng(4).integers(0,256,(24,32,3)).astype(float)
        midpoint=np.roll(left,1,axis=1)
        uniform=diagnose(left,midpoint,np.roll(left,2,axis=1))
        self.assertEqual(uniform['reference_offset_from_uniform_midpoint_pixels'],[0.0,0.0])
        self.assertFalse(uniform['reconstruction_and_smoothness_require_separate_evidence'])
        quantized=diagnose(left,midpoint,np.roll(left,3,axis=1))
        self.assertEqual(quantized['reference_offset_from_uniform_midpoint_pixels'],[-.5,0.0])
        self.assertTrue(quantized['reconstruction_and_smoothness_require_separate_evidence'])
        self.assertFalse(quantized['image_quality_qualified'])

    def test_ambiguous_images_do_not_establish_motion(self):
        image=np.zeros((24,32,3))
        self.assertIsNone(diagnose(image,image,image)['reference_offset_from_uniform_midpoint_pixels'])
