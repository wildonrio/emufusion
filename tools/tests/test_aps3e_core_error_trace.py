import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'engines/diagnostics/prepare_core_error_trace.py'
SOURCE = ROOT / ('engines/build/sources/aps3e-b5ae1af50d5e2f3b705506e7380a4504e086840b/'
                 'app/src/main/cpp/aps3e_emu.cpp')
spec = importlib.util.spec_from_file_location('core_error_trace', SCRIPT)
trace = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trace)


class CoreErrorTraceTest(unittest.TestCase):
    def test_changed_source_rejected(self):
        with self.assertRaises(ValueError):
            trace.instrument(b'different source')

    def test_only_listener_and_install_added(self):
        original = SOURCE.read_bytes()
        result = trace.instrument(original)
        restored = result.replace(trace.LISTENER + '\n', '', 1).replace(
            '        install_lucent_core_error_listener();\n', '', 1)
        self.assertEqual(restored, original.decode())

    def test_existing_output_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'existing.cpp'
            output.write_text('another agent owns this')
            result = subprocess.run(['python3', str(SCRIPT), '--source', str(SOURCE),
                                     '--output', str(output)], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(output.read_text(), 'another agent owns this')

    def test_listener_filters_chunks_and_registers_once(self):
        # Execute the exact injected listener against a minimal logs/Android API.
        prefix = r'''
#include <cassert>
#include <cstdint>
#include <cstdarg>
#include <cstdio>
#include <string>
#include <vector>
using u64 = uint64_t;
std::vector<std::string> captured;
int __android_log_print(int, const char*, const char* format, ...) {
    char buffer[4096]; va_list args; va_start(args, format);
    int size = vsnprintf(buffer, sizeof(buffer), format, args); va_end(args);
    assert(size >= 0 && size < int(sizeof(buffer)));
    captured.emplace_back(buffer); return size;
}
namespace logs {
enum class level : unsigned char { always=0, fatal=1, error=2, warning=5, notice=6, trace=7 };
struct channel { const char* name; };
struct message {
    level severity; channel source;
    operator level() const { return severity; }
    const channel* operator->() const { return &source; }
};
struct listener {
    static inline unsigned registrations = 0;
    virtual ~listener() = default;
    virtual void log(u64, const message&, const std::string&, const std::string&) = 0;
    static void add(listener*) { ++registrations; }
};
}
'''
        suffix = r'''
int main() {
    install_lucent_core_error_listener(); install_lucent_core_error_listener();
    assert(logs::listener::registrations == 1 && captured.size() == 1);
    assert(captured[0] == "READY fatal/error mirror"); captured.clear();
    LucentCoreErrorListener listener;
    for (auto level : {logs::level::always, logs::level::warning,
                      logs::level::notice, logs::level::trace}) {
        listener.log(1, {level, {"SPU"}}, "thread", "filtered");
    }
    assert(captured.empty());
    listener.log(42, {logs::level::error, {"RSX"}}, "worker", std::string(6100, 'x'));
    assert(captured.size() == 3);
    assert(captured[0].find("stamp=42 level=2 channel=RSX thread=worker offset=0 ") == 0);
    assert(captured[1].find("offset=2800 ") != std::string::npos);
    assert(captured[2].find("offset=5600 ") != std::string::npos);
    std::size_t copied = 0;
    for (const auto& entry : captured) copied += entry.size() - entry.find(" ", entry.find("offset=")) - 1;
    assert(copied == 6100);
    captured.clear();
    listener.log(43, {logs::level::fatal, {nullptr}}, "", "");
    assert(captured.size() == 1 && captured[0].find("level=1") != std::string::npos);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            (tmp / 'android').mkdir()
            (tmp / 'android/log.h').write_text('#define ANDROID_LOG_ERROR 6\n#define ANDROID_LOG_INFO 4\n')
            source = tmp / 'listener.cpp'
            source.write_text(prefix + trace.LISTENER + suffix)
            binary = tmp / 'listener'
            subprocess.run(['c++', '-std=c++17', '-I', str(tmp), str(source), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    unittest.main()
