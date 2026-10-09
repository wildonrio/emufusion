import sys
from pathlib import Path
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from qa_rife_reconstruction_filters import sample_lanczos
from qa_rife_texture_translation import render


class ReconstructionFiltersTest(unittest.TestCase):
    def test_plateau_limiter_preserves_fine_texture_reconstruction(self):
        image=render(0,(3,3),.38)
        y,x=np.mgrid[:48,:80]
        raw=sample_lanczos(image,x-1.5,y-1.5)
        adaptive=sample_lanczos(image,x-1.5,y-1.5,'plateau')
        np.testing.assert_array_equal(raw[8:-8,8:-8],adaptive[8:-8,8:-8])

    def test_plateau_limiter_removes_halos(self):
        y,x=np.mgrid[:16,:40]
        image=np.repeat(np.where(x<20,30.,220.)[...,None],3,axis=2)
        result=sample_lanczos(image,x-.5,y,'plateau')
        self.assertGreaterEqual(result.min(),30)
        self.assertLessEqual(result.max(),220)
        np.testing.assert_allclose(result[:,20],125,atol=1e-10)

    def test_integer_samples_are_preserved(self):
        image=np.random.default_rng(81).uniform(20,230,(16,20,3))
        y,x=np.mgrid[:16,:20]
        for limited in (False,True):
            np.testing.assert_allclose(sample_lanczos(image,x,y,limited),image,atol=1e-10)

    def test_constant_color_is_preserved_at_fractional_positions(self):
        image=np.full((16,20,3),117.)
        y,x=np.mgrid[:16,:20]
        np.testing.assert_allclose(sample_lanczos(image,x+.3,y-.4),image,atol=1e-10)

    def test_range_limiter_removes_step_halos_without_holding_endpoint(self):
        y,x=np.mgrid[:16,:40]
        image=np.repeat(np.where(x<20,30.,220.)[...,None],3,axis=2)
        raw=sample_lanczos(image,x-.5,y)
        limited=sample_lanczos(image,x-.5,y,True)
        self.assertLess(raw.min(),20)
        self.assertGreater(raw.max(),230)
        self.assertGreaterEqual(limited.min(),30)
        self.assertLessEqual(limited.max(),220)
        np.testing.assert_allclose(limited[:,20],125,atol=1e-10)
