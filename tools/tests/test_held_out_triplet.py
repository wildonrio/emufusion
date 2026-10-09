import sys,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import verify_held_out_triplet as checker


class TripletTest(unittest.TestCase):
    def test_identity_and_negative_controls(self):
        a=dict(leftSequence=1,rightSequence=2,leftSubmission=10,rightSubmission=11,
               leftTimestampNs=100,rightTimestampNs=120,contiguousCapture=True)
        b=dict(leftSequence=2,rightSequence=3,leftSubmission=11,rightSubmission=12,
               leftTimestampNs=120,rightTimestampNs=140,contiguousCapture=True)
        plane=(1,1,b"abcd");result=({},dict(previousFull=plane,currentFull=plane))
        with tempfile.TemporaryDirectory() as directory:
            first,second=Path(directory)/"a.bin",Path(directory)/"b.bin"
            Path(str(first)+".json").write_text(json.dumps(a))
            for key,value in [(None,None),("leftSequence",3),("rightSubmission",13),
                              ("leftTimestampNs",121),("contiguousCapture",False)]:
                other=b.copy()
                if key:other[key]=value
                Path(str(second)+".json").write_text(json.dumps(other))
                with patch.object(checker,"read_dump",return_value=result):
                    if key:
                        with self.assertRaises(ValueError):checker.verify(first,second)
                    else:self.assertEqual(checker.verify(first,second)["reference_phase"],.5)
            Path(str(second)+".json").write_text(json.dumps(b))
            with patch.object(checker,"read_dump",side_effect=[result,({},dict(previousFull=(1,1,b"xxxx")))]):
                with self.assertRaises(ValueError):checker.verify(first,second)


if __name__=="__main__":unittest.main()
