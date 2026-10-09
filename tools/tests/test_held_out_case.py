import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from prepare_held_out_case import outer_planes


class HeldOutCaseTest(unittest.TestCase):
    def test_only_outer_pixels_can_enter_input(self):
        left=(2,2,bytes([10,20,30,255])*4)
        right=(2,2,bytes([40,50,60,255])*4)
        result=outer_planes(left,right)
        self.assertEqual(result['previousFull'],left)
        self.assertEqual(result['currentFull'],right)
        self.assertEqual(len(result),10)
        for d in range(2):
            self.assertEqual(result[f'final{d}'][2],bytes(16))
            self.assertEqual(result[f'seed{d}'][2],bytes(4))
        # No captured motion, hidden frame, or confidence parameter exists.
        import inspect
        self.assertEqual(list(inspect.signature(outer_planes).parameters),['previous','current'])


if __name__=='__main__':unittest.main()
