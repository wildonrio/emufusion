import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from run_native_rife_device_probe import validate_geometry


class ProbeGeometryTest(unittest.TestCase):
    def geometry(self, width, height, analysis=None, pipeline=True):
        return validate_geometry(dict(width=width, height=height, phase=.5,
                                      format='RGBA8-bottom-up'), analysis, pipeline)

    def test_native_switch_and_legacy_geometry(self):
        for width, height in ((1920, 1080), (1280, 720), (256, 192), (256, 240)):
            self.assertEqual(self.geometry(width, height), (width, height, width))

    def test_exact_aspect_reduction(self):
        self.assertEqual(self.geometry(1920, 1080, 640), (1920, 1080, 640))
        self.assertEqual(self.geometry(256, 240, 128), (256, 240, 128))

    def test_invalid_or_rounded_geometry_rejected(self):
        for width, height, analysis in ((1920,1080,641), (0,720,None),
                                        (1921,1080,None), (1280,1081,None),
                                        (1280,720,1920), (1280,720,0)):
            with self.assertRaises(ValueError):
                self.geometry(width, height, analysis)

    def test_other_probe_modes_remain_legacy_only(self):
        self.assertEqual(self.geometry(256,192,pipeline=False), (256,192,256))
        for values in ((1920,1080,None), (256,240,None), (256,192,128)):
            with self.assertRaises(ValueError):
                self.geometry(*values,pipeline=False)


if __name__ == '__main__':
    unittest.main()
