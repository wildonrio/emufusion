"""The library "Updating" panel sits LEFT of the single-screen preview.

Owner, 2026-10-11: "Updating box should appear to the left of the preview video
not below it." On single-screen devices the preview is the upper-right PiP;
the panel is top-aligned with it, to its left, and never overlaps it. The Thor
(dual screen) keeps the panel in its corner.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
THEME = (ROOT / 'theme/theme.qml').read_text(encoding='utf-8')


class ImportToastPlacementTest(unittest.TestCase):
    def test_left_of_preview_top_aligned(self):
        toast = THEME[THEME.index('        id: importToast'):][:1600]
        self.assertIn('property bool besidePreview: !root.dualScreenDevice && singleScreenPip.visible', toast)
        self.assertIn('x: besidePreview ? singleScreenPip.x - width - 16 : 0', toast)
        self.assertIn('y: besidePreview ? singleScreenPip.y : 0', toast)
        self.assertIn('singleScreenPip.x - 16 - 56 - root.cutoutSafeInset', toast)
        self.assertNotIn('singleScreenPip.y + singleScreenPip.height', toast)
        self.assertIn('anchors.right: besidePreview ? undefined : parent.right', toast)


if __name__ == '__main__':
    unittest.main()
