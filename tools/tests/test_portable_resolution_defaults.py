"""Exercise PSP/N64 production resolution defaults under ASan/UBSan."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]

class PortableResolutionDefaultsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix='emufusion-portable-resolution-')
        cls.addClassCleanup(cls.directory.cleanup)
        cls.binary = str(Path(cls.directory.name) / 'resolution-test')
        subprocess.run(['cc', '-std=c11', '-O1', '-Wall', '-Wextra', '-Werror',
            '-fsanitize=address,undefined', '-pthread',
            str(ROOT / 'unified-android/native/tests/portable_resolution_test.c'),
            '-ldl', '-lm', '-o', cls.binary], check=True)

    def check_policy(self, system):
        result = subprocess.run([self.binary, system], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('fallback and geometry policy pass', result.stdout)

    def test_psp_default_and_override(self):
        self.check_policy('psp')

    def test_n64_default_and_override(self):
        self.check_policy('n64')

if __name__ == '__main__':
    unittest.main()
