import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'engines/diagnostics'))
import prepare_restore_execution_probe as probe
import prepare_mfc_progress_trace as mfc
from package_spurs_trace import trace_profile


class RestoreExecutionProbeTest(unittest.TestCase):
    def test_normal_input_profile_still_rejects_mfc_without_restore_scope(self):
        with self.assertRaises(ValueError):
            trace_profile(mfc_progress=True, adapter_input_only=True)
        result = trace_profile(mfc_progress=True, adapter_input_only=True,
                               getllar_read_barrier=True, combined_flip_retirement=True,
                               restore_diagnostic=True)
        self.assertEqual(result['sourcePatch'], 'engines/patches/aps3e-lucent-adapter.cpp')

    def test_only_markers_and_retained_barrier_extend_reviewed_mfc_probe(self):
        source = (ROOT/'engines/build/sources/aps3e-b5ae1af50d5e2f3b705506e7380a4504e086840b/app/src/main/cpp/rpcs3/rpcs3/Emu/Cell/SPUThread.cpp').read_bytes()
        result = probe.instrument(source)
        self.assertEqual(result.count(probe.BARRIER), 1)
        stripped = re.sub(re.escape(probe.BEGIN)+r'.*?'+re.escape(probe.END), '', result, flags=re.S)
        self.assertEqual(stripped, mfc.instrument(source))
        with self.assertRaises(ValueError):
            probe.instrument(source+b' ')


if __name__ == '__main__':
    unittest.main()
