"""The replay bench's invented-content measure matches A and C at sub-pixel
phases of its scoring plane (2026-11-03): a correct move of thin, high-contrast
detail by a fraction of a scoring pixel is not invented, a double image is."""
import sys
from pathlib import Path
import unittest

try:
    import torch
except ImportError:  # PyTorch is an optional, very large research dependency.
    raise unittest.SkipTest("PyTorch is not installed")
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'qa'))
import replay_invented as RI

W, H, SCALE = 96, 54, 4


def full_image():
    """Irregular thin detail: 4 px bright vertical strokes (one scoring pixel
    wide) at random places on a dark ground, as text and foliage are."""
    rng = np.random.default_rng(7)
    img = np.full((H * SCALE, W * SCALE, 3), 40, np.uint8)
    for _ in range(260):
        y, x = rng.integers(0, H * SCALE - 12), rng.integers(0, W * SCALE - 4)
        img[y:y + 12, x:x + 4] = 230
    return img


def shifted(img, dx):
    """img moved dx full-size pixels right (bilinear), at full size."""
    return RI.fit(img, img.shape[1], img.shape[0], -dx, 0.0)


def invented(g, a, c, phases):
    refs = RI.references((a, c), W, H, phases)
    return 100.0 * RI.solid(RI.best_match(RI.t(g), refs) > RI.T).float().mean().item()


class SubpixelReferenceTest(unittest.TestCase):
    def test_perfect_fractional_move_is_not_invented(self):
        a = full_image()
        c = shifted(a, 6.0)
        middle = RI.fit(shifted(a, 3.0), W, H)          # 0.75 of a scoring pixel
        self.assertGreater(invented(middle, a, c, 1), 0.05)    # whole scoring pixels only
        self.assertLess(invented(middle, a, c, 4), 0.01)

    def test_double_image_stays_invented(self):
        a = full_image()
        c = shifted(a, 6.0)
        ghost = ((RI.fit(a, W, H).astype(np.int16) + RI.fit(c, W, H)) // 2).astype(np.uint8)
        # Phases forgive part of a ghost of detail this thin (2.6 -> 0.25%), but
        # it still exceeds the 10/10 bar.
        self.assertGreater(invented(ghost, a, c, 4), RI.MIN_AREA)

    def test_default_and_history_option(self):
        self.assertEqual(RI.PHASES, 4)
        source = (Path(RI.__file__)).read_text()
        self.assertIn("refs = references((p['previous'], p['current']), w, h)", source)
        self.assertIn("'--phases', type=int, default=PHASES", source)


if __name__ == '__main__':
    unittest.main()
