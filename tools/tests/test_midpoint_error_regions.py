import unittest
import numpy as np
from tools.analyze_midpoint_error_regions import analyze

class ErrorRegionsTest(unittest.TestCase):
    def test_unsigned_difference_and_border_exclusion(self):
        a=np.full((192,256,4),255,np.uint8);b=a.copy()
        b[90,40,:3]=0;b[0,0,:3]=0;b[95,45,:3]=215
        result=analyze(a,b)
        self.assertEqual(result['severe_pixels'],1)
        self.assertEqual(result['tiles'][0]['max_error'],255)
        self.assertFalse(result['image_quality_qualified'])
