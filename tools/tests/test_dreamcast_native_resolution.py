"""Run the real native host's Dreamcast option selection with sanitizers."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]

class DreamcastNativeResolutionTest(unittest.TestCase):
    def test_real_host_option_selection(self):
        with tempfile.TemporaryDirectory(prefix='emufusion-dc-resolution-') as directory:
            binary = str(Path(directory) / 'resolution-test')
            subprocess.run(['cc', '-std=c11', '-O1', '-Wall', '-Wextra', '-Werror',
                '-fsanitize=address,undefined', '-pthread',
                str(ROOT / 'unified-android/native/tests/dreamcast_resolution_test.c'),
                '-ldl', '-lm', '-o', binary], check=True)
            result = subprocess.run([binary], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('supported override and fallback pass', result.stdout)

if __name__ == '__main__':
    unittest.main()
