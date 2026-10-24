"""The all-systems header shows only real companies, with no blank slots.

Owner, 2026-10-24: black areas where a logo seemed missing, and logos for
companies whose systems had no game. The gaps were fixed-width slots around
square marks (NEC's mark was 80 px of a 300 px square) and dark official
marks on the dark header (3DO, Sinclair, Commodore). A Microsoft logo came from
the lone PC Engine CD title being filed under "Microsoft Windows".
"""
import re
import unittest

from PIL import Image

from tools.tests.test_first_install_startup import ROOT

THEME = ROOT / 'theme/theme.qml'
BRANDS = ROOT / 'theme/assets/brands'
IMPORTER = ROOT / 'android-companion/src/com/thorium/preview/ImportManager.java'


class LibraryBrandRowTest(unittest.TestCase):
    def setUp(self):
        self.theme = THEME.read_text()

    def test_each_mark_takes_its_own_width_and_missing_marks_take_none(self):
        row = self.theme[self.theme.index('model: root.availableBrandSlugs\n\n'):][:2200]
        self.assertIn('brandMark.status === Image.Ready', row)
        self.assertIn('brandMark.implicitWidth / brandMark.implicitHeight', row)
        self.assertIn('visible: loaded', row)
        self.assertNotIn('modelData === "sony" ? 130', row)
        self.assertIn('visible: root.brandLogoIsDark(modelData)', row)

    def test_dark_marks_are_drawn_white_in_the_header_too(self):
        helper = self.theme[self.theme.index('function useWhiteBrandLogo(index) {'):][:200]
        self.assertIn('if (brandLogoIsDark(brandSlugForSystem(index))) return true', helper)
        for slug in ('3do', 'sinclair', 'commodore'):
            self.assertIn('slug === "%s"' % slug, self.theme)

    def test_marks_carry_no_transparent_margins(self):
        for path in sorted(BRANDS.glob('*.png')):
            image = Image.open(path).convert('RGBA')
            self.assertEqual(image.getchannel('A').getbbox(), (0, 0) + image.size,
                             f'{path.name} has transparent margins')

    def test_every_game_is_filed_under_its_own_system(self):
        source = IMPORTER.read_text()
        self.assertNotIn('"Microsoft Windows" : system.collection', source)
        self.assertIn('out.append("\\ncollection: ").append(system.collection)', source)

    def test_brands_come_only_from_systems_with_games(self):
        rebuild = self.theme[self.theme.index('function rebuildVisibleSystems() {'):][:600]
        self.assertIn('collection.games.count <= 0', rebuild)
        refresh = self.theme[self.theme.index('function refreshAvailableBrands() {'):][:600]
        self.assertTrue(re.search(r'for \(var index = 1; index < systemModel\.count', refresh))


if __name__ == '__main__':
    unittest.main()
