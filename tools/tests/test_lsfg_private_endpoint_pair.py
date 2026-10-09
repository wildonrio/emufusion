"""Actual native private-pair decisions with controlled GPU/sync-file leaves.

This is host regression evidence, not Android GPU, compositor or pixel-quality
qualification. Endpoint/proof command recording is a counted, controlled leaf;
the production selectors, readiness, activation, analysis and retirement execute.
"""
from pathlib import Path
import hashlib
import os
import re
import subprocess
import tempfile
import unittest

from tools.tests.test_lsfg_surface_callback_diagnostics import declaration as extract

ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / "unified-android/lsfg-qualification-native"


def fixture_source():
    source = (NATIVE / "owned_vulkan_host.cpp").read_text()
    header = (NATIVE / "owned_vulkan_host.hpp").read_text()
    structs = "\n".join(extract(header, "struct " + name + " {", True) for name in (
        "LiveRequest", "PreparedPresentation", "SurfaceSubmission", "Completion"))
    structs += "\n" + "\n".join(extract(source, signature, True) for signature in (
        "struct ImportedImage {", "struct ImportedSlot {", "enum class LiveSlotState {",
        "struct LiveSlot {", "struct DropDrainObservation {"))
    methods = "\n\n".join(extract(source, signature) for signature in (
        "std::optional<PreparedPresentation> tryPreparePrivateGenerated(",
        "std::optional<PreparedPresentation> tryPreparePrivateEndpointPair(",
        "std::optional<PreparedPresentation> tryPreparePrivateOutput(",
        "void holdPrivatePrepared(", "uint32_t privatePreparedPairStatus(",
        "bool activatePrivatePrepared(", "void abandonPrivatePrepared(",
        "bool referencesSourceImage(", "void validateLiveRequest(",
        "void resetLiveSlotForRequest(", "LiveSlot& requirePrepared(",
        "ImportedImage& selectedImage(", "AHardwareBuffer* selectedBuffer(",
        "std::optional<SurfaceSubmission> pollSurfaceSubmission()",
        "std::optional<Completion> pollSurfaceCompletion(", "LiveSlot* findSurfaceSlot(",
        "uint64_t proofFenceTimestamp(", "bool readyFdSignaled(",
        "DropDrainObservation observeDropDrain(", "void retireAbandonedCopies()",
        "void resetLiveSlotStorage(", "void closeReadyFd(", "static uint64_t ppm(",
        "uint32_t analyzePrivatePairStatus(", "Completion analyzeCompletion("))
    constants = source[source.index("constexpr uint32_t kProofWidth ="):
                       source.index("uint64_t monotonicNs()")]
    replacements = {
        "@DECLARATIONS@": structs, "@METHODS@": methods, "@CONSTANTS@": constants,
        "@READY@": extract(source, "struct ReadyFenceObservation {", True) + "\n" +
                    extract(source, "ReadyFenceObservation observeReadyFence(int fd)"),
        "@SLOT_COUNT@": re.search(r"static constexpr uint32_t kFixedSlotCount = [^;]+;", header).group(),
    }
    fixture = (ROOT / "tools/tests/fixtures/lsfg_private_endpoint_pair.cpp.in").read_text()
    for key, value in replacements.items():
        assert fixture.count(key) == 1, key
        fixture = fixture.replace(key, value)
    assert not re.search(r"@[A-Z_]+@", fixture)
    return fixture


class PrivateEndpointPairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory(prefix="lsfg-private-endpoint-")
        cls.addClassCleanup(cls.scratch.cleanup)
        directory = Path(cls.scratch.name)
        source = directory / "fixture.cpp"
        source.write_text(fixture_source())
        cls.binary = directory / "fixture"
        compiled = subprocess.run([
            "c++", "-std=c++20", "-Wall", "-Wextra", "-Werror",
            "-Wno-missing-field-initializers", "-g", "-O1",
            "-fno-omit-frame-pointer", "-fsanitize=address,undefined",
            str(source), "-o", str(cls.binary),
        ], capture_output=True, text=True, timeout=60)
        if compiled.returncode:
            raise AssertionError(compiled.stdout + compiled.stderr)
        for name in ("owned_vulkan_host.cpp", "owned_vulkan_host.hpp"):
            print("SOURCE_SHA256", name, hashlib.sha256((NATIVE / name).read_bytes()).hexdigest())

    def case(self, name):
        env = dict(os.environ, ASAN_OPTIONS="detect_leaks=0:abort_on_error=1",
                   UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")
        result = subprocess.run([str(self.binary), name], capture_output=True,
                                text=True, timeout=10, env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS " + name, result.stdout)

    def test_real_and_generated_private_work_remain_distinct(self):
        self.case("isolation")

    def test_inference_reservation_preserves_three_presentation_slots(self):
        self.case("reserved_inference_capacity")

    def test_actual_selected_endpoint_matches_proof_sample_not_default_tile(self):
        self.case("selection")

    def test_expiry_preserves_pair_fds_and_has_no_visible_identity_or_gpu_resubmit(self):
        self.case("expiry")

    def test_readiness_requires_exact_kernel_signal_and_is_idempotent(self):
        self.case("readiness")

    def test_real_proof_queues_behind_copy_without_cpu_poll_delay(self):
        self.case("queued_dependency")

    def test_source_copy_lease_ends_before_fixed_proof_and_output_slot_retirement(self):
        self.case("retirement")

    def test_invalid_abandoned_fence_retains_source_ownership(self):
        self.case("invalid_retirement")

    def test_post_submit_export_or_dup_failure_quarantines_owned_proof(self):
        self.case("export_failure")


if __name__ == "__main__":
    unittest.main(verbosity=2)
