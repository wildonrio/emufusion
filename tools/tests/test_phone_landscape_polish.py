"""Phone-landscape polish found by the October 8 clean-phone survey.

1. Landscape windows left a 128px black band beside the camera cutout.
2. Settings showed the theme's own version constant, not the installed app's.
3. aPS3e's first-launch progress title read "PROGRESS DIALOG COMPILING PPU
   MODULES": its interface strings were never published to the library.
(Footer overlap: test_footer_legend_fit.py; pause menu: test_pause_menu_fits_short_screens.py.)
"""
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / 'unified-android/src/com/thorium/preview'


def read(path):
    return path.read_text(encoding='utf-8')


class CutoutTest(unittest.TestCase):
    def test_frontend_and_game_windows_extend_into_the_cutout(self):
        full = read(SRC / 'FullDisplayWindow.java')
        helper = full.split('public static void extendIntoCutout(Window window) {', 1)[1].split('\n    }', 1)[0]
        self.assertIn('Build.VERSION.SDK_INT < 28) return;', helper)
        self.assertIn('LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES', helper)
        self.assertIn('window.setAttributes(attributes);', helper)
        apply_once = full.split('private static void applyOnce(Activity activity) {', 1)[1]
        self.assertIn('extendIntoCutout(activity.getWindow());', apply_once.split('\n', 3)[2])
        game = read(SRC / 'game/LucentGameActivity.java')
        immersive = game.split('private void enterImmersiveMode() {', 1)[1].split('\n    }', 1)[0]
        self.assertIn('FullDisplayWindow.extendIntoCutout(getWindow());', immersive)


class VersionLabelTest(unittest.TestCase):
    def test_labels_show_the_installed_app_version(self):
        update = read(ROOT / 'android-companion/src/com/thorium/preview/UpdateManager.java')
        self.assertIn('installedAppVersion = currentVersionName();', update)
        self.assertIn('value.put("appVersion", installedAppVersion);', update)
        theme = read(ROOT / 'theme/theme.qml')
        self.assertIn('if (payload.appVersion) root.installedAppVersion = String(payload.appVersion)', theme)
        self.assertIn('installedAppVersion : lucentVersion', theme)
        self.assertEqual(3, theme.count('root.displayVersion'))
        self.assertNotIn('" + root.lucentVersion', theme)


class Aps3eStringsTest(unittest.TestCase):
    def test_strings_are_published_before_the_library_loads(self):
        directory = read(SRC / 'game/NativeAdapterSystemDirectory.java')
        prepare = directory.split('static File prepareForOpen(Context context, String engineId, String systemId,\n', 1)[1]
        prepare = prepare.split('\n    }', 1)[0]
        self.assertIn('String[] strings = Aps3eLocalizedStrings.KEYS_AND_VALUES;', prepare)
        self.assertIn('Os.setenv(strings[i], strings[i + 1], false);', prepare)
        self.assertLess(prepare.index('APS3E_DATA_DIR'), prepare.index('Aps3eLocalizedStrings'))

    def test_table_has_english_text_for_the_progress_dialog(self):
        table = read(SRC / 'game/Aps3eLocalizedStrings.java')
        self.assertIn('"PROGRESS_DIALOG_COMPILING_PPU_MODULES", "Compiling PPU Modules...",', table)
        self.assertIn('"PROGRESS_DIALOG_BUILDING_SPU_CACHE", "Building SPU Cache...",', table)
        self.assertGreater(table.count('\n            "'), 250)

    def test_table_matches_the_pinned_aps3e_source(self):
        if not (ROOT / 'engines/build/sources/aps3e-b5ae1af50d5e2f3b705506e7380a4504e086840b').is_dir():
            self.skipTest('pinned aPS3e source is local-only (engines/build)')
        run = subprocess.run([sys.executable, str(ROOT / 'tools/generate_aps3e_localized_strings.py'), '--check'],
                             capture_output=True, text=True)
        self.assertEqual(0, run.returncode, run.stdout + run.stderr)


if __name__ == '__main__':
    unittest.main()
