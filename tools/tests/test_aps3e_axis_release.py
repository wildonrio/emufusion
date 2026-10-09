"""Execute the real adapter input functions against a persistent virtual pad."""
from pathlib import Path
import importlib.util
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "engines/patches/aps3e-lucent-adapter.cpp"


def input_functions(text):
    mapping = text[text.index("int virtual_key("):text.index("\n} // namespace")]
    start = text.index("static void adapter_set_control(")
    return mapping + text[start:text.index("static void adapter_pause(", start)]


PREFIX = r'''
#include "lucent_native_adapter.h"
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <iostream>
struct lucent_native_engine { bool started = true, stopped = false; };
namespace ae {
unsigned values[26]{};
unsigned calls = 0;
void key_event(std::uint32_t key, bool pressed, std::uint16_t magnitude) {
    ++calls;
    if (key >= 26) std::abort();
    // Upstream AndroidVirtualPadHandler retains each min/max key separately.
    values[key] = pressed ? magnitude : 0;
    for (auto pair : {std::pair{9,11}, {10,12}, {13,15}, {14,16}})
        if (values[pair.first] && values[pair.second]) {
            std::cerr << "opposite directions held simultaneously\n";
            std::exit(12);
        }
}
}
'''
SUFFIX = r'''
int main() {
    lucent_native_engine engine;
    struct Axis { lucent_native_control control; unsigned negative, positive; };
    const Axis axes[] = {{LUCENT_PAD_LSTICK_X,9,11}, {LUCENT_PAD_LSTICK_Y,10,12},
                         {LUCENT_PAD_RSTICK_X,13,15}, {LUCENT_PAD_RSTICK_Y,14,16}};
    for (auto axis : axes) {
        for (float value : {-1.f, 0.f, 1.f, 0.f, -.5f, .25f, -.25f, 0.f,
                            -.001f, .001f, 0.f, -2.f, 2.f, 0.f}) {
            adapter_set_control(&engine, 0, axis.control, value);
            unsigned magnitude = std::clamp(std::abs(value), 0.f, 1.f) * 255.f;
            if (ae::values[axis.negative] != (value < 0 ? magnitude : 0) ||
                ae::values[axis.positive] != (value > 0 ? magnitude : 0)) {
                std::cerr << "axis did not release/update both directions: "
                          << axis.control << " value=" << value << '\n';
                return 10;
            }
        }
    }
    // Updating one axis must not clear another held axis or a digital button.
    adapter_set_control(&engine, 0, LUCENT_PAD_A, 1.f);
    adapter_set_control(&engine, 0, LUCENT_PAD_LSTICK_X, -1.f);
    adapter_set_control(&engine, 0, LUCENT_PAD_LSTICK_Y, 1.f);
    if (ae::values[6] != 255 || ae::values[9] != 255 || ae::values[12] != 255) return 20;
    adapter_set_control(&engine, 0, LUCENT_PAD_LSTICK_Y, 0.f);
    if (ae::values[6] != 255 || ae::values[9] != 255 || ae::values[12]) return 21;
    adapter_set_control(&engine, 0, LUCENT_PAD_LSTICK_X, 0.f);
    adapter_set_control(&engine, 0, LUCENT_PAD_A, 0.f);
    if (ae::values[6] || ae::values[9]) return 22;
    unsigned before = ae::calls;
    adapter_set_control(&engine, 1, LUCENT_PAD_LSTICK_X, -1.f);
    adapter_set_control(nullptr, 0, LUCENT_PAD_A, 1.f);
    engine.stopped = true;
    adapter_set_control(&engine, 0, LUCENT_PAD_A, 1.f);
    engine.stopped = false; engine.started = false;
    adapter_set_control(&engine, 0, LUCENT_PAD_A, 1.f);
    if (ae::calls != before) return 23;
}
'''


@unittest.skipUnless(shutil.which("c++"), "C++ compiler unavailable")
class Aps3eAxisReleaseTest(unittest.TestCase):
    def test_package_profile_never_claims_renderer_or_cpu_changes(self):
        script = ROOT / 'engines/diagnostics/package_spurs_trace.py'
        spec = importlib.util.spec_from_file_location('input_package', script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        profile = module.trace_profile(adapter_input_only=True)
        self.assertIsNone(profile['targetAddress'])
        self.assertIsNone(profile['helper'])
        self.assertEqual(profile['sourcePatch'], str(SOURCE.relative_to(ROOT)))
        self.assertIn('no added tracing', profile['traceScope'])
        combined = module.trace_profile(adapter_input_only=True, getllar_read_barrier=True)
        self.assertIn('GETLLAR payload-before-stamp read barrier', combined['traceScope'])
        self.assertIn('no added tracing', combined['traceScope'])
        self.assertNotIn('GETLLAR', profile['traceScope'])
        with self.assertRaises(ValueError):
            module.trace_profile(getllar_read_barrier=True)
        for flag in ('--wsi-trace', '--core-error-trace', '--mfc-progress-trace',
                     '--spurs-workload-trace', '--ppu-wait-trace',
                     '--render-progress-trace', '--retirement-only'):
            result = subprocess.run([
                'python3', str(script), '--output-dir', '/nonexistent/unwritten',
                '--trace-library', '/nonexistent/unread', '--trace-sha256', '0' * 64,
                '--without-trace', '--adapter-input-only', flag,
            ], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn('input-only requires', result.stderr)

    def test_real_adapter_releases_sticks_without_affecting_other_controls(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.cpp"
            binary = Path(directory) / "input"
            source.write_text(PREFIX + input_functions(SOURCE.read_text()) + SUFFIX)
            subprocess.run(["c++", "-std=c++20", "-Wall", "-Wextra", "-Werror",
                            "-fsanitize=address,undefined", "-I",
                            str(ROOT / "unified-android/native/include"),
                            str(source), "-o", str(binary)], check=True)
            result = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
