import unittest
import numpy as np
from tools.analyze_midpoint_fields import raw_vectors,validated_vectors

class FieldDecodeTest(unittest.TestCase):
    def test_signed_q8(self):
        values=np.array([[[248,0,0,128],[8,0,255,128]]],dtype=np.uint8)
        np.testing.assert_array_equal(raw_vectors(values),[[[-8,.5],[8,-.5]]])

    def test_validated_zero_and_extremes(self):
        values=np.array([[128,128,255,255],[255,1,0,0]],dtype=np.uint8)
        np.testing.assert_allclose(validated_vectors(values),[[0,0],[38.4,-38.4]])
