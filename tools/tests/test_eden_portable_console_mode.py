"""Execute the adapter's mode assignment; device QA must prove guest behavior."""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
ADAPTER = ROOT / "engines/patches/eden-lucent-adapter.cpp"
VENDORED = ROOT / "engines/build/switch-src/eden/src/android/app/src/main/jni/lucent_adapter.cpp"


def mode_assignment(source):
    code = re.sub(r"/\*.*?\*/|//[^\n]*", "", source, flags=re.S)
    matches = re.findall(r"Settings::values\.use_docked_mode\.SetValue\([^;]+;", code)
    if len(matches) != 1:
        raise ValueError("Expected exactly one explicit console-mode default")
    return matches[0]


class PortableConsoleMode(unittest.TestCase):
    def test_actual_assignment_resets_docked_to_handheld(self):
        assignment = mode_assignment(ADAPTER.read_text())
        fixture = r'''
            #include <cassert>
            namespace Settings {
                enum class ConsoleMode { Handheld, Docked };
                struct Setting {
                    ConsoleMode value = ConsoleMode::Docked;
                    void SetValue(ConsoleMode next) { value = next; }
                    ConsoleMode GetValue() const { return value; }
                };
                struct Values { Setting use_docked_mode; } values;
            }
            void apply() { ASSIGNMENT }
            int main() {
                for (auto previous : {Settings::ConsoleMode::Docked,
                                      Settings::ConsoleMode::Handheld}) {
                    Settings::values.use_docked_mode.SetValue(previous);
                    apply();
                    assert(Settings::values.use_docked_mode.GetValue() ==
                           Settings::ConsoleMode::Handheld);
                }
            }
        '''.replace("#include <cassert>", "#include <cassert>\n#include <initializer_list>").replace("ASSIGNMENT", assignment)
        with tempfile.TemporaryDirectory(prefix="eden-portable-mode-") as directory:
            source = Path(directory) / "mode.cpp"
            binary = Path(directory) / "mode"
            source.write_text(fixture)
            subprocess.run([os.environ.get("CXX", "clang++"), "-std=c++17",
                            "-fsanitize=address,undefined", str(source), "-o", str(binary)],
                           check=True, capture_output=True, text=True)
            result = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_default_is_applied_during_load_before_session_initialization(self):
        source = ADAPTER.read_text()
        load = source.index("static bool adapter_load(")
        mode = source.index(mode_assignment(source))
        initialize = source.index("session.InitializeSystem(!first_session);")
        start = source.index("static bool adapter_start(")
        self.assertLess(load, mode)
        self.assertLess(mode, initialize)
        self.assertLess(initialize, start)

    def test_local_build_input_matches_canonical_adapter(self):
        if not VENDORED.is_file():
            self.skipTest("local Eden sources unavailable")
        self.assertEqual(ADAPTER.read_bytes(), VENDORED.read_bytes())

    def test_effective_mode_log_follows_logger_initialization(self):
        source = ADAPTER.read_text()
        initialize = source.index("session.InitializeSystem(!first_session);")
        mode_log = source.index('LOG_INFO(Frontend, "EmuFusion Switch console mode=')
        loaded = source.index("engine->loaded.store(true);")
        self.assertLess(initialize, mode_log)
        self.assertLess(mode_log, loaded)


if __name__ == "__main__":
    unittest.main()
