import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
DIAG = ROOT / 'engines/diagnostics'
sys.path.insert(0, str(DIAG))
import prepare_spurs_workload_trace as trace

SOURCE = ROOT / ('engines/build/sources/aps3e-b5ae1af50d5e2f3b705506e7380a4504e086840b/'
                 'app/src/main/cpp/rpcs3/rpcs3/Emu/Cell/SPUThread.cpp')


class SpursWorkloadTraceTest(unittest.TestCase):
    def test_preserves_original_body_and_rejects_source_drift(self):
        payload = SOURCE.read_bytes()
        result = trace.instrument(payload)
        helper = '\n' + trace.HEADER.read_text().replace('#pragma once\n', '', 1) + '\n'
        restored = result.replace(helper, '', 1).replace(trace.NEW_SINK, trace.OLD_SINK, 1)
        self.assertEqual(restored, trace.mfc.instrument(payload))
        self.assertNotIn('vm::', trace.NEW_SINK)
        self.assertIn('atomic_storage<u32>::load(group->max_run)', trace.NEW_SINK)
        with self.assertRaisesRegex(ValueError, 'changed'):
            trace.instrument(payload + b'\n// unrelated new edit\n')

    def test_output_cannot_overwrite_another_agents_file(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'existing.cpp'
            output.write_text('another agent owns this')
            run = subprocess.run(['python3', str(DIAG / 'prepare_spurs_workload_trace.py'),
                                  '--source', str(SOURCE), '--output', str(output)], capture_output=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertEqual(output.read_text(), 'another agent owns this')

    def test_decoder_has_correct_endianness_offsets_and_does_not_mutate_samples(self):
        code = r'''
#include "lucent_spurs_workload_snapshot.h"
#include <cassert>
#include <cstring>
#include <string>
using namespace lucent_spurs_workload;
int main() {
    snapshot s{0x30030f00, 0x123, 2, 5, 5, 1, true, false};
    s.kernel[0x44]=0x30; s.kernel[0x45]=0x03; s.kernel[0x46]=0x0f;
    s.kernel[0x54]=0x12; s.kernel[0x55]=0x34; s.kernel[0x56]=0x56; s.kernel[0x57]=0x78;
    s.kernel[0x5f]=7; s.kernel[0x6b]=1;
    s.kernel[0x6c]=0x12; s.kernel[0x6d]=0xab;
    s.kernel[0x6e]=0xcd; s.kernel[0x6f]=0xef;
    for (unsigned i=0;i<128;++i) s.reservation[i]=i;
    const auto before=s;
    std::string record;
    emit("pair=3 phase=return raddr=30056000", s, [&](const char* line) { record=line; });
    assert(record.find("pair=3 phase=return raddr=30056000") != std::string::npos);
    assert(record.find("max_num=5 max_run=5 running=1") != std::string::npos);
    assert(record.find("ctx_matches=1 wkl_addr=0000000012345678 wkl_id=7 idle=1 runnable1=12ab runnable2=cdef") != std::string::npos);
    assert(record.find("owner_rdata=0001020304050607") != std::string::npos);
    assert(record.substr(record.size()-8)=="7c7d7e7f");
    assert(std::memcmp(&before, &s, sizeof(s))==0);
    s.kernel[0x40]=1; // A mismatched 64-bit context pointer must not validate.
    emit("phase=enter raddr=00000000", s, [&](const char* line) { record=line; });
    assert(record.find("ctx_matches=0") != std::string::npos);
    assert(record.size()<2303);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'test.cpp'
            binary = Path(directory) / 'test'
            source.write_text(code)
            subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                            '-fno-exceptions', '-fsanitize=address,undefined',
                            '-I', str(DIAG), str(source), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

    def test_profile_discloses_payload_and_requires_progress_sampler(self):
        spec = importlib.util.spec_from_file_location('workload_package', DIAG / 'package_spurs_trace.py')
        package = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(package)
        profile = package.trace_profile(True, True)
        self.assertIn('reservation-buffer', profile['traceScope'])
        self.assertEqual(ROOT / profile['helper'], trace.HEADER)
        run = subprocess.run(['python3', str(DIAG / 'package_spurs_trace.py'),
                              '--output-dir', 'unused', '--trace-sha256', 'unused',
                              '--trace-library', 'unused', '--spurs-workload-trace'],
                             capture_output=True, text=True)
        self.assertNotEqual(run.returncode, 0)
        self.assertIn('requires --mfc-progress-trace', run.stderr)


if __name__ == '__main__':
    unittest.main()
