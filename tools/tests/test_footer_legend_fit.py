"""Footer button legends must not run into the view label on narrow phones.

October 9 clean-phone run (1152 px window): the right-aligned legends drew over
"COVER VIEW" / "SYSTEM VIEW" and the cover-row hint. Wide windows (the Thor's
1920 px) must render exactly as before, so the legends only fall back to a
compact set, then shrink, when the full text does not fit.
"""
from pathlib import Path
import unittest

THEME = (Path(__file__).resolve().parents[2] / 'theme' / 'theme.qml').read_text(encoding='utf-8')


def block(start):
    index = THEME.index(start)
    return THEME[index:index + 2600]


class FooterLegendFitTest(unittest.TestCase):
    def test_left_labels_bound_the_legends(self):
        left = THEME.split('readonly property real footerLegendLeft:', 1)[1].split('\n\n', 1)[0]
        self.assertIn('footerViewName.x + footerViewName.paintedWidth', left)
        self.assertIn('coverNavigationHint.x + coverNavigationHint.paintedWidth', left)
        self.assertIn('id: footerViewName', THEME)
        self.assertIn('id: coverNavigationHint', THEME)

    def test_both_legends_fit_without_changing_wide_layouts(self):
        for start, metrics in (('"L1 / R1  SORT     L2 / R2  SYSTEM', 'gamesLegendMetrics'),
                               ('id: displaySettingsHint', 'homeLegendMetrics')):
            start = THEME.rfind('Text {', 0, THEME.index(start))
            legend = THEME[start:start + 2600]
            self.assertIn('width: Math.max(0, parent.width - root.footerSideMargin - root.footerLegendLeft)', legend)
            self.assertIn('horizontalAlignment: Text.AlignRight', legend)
            self.assertIn('fontSizeMode: Text.HorizontalFit', legend)
            self.assertIn('font.pixelSize: root.footerFontSize', legend)
            self.assertIn(metrics + '.advanceWidth <= width ? fullLegend :', legend)
            self.assertRegex(legend, r'text: (gamesLegend|displaySettingsHint)\.fullLegend')
            self.assertNotIn('parent.fullLegend', legend)

    def test_settings_tap_target_stays_on_the_painted_legend(self):
        legend = block('id: displaySettingsHint')
        mouse = legend.split('MouseArea {', 1)[1].split('}', 1)[0]
        self.assertIn('width: parent.paintedWidth + 36', mouse)
        self.assertNotIn('anchors.fill: parent', mouse)


if __name__ == '__main__':
    unittest.main()
