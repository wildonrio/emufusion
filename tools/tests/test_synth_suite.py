"""The synthetic frame-generation suite writes exact, deterministic ground truth."""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

try:
    import numpy as np
    from PIL import Image
    from tools.learned_framegen import synth_suite
except ImportError:  # numpy/Pillow absent: the suite cannot run here
    synth_suite = None


@unittest.skipIf(synth_suite is None, "numpy and Pillow are required")
class SynthSuiteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        synth_suite.generate(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def load(self, case, idx, key):
        return np.asarray(Image.open(self.root / case / f'{idx:04d}' / f'{key}.png').convert('RGB')).astype(np.int16)

    def test_cases_and_layout(self):
        cases = sorted(p.name for p in self.root.iterdir())
        for expected in ('pan02', 'pan24', 'hud_over_pan', 'object32', 'spriteflat48', 'spritetex32',
                         'rotate', 'text_appears', 'text_vanishes', 'fade', 'pixel_scroll1', 'pixel_scroll2'):
            self.assertIn(expected, cases)
        meta = json.loads((self.root / 'pan02' / '0000' / 'meta.json').read_text())
        self.assertEqual((meta['case'], meta['phase']), ('pan02', 0.5))
        self.assertEqual(self.load('pan02', 0, 'A').shape, (synth_suite.H, synth_suite.W, 3))

    def test_pan_middle_frame_is_the_exact_midpoint(self):
        a, b, c = (self.load('pan12', 0, k) for k in 'ABC')
        # The scene moves 12 px between A and C: B is A moved by 6, C by 12.
        self.assertTrue((b[:, :-6] == a[:, 6:]).all())
        self.assertTrue((c[:, :-12] == a[:, 12:]).all())

    def test_fade_is_linear(self):
        a, b, c = (self.load('fade', 0, k) for k in 'ABC')
        self.assertLessEqual(np.abs((a + c) / 2 - b).max(), 1.0)

    def test_deterministic(self):
        with tempfile.TemporaryDirectory() as other:
            synth_suite.generate(other)
            for rel in ('spritetex32/0000/B.png', 'text_vanishes/0003/A.png', 'pixel_scroll1/0002/B.png'):
                self.assertEqual(hashlib.sha256((self.root / rel).read_bytes()).hexdigest(),
                                 hashlib.sha256((Path(other) / rel).read_bytes()).hexdigest(), rel)


if __name__ == '__main__':
    unittest.main()
