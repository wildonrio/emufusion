"""Source-only Switch identity contracts; never a device/guest-clock PASS."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
EDEN = ROOT / "engines/build/switch-src/eden/src"


def run(command):
    result = subprocess.run([str(value) for value in command], capture_output=True, text=True)
    if result.returncode:
        raise AssertionError(f"{command}\n{result.stdout}\n{result.stderr}")
    return result.stdout


class SourceImageJoinTest(unittest.TestCase):
    def test_actual_native_host_optional_dlsym_and_exact_identity_checks(self):
        native = ROOT / "unified-android/native"
        source = r'''
#include "lucent_native_adapter_host.h"
#include <assert.h>
#include <stdlib.h>
static size_t audio(void* context, const int16_t* frames, size_t count) {
    (void)context; (void)frames; return count;
}
int main(int argc, char** argv) {
    assert(argc == 6); char error[512] = {0}; uint32_t window = 0;
    lucent_source_image_v1 row; lucent_source_binding_v1 binding;
    lucent_native_adapter_host* host = lucent_native_adapter_open(argv[1], argv[2], error, sizeof(error));
    assert(host);
    assert(lucent_native_adapter_source_image_binding(host, &binding, sizeof(binding)) == LUCENT_SOURCE_CLOSED);
    assert(lucent_native_adapter_create(host, error, sizeof(error)));
    lucent_native_load_request request = {argv[2], argv[2], argv[3]};
    assert(lucent_native_adapter_load(host, &request, error, sizeof(error)));
    lucent_native_io io = {LUCENT_NATIVE_RENDER_VULKAN_WINDOW, &window, NULL, audio, NULL};
    assert(lucent_native_adapter_start(host, &io, error, sizeof(error)));
    assert(lucent_native_adapter_source_image_binding(host, &binding, sizeof(binding)) == strtoul(argv[4], NULL, 10));
    const uint32_t status = lucent_native_adapter_query_source_image(host, 11, 12, 1000, &row, sizeof(row));
    assert(status == strtoul(argv[5], NULL, 10));
    if (status == LUCENT_SOURCE_MATCH_ACCEPTED) {
        assert(row.buffer_timestamp_ns == 1000 && row.composition.layers[0].queue_frame_number == 42);
    }
    assert(lucent_native_adapter_query_source_image(host, 11, 12, 1000, &row, 1) == LUCENT_SOURCE_BAD_ARGUMENT);
    assert(lucent_native_adapter_query_source_image(host, 11, 12, 0, &row, sizeof(row)) == LUCENT_SOURCE_BAD_ARGUMENT);
    assert(lucent_native_adapter_producer_timeline_hz(host) == 0.0); // Metadata grants no clock authority.
    assert(lucent_native_adapter_stop(host, error, sizeof(error)));
    assert(lucent_native_adapter_query_source_image(host, 11, 12, 1000, &row, sizeof(row)) == LUCENT_SOURCE_CLOSED);
    lucent_native_adapter_destroy(host);
}
'''
        compiler = shutil.which("cc")
        self.assertIsNotNone(compiler)
        with tempfile.TemporaryDirectory(prefix="native-source-image-test-") as temporary:
            directory = Path(temporary)
            main = directory / "host.c"
            main.write_text(source)
            game = directory / "game.mock"
            game.write_bytes(b"\x07")
            executable = directory / "host"
            run([compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-I", native / "include",
                 native / "lucent_native_adapter_host.c", main, "-ldl", "-o", executable])
            for name, defines, binding_status, row_status in (
                    ("old", [], 7, 7),
                    ("value", ["MOCK_SOURCE_IMAGE_SIDEBAND"], 1, 1),
                    ("bad_binding", ["MOCK_SOURCE_IMAGE_SIDEBAND", "MOCK_SOURCE_BAD_BINDING"], 9, 1),
                    ("bad_row", ["MOCK_SOURCE_IMAGE_SIDEBAND", "MOCK_SOURCE_BAD_ROW"], 1, 9)):
                library = directory / (name + ".so")
                run([compiler, "-std=c11", "-fPIC", "-shared", *[f"-D{value}=1" for value in defines],
                     native / "tests/mock_native_adapter.c", "-o", library])
                run([executable, library, directory, game, binding_status, row_status])

    def test_compiled_value_ledger_boundaries_lifetime_exact_keys_and_content_holds(self):
        # Uncommitted, build-Mac-only input (see tools/run_ci_tests.py).
        for needed in (EDEN / "common/lucent_source_image_types.h",):
            if not needed.exists():
                self.skipTest("local-only input absent: " + str(needed))
        source = r'''
#include "eden-lucent-source-image.h"
#include <cassert>
#include <thread>
#include <atomic>
using namespace Lucent;
lucent_source_composition_v1 image(SourceImageLedger& ledger, uint64_t frame = 1) {
    lucent_source_composition_v1 out{};
    auto header = ledger.Composition(0, 1, 50);
    lucent_source_layer_v1 layer{};
    layer.queue_epoch = 500; layer.queue_frame_number = frame;
    layer.flags = LUCENT_SOURCE_LAYER_ACQUIRED;
    AppendSourceLayer(out, header, layer);
    return out;
}
int main() {
    static_assert(sizeof(lucent_source_image_v1) <= 4096);
    static_assert(sizeof(lucent_source_binding_v1) == 64);
    SourceImageLedger ledger;
    lucent_source_binding_v1 binding{};
    lucent_source_image_v1 row{};
    assert(ledger.Binding(&binding, sizeof(binding)) == LUCENT_SOURCE_CLOSED);
    ledger.BeginSession(); ledger.BindSurface(); ledger.NewSwapchain();
    assert(ledger.Binding(&binding, sizeof(binding)) == LUCENT_SOURCE_MATCH_ACCEPTED);
    auto query = [&](uint64_t timestamp) {
        return ledger.Query(binding.session_epoch, binding.surface_epoch, timestamp, &row, sizeof(row));
    };
    auto first = image(ledger);
    assert(ledger.BeginPresent(first, 90, 1, 0, false) == 0);
    auto token = ledger.BeginPresent(first, 100, 1, 0, true);
    assert(token > 0 && query(100) == LUCENT_SOURCE_PENDING);
    first.layers[0].queue_frame_number = 999; // Original no longer owns recorded value.
    ledger.FinishPresent(token, 0, true);
    assert(query(100) == LUCENT_SOURCE_MATCH_ACCEPTED);
    assert(row.composition.layers[0].queue_frame_number == 1);
    assert(query(99) == LUCENT_SOURCE_NOT_FOUND && query(101) == LUCENT_SOURCE_NOT_FOUND);
    auto held = image(ledger);
    held.layers[0].flags = LUCENT_SOURCE_LAYER_HELD;
    auto heldToken = ledger.BeginPresent(held, 110, 2, 1, true);
    ledger.FinishPresent(heldToken, 0, true);
    assert(query(110) == LUCENT_SOURCE_MATCH_ACCEPTED);
    assert(row.composition.layers[0].queue_frame_number == 1);
    assert(row.composition.layers[0].flags == LUCENT_SOURCE_LAYER_HELD);
    auto duplicate = ledger.BeginPresent(held, 110, 3, 2, true);
    ledger.FinishPresent(duplicate, 0, true);
    assert(query(110) == LUCENT_SOURCE_AMBIGUOUS);
    auto rejected = ledger.BeginPresent(held, 120, 4, 2, true);
    ledger.FinishPresent(rejected, -1, false);
    assert(query(120) == LUCENT_SOURCE_REJECTED);
    auto retried = ledger.BeginPresent(held, 130, 5, 3, true);
    ledger.FinishPresent(retried, 0, true);
    assert(query(130) == LUCENT_SOURCE_MATCH_ACCEPTED);
    assert(query(120) == LUCENT_SOURCE_REJECTED);

    lucent_source_composition_v1 mixed{};
    auto multiHeader = ledger.Composition(0, 2, 50);
    auto left = held.layers[0]; auto overlay = left;
    overlay.queue_epoch = 501; overlay.flags = LUCENT_SOURCE_LAYER_OVERLAY | LUCENT_SOURCE_LAYER_ACQUIRED;
    AppendSourceLayer(mixed, multiHeader, left);
    AppendSourceLayer(mixed, multiHeader, overlay);
    assert(mixed.retained_layer_count == 2 && mixed.layers[0].queue_epoch != mixed.layers[1].queue_epoch);
    assert(mixed.layers[0].queue_frame_number == mixed.layers[1].queue_frame_number);
    lucent_source_composition_v1 overfull{};
    auto overHeader = ledger.Composition(0, 9, 50);
    for (int i = 0; i < 9; ++i) AppendSourceLayer(overfull, overHeader, left);
    assert(overfull.retained_layer_count == 8 && overfull.header.layer_count == 9);
    assert(!(overfull.header.flags & LUCENT_SOURCE_COMPOSITION_COMPLETE));
    lucent_source_composition_v1 inconsistent{};
    AppendSourceLayer(inconsistent, multiHeader, left);
    ++multiHeader.composition_ordinal;
    AppendSourceLayer(inconsistent, multiHeader, overlay);
    assert(inconsistent.header.flags & LUCENT_SOURCE_COMPOSITION_INCONSISTENT);

    for (uint64_t i = 0; i < 130; ++i) {
        auto next = image(ledger, i + 2);
        auto nextToken = ledger.BeginPresent(next, 1000 + i, static_cast<uint32_t>(i + 10), 0, true);
        ledger.FinishPresent(nextToken, 0, true);
    }
    assert(query(100) == LUCENT_SOURCE_NOT_FOUND);
    ledger.NewSwapchain();
    assert(query(1129) == LUCENT_SOURCE_NOT_FOUND);
    assert(ledger.BeginPresent(held, 1200, 150, 0, true) == 0); // Old swapchain composition.
    ledger.BindSurface();
    assert(query(1129) == LUCENT_SOURCE_STALE_EPOCH);
    assert(image(ledger).header.session_epoch == 0); // Binding awaits its new swapchain.
    ledger.NewSwapchain();
    assert(ledger.Binding(&binding, sizeof(binding)) == LUCENT_SOURCE_MATCH_ACCEPTED);
    auto newSurface = image(ledger);
    auto newToken = ledger.BeginPresent(newSurface, 2000, 151, 0, true);
    ledger.FinishPresent(token, -1, false); // Old token cannot mutate a newly allocated row.
    assert(query(2000) == LUCENT_SOURCE_PENDING);
    ledger.FinishPresent(newToken, 0, true);
    assert(query(2000) == LUCENT_SOURCE_MATCH_ACCEPTED);
    ledger.Close();
    assert(query(2000) == LUCENT_SOURCE_CLOSED);
    ledger.BeginSession(); ledger.BindSurface(); ledger.NewSwapchain();
    assert(query(2000) == LUCENT_SOURCE_STALE_EPOCH);

    // Single producer and independent readers exercise the real protected
    // values. A busy try_lock is a missing diagnostic, never a torn record.
    assert(ledger.Binding(&binding, sizeof(binding)) == LUCENT_SOURCE_MATCH_ACCEPTED);
    std::atomic<uint64_t> latest{0}; std::atomic<bool> finished{false};
    std::thread producer([&] {
        for (uint64_t i = 1; i <= 5000; ++i) {
            auto current = image(ledger, i);
            auto id = ledger.BeginPresent(current, 10000 + i, static_cast<uint32_t>(i), 0, true);
            ledger.FinishPresent(id, 0, true);
            latest.store(10000 + i);
        }
        finished.store(true);
    });
    while (!finished.load()) {
        const auto timestamp = latest.load();
        if (!timestamp) continue;
        const auto status = query(timestamp);
        if (status == LUCENT_SOURCE_MATCH_ACCEPTED || status == LUCENT_SOURCE_PENDING) {
            assert(row.buffer_timestamp_ns == timestamp);
            assert(row.composition.layers[0].queue_frame_number == timestamp - 10000);
        }
    }
    producer.join();
}
'''
        compiler = shutil.which("c++")
        self.assertIsNotNone(compiler)
        with tempfile.TemporaryDirectory(prefix="eden-source-image-test-") as temporary:
            directory = Path(temporary)
            main = directory / "source_image.cpp"
            main.write_text(source)
            # Mirror is validated independently below; actual common helper ABI
            # is the input used by the Eden compilation, not a Python model.
            executable = directory / "source_image"
            run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-pthread",
                 "-I", ROOT / "engines/patches", "-iquote", EDEN / "common",
                 main, "-o", executable])
            run([executable])

    def test_canonical_metadata_headers_equal_used_vendor_headers(self):
        for canonical, actual in (("engines/patches/eden-lucent-source-image.h", "lucent_source_image.h"),
                                  ("unified-android/native/include/lucent_native_source_image.h", "lucent_source_image_types.h")):
            self.assertEqual((ROOT / canonical).read_bytes(), (EDEN / "common" / actual).read_bytes())

    def test_used_value_owned_chain_reaches_exact_present(self):
        composer = (EDEN / "core/hle/service/nvnflinger/hardware_composer.cpp").read_text()
        for expected in (".queue_frame_number = item.frame_number", ".queue_epoch = layer->lucent_queue_epoch",
                         "LUCENT_SOURCE_LAYER_HELD", "layer.source_header = source_header"):
            self.assertIn(expected, composer)
        converter = (EDEN / "core/hle/service/nvdrv/devices/nvdisp_disp0.cpp").read_text()
        self.assertIn(".source_layer = layer.source_layer", converter)
        gpu = (EDEN / "video_core/gpu.cpp").read_text()
        self.assertIn("composite_layers = std::move(layers)", gpu)
        self.assertIn("current_request_counter, composite_layers]", gpu)
        renderer = (EDEN / "video_core/renderer_vulkan/renderer_vulkan.cpp").read_text()
        self.assertIn("AppendSourceLayer(frame->source_image", renderer)
        manager = (EDEN / "video_core/renderer_vulkan/vk_present_manager.cpp").read_text()
        self.assertIn("frame->source_image = {}", manager)
        self.assertIn("swapchain.Present(render_semaphore, &frame->source_image)", manager)
        swapchain = (EDEN / "video_core/renderer_vulkan/vk_swapchain.cpp").read_text()
        self.assertLess(swapchain.index("BeginPresent("), swapchain.index("present_queue.Present(present_info)"))
        self.assertLess(swapchain.index("present_queue.Present(present_info)"), swapchain.index("FinishPresent("))
        self.assertIn("desiredPresentTime = static_cast<u64>(now_ns)", swapchain)

    def test_no_authority_is_added_and_queries_hold_a_nonblocking_session_lease(self):
        adapter = (ROOT / "engines/patches/eden-lucent-adapter.cpp").read_text()
        export = adapter.split("uint32_t lucent_native_adapter_timing_capabilities_v1(void)")[1].split("}", 1)[0]
        self.assertNotIn("AUTHORITATIVE", export)
        java = (ROOT / "unified-android/src/com/thorium/preview/NativeAdapterHost.java").read_text()
        self.assertEqual(java.count("sourceQueryLease.readLock().tryLock()"), 2)
        self.assertIn("sourceQueryLease.writeLock().lock()", java.split("@Override public void close()", 1)[1])
        self.assertIn("sourceQueryLease.writeLock().lock()", java.split("public void stop()", 1)[1])
        self.assertIn("nativeQuerySourceImage(", java)


if __name__ == "__main__":
    unittest.main()
