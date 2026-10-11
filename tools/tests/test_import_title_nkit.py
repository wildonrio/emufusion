"""Library titles drop the NKit container suffix.

Seen on the phone AVD library: "Mario Kart Double Dash.nkit". Rows already in
the registry pass through cleanTitle when read back, so they are fixed too.
"""
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.tests.test_first_install_startup import JAVA, ROOT, method

IMPORTER = ROOT / 'android-companion/src/com/thorium/preview/ImportManager.java'


class ImportTitleNkitTest(unittest.TestCase):
    def test_nkit_suffix_removed(self):
        body = method(IMPORTER.read_text(), '    private static String cleanTitle(')
        source = 'import java.util.*;\nimport java.util.regex.*;\npublic class TitleProbe {\n' + body + r'''
    public static void main(String[] args) {
        for (String value : args) System.out.println(cleanTitle(value));
    }
}
'''
        with tempfile.TemporaryDirectory(prefix='nkit-title-') as work:
            path = Path(work) / 'TitleProbe.java'
            path.write_text(source)
            subprocess.run([str(JAVA / 'javac'), '-d', work, str(path)], check=True,
                           capture_output=True, text=True, timeout=60)
            run = subprocess.run([str(JAVA / 'java'), '-cp', work, 'TitleProbe',
                                  'Mario Kart Double Dash.nkit', 'Super Mario Sunshine (USA).nkit',
                                  'Pikmin'], check=True, capture_output=True, text=True, timeout=30)
        lines = run.stdout.splitlines()
        self.assertEqual(lines[0], 'Mario Kart Double Dash')
        self.assertNotIn('nkit', lines[1].lower())
        self.assertEqual(lines[2], 'Pikmin')


if __name__ == '__main__':
    unittest.main()
