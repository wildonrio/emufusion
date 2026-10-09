"""Bounded diagnostic regressions, not physical presentation qualification."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / "unified-android/lsfg-qualification-native"


class LsfgRawTimingDiagnosticsTest(unittest.TestCase):
    def compile_run(self, source):
        compiler = shutil.which("c++")
        self.assertIsNotNone(compiler)
        with tempfile.TemporaryDirectory(prefix="lsfg-raw-diagnostic-") as temporary:
            root = Path(temporary)
            unit = root / "test.cpp"
            unit.write_text(source)
            executable = root / "test"
            result = subprocess.run([compiler, "-std=c++20", "-Wall", "-Wextra", "-Werror",
                                     "-fsanitize=address,undefined", "-I", str(NATIVE),
                                     str(unit), "-o", str(executable)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(executable)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_fixed_exact_identity_join_and_host_lifetime_budget(self):
        self.compile_run((NATIVE / "tests/presentation_timing_diagnostics_test.cpp").read_text())

    def test_actual_logger_keeps_raw_separate_and_startup_cannot_consume_budget(self):
        native = (NATIVE / "lsfg_qualification_jni.cpp").read_text()
        logger = native.split("void logSurfaceTimingDiagnostic(", 1)[1].split(
            "std::optional<emufusion::lsfg::OwnedVulkanHost::Completion>\nprogressLiveSurfacePipeline", 1)[0]
        self.compile_run(r'''
#include "presentation_timing_diagnostics.hpp"
#include <cassert>
#include <cstdarg>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>
namespace emufusion::lsfg {
struct OwnedSurfaceControlPresenter {
    struct Completion {
        uint64_t presentId = 0, rawPresentFenceTimeNs = 0, actualPresentTimeNs = 0;
        uint64_t transactionApplyStartNs = 0, transactionApplyEndNs = 0, latchTimeNs = 0;
    };
};
struct OwnedVulkanHost {
    struct Completion { uint64_t gpuCompletionNs = 0, gpuWorkNs = 0; };
};
}
struct Host {
    emufusion::lsfg::PresentationTimingDiagnostics timingDiagnostics;
    bool selfTestLiveCadence = false;
    uint64_t selfTestPresentFenceOffsetNs = 8333333;
};
constexpr int ANDROID_LOG_ERROR = 1, ANDROID_LOG_INFO = 2;
constexpr const char* LOG_TAG = "fixture";
std::vector<std::string> logs;
int __android_log_print(int, const char*, const char* format, ...) {
    char output[4096]; va_list args; va_start(args, format);
    int size = vsnprintf(output, sizeof(output), format, args); va_end(args);
    assert(size > 0 && static_cast<size_t>(size) < sizeof(output));
    logs.emplace_back(output); return size;
}
void logSurfaceTimingDiagnostic(''' + logger + r'''
int main() {
    Host host;
    host.timingDiagnostics.submitted(0, {7, 20000000, 18000000, 51, 20010000, 9700000});
    const emufusion::lsfg::OwnedSurfaceControlPresenter::Completion row{
        7, 20000123, 28333456, 8000000, 8000100, 9000000};
    const emufusion::lsfg::OwnedVulkanHost::Completion gpu{8500000, 300000};
    for (int i = 0; i < 240; ++i)
        logSurfaceTimingDiagnostic(&host, "startup-live-cadence", row, true, &gpu, false);
    assert(logs.empty() && host.timingDiagnostics.liveRows() == 0);
    host.selfTestLiveCadence = true;
    logSurfaceTimingDiagnostic(&host, "startup-live-pair", row, true, &gpu, false);
    assert(logs.empty());
    for (int i = 0; i < 100; ++i)
        logSurfaceTimingDiagnostic(&host, "live", row, true, &gpu, false);
    assert(logs.size() == 32 && host.timingDiagnostics.liveRows() == 32);
    assert(row.rawPresentFenceTimeNs == 20000123 && row.actualPresentTimeNs == 28333456);
    assert(logs.front().find("presentId=7 requestKnown=1 rawPresentFenceNs=20000123") != std::string::npos);
    assert(logs.front().find("addedOffsetNs=8333333 normalizedKnown=1 normalizedPresentNs=28333456") != std::string::npos);
    assert(logs.front().find("physicalTargetNs=20000000 driverDesiredNs=18000000 vsyncId=51") != std::string::npos);
    assert(logs.front().find("gpuSignalKnown=1 gpuSignalNs=8500000") != std::string::npos);
    logSurfaceTimingDiagnostic(&host, "live", row, true, nullptr, true);
    assert(logs.size() == 33);
    assert(logs.back().find("failed=1") != std::string::npos);
    assert(logs.back().find("gpuSignalKnown=0 gpuSignalNs=0") != std::string::npos);
    logSurfaceTimingDiagnostic(&host, "live", row, true, nullptr, true);
    assert(logs.size() == 33);
}
''')

    def test_diagnostics_preserve_existing_raw_capture_normalization_and_wire_abi(self):
        presenter = (NATIVE / "owned_surface_control_presenter.cpp").read_text()
        self.assertIn(".rawPresentFenceTimeNs = physicalTimestampNs,", presenter)
        native = (NATIVE / "lsfg_qualification_jni.cpp").read_text()
        self.assertIn("physical->actualPresentTimeNs = normalizedPhysicalPresentTime(", native)
        self.assertNotIn("physical->rawPresentFenceTimeNs =", native)
        self.assertIn("host->timingDiagnostics.submitted(submission->slotIndex", native)
        self.assertIn("logSurfaceTimingDiagnostic(host, diagnosticStage, physicalRow->second,", native)
        self.assertIn("Surface timing setup phaseProbeId=", native)
        self.assertIn("phaseProbe->rawPresentFenceTimeNs", native)
        self.assertNotIn("timingDiagnostics =", native)
        self.assertNotIn("timingDiagnostics.reset", native)
        gpu = (NATIVE / "owned_vulkan_host.cpp").read_text()
        self.assertIn(".gpuCompletionNs = slot.gpuCompletionObservedNs,", gpu)
        # New native diagnostic fields are deliberately absent from Java's
        # existing result array, not an accidental unversioned ABI extension.
        result = native.split("Java_com_thorium_preview_game_NativeLsfgBridge_poll", 1)[1]
        result = result.split('extern "C"', 1)[0]
        self.assertIn("const jlong values[24]", result)
        self.assertIn("NewLongArray(24)", result)
        self.assertNotIn("completion->gpuCompletionNs", result)


if __name__ == "__main__":
    unittest.main()
