"""Local candidate reproducibility checks, NOT a PS3 runtime qualification.

All patch operations use temporary copies. The inherited source, normal build
objects, staged adapter and source lock are never written. Optional heavyweight
local artifacts are skipped when absent; patch-shape checks always run.
"""

import hashlib
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
HISTORICAL_PATCH = ROOT / "engines/patches/aps3e-getllar-read-barrier.patch"
PATCH = ROOT / "engines/patches/aps3e-getllar-read-barrier-build.patch"
TRACE_PATCH = ROOT / "docs/qa/ps3-spurs-journal-2026-09-08/SPUThread.trace.patch"
REL = Path("app/src/main/cpp/rpcs3/rpcs3/Emu/Cell/SPUThread.cpp")
SOURCE = ROOT / "engines/build/sources/aps3e-b5ae1af50d5e2f3b705506e7380a4504e086840b" / REL
OBJECT = ROOT / "docs/qa/ps3-spurs-journal-2026-09-08/SPUThread.read-barrier-normal.o"
LLVM = Path("/Users/tyleryoung/Library/Android/sdk/ndk/27.0.12077973/toolchains/llvm/prebuilt/darwin-x86_64/bin")
STAMP = "if (u64 time0 = vm::reservation_acquire(addr); (ntime & test_mask) != (time0 & test_mask))"


class GetllarReadBarrierTest(unittest.TestCase):
    def test_candidate_is_only_four_added_lines_before_stamp_check(self):
        patch = PATCH.read_bytes()
        self.assertEqual("3577116a33bd882e3013b3ddab87239731270a1b39d5d99badc94c2d496e7b95",
                         hashlib.sha256(HISTORICAL_PATCH.read_bytes()).hexdigest())
        def additions(payload):
            return [line for line in payload.splitlines()
                    if line.startswith(b"+") and not line.startswith(b"+++")]
        self.assertEqual(additions(HISTORICAL_PATCH.read_bytes()), additions(patch))
        added = [line[1:] for line in patch.decode().splitlines()
                 if line.startswith("+") and not line.startswith("+++")]
        removed = [line for line in patch.decode().splitlines()
                   if line.startswith("-") and not line.startswith("---")]
        self.assertEqual(4, len(added))
        self.assertEqual([], removed)
        self.assertTrue(all(line.lstrip().startswith("//") for line in added[:3]))
        self.assertEqual("atomic_fence_acquire();", added[-1].strip())
        self.assertIn(" " + "\t" * 3 + STAMP, patch.decode().splitlines())

    @unittest.skipUnless(SOURCE.is_file(), "local pinned aPS3e source not available")
    def test_roundtrip_with_and_without_diagnostic_blocks_preserves_other_edits(self):
        original = SOURCE.read_bytes()
        with tempfile.TemporaryDirectory(prefix="aps3e-getllar-regression-") as folder:
            work = Path(folder)
            target = work / REL
            target.parent.mkdir(parents=True)
            target.write_bytes(original)

            def apply(*flags, success=True):
                result = subprocess.run(["git", "apply", *flags, str(PATCH)],
                                        cwd=work, capture_output=True, text=True)
                self.assertEqual(success, result.returncode == 0, result.stderr)

            # The current candidate is already patched. Reapplying must fail,
            # while reversing and applying must reproduce every byte.
            apply("--check", success=False)
            apply("--reverse")
            before = target.read_bytes()
            apply()
            self.assertEqual(original, target.read_bytes())

            # Remove only the seven diagnostic guards in the temporary copy.
            # Pin the reconstructed pre-diagnostic source so a changed source
            # is reported for review, never silently overwritten or normalized.
            self.assertEqual(7, before.count(b"#if defined(LUCENT_SPURS_TASKSET_TRACE)"))
            target.write_bytes(before)
            result = subprocess.run(["git", "apply", "--reverse", str(TRACE_PATCH)],
                                    cwd=work, capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)
            clean = target.read_bytes()
            self.assertEqual("c172ad19362909c4970570e713cc87543c1b3d1fc3c4fc68d1ae8bb915583948",
                             hashlib.sha256(clean).hexdigest())
            target.write_bytes(clean)
            apply("--check")
            apply()
            patched = target.read_text()
            self.assertNotIn("LUCENT_SPURS_TASKSET_TRACE", patched)
            self.assertRegex(patched, r"mov_rdata\(rdata, data\);\s*\}\s*"
                             r"(?://[^\n]*\n\s*){3}atomic_fence_acquire\(\);\s*"
                             + re.escape(STAMP))
            apply("--check", success=False)
            apply("--reverse")
            self.assertEqual(clean, target.read_bytes())
        self.assertEqual(original, SOURCE.read_bytes())

    @unittest.skipUnless(OBJECT.is_file() and (LLVM / "llvm-objdump").is_file(),
                         "local compiled candidate or pinned NDK not available")
    def test_tested_arm_object_has_barrier_and_no_trace_symbols(self):
        self.assertEqual("7022984aa4246ac2e55f4ee3d7c433ca2611eb1de5f59c86346b73ef997cb0eb",
                         hashlib.sha256(OBJECT.read_bytes()).hexdigest())
        symbols = subprocess.check_output([str(LLVM / "llvm-nm"), "-C", str(OBJECT)], text=True)
        self.assertNotIn("lucent_spurs", symbols)
        disassembly = subprocess.check_output([
            str(LLVM / "llvm-objdump"), "-d",
            "--disassemble-symbols=_ZN10spu_thread15process_mfc_cmdEv", str(OBJECT)], text=True)
        # Exact compiled witness, not a portable offset contract or a proof
        # covering every concurrent writer / every game.
        self.assertRegex(disassembly, r"105c:\s+d50339bf\s+dmb\s+ishld")
        self.assertRegex(disassembly, r"1078:\s+c8dffd08\s+ldar\s+x8, \[x8\]")


if __name__ == "__main__":
    unittest.main()
