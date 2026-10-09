import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('rgba_compare',
    Path(__file__).resolve().parents[1] / 'qa/compare_rife_rgba.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class RgbaComparisonTest(unittest.TestCase):
    def test_rgb_separate_from_alpha(self):
        result = module.compare(bytes([0,10,20,255]),bytes([0,13,20,0]))
        self.assertEqual(result['rgb_mae_255'],1)
        self.assertEqual(result['rgb_max_error_255'],3)
        self.assertEqual(result['different_pixels'],1)
        self.assertFalse(result['alpha_equal'])
        self.assertFalse(result['image_quality_qualified'])

    def test_invalid_sizes_rejected(self):
        for left,right in ((b'',b''),(b'1234',b'123'),(b'123',b'123')):
            with self.assertRaises(ValueError): module.compare(left,right)
