"""Library UI keeps clear of a phone's camera cutout.

The window extends under the cutout (no black band when held sideways), so
the "PLAYSTATION 3" heading ran under the punch hole on the phone AVD. The
companion reports the cutout depth; the theme insets its UI layer, the root
footer, the preview and the status panel by it on both sides, while the
backgrounds stay full-bleed.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
THEME = (ROOT / 'theme/theme.qml').read_text(encoding='utf-8')
SERVICE = (ROOT / 'android-companion/src/com/thorium/preview/PreviewService.java').read_text(encoding='utf-8')
INSET = (ROOT / 'android-companion/src/com/thorium/preview/DisplayCutoutInset.java').read_text(encoding='utf-8')


class CutoutSafeInsetTest(unittest.TestCase):
    def test_companion_reports_cutout_depth(self):
        caps = SERVICE[SERVICE.index('"/capabilities".equals(path)'):]
        caps = caps[:caps.index('} else if')]
        self.assertIn('\\"cutoutInsetFraction\\":', caps)
        self.assertIn('DisplayCutoutInset.fraction(this)', caps)
        self.assertIn('Locale.US', caps, 'a comma decimal would break the JSON')
        self.assertIn('display.getCutout()', INSET)
        self.assertIn('Math.min(0.12, depth / (double) longSide)', INSET)
        self.assertIn('Build.VERSION.SDK_INT < 29', INSET)

    def test_theme_insets_ui_not_backgrounds(self):
        self.assertIn('Math.max(0, Math.min(0.12, cutout))', THEME)
        self.assertIn('Math.round(cutoutInsetFraction * Math.max(width, height))', THEME)
        chrome = THEME[THEME.index('        id: chrome\n'):][:200]
        self.assertIn('anchors.leftMargin: root.cutoutSafeInset', chrome)
        self.assertIn('anchors.rightMargin: root.cutoutSafeInset', chrome)
        # The update status line is centred (no edge inset needed).
        for item in ('id: footerViewName', 'id: displaySettingsHint', 'id: singleScreenPip'):
            block = THEME[THEME.index(item):][:1600]
            self.assertIn('root.cutoutSafeInset', block, item)
        # The first full-screen backdrop is still drawn edge to edge.
        backdrop = THEME[THEME.index('    Rectangle {\n        anchors.fill: parent\n        color: "#07090d"'):][:120]
        self.assertNotIn('Margin', backdrop)


if __name__ == '__main__':
    unittest.main()
