"""Startup diagnostics must leave all existing operations unchanged."""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'engines/diagnostics'))
from prepare_restore_startup_probe import BEGIN, END, prepare


class RestoreStartupProbeTest(unittest.TestCase):
    def test_only_bounded_markers_added_to_exact_sources(self):
        core = ROOT/'engines/build/sources/aps3e-b5ae1af50d5e2f3b705506e7380a4504e086840b/app/src/main/cpp/rpcs3/rpcs3/Emu'
        for suffix in ('CPU/CPUThread.cpp', 'Cell/PPUThread.cpp'):
            with self.subTest(source=suffix):
                path = core/suffix
                original = path.read_bytes()
                result = prepare(original, path.name)
                recovered = re.sub(re.escape(BEGIN)+r'.*?'+re.escape(END), '', result, flags=re.S)
                self.assertEqual(recovered.encode(), original)
                self.assertIn('LucentRestoreStartup', result)
                with self.assertRaises(ValueError):
                    prepare(original+b' ', path.name)


if __name__ == '__main__':
    unittest.main()
