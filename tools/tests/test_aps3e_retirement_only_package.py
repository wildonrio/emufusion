"""Keep the no-added-trace candidate's metadata distinct from CPU diagnostics."""
import importlib.util
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'engines/diagnostics/package_spurs_trace.py'
spec = importlib.util.spec_from_file_location('retirement_package', SCRIPT)
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


class RetirementOnlyPackageTest(unittest.TestCase):
    def test_wrapper_cli_rejects_incomplete_composition(self):
        for flags in ([], ['--without-trace'], ['--combined-flip-retirement']):
            result = subprocess.run([
                'python3', str(SCRIPT), '--output-dir', '/nonexistent/unwritten',
                '--trace-library', '/nonexistent/unread', '--trace-sha256', '0' * 64,
                '--wrapper-sync-lifetime', *flags,
            ], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn('wrapper lifetime requires retained composition without tracing', result.stderr)

    def test_composed_retirement_retains_input_and_barrier_without_tracing(self):
        profile = package.trace_profile(adapter_input_only=True,
                                        getllar_read_barrier=True,
                                        combined_flip_retirement=True)
        self.assertIsNone(profile['helper'])
        self.assertIsNone(profile['targetAddress'])
        for correction in ('stick-direction release', 'GETLLAR', 'flip-retirement',
                           'no added tracing'):
            self.assertIn(correction, profile['traceScope'])
        for input_fix, barrier in ((False, False), (True, False), (False, True)):
            with self.assertRaises(ValueError):
                package.trace_profile(adapter_input_only=input_fix,
                                      getllar_read_barrier=barrier,
                                      combined_flip_retirement=True)

    def test_composed_cli_rejects_missing_retained_corrections(self):
        result = subprocess.run([
            'python3', str(SCRIPT), '--output-dir', '/nonexistent/unwritten',
            '--trace-library', '/nonexistent/unread', '--trace-sha256', '0' * 64,
            '--without-trace', '--combined-flip-retirement',
        ], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('combined flip retirement requires', result.stderr)

    def test_profile_has_no_guest_target_or_trace_helper(self):
        profile = package.trace_profile(retirement_only=True)
        self.assertIsNone(profile['targetAddress'])
        self.assertIsNone(profile['helper'])
        self.assertEqual(profile['sourcePatch'],
                         'engines/diagnostics/prepare_flip_retirement.py')
        self.assertIn('no added tracing', profile['traceScope'])

    def test_sampling_profile_cannot_be_labelled_retirement_only(self):
        for flags in ((True, False), (False, True), (True, True)):
            with self.assertRaises(ValueError):
                package.trace_profile(*flags, retirement_only=True)

    def test_cli_rejects_trace_flags_before_touching_output(self):
        for flag in ('--wsi-trace', '--core-error-trace', '--mfc-progress-trace',
                     '--spurs-workload-trace', '--ppu-wait-trace', '--render-progress-trace'):
            result = subprocess.run([
                'python3', str(SCRIPT), '--output-dir', '/nonexistent/unwritten',
                '--trace-library', '/nonexistent/unread', '--trace-sha256', '0' * 64,
                '--without-trace', '--retirement-only', flag,
            ], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn('retirement-only requires', result.stderr)


if __name__ == '__main__':
    unittest.main()
