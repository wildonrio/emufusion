import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'engines/diagnostics/prepare_ppu_usleep_trace.py'
SOURCE = ROOT / ('engines/build/sources/aps3e-b5ae1af50d5e2f3b705506e7380a4504e086840b/'
                 'app/src/main/cpp/rpcs3/rpcs3/Emu/Cell/lv2/sys_timer.cpp')
spec = importlib.util.spec_from_file_location('ppu_wait_trace', SCRIPT)
trace = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trace)


class PpuWaitTraceTest(unittest.TestCase):
    def test_original_source_is_exactly_preserved(self):
        original = SOURCE.read_bytes()
        result = trace.instrument(original)
        self.assertEqual(result.replace(trace.additions(), '', 1).replace(trace.HOOK, '', 1),
                         original.decode())
        self.assertIn('vm::check_addr(first, vm::page_readable | vm::page_executable, 128)', trace.HOOK)
        self.assertNotIn('g_sudo_addr', trace.HOOK)

    def test_source_drift_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'changed'):
            trace.instrument(SOURCE.read_bytes() + b'\n// other agent\n')

    def test_existing_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'sys_timer.cpp'
            output.write_text('other agent data')
            run = subprocess.run(['python3', str(SCRIPT), '--source', str(SOURCE),
                                  '--output', str(output)], capture_output=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertEqual(output.read_text(), 'other agent data')

    def test_actual_budget_rejects_wraparound_and_caps_all_work(self):
        code = r'''
#include "lucent_ppu_wait_trace.h"
#include <cassert>
int main() {
    lucent_ppu_wait::budget b;
    uint64_t now=0; unsigned clocks=0;
    auto clock=[&] { ++clocks; return now; };
    assert(b.sample(clock));
    for(unsigned i=0;i<1000;++i) assert(!b.sample(clock));
    now=1000000; assert(b.sample(clock));
    now=0; assert(!b.sample(clock));
    for(unsigned i=0;i<1000;++i) { now+=1000000; b.sample(clock); }
    assert(b.samples==600);
    const auto old=clocks; assert(!b.sample(clock)); assert(clocks==old);
    assert(!b.new_code_site(0)); assert(!b.new_code_site(63));
    assert(!b.new_code_site(65)); assert(!b.new_code_site(0x100000000ULL));
    assert(!b.new_code_site(0xfffffffcULL)); assert(b.new_code_site(0xffffffbcULL));
    assert(!b.new_code_site(0xffffffbcULL));
    for(unsigned i=0;i<7;++i) assert(b.new_code_site(0x10000+128*i));
    assert(!b.new_code_site(0x20000)); assert(b.code_sites==8);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'test.cpp'
            source.write_text(code)
            binary = Path(directory) / 'test'
            subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                            '-fno-exceptions', '-fsanitize=address,undefined',
                            '-I', str(trace.HEADER.parent), str(source), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    unittest.main()
