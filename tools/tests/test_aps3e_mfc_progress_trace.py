import hashlib
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'engines/diagnostics/prepare_mfc_progress_trace.py'
SOURCE = ROOT / ('engines/build/sources/aps3e-b5ae1af50d5e2f3b705506e7380a4504e086840b/'
                 'app/src/main/cpp/rpcs3/rpcs3/Emu/Cell/SPUThread.cpp')
spec = importlib.util.spec_from_file_location('mfc_progress_trace', SCRIPT)
trace = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trace)


class MfcProgressTraceTest(unittest.TestCase):
    def test_source_drift_rejected(self):
        with self.assertRaisesRegex(ValueError, 'changed'):
            trace.instrument(SOURCE.read_bytes() + b'\n// another agent\n')

    def test_packaging_provenance_describes_generic_not_old_address_trace(self):
        package_spec = importlib.util.spec_from_file_location(
            'mfc_package', SCRIPT.with_name('package_spurs_trace.py'))
        package = importlib.util.module_from_spec(package_spec)
        package_spec.loader.exec_module(package)
        profile = package.trace_profile(True)
        self.assertIsNone(profile['targetAddress'])
        self.assertEqual(ROOT / profile['helper'], trace.HEADER)
        self.assertEqual(ROOT / profile['sourcePatch'], SCRIPT)
        historical = package.trace_profile()
        self.assertEqual(historical['targetAddress'], '0x31ee7680')
        self.assertNotEqual(historical['helper'], profile['helper'])
        run = subprocess.run(['python3', str(SCRIPT.with_name('package_spurs_trace.py')),
                              '--output-dir', 'unused', '--trace-sha256', 'unused',
                              '--trace-library', 'unused', '--mfc-progress-trace'],
                             capture_output=True, text=True)
        self.assertNotEqual(run.returncode, 0)
        self.assertIn('requires --without-trace', run.stderr)

    def test_original_body_and_every_other_byte_preserved(self):
        original = SOURCE.read_bytes()
        result = trace.instrument(original)
        restored = result.replace(trace.additions(), '', 1).replace(trace.PREFIX, '', 1).replace(trace.SUFFIX, '', 1)
        self.assertEqual(restored, original.decode())
        self.assertEqual(hashlib.sha256(SOURCE.read_bytes()).hexdigest(), trace.EXPECTED_SHA)

    def test_existing_output_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'SPUThread.cpp'
            output.write_text('owned by another agent')
            run = subprocess.run(['python3', str(SCRIPT), '--source', str(SOURCE),
                                  '--output', str(output)], capture_output=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertEqual(output.read_text(), 'owned by another agent')

    def compile_run(self, code, extra_flags=()):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            (tmp / 'android').mkdir()
            (tmp / 'android/log.h').write_text('#define ANDROID_LOG_INFO 4\n')
            source = tmp / 'test.cpp'
            source.write_text(code)
            binary = tmp / 'test'
            subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                            *extra_flags, '-I', str(tmp), '-I', str(trace.HEADER.parent),
                            str(source), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

    def test_actual_journal_limits_counts_and_preserves_results(self):
        self.compile_run(r'''
#include "lucent_mfc_progress_trace.h"
#include <cassert>
#include <stdexcept>
#include <string>
#include <vector>
using namespace lucent_mfc_progress;
int main() {
    journal j;
    uint64_t now = 0;
    unsigned clocks = 0, snapshots = 0, operations = 0, results = 0;
    observation state{1, 0x11e4, 0xb4, 0, 0x12345680, 0x100, 0x12345680,
                      0x123456789abcdef0ULL, 0xfedcba9876543210ULL};
    std::vector<std::string> lines;
    auto clock = [&]() noexcept { ++clocks; return now; };
    auto snapshot = [&]() noexcept { ++snapshots; return state; };
    auto sink = [&](const char* s) noexcept { lines.emplace_back(s); };
    auto operation = [&]() { ++operations; return true; };
    auto get_ok = [&]() noexcept { ++results; return outcome::get_ok; };
    assert(j.run(command::other, 1, operation, get_ok, snapshot, clock, sink));
    assert(operations == 1 && clocks == 0 && results == 0 && snapshots == 0);
    assert(j.run(command::getllar, 1, operation, get_ok, snapshot, clock, sink));
    assert(lines.size() == 2 && j.count.get_started == 1 && j.count.get_ok == 1);
    assert(lines[0].find("phase=enter") != std::string::npos);
    assert(lines[0].find("get_ok=0") != std::string::npos);
    assert(lines[1].find("phase=return") != std::string::npos);
    assert(lines[1].find("get_ok=1") != std::string::npos);
    assert(lines[1].find("rtime=123456789abcdef0 events=fedcba9876543210") != std::string::npos);
    for (unsigned i = 0; i < 10000; ++i)
        assert(j.run(command::getllar, 1, operation, get_ok, snapshot, clock, sink));
    assert(lines.size() == 2 && j.count.get_ok == 10001);
    now = journal::interval_us;
    assert(!j.run(command::getllar, 1, [] { return false; }, get_ok, snapshot, clock, sink));
    assert(j.count.stopped == 1 && results == 10001);
    assert(lines.back().find("phase=stopped") != std::string::npos);
    now += journal::interval_us;
    const unsigned before_exception = results;
    try {
        j.run(command::putllc, 1, []() -> bool { throw std::runtime_error("original"); },
              get_ok, snapshot, clock, sink);
        assert(false);
    } catch (const std::runtime_error& error) {
        assert(std::string(error.what()) == "original");
    }
    assert(j.count.unwound == 1 && results == before_exception);
    assert(lines.back().find("phase=unwind") != std::string::npos);
    now += journal::interval_us;
    assert(j.run(command::putllc, 1, operation, [] { return outcome::put_failed; }, snapshot, clock, sink));
    assert(j.count.put_started == 2 && j.count.put_failed == 1);
    assert(j.run(command::putllc, 1, operation, [] { return outcome::put_ok; }, snapshot, clock, sink));
    assert(j.count.put_ok == 1);
    assert(j.run(command::getllar, 1, operation, [] { return outcome::unknown; }, snapshot, clock, sink));
    assert(j.count.unknown == 1);
    now = 0; // Backward clock must not bypass the rate limit.
    const auto old_pairs = j.pairs;
    assert(j.run(command::getllar, 1, operation, get_ok, snapshot, clock, sink));
    assert(j.pairs == old_pairs);
    now = 4 * journal::interval_us;
    state.owner = 2;
    assert(j.run(command::getllar, 2, operation, get_ok, snapshot, clock, sink));
    assert(j.count.get_started == 1 && j.count.put_started == 0);
    assert(j.pairs == old_pairs + 1); // Identity changes cannot reset the budget.
    for (unsigned i = 0; i < 700; ++i) {
        now += journal::interval_us;
        assert(j.run(command::getllar, 2, operation, get_ok, snapshot, clock, sink));
    }
    assert(j.pairs == journal::max_pairs && lines.size() == 2 * journal::max_pairs);
    const auto final_clocks = clocks;
    assert(j.run(command::getllar, 3, operation, get_ok, snapshot, clock, sink));
    assert(clocks == final_clocks && snapshots == 2 * journal::max_pairs);
    assert(lines.back().find("budget_left=0") != std::string::npos);
}
''', ('-fsanitize=address,undefined', '-fno-omit-frame-pointer'))

    def test_exact_source_wrapper_binds_status_without_consuming_channel(self):
        prefix = r'''
#include <cassert>
#include <cstdint>
#include <stdexcept>
using u32 = uint32_t;
unsigned log_count = 0;
int __android_log_write(int, const char*, const char*) { return ++log_count; }
uint64_t get_system_time() { return 1234567; }
enum { MFC_GETLLAR_CMD=0xd0, MFC_PUTLLC_CMD=0xb4,
       MFC_GETLLAR_SUCCESS=4, MFC_PUTLLC_SUCCESS=0, MFC_PUTLLC_FAILURE=1 };
struct spu_thread {
    u32 id=1, pc=0x11e4, raddr=0x123480;
    uint64_t rtime=128;
    struct { u32 cmd=MFC_GETLLAR_CMD, eah=0, eal=0x123480, lsa=0x100; } ch_mfc_cmd;
    struct { uint64_t all=0; auto load() const { return *this; } } ch_events;
    struct {
        unsigned reads=0, value=MFC_GETLLAR_SUCCESS;
        unsigned get_value() { ++reads; return value; }
    } ch_atomic_stat;
    unsigned calls=0;
    int mode=0;
    bool process_mfc_cmd();
};
'''
        body = r'''
    ++calls;
    if (mode == 1) return false;
#if defined(__cpp_exceptions)
    if (mode == 2) throw std::runtime_error("original exception");
#endif
    if ([&]() { return mode == 3; }()) return true;
    return true;
'''
        suffix = r'''
int main() {
    spu_thread s;
    assert(s.process_mfc_cmd() && s.calls == 1 && s.ch_atomic_stat.reads == 1);
    assert(s.ch_atomic_stat.value == MFC_GETLLAR_SUCCESS && log_count == 2);
    s.mode=1;
    assert(!s.process_mfc_cmd() && s.calls == 2 && s.ch_atomic_stat.reads == 1);
#if defined(__cpp_exceptions)
    s.mode=2;
    try { s.process_mfc_cmd(); assert(false); } catch (const std::runtime_error&) {}
    assert(s.calls == 3 && s.ch_atomic_stat.reads == 1);
#else
    ++s.calls; // Keep subsequent expected counts identical in the no-exception build.
#endif
    s.mode=3;
    assert(s.process_mfc_cmd() && s.calls == 4 && s.ch_atomic_stat.reads == 2);
    s.ch_mfc_cmd.cmd=MFC_PUTLLC_CMD;
    s.ch_atomic_stat.value=MFC_PUTLLC_FAILURE;
    assert(s.process_mfc_cmd() && s.calls == 5 && s.ch_atomic_stat.reads == 3);
    assert(s.ch_atomic_stat.value == MFC_PUTLLC_FAILURE);
    s.ch_mfc_cmd.cmd=0;
    assert(s.process_mfc_cmd() && s.calls == 6 && s.ch_atomic_stat.reads == 3);
}
'''
        fixture = prefix + trace.additions() + trace.START + trace.PREFIX + body + trace.SUFFIX + '\n}\n' + suffix
        self.compile_run(fixture)
        self.compile_run(fixture, ('-fno-exceptions',))


if __name__ == '__main__':
    unittest.main()
