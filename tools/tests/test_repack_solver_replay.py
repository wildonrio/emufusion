import sys,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from prepare_held_out_case import outer_planes
from qa_repack_solver_replay import repack


class ReplayValidationTest(unittest.TestCase):
    def test_static_matches_and_confidence_ceiling(self):
        a=np.random.default_rng(3).integers(0,256,(8,12,4),dtype=np.uint8)
        p=outer_planes((12,8,a.tobytes()),(12,8,a.tobytes()))
        p['validated0']=(12,8,bytes([128,128,37,0])*96)
        r=repack({'history_width':12,'history_height':8,'flow_limits':[10]},p,[bytes(384),bytes(384)])
        self.assertEqual(r['validated0'][2][2::4],bytes([37])*96)
        self.assertEqual(r['validated1'][2][2::4],bytes([255])*96)
        self.assertEqual(r['previousFull'],p['previousFull'])

    def test_nonreciprocal_flow_rejected_even_on_flat_image(self):
        a=bytes([100,100,100,255])*96;p=outer_planes((12,8,a),(12,8,a))
        raw=bytes([4,0,0,0])*96
        r=repack({'history_width':12,'history_height':8,'flow_limits':[10]},p,[raw,bytes(384)])
        self.assertEqual(r['validated0'][2][2::4],bytes(96))


if __name__=='__main__':unittest.main()
