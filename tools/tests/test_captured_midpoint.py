import importlib.util
from pathlib import Path
import unittest
import numpy as np

spec = importlib.util.spec_from_file_location('capture', Path(__file__).parents[1]/'analyze_captured_midpoint.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class CaptureTests(unittest.TestCase):
    def test_copy_and_crossfade_controls(self):
        a = np.zeros((2,2,3), dtype=np.uint8)
        b = np.full_like(a, 200)
        for name, g in [('left',a),('right',b),('crossfade',np.full_like(a,100))]:
            result = module.compare(a,b,g)
            self.assertTrue(result['controls'][name]['equal_within_1'])
            self.assertFalse(result['image_quality_qualified'])
            self.assertEqual(result['endpoint_changing_pixels'],4)

    def test_agreement_does_not_claim_truth(self):
        a = np.full((1,1,3),255,dtype=np.uint8)
        result = module.compare(a,a,np.zeros_like(a))
        self.assertEqual(result['endpoint_agreeing_pixels_changed_over_40'],1)
        self.assertIsNone(result['controls']['left']['changing_rgb_mae'])
        self.assertFalse(result['ground_truth_available'])

    def test_shape_rejected(self):
        with self.assertRaises(ValueError):
            module.compare(np.zeros((1,1,4)),np.zeros((1,1,4)),np.zeros((1,1,4)))
