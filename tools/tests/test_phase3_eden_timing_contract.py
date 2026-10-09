"""Execute the used clock helper/native loader; no device or cadence PASS claims."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / "unified-android/native"
EDEN = ROOT / "engines/build/switch-src/eden"


def checked(command):
    result = subprocess.run([str(item) for item in command], capture_output=True, text=True)
    if result.returncode:
        raise AssertionError(f"{command}\n{result.stdout}\n{result.stderr}")
    return result.stdout


class EdenTimingContractTest(unittest.TestCase):
    def test_actual_clock_helper_preserves_fraction_and_swap_interval(self):
        compiler = shutil.which("c++")
        self.assertIsNotNone(compiler, "a C++ compiler is required, not a skipped clock test")
        source = r'''
#include "eden-lucent-pacing.h"
#include <cassert>
#include <limits>
int main() {
    using namespace Lucent;
    assert(!UsesFgPresentation());
    SetFgPresentation(true);
    assert(UsesFgPresentation());
    SetFgPresentation(false);
    assert(!UsesFgPresentation());
    assert(SetPacedVsyncHz(0.0));
    assert(BaseVsyncHz() == 60.0);
    for (double hz : {59.55, 59.94, 60000.0 / 1001.0, 60.0, 60.45}) {
        assert(SetPacedVsyncHz(hz));
        assert(PacedVsyncHz() == hz);
        for (int swap = 1; swap <= 4; ++swap) {
            auto period = CompositionPeriodNs(BaseVsyncHz(), swap, 1.0);
            long double exact = 1000000000.0L * swap / hz;
            assert(std::abs(period - exact) <= 0.500001L);
        }
    }
    const double before = PacedVsyncHz();
    for (double hz : {-1.0, 20.0, 30.0, 40.0, 50.0, 59.549999, 60.450001,
                      std::numeric_limits<double>::infinity(),
                      std::numeric_limits<double>::quiet_NaN()}) {
        assert(!SetPacedVsyncHz(hz));
        assert(PacedVsyncHz() == before);
    }
    assert(CompositionPeriodNs(60.0, 1, 0.5) == 8333333);
    assert(CompositionPeriodNs(60.0, 2, 1.0) == 33333333);
    assert(CompositionPeriodNs(60.0, 3, 1.0) == 50000000);
    assert(CompositionPeriodNs(60.0, 0, 1.0) == 0);
    assert(CompositionPeriodNs(0.0, 1, 1.0) == 0);
    ResetTimingDiagnostics();
    assert(RecordViCallback(2, 33333333) == 1);
    assert(RecordViCallback(2, 33333333) == 2);
    assert(RecordSubmissionAttempt() == 1);
    assert(g_vi_callbacks.load() == 2 && g_submission_attempts.load() == 1);
    assert(SetPacedVsyncHz(0.0));
    assert(BaseVsyncHz() == 60.0);
}
'''
        with tempfile.TemporaryDirectory(prefix="eden-clock-test-") as temporary:
            directory = Path(temporary)
            main = directory / "clock.cpp"
            main.write_text(source)
            executable = directory / "clock"
            checked([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                     "-include", "initializer_list", "-I", ROOT / "engines/patches",
                     main, "-o", executable])
            checked([executable])

    def test_used_vi_path_retains_composition_scale_and_never_averaged_fps(self):
        source = (EDEN / "src/core/hle/service/vi/conductor.cpp").read_text()
        self.assertEqual(2, source.count("Lucent::CompositionPeriodNs(base_fps, m_swap_interval, speed_scale)"))
        self.assertEqual(2, source.count("speed_scale /= m_compose_speed_scale;"))
        self.assertNotIn("static_cast<f32>(lucent_paced_hz)", source)
        self.assertNotIn("average_game_fps", source)
        self.assertIn("kind=callback-not-retired-guest-image", source)

    def test_submission_timestamp_is_not_a_manufactured_guest_grid(self):
        source = (EDEN / "src/video_core/renderer_vulkan/vk_swapchain.cpp").read_text()
        self.assertIn("desiredPresentTime = static_cast<u64>(now_ns)", source)
        self.assertIn("if (device.HasLucentDisplayTiming() && Lucent::UsesFgPresentation())", source)
        self.assertIn("if (source_image && Lucent::UsesFgPresentation())", source)
        self.assertNotIn("s_lucent_last_slot", source)
        self.assertNotIn("kLucentStampPeriodNs", source)
        self.assertIn("sourceIdentity=unjoined physicalPresent=unverified", source)
        adapter = (ROOT / "engines/patches/eden-lucent-adapter.cpp").read_text()
        export = adapter.split("uint32_t lucent_native_adapter_timing_capabilities_v1(void)")[1].split("}", 1)[0]
        self.assertNotIn("LUCENT_NATIVE_TIMING_AUTHORITATIVE_SOURCE_TIMELINE", export)

    def test_tracked_patch_and_canonical_sources_reproduce_current_subset(self):
        # Uncommitted, build-Mac-only input (see tools/run_ci_tests.py).
        if not (ROOT / "engines/build/switch-src/eden/src").is_dir():
            self.skipTest("local-only input absent: engines/build/switch-src/eden")
        checked(["python3", ROOT / "engines/tools/apply_eden_timing_patch.py"])

    def test_all_native_adapters_require_explicit_source_authority(self):
        source = (ROOT / "unified-android/src/com/thorium/preview/game/InWindowGameHost.java").read_text()
        self.assertNotIn("setSlotLatticeProducer(true)", source)
        native = (ROOT / "unified-android/src/com/thorium/preview/game/NativeAdapterEngineSession.java").read_text()
        self.assertIn("active.producerTimelineHz()", native)
        self.assertNotIn("pacedVideoHz > 0.0 ? pacedVideoHz : declaredVideoHz()", native)

    def test_presentation_configuration_follows_actual_surface_on_start_and_rebind(self):
        source = (ROOT / "unified-android/src/com/thorium/preview/game/NativeAdapterEngineSession.java").read_text()
        self.assertIn("configureNativePresentation(active, current);\n                    active.start(current, lower);", source)
        self.assertIn("FrameGenerationRendererRegistry.find(primary) != null", source)
        self.assertIn("configureNativePresentation(active, primary);\n        active.surfaceRecreated(primary, lower);", source)
        self.assertEqual(1, source.count("active.surfaceRecreated("))

    def test_source_checkpoint_does_not_claim_old_artifact_contains_changes(self):
        lock = json.loads((ROOT / "engines/eden-source-lock.json").read_text())
        checkpoint = lock["timingSourceCheckpoint"]
        self.assertIn(checkpoint["status"], {"rebuild-required", "rebuilt-device-unverified", "rebuilt-validated"})
        if checkpoint["status"] == "rebuild-required":
            self.assertEqual(lock["artifact"]["sha256"], checkpoint["previousArtifactSha256"])
        else:
            artifact = lock["artifact"]
            self.assertNotEqual(artifact["sha256"], checkpoint["previousArtifactSha256"])
            if artifact["sha256"] != checkpoint["rebuiltArtifactSha256"]:
                # A later rebuild may supersede the timing checkpoint artifact only when
                # the artifact record names it as the direct predecessor, rebuilt from
                # the same pinned core checkout (so the timing subset is carried forward).
                self.assertIn(f"from the prior entry ({checkpoint['rebuiltArtifactSha256']},",
                              artifact["note"])
                self.assertIn(f"still-pinned {lock['core']['commit']} checkout", artifact["note"])
            self.assertTrue(checkpoint["buildEvidencePath"])
        if checkpoint["status"] == "rebuilt-validated":
            self.assertTrue(checkpoint["deviceEvidencePath"])
        else:
            self.assertEqual("UNVERIFIED", checkpoint["deviceEvidenceStatus"])


class NativeTimingCapabilityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="native-timing-test-")
        cls.directory = Path(cls.temporary.name)
        cls.compiler = shutil.which("cc")
        if cls.compiler is None:
            raise AssertionError("C compiler required for actual dlsym contract test")
        source = r'''
#include "lucent_native_adapter_host.h"
#include <assert.h>
#include <math.h>
#include <stdlib.h>
#include <stdint.h>
static size_t audio(void *ctx, const int16_t *frames, size_t count) {
    (void)ctx; (void)frames; return count;
}
int main(int argc, char **argv) {
    assert(argc == 6);
    char error[512] = {0}; uint32_t window = 0;
    lucent_native_adapter_host *host = lucent_native_adapter_open(argv[1], argv[2], error, sizeof(error));
    assert(host);
    assert(lucent_native_adapter_timing_capabilities(host) == 0);
    assert(lucent_native_adapter_producer_timeline_hz(host) == 0);
    assert(lucent_native_adapter_create(host, error, sizeof(error)));
    lucent_native_load_request request = {argv[2], argv[2], argv[3]};
    assert(lucent_native_adapter_load(host, &request, error, sizeof(error)));
    assert(!lucent_native_adapter_set_fg_presentation(host, false));
    assert(!lucent_native_adapter_set_fg_presentation(host, true));
    lucent_native_io io = {LUCENT_NATIVE_RENDER_VULKAN_WINDOW, &window, NULL, audio, NULL};
    assert(lucent_native_adapter_start(host, &io, error, sizeof(error)));
    assert(lucent_native_adapter_timing_capabilities(host) == strtoul(argv[4], NULL, 10));
    assert(lucent_native_adapter_producer_timeline_hz(host) == strtod(argv[5], NULL));
    assert(!lucent_native_adapter_set_paced_video_hz(host, 40.0));
    assert(!lucent_native_adapter_set_paced_video_hz(host, NAN));
    assert(!lucent_native_adapter_set_paced_video_hz(host, -1));
    assert(!lucent_native_adapter_set_paced_video_hz(host, 59.549999));
    assert(!lucent_native_adapter_set_paced_video_hz(host, 60.450001));
    assert(lucent_native_adapter_set_paced_video_hz(host, 59.55));
    assert(lucent_native_adapter_set_paced_video_hz(host, 59.94));
    assert(lucent_native_adapter_set_paced_video_hz(host, 0));
    assert(lucent_native_adapter_stop(host, error, sizeof(error)));
    assert(lucent_native_adapter_producer_timeline_hz(host) == 0);
    lucent_native_adapter_destroy(host);
}
'''
        main = cls.directory / "host.c"
        main.write_text(source)
        cls.executable = cls.directory / "host"
        (cls.directory / "game.mock").write_bytes(b"\x07")
        checked([cls.compiler, "-std=c11", "-O1", "-Wall", "-Wextra", "-Werror",
                 "-I", NATIVE / "include", NATIVE / "lucent_native_adapter_host.c",
                 main, "-ldl", "-o", cls.executable])

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def variant(self, name, flags, hz, expected_flags, expected_hz):
        library = self.directory / (name + ".so")
        defines = ["-DMOCK_NO_FG_PRESENTATION=1"]
        if flags is not None:
            defines.append(f"-DMOCK_TIMING_CAPABILITIES={flags}")
        if hz is not None:
            defines.append(f"-DMOCK_PRODUCER_TIMELINE_HZ={hz}")
        checked([self.compiler, "-std=c11", "-fPIC", "-shared", *defines,
                 NATIVE / "tests/mock_native_adapter.c", "-o", library])
        checked([self.executable, library, self.directory, self.directory / "game.mock",
                 expected_flags, expected_hz])

    def test_old_adapter_missing_all_hooks_is_unknown(self):
        self.variant("old", None, None, 0, 0)

    def test_rate_hook_without_capability_is_not_authority(self):
        self.variant("orphan_rate", None, 60, 0, 0)

    def test_submission_timestamps_even_with_rate_are_not_authority(self):
        self.variant("submission", 3, 60, 3, 0)

    def test_authority_requires_the_finite_rate_hook(self):
        self.variant("no_rate", 4, None, 4, 0)
        self.variant("zero_rate", 4, 0, 4, 0)
        self.variant("invalid_rate", 4, "(0.0/0.0)", 4, 0)
        self.variant("infinite_rate", 4, "(1.0/0.0)", 4, 0)

    def test_explicit_future_authority_preserves_fraction_and_masks_unknown_bits(self):
        self.variant("future", 255, 59.94, 7, 59.94)

    def test_existing_native_adapter_lifecycle_harness_still_passes(self):
        libraries = []
        for name, define in (("lifecycle", None), ("mismatch", "MOCK_ABI_MISMATCH"),
                             ("setter", "MOCK_JAVA_VM_SETTER_SUCCESS"),
                             ("setter_failure", "MOCK_JAVA_VM_SETTER_FAILURE")):
            library = self.directory / (name + ".so")
            definitions = [] if define is None else [f"-D{define}=1"]
            checked([self.compiler, "-std=c11", "-fPIC", "-shared", *definitions,
                     NATIVE / "tests/mock_native_adapter.c", "-o", library])
            libraries.append(library)
        executable = self.directory / "lifecycle"
        checked([self.compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
                 NATIVE / "lucent_native_adapter_host.c",
                 NATIVE / "tests/native_adapter_host_test.c", "-ldl", "-o", executable])
        checked([executable, *libraries, self.directory, self.directory,
                 self.directory / "game.mock"])


if __name__ == "__main__":
    unittest.main()
