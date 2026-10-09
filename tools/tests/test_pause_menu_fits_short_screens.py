"""The in-game pause menu must show every row on short landscape screens.

October 8 clean-phone survey: on a 1280x720 phone the six-row menu pushed
"Exit to EmuFusion" below the window until the list was scrolled. The Thor's
1080px panel at density 2.30625 is even shorter in dp, so its title was cut
when Exit had focus.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
HOST = (ROOT / 'unified-android/src/com/thorium/preview/game/InWindowGameHost.java').read_text()
BODY = HOST[HOST.index('    private FrameLayout createPauseOverlay() {'):
            HOST.index('     * Lazily builds the multiplayer invite/schedule overlay')]


def layout(height_px, density, rows):
    """Mirror of createPauseOverlay's sizing, in pixels."""
    dp = lambda v: round(v * density)
    available = height_px - dp(32)
    compact = dp(28 + 30) + dp(54 + 8) + rows * dp(58 + 8) > available
    gap = dp(6) if compact else dp(8)
    title = dp(40) if compact else dp(54)
    pad = (dp(16), dp(16)) if compact else (dp(28), dp(30))
    row = dp(58)
    if compact:
        row = max(dp(40), min(dp(58), (available - pad[0] - pad[1] - title - gap) // rows - gap))
    total = pad[0] + pad[1] + title + gap + rows * (row + gap)
    return compact, row, total, available


class PauseMenuFitTest(unittest.TestCase):
    def test_sizing_code_is_what_the_mirror_assumes(self):
        for line in ('int available = activity.getResources().getDisplayMetrics().heightPixels - dp(32);',
                     'boolean compact = dp(28 + 30) + dp(54 + 8) + rows * dp(58 + 8) > available;',
                     'int gap = compact ? dp(6) : dp(8);',
                     'int titleHeight = compact ? dp(40) : dp(54);',
                     '(available - padTop - padBottom - titleHeight - gap) / rows - gap));',
                     'panel.addView(title, pauseRowParams(titleHeight, gap));'):
            self.assertIn(line, BODY)
        self.assertEqual(7, BODY.count('pauseRowParams(rowHeight, gap)'))
        self.assertNotIn('rowParams(dp(58))', BODY)
        self.assertIn('ScrollView scroller = new ScrollView(activity);', BODY)
        # A long game name shrinks onto one line instead of wrapping under Resume.
        self.assertIn('title.setMaxLines(1);', BODY)
        self.assertIn('setAutoSizeTextTypeUniformWithConfiguration(', BODY)

    def test_every_row_fits_on_a_720px_phone_and_the_thor(self):
        for name, height, density in (('phone 720p @1.5', 720, 1.5), ('Thor 1080p @2.30625', 1080, 2.30625)):
            compact, row, total, available = layout(height, density, 6)
            self.assertTrue(compact, name)
            self.assertLessEqual(total, available, name)
            self.assertGreaterEqual(row, round(40 * density), name)

    def test_tall_screens_keep_the_original_menu(self):
        compact, row, _, _ = layout(1440, 2.0, 6)
        self.assertFalse(compact)
        self.assertEqual(row, 116)


if __name__ == '__main__':
    unittest.main()
