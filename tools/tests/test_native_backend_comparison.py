import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class NativeBackendComparisonTest(unittest.TestCase):
    def test_scoring_and_identity_check(self):
        script = Path(__file__).resolve().parents[1] / 'score_native_backend_comparison.py'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case, inference = root/'case', root/'inference'
            case.mkdir(); inference.mkdir()
            def frame(value):
                return bytes([value, value, value, 255]) * (256*192)
            left, right, truth = frame(0), frame(100), frame(50)
            (case/'native-left.rgba').write_bytes(left)
            (case/'native-right.rgba').write_bytes(right)
            (case/'withheld-reference.rgba').write_bytes(truth)
            (inference/'generated.rgba').write_bytes(truth)
            sha = lambda data: hashlib.sha256(data).hexdigest()
            metadata = {'input_manifest': {'inputs': {
                'left.rgba': {'sha256': sha(left)}, 'right.rgba': {'sha256': sha(right)}}},
                'generated_sha256': sha(truth)}
            (inference/'inference.json').write_text(json.dumps(metadata))
            result = subprocess.run([sys.executable, str(script), str(case), str(inference)], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            scores = json.loads((inference/'comparison.json').read_text())
            self.assertEqual(scores['scores']['generated']['changing_rgb_mae'], 0)
            self.assertEqual(scores['scores']['hold_left']['changing_rgb_mae'], 50)
            self.assertFalse(scores['image_quality_qualified'])
            (inference/'generated.rgba').write_bytes(left)
            rejected = subprocess.run([sys.executable, str(script), str(case), str(inference)], capture_output=True)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn(b'hash mismatch', rejected.stderr)


if __name__ == '__main__':
    unittest.main()
