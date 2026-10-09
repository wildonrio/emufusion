import sys,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from prepare_controlled_pan_case import pan
from qa_exact_pan_flow import exact_planes


class PanTest(unittest.TestCase):
    def test_oracle_signed_q8_8_and_endpoint_preservation(self):
        original={'previousFull':(1,1,bytes([1,2,3,255]))}
        result=exact_planes({'history_width':8,'history_height':2,'flow_limits':[38.4]},original)
        self.assertEqual(result['previousFull'],original['previousFull'])
        for direction,expected in [(0,4),(1,-4)]:
            raw=result[f'final{direction}'][2]
            self.assertEqual(len(raw),8*2*4)
            self.assertEqual(int.from_bytes(raw[:2],'big',signed=True)/256,expected)
            self.assertEqual(raw[2:4],bytes(2))
        self.assertNotIn('final0',original)

    def test_integer_translation_and_clamped_edge(self):
        source=np.arange(2*8*4).reshape(2,8,4)
        shifted=pan(source,2)
        np.testing.assert_array_equal(shifted[:,:6],source[:,2:])
        np.testing.assert_array_equal(shifted[:,-2:],np.repeat(source[:,-1:],2,axis=1))
        np.testing.assert_array_equal(pan(source,0),source)


if __name__=='__main__':unittest.main()
