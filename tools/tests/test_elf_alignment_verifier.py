import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "unified-android" / "tools" / "verify_elf_alignment.py"
SPEC = importlib.util.spec_from_file_location("verify_elf_alignment", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def elf_with_alignment(alignment: int) -> bytes:
    data = bytearray(64 + 56)
    data[:4] = b"\x7fELF"
    data[4] = 2
    data[5] = 1
    struct.pack_into("<Q", data, 32, 64)
    struct.pack_into("<H", data, 54, 56)
    struct.pack_into("<H", data, 56, 1)
    struct.pack_into("<I", data, 64, 1)
    struct.pack_into("<Q", data, 64 + 48, alignment)
    return bytes(data)


class ElfAlignmentVerifierTest(unittest.TestCase):
    def make_apk(self, alignment: int) -> Path:
        handle = tempfile.NamedTemporaryFile(suffix=".apk", delete=False)
        handle.close()
        apk = Path(handle.name)
        with zipfile.ZipFile(apk, "w") as archive:
            archive.writestr(
                "lib/arm64-v8a/liblucent_test.so",
                elf_with_alignment(alignment),
            )
        self.addCleanup(apk.unlink)
        return apk

    def test_accepts_16k_alignment(self):
        self.assertEqual([], MODULE.verify(self.make_apk(0x4000)))

    def test_rejects_4k_alignment(self):
        errors = MODULE.verify(self.make_apk(0x1000))
        self.assertEqual(1, len(errors))
        self.assertIn("below 0x4000", errors[0])

    def test_allowlisted_4k_library_becomes_warning_not_error(self):
        apk = self.make_apk(0x1000)
        errors, warnings = MODULE.verify_report(apk, ["liblucent_test.so"])
        self.assertEqual([], errors)
        self.assertEqual(1, len(warnings))
        self.assertIn("liblucent_test.so", warnings[0])
        self.assertIn("allowlisted", warnings[0])

    def test_allowlist_does_not_cover_other_libraries(self):
        apk = self.make_apk(0x1000)
        errors, warnings = MODULE.verify_report(apk, ["libssl.so"])
        self.assertEqual([], warnings)
        self.assertEqual(1, len(errors))
        self.assertIn("liblucent_test.so", errors[0])

    def test_allowlisted_16k_library_produces_no_warning(self):
        apk = self.make_apk(0x4000)
        errors, warnings = MODULE.verify_report(apk, ["liblucent_test.so"])
        self.assertEqual([], errors)
        self.assertEqual([], warnings)

    def test_verify_accepts_allowlist_for_compatibility(self):
        self.assertEqual(
            [], MODULE.verify(self.make_apk(0x1000), ["liblucent_test.so"])
        )

    def test_build_script_gates_on_the_hardcoded_allowlist(self):
        build = (ROOT / "unified-android" / "build.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("ALLOWED_4K_LIBS=", build)
        self.assertIn("--allow-4k-lib", build)
        self.assertIn("MUST SHRINK TO ZERO BEFORE RELEASE", build)
        # The release path stays strict: no allowlist at all.
        self.assertIn(
            'if [ "${LUCENT_REQUIRE_16K_ALIGNMENT:-0}" = 1 ]; then\n'
            '    python3 "$PROJECT_DIR/tools/verify_elf_alignment.py" "$OUTPUT" >/dev/null',
            build,
        )
        # Libraries known to be correctly 16 KiB aligned must never be waived.
        allowlist = build.split("ALLOWED_4K_LIBS=\"", 1)[1].split('"', 1)[0]
        for aligned in (
            "liblucent_libretro_host.so",
            "liblucent_vulkan_host.so",
            "liblucent_core_blastem.so",
            "liblucent_core_mupen64plus_next.so",
            "liblucent_core_melonds_ds.so",
            "liblucent_core_swanstation.so",
            "liblucent_core_dosbox_pure.so",
            "liblucent_core_armsx2.so",
            "liblucent_core_dolphin.so",
            "liblucent_core_scummvm.so",
        ):
            self.assertNotIn(aligned, allowlist.split())


if __name__ == "__main__":
    unittest.main()
