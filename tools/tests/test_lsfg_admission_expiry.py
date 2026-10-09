#!/usr/bin/env python3
"""Compile exact candidate admission/JNI methods with controlled host stubs.

Only generated test artifacts are written, in a temporary build directory.
No Android runtime, Vulkan driver, AHB import, or real timing is simulated as
qualified evidence. The extracted production paths own all tested decisions.
"""

from pathlib import Path
import hashlib
import os
import re
import subprocess
import tempfile
import unittest


TESTS = Path(__file__).resolve().parent
NATIVE = Path(os.environ.get("EMUFUSION_NATIVE_TEST_SOURCE", TESTS.parents[1] / "unified-android/lsfg-qualification-native")).resolve()


def extract(text, signature, trailing_semicolon=False):
    """Take an unmodified complete C++ declaration, ignoring quoted braces."""
    start = text.index(signature)
    opening = text.index("{", start)
    # Keep the same offsets while masking comments and ordinary literals.
    tokens = re.compile(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', re.S)
    masked = tokens.sub(lambda match: " " * len(match.group()), text)
    depth = 0
    for index in range(opening, len(text)):
        if masked[index] == "{":
            depth += 1
        elif masked[index] == "}":
            depth -= 1
            if depth == 0:
                end = index + 1
                if trailing_semicolon:
                    assert text[end] == ";", signature
                    end += 1
                return text[start:end]
    raise AssertionError("unterminated declaration: " + signature)


def fixture_source():
    cpp = (NATIVE / "owned_vulkan_host.cpp").read_text()
    hpp = (NATIVE / "owned_vulkan_host.hpp").read_text()
    jni = (NATIVE / "lsfg_qualification_jni.cpp").read_text()
    declarations = "\n".join(extract(hpp, "struct " + name + " {", True)
                             for name in ("LiveRequest", "PreparedPresentation",
                                          "SurfaceSubmission", "Completion"))
    declarations += "\n" + "\n".join(
        extract(cpp, signature, True) for signature in (
            "struct ImportedImage {", "enum class LiveSlotState {",
            "struct LiveSlot {", "struct DropDrainObservation {"))
    methods = "\n\n".join(extract(cpp, signature) for signature in (
        "void validateLiveRequest(const LiveRequest& request) const",
        "void resetLiveSlotForRequest(LiveSlot& slot, const LiveRequest& request)",
        "LiveSlot& requirePrepared(const PreparedPresentation& prepared)",
        "std::optional<PreparedPresentation> tryPrepare(const LiveRequest& request)",
        "bool activatePrivatePrepared(const PreparedPresentation& prepared,",
        "void presentPrepared(const PreparedPresentation& prepared,",
        "void markSurfaceCutoffDrop(LiveSlot& slot, uint64_t now, uint32_t branch)",
        "DropDrainObservation observeDropDrain(const LiveSlot& slot)",
        "std::optional<Completion> pollDroppedSurfacePresentation()",
        "uint64_t oldestPendingSurfacePresentId() const",
        "void resetLiveSlotStorage(LiveSlot& slot)",
        "void closeReadyFd(LiveSlot& slot)",
        "void retireAbandonedCopies()"))
    # These exact prefixes reach the tested early-return/expiry branches. A
    # sentinel throws if a case accidentally reaches excluded GPU proof code.
    submission = extract(cpp, "std::optional<SurfaceSubmission> pollSurfaceSubmission()")
    methods += "\n" + submission[:submission.index("        try {")]
    methods += '\nthrow std::logic_error("fixture excludes non-expired Surface proof submission");\n}\n'
    status = extract(cpp, "uint32_t privatePreparedPairStatus(")
    methods += status[:status.index("        try {")]
    methods += '\nthrow std::logic_error("fixture requires already-private-ready proof");\n}\n'
    enqueue = extract(jni, 'extern "C" JNIEXPORT jint JNICALL\nJava_com_thorium_preview_game_NativeLsfgBridge_enqueue(')
    prepared = extract(jni, "struct PreparedGenerated {", True)
    prepared += "\n" + extract(jni, "struct PreparedRealPair {", True)
    replacements = {
        "@READY_OBSERVATION@": extract(cpp, "struct ReadyFenceObservation {", True),
        "@DECLARATIONS@": declarations,
        "@METHODS@": methods,
        "@PREPARED_GENERATED@": prepared,
        "@JNI_ENQUEUE@": enqueue,
        "@DRAIN_TIMEOUT@": re.search(r"constexpr uint64_t kDroppedDrainTimeoutNs = [^;]+;", cpp).group(),
        "@SLOT_COUNT@": re.search(r"static constexpr uint32_t kFixedSlotCount = [^;]+;", hpp).group(),
        "@JNI_SLOT_COUNT@": re.search(r"constexpr uint32_t kSlotCount = [^;]+;", jni).group(),
    }
    template = (TESTS / "fixtures/lsfg_admission_expiry.cpp.in").read_text()
    for key, value in replacements.items():
        assert template.count(key) == 1, key
        template = template.replace(key, value)
    assert not re.search(r"@[A-Z_]+@", template)
    return template


CASES = (
    "malformed_expired", "entry_expired", "retirement_expiry",
    "retirement_then_fresh", "no_idle_slot", "pre_deadline_accept",
    "private_expiry_preserves", "private_malformed_expired",
    "private_accept_once", "jni_expiry_preserves", "jni_malformed_expired", "jni_sequence_boundary",
    "jni_pair_mismatch", "jni_unknown_pair_status", "jni_queue_backpressure",
    "jni_endpoint_expiry", "jni_endpoint_accept_once", "post_submit_expiry",
    "accepted_drop_retirement", "private_drop_waits_for_proof",
    "accepted_drop_timeout", "accepted_drop_fence_error", "export_failure_owned",
)


class AdmissionExpiryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory(prefix="lsfg-admission-")
        cls.addClassCleanup(cls.scratch.cleanup)
        build = Path(cls.scratch.name)
        source = build / "admission_expiry_fixture.cpp"
        source.write_text(fixture_source())
        cls.binary = build / "admission-expiry"
        command = ["c++", "-std=c++20", "-Wall", "-Wextra", "-Werror",
                   "-Wno-missing-field-initializers", "-g", "-O1",
                   "-fno-omit-frame-pointer", "-fsanitize=address,undefined",
                   "-I", str(NATIVE), str(source), "-o", str(cls.binary)]
        compiled = subprocess.run(command, capture_output=True, text=True, timeout=60)
        if compiled.returncode:
            raise AssertionError(compiled.stdout + compiled.stderr)
        for name in ("owned_vulkan_host.cpp", "owned_vulkan_host.hpp",
                     "lsfg_qualification_jni.cpp", "midpoint_timestamp.hpp"):
            print("SOURCE_SHA256", name, hashlib.sha256((NATIVE / name).read_bytes()).hexdigest())
        print("SANITIZERS address,undefined; extracted actual native methods + complete JNI enqueue")

    def run_case(self, case):
        env = dict(os.environ, ASAN_OPTIONS="detect_leaks=0:abort_on_error=1",
                   UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")
        result = subprocess.run([str(self.binary), case], capture_output=True,
                                text=True, env=env, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS " + case, result.stdout)


for case_name in CASES:
    def test(self, name=case_name):
        self.run_case(name)
    setattr(AdmissionExpiryTests, "test_" + case_name, test)


if __name__ == "__main__":
    unittest.main(verbosity=2)
