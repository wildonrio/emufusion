"""The game layer is opaque 8-bit: the library must never show through it.

RGBA_8888 made the media-overlay game layer translucent wherever a core left
alpha below 1: PS2 framebuffers (menu visible through the whole picture) and
aPS3e/Cemu letterbox bars (menu visible at the sides). RGBX_8888 keeps 8-bit
colour (the RGB_565 default banded Wii games on some phones) and is opaque.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
VIEW = (ROOT / 'unified-android/src/com/thorium/preview/game/GameSurfaceView.java').read_text()


class GameSurfaceOpaqueTest(unittest.TestCase):
    def test_opaque_8bit_format(self):
        self.assertIn('getHolder().setFormat(android.graphics.PixelFormat.RGBX_8888);', VIEW)
        self.assertNotIn('PixelFormat.RGBA_8888', VIEW)
        self.assertIn('setZOrderMediaOverlay(true);', VIEW)


if __name__ == '__main__':
    unittest.main()
