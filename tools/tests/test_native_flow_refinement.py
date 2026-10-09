import sys
import unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from qa_refine_native_flow import refine,multiscale


class NativeRefinementTest(unittest.TestCase):
    def test_shared_proposal_escapes_wrong_local_basin(self):
        source=np.random.default_rng(31).integers(0,256,(24,40,3)).astype(float)
        peer=np.concatenate([np.repeat(source[:,:1],6,axis=1),source[:,:-6]],axis=1)
        initial=np.zeros((24,40,2));initial[...,0]=6
        initial[6:18,10:20]=0
        result=refine(source,peer,initial,shared_candidates=True)
        np.testing.assert_array_equal(result[8:16,12:18,0],6)
        np.testing.assert_array_equal(result[8:16,12:18,1],0)

    def test_shared_proposal_preserves_independent_motion(self):
        source=np.random.default_rng(32).integers(0,256,(32,48,3)).astype(float)
        peer=source.copy()
        peer[10:22,23:35]=source[10:22,18:30]
        initial=np.zeros((32,48,2));initial[10:22,18:30,0]=5
        result=refine(source,peer,initial,shared_candidates=True)
        np.testing.assert_array_equal(result[12:20,20:28,0],5)
        np.testing.assert_array_equal(result[2:8,2:40],0)

    def test_multiscale_reaches_eight_pixel_translation(self):
        source=np.random.default_rng(17).integers(0,256,(48,64,3)).astype(float)
        peer=np.concatenate([np.repeat(source[:,:1],8,axis=1),source[:,:-8]],axis=1)
        result=multiscale(source,peer)
        error=np.linalg.norm(result[12:-12,12:-16]-np.array([8,0]),axis=2)
        self.assertLess(np.median(error),.1)
        self.assertGreater(np.mean(error<.5),.9)

    def test_multiscale_static_odd_size(self):
        source=np.random.default_rng(19).integers(0,256,(25,33,3)).astype(float)
        np.testing.assert_array_equal(multiscale(source,source),0)

    def test_known_translation_recovers_interior(self):
        source=np.random.default_rng(7).integers(0,256,(12,16,3)).astype(float)
        peer=np.concatenate([source[:,:1],source[:,:-1]],axis=1)
        initial=np.zeros((12,16,2));initial[...,0]=1.75
        result=refine(source,peer,initial)
        np.testing.assert_array_equal(result[2:-2,2:-3,0],1)
        np.testing.assert_array_equal(result[2:-2,2:-3,1],0)

    def test_static_image_stays_zero(self):
        source=np.random.default_rng(9).integers(0,256,(8,12,3)).astype(float)
        np.testing.assert_array_equal(refine(source,source,np.zeros((8,12,2))),0)


if __name__=="__main__":unittest.main()
