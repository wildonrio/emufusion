import sys
from pathlib import Path
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from measure_generated_motion_phase import measure


class GeneratedMotionPhaseTest(unittest.TestCase):
    def test_halfway_and_hold_are_distinguished(self):
        left=np.random.default_rng(7).integers(0,256,(40,48,3)).astype(float)
        right=np.roll(left,2,axis=1)
        result=measure(left,right,{'midpoint':np.roll(left,1,axis=1),'hold':left})
        self.assertEqual(result['candidates']['midpoint']['best_phase'],.5)
        self.assertEqual(result['candidates']['hold']['best_phase'],0)
        self.assertFalse(result['qualified'])

    def test_stationary_scene_cannot_prove_interpolation(self):
        source=np.zeros((40,48,3))
        result=measure(source,source,{'candidate':source})
        self.assertFalse(result['qualified'])
        self.assertIn('reason',result)
