import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from verify_rife_transport_equivalence import verify


class EquivalenceTest(unittest.TestCase):
    def test_exact_pixels_and_reject_mismatches(self):
        with tempfile.TemporaryDirectory() as root:
            a,b = Path(root)/'a',Path(root)/'b'
            identity = {'native_library':'lib','flownet.param':'graph','flownet.bin':'weights'}
            def write(path, pixels):
                path.mkdir(exist_ok=True)
                (path/'generated.rgba').write_bytes(pixels)
                (path/'identity.json').write_text(json.dumps(identity))
                (path/'inference.json').write_text(json.dumps({
                    'input_manifest':{'width':1,'height':1,'inputs':'same'},
                    'generated_sha256':hashlib.sha256(pixels).hexdigest()}))
            write(a,b'\x01\x02\x03\xff');write(b,b'\x01\x02\x03\xff')
            self.assertTrue(verify(a,b)['transport_equivalent'])
            self.assertFalse(verify(a,b)['image_quality_qualified'])
            write(b,b'\x01\x00\x00\xff')
            with self.assertRaisesRegex(ValueError,'pixels differ'):verify(a,b)
            write(b,b'\x01\x02\x03\xff')
            (b/'identity.json').write_text(json.dumps(dict(identity,native_library='other')))
            with self.assertRaisesRegex(ValueError,'different build'):verify(a,b)


if __name__=='__main__':unittest.main()
