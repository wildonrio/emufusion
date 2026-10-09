import sys
from pathlib import Path
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from qa_rife_blend_ablation import blend


class BlendAblationTest(unittest.TestCase):
    def test_identity_when_warps_agree(self):
        source=np.full((3,4,3),.4);mask=np.full((3,4,1),.3)
        for power in (1,2,4,'hard'):
            np.testing.assert_array_equal(blend(source,source,mask,power),102)

    def test_endpoints_and_finite_tie(self):
        left=np.zeros((1,3,3));right=np.ones_like(left)
        mask=np.array([[[0.],[.5],[1.]]])
        for power in (1,2,4):
            result=blend(left,right,mask,power)
            np.testing.assert_array_equal(result[0,:,0],[255,128,0])

    def test_stronger_weight_does_not_reverse_preference(self):
        left=np.zeros((1,1,3));right=np.ones_like(left);mask=np.full((1,1,1),.8)
        values=[blend(left,right,mask,power)[0,0,0] for power in (1,2,4,'hard')]
        self.assertEqual(values,sorted(values,reverse=True))
