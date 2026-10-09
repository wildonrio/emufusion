import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import analyze_real_flow_alignment as analysis


class RealFlowAlignmentTest(unittest.TestCase):
    def fixture(self, reverse=False):
        w,h=32,4
        row=[(x*73)%256 for x in range(w)]
        row[-1]=row[-2]
        def rgba(values):
            return bytes(v for _ in range(h) for c in values for v in (c,c,c,255))
        planes={"previousFull":(w,h,rgba(row)),
                "currentFull":(w,h,rgba([row[0]]+row[:-1]))}
        for d,motion in [(0,-256),(1,256)]:
            if reverse: motion=-motion
            planes[f"final{d}"]=(w,h,(motion.to_bytes(2,"big",signed=True)+b"\0\0")*(w*h))
            planes[f"validated{d}"]=(w,h,bytes([128,128,255,255])*(w*h))
        return {"history_width":w,"history_height":h,"flow_limits":[32,32]},planes

    def test_correct_forward_and_backward_correspondence(self):
        with patch.object(analysis,"read_dump",return_value=self.fixture()):
            result=analysis.analyze("unused")
        for direction in result["directions"]:
            self.assertGreater(direction["changed"]["pixels"],0)
            self.assertEqual(direction["changed"]["mean_warped_error"],0)

    def test_wrong_direction_is_not_accepted_as_aligned(self):
        with patch.object(analysis,"read_dump",return_value=self.fixture(True)):
            result=analysis.analyze("unused")
        for direction in result["directions"]:
            self.assertGreater(direction["changed"]["mean_warped_error"],40)


if __name__=="__main__":
    unittest.main()
