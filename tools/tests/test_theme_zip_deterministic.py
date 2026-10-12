"""The bundled theme archive depends only on theme paths and contents."""
from pathlib import Path
import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "unified-android/tools/zip_theme_deterministic.py"
BUILD = (ROOT / "unified-android/build.sh").read_text()


class ThemeZipDeterministicTest(unittest.TestCase):
    def make(self, theme, output):
        subprocess.run([sys.executable, str(TOOL), str(theme), str(output)], check=True)
        return hashlib.sha256(output.read_bytes()).hexdigest()

    def test_timestamps_and_order_do_not_change_the_archive(self):
        with tempfile.TemporaryDirectory(prefix="theme-zip-") as tmp:
            theme = Path(tmp, "theme")
            (theme / "assets/branding").mkdir(parents=True)
            (theme / "theme.qml").write_text("import QtQuick 2.0\n")
            (theme / "assets/branding/icon.png").write_bytes(b"\x89PNG fixture")
            first = self.make(theme, Path(tmp, "a.zip"))
            os.utime(theme / "theme.qml", (1_000_000_000, 1_000_000_000))
            second = self.make(theme, Path(tmp, "b.zip"))
            self.assertEqual(first, second)
            (theme / "theme.qml").write_text("import QtQuick 2.15\n")
            self.assertNotEqual(first, self.make(theme, Path(tmp, "c.zip")))
            with zipfile.ZipFile(Path(tmp, "c.zip")) as archive:
                self.assertEqual(["assets/branding/icon.png", "theme.qml"], archive.namelist())
                self.assertEqual(b"import QtQuick 2.15\n", archive.read("theme.qml"))

    def test_symlinks_are_refused(self):
        with tempfile.TemporaryDirectory(prefix="theme-zip-") as tmp:
            theme = Path(tmp, "theme")
            theme.mkdir()
            (theme / "real.qml").write_text("x")
            (theme / "link.qml").symlink_to(theme / "real.qml")
            result = subprocess.run([sys.executable, str(TOOL), str(theme), str(Path(tmp, "a.zip"))],
                                    capture_output=True, text=True)
            self.assertNotEqual(0, result.returncode)

    def test_build_uses_the_deterministic_archive(self):
        self.assertIn('tools/zip_theme_deterministic.py" "$ROOT_DIR/theme"', BUILD)
        self.assertNotIn("/usr/bin/zip -q -r \"$THEME_ARCHIVE", BUILD)


if __name__ == "__main__":
    unittest.main()
