import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
DIAG = ROOT / 'engines/diagnostics'
SOURCE = ROOT / 'engines/build/sources/aps3e-b5ae1af50d5e2f3b705506e7380a4504e086840b/app/src/main/cpp/rpcs3/rpcs3/Emu/RSX/VK/VKPresent.cpp'
sys.path.insert(0, str(DIAG))
try:
    spec = importlib.util.spec_from_file_location('render_progress', DIAG / 'prepare_render_progress.py')
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
finally:
    sys.path.pop(0)


class RenderProgressTest(unittest.TestCase):
    def test_packaging_rejects_mixed_cpu_or_verbose_trace(self):
        for flag in ('--wsi-trace', '--ppu-wait-trace', '--mfc-progress-trace',
                     '--spurs-workload-trace', '--core-error-trace'):
            run = subprocess.run([
                sys.executable, str(DIAG / 'package_spurs_trace.py'),
                '--output-dir', '/nonexistent/unwritten', '--trace-library', '/nonexistent/unread',
                '--trace-sha256', '0' * 64, '--without-trace', '--render-progress-trace', flag,
            ], capture_output=True, text=True)
            self.assertEqual(run.returncode, 2)
            self.assertIn('render-progress requires', run.stderr)

    def test_rejects_source_drift(self):
        with self.assertRaises(ValueError):
            generator.instrument(b'other agent edits')

    @unittest.skipUnless(SOURCE.is_file(), 'pinned local source absent')
    def test_reversible_instrumentation_and_single_driver_calls(self):
        payload = SOURCE.read_bytes()
        text, edits = generator.instrument(payload)
        original = text
        for old, new in reversed(edits):
            self.assertEqual(text.count(new), 1)
            text = text.replace(new, old, 1)
        self.assertEqual(text, generator.prepare(payload))
        for operation in ('m_swapchain->present(', 'queue_swap_request(',
                          'm_swapchain->acquire_next_swapchain_image(',
                          '_vkDeviceWaitIdle(', 'get_present_source('):
            self.assertEqual(original.count(operation), payload.decode().count(operation))
        self.assertEqual(payload, SOURCE.read_bytes())

    @unittest.skipUnless(SOURCE.is_file(), 'pinned local source absent')
    def test_refuses_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'source.cpp'
            output.write_text('preserve')
            run = subprocess.run([sys.executable, str(DIAG / 'prepare_render_progress.py'),
                                  '--source', str(SOURCE), '--output', str(output)], capture_output=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertEqual(output.read_text(), 'preserve')

    @unittest.skipUnless(shutil.which('c++'), 'compiler absent')
    def test_gate_counts_every_call_but_limits_sampling(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'test.cpp'
            binary = Path(directory) / 'test'
            source.write_text('''#include "lucent_render_progress.h"
#include <cassert>
int main() {
    lucent_render_progress::Gate gate, other;
    assert(gate.sample(0));
    for (unsigned t = 1; t < 1000; ++t) assert(!gate.sample(t));
    assert(gate.calls == 1000);
    assert(gate.sample(1000));
    assert(!gate.sample(1000));
    assert(gate.sample(5000));
    assert(other.sample(5000));
    assert(other.calls == 1 && gate.calls == 1003);
}
''')
            subprocess.run(['c++', '-std=c++20', '-Wall', '-Wextra', '-Werror',
                            '-fsanitize=address,undefined', '-I', str(DIAG),
                            str(source), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    unittest.main()
