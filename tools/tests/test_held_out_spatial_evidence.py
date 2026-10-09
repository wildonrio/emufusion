import importlib.util
from pathlib import Path
import sys
import unittest
import numpy as np

TOOLS=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(TOOLS))
from score_held_out_frame import spatial_evidence


class SpatialEvidenceTest(unittest.TestCase):
    def test_static_damage_is_not_hidden_by_moving_region(self):
        a=np.zeros((2,2,3));b=a.copy();r=a.copy();g=a.copy()
        b[0,0]=100;r[0,0]=50;g[0,0]=50;g[1,1]=80
        result=spatial_evidence(a,b,r,g)
        self.assertEqual(result['regions']['stable']['pixels_error_over_40'],1)
        self.assertEqual(result['regions']['changing']['pixels_error_over_1'],0)
        self.assertFalse(result['image_quality_qualified'])

    def test_copy_and_crossfade_controls_are_detected(self):
        a=np.zeros((2,2,3));b=np.full_like(a,100);r=np.full_like(a,30)
        for key,g in [('left',a),('right',b),('crossfade',(a+b)/2)]:
            result=spatial_evidence(a,b,r,g)
            self.assertTrue(result['copy_controls'][key]['whole_image_equal_within_1'])
            self.assertEqual(result['copy_controls'][key]['changing_pixels_distinct_over_1'],0)

    def test_unsigned_subtraction_and_empty_regions(self):
        a=np.full((2,2,3),255,dtype=np.uint8);g=np.zeros_like(a)
        result=spatial_evidence(a,a,a,g)
        self.assertEqual(result['regions']['stable']['rgb_mae'],255)
        self.assertIsNone(result['regions']['changing']['rgb_mae'])
        with self.assertRaises(ValueError):spatial_evidence(a,a,a,g[:1])


if __name__=='__main__':unittest.main()
