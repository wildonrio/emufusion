"""Copy paths must not quantize UV differently when flipping generated images.

The half-float experiment models a permitted mediump implementation, not a
claim that host arithmetic reproduces a particular Adreno shader compiler.
"""
from pathlib import Path
import struct
import unittest

SOURCE = Path(__file__).resolve().parents[2] / 'unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java'


def rounded(value, format):
    return struct.unpack(format, struct.pack(format, value))[0]


class CopyCoordinatePrecisionTest(unittest.TestCase):
    def test_copy_and_flipped_copy_use_matching_high_precision(self):
        source = SOURCE.read_text()
        for name in ('TEXTURE_COPY_SHADER', 'EXTERNAL_GENERATED_TEXTURE_COPY_SHADER'):
            shader = source.split('String ' + name + ' =', 1)[1].split(';\n\n', 1)[0]
            self.assertIn('precision highp float;', shader)
            self.assertNotIn('precision mediump float;', shader)

    def test_half_float_flip_can_move_sampling_by_visible_fraction_of_texel(self):
        errors = {}
        for precision in ('e', 'f'):
            maximum = 0.0
            for row in range(1080):
                uv = rounded((row + .5) / 1080, precision)
                # Sample an upside-down copy of the same 240-row texture.
                restored = 1.0 - rounded(1.0 - uv, precision)
                maximum = max(maximum, abs(restored - uv) * 240)
            errors[precision] = maximum
        self.assertGreater(errors['e'], .05)
        self.assertLess(errors['f'], .00002)


if __name__ == '__main__':
    unittest.main()
