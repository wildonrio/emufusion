"""Library update status is one line of text at the top centre (no panel).

Owner, 2026-10-11: "let's just move it into ... just a one line text at the
very top middle of the screen ... instead of a box. The box is just annoying."
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
THEME = (ROOT / 'theme/theme.qml').read_text(encoding='utf-8')


class ImportStatusLineTest(unittest.TestCase):
    def test_single_centred_line(self):
        block = THEME[THEME.index('        id: importToast\n'):][:2200]
        # Screen-centred when it fits, else kept between the mark and the icons.
        self.assertIn('(parent.width - width) / 2', block)
        self.assertIn('property real freeLeft: root.cutoutSafeInset + topBar.x + 230 + 24', block)
        self.assertIn('voiceFeedbackButton.x', block)
        self.assertIn('y: 34 + Math.round((58 - height) / 2)', block)
        self.assertIn('text: root.importStatusLineText()', block)
        self.assertIn('maximumLineCount: 1', block)
        self.assertIn('elide: Text.ElideRight', block)
        # No panel: no border, background plate or progress bar.
        self.assertNotIn('border.width', block)
        self.assertNotIn('color: "#ee0b0f16"', block)

    def test_line_text(self):
        fn = THEME[THEME.index('function importStatusLineText()'):][:700]
        self.assertIn('"Updating library  •  "', fn)
        self.assertIn('importCurrent + " of " + importTotal', fn)
        self.assertIn('"Library update paused  •  "', fn)


if __name__ == '__main__':
    unittest.main()
