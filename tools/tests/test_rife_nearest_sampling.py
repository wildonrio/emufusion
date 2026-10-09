import sys
from pathlib import Path
import unittest
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from qa_rife_final_sampling import sample_nearest


class NearestSamplingTest(unittest.TestCase):
    def test_identity_and_clamped_motion(self):
        image=np.arange(36).reshape(3,4,3)
        y,x=np.mgrid[:3,:4]
        np.testing.assert_array_equal(sample_nearest(image,x,y),image)
        np.testing.assert_array_equal(sample_nearest(image,x-1,y),image[:,[0,0,1,2]])
        np.testing.assert_array_equal(sample_nearest(image,x+10,y+10),
                                     np.broadcast_to(image[-1,-1],image.shape))

    def test_subpixel_rounding_is_explicit_not_endpoint_hold(self):
        image=np.arange(36).reshape(3,4,3)
        y,x=np.mgrid[:3,:4]
        np.testing.assert_array_equal(sample_nearest(image,x+.49,y),image)
        np.testing.assert_array_equal(sample_nearest(image,x+.5,y),image[:,[1,2,3,3]])


if __name__=='__main__':unittest.main()
