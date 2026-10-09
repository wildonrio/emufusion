"""Execute the patch's guards against deterministic cache-line interleavings.

No native compilation, threads, or device access. Each 16-byte load/store is
one model step, avoiding a C++ data race in the test itself. The tearing writer
is explicitly unversioned (e.g. a writer outside the reservation protocol),
NOT Accurate SPU DMA. A separate failed reservation lock may transiently add
64 and return to the original version without writing the payload.

This rejects one finite false-success witness; it neither proves arbitrary
unversioned ABA impossible nor identifies the writer in the ICO failure.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
PATCH = ROOT / "engines/patches/aps3e-putllc-unchanged-race.patch"
LOCK = ROOT / "engines/aps3e-source-lock.json"
CMP = "cmp_rdata(rdata, vm::_ref<spu_rdata_t>(addr))"
VERSION = "res == rtime"
CAS = "res.compare_and_swap_test(rtime, rtime + 128)"


def guard_operands(side):
    guards = re.findall(r"^" + re.escape(side) + r"\s*if \((.*)\)$",
                        PATCH.read_text(), re.M)
    if len(guards) != 1:
        raise AssertionError("expected exactly one changed PUTLLC guard")
    operands = guards[0].split(" && ")
    if any(value not in (CMP, VERSION, CAS) for value in operands):
        raise AssertionError("unexpected guard: update the interleaving model")
    return operands


class Line:
    def __init__(self, scenario="equal"):
        # Eight independently copied 16-byte chunks form the 128-byte line.
        self.saved = [bytes([n]) * 16 for n in range(8)]
        self.live = list(self.saved)
        self.rtime = 0x100
        self.version = self.rtime
        self.scenario = scenario
        self.comparisons = 0
        self.cas_calls = 0
        self.states = []
        if scenario in ("tear", "transient_lock", "versioned_tear"):
            self.live[7] = b"C" * 16
        elif scenario == "different":
            self.live[0] = b"D" * 16
        self.states.append(tuple(self.live))

    def compare(self):
        self.comparisons += 1
        observed = []
        for index in range(8):
            observed.append(self.live[index])
            if self.comparisons == 1 and index == 0 and self.scenario in (
                    "tear", "transient_lock", "versioned_tear"):
                # Reader saw the old first chunk. An independent writer now
                # changes that chunk, then restores the final chunk before
                # the reader reaches it. The complete live line NEVER equals
                # saved, but this first torn comparison reports equality.
                self.live[0] = b"D" * 16
                self.states.append(tuple(self.live))
                self.live[7] = self.saved[7]
                self.states.append(tuple(self.live))
                if self.scenario == "transient_lock":
                    self.version += 64  # separate unsuccessful lock owner
                elif self.scenario == "versioned_tear":
                    self.version += 128  # a completed versioned writer
        return observed == self.saved

    def cas(self):
        self.cas_calls += 1
        if self.scenario == "transient_lock":
            self.version -= 64  # failed lock releases, without payload write
        if self.version != self.rtime:
            return False
        self.version += 128
        return True

    def evaluate(self, operands):
        # C++ && evaluates left-to-right and short-circuits. Execute the actual
        # patch guard's ordered operands, not a separately hard-coded policy.
        for operand in operands:
            result = (self.compare() if operand == CMP else
                      self.version == self.rtime if operand == VERSION else
                      self.cas())
            if not result:
                return False
        return True


class PutllcRaceTest(unittest.TestCase):
    def selected_guard(self):
        mode = os.environ.get("APS3E_PUTLLC_REGRESSION_GUARD", "new")
        self.assertIn(mode, ("old", "new"))
        return guard_operands("-" if mode == "old" else "+")

    def test_torn_comparison_must_not_report_success(self):
        line = Line("tear")
        self.assertFalse(line.evaluate(self.selected_guard()),
                         "torn comparison falsely accepted unchanged PUTLLC")
        self.assertTrue(all(state != tuple(line.saved) for state in line.states))
        self.assertEqual(2, line.comparisons)
        self.assertEqual(0, line.cas_calls)

    def test_transient_lock_must_reject_before_it_disappears(self):
        line = Line("transient_lock")
        self.assertFalse(line.evaluate(self.selected_guard()),
                         "reservation transient vanished before the sole CAS")
        self.assertTrue(all(state != tuple(line.saved) for state in line.states))
        self.assertEqual(1, line.comparisons)
        self.assertEqual(0, line.cas_calls)

    def test_old_guard_exhibits_both_false_successes(self):
        for scenario in ("tear", "transient_lock"):
            with self.subTest(scenario=scenario):
                line = Line(scenario)
                self.assertTrue(line.evaluate(guard_operands("-")))
                self.assertNotEqual(line.saved, line.live)
                self.assertEqual(line.rtime + 128, line.version)

    def test_stable_equal_different_and_versioned_writer_controls(self):
        for side in ("-", "+"):
            for scenario, expected in (("equal", True), ("different", False),
                                       ("versioned_tear", False)):
                with self.subTest(side=side, scenario=scenario):
                    self.assertEqual(expected, Line(scenario).evaluate(
                        guard_operands(side)))

    def test_exact_upstream_change_and_inherited_candidate_identity(self):
        self.assertEqual([CMP, CAS], guard_operands("-"))
        self.assertEqual([CMP, VERSION, CMP, CAS], guard_operands("+"))
        patch = PATCH.read_bytes()
        added = [line for line in patch.splitlines()
                 if line.startswith(b"+") and not line.startswith(b"+++")]
        removed = [line for line in patch.splitlines()
                   if line.startswith(b"-") and not line.startswith(b"---")]
        self.assertEqual((2, 1), (len(added), len(removed)))
        lock = json.loads(LOCK.read_text())
        relative = str(PATCH.relative_to(ROOT))
        active, = [item for item in lock["patches"] if item["path"] == relative]
        candidate, = [item for item in lock["candidatePatches"]
                      if item["path"] == relative]
        self.assertEqual("STAGED_VIA_ABI2_RELINK_REJECTED_AS_ICO_FIX", candidate["status"])
        self.assertEqual(active["sha256"], candidate["sha256"])
        self.assertEqual(active["bytes"], candidate["bytes"])
        self.assertEqual(2, lock["adapterAbi"]["abiVersion"])
        self.assertFalse(candidate["deviceQualified"])
        self.assertEqual(
            "9f22b99a11eebf0c429cad0f289224e38c8c81ac6c28f840ec5da6706894b307",
            candidate["artifact"]["sha256"])
        self.assertEqual(
            "a787c93906d8998291a48491e0acdc32817ab318ec8f9cfc71bc6880c42b3d62",
            lock["priorRetainedMilestone"]["previousStagedSha256"])
        # The ABI2 artifact is historical. Later retained builds keep PUTLLC
        # while changing other objects; bind the current artifact to real bytes.
        staged = ROOT / lock["artifact"]["stagedPath"]
        self.assertEqual(staged.stat().st_size, lock["artifact"]["bytes"])
        self.assertEqual(hashlib.sha256(staged.read_bytes()).hexdigest(),
                         lock["artifact"]["sha256"])
        self.assertEqual(len(patch), candidate["bytes"])
        self.assertEqual(hashlib.sha256(patch).hexdigest(), candidate["sha256"])
        self.assertEqual("8126a199f529e2bcd0025815fb9cffd0fa9fb700",
                         candidate["upstreamCommit"])


if __name__ == "__main__":
    unittest.main()
