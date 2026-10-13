"""A dense epoch teardown discards its timer queries, so it must also forget the
per-pair stage slots those queries were filling.

A pair that had reported only some stages when its queries were discarded stayed
in its slot. When the slot came round 128 promotions later the next pair saw a
foreign sequence and rejected with wrapped-incomplete-timer-pair; that reject
returned before clearing the slot, so it fired again every 128 promotions. On
the Thor Sonic Superstars at 4x re-armed every ~120 pairs (2026-10-13), and each
loop spent one of the session's transient re-arms.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
GENERATOR = (ROOT / "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java").read_text()


def method(signature):
    start = GENERATOR.index(signature)
    brace = GENERATOR.index("{", start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (GENERATOR[end] == "{") - (GENERATOR[end] == "}")
        end += 1
    return GENERATOR[start:end]


class DenseTimerEpochSlotsTest(unittest.TestCase):
    def test_teardown_clears_pair_slots_after_discarding_queries(self):
        body = method("private void teardownDenseEpoch(String reason)")
        discard = body.index("timer.discardPending();")
        for clear in ("java.util.Arrays.fill(densePairSequence, 0L);",
                      "java.util.Arrays.fill(densePairTotalUs, 0L);",
                      "java.util.Arrays.fill(densePairMask, 0);"):
            self.assertIn(clear, body)
            self.assertGreater(body.index(clear), discard, clear)

    def test_every_rejection_tears_the_epoch_down(self):
        body = method("private void rejectDense(String reason, Throwable failure)")
        self.assertIn('teardownDenseEpoch("runtime-reject");', body)

    def test_wrap_is_still_detected_within_an_epoch(self):
        body = method("private void pollDenseTimers()")
        self.assertIn("if (densePairSequence[pair] != 0L && densePairSequence[pair] != sequence) {",
                      body)
        self.assertIn('rejectDense("wrapped-incomplete-timer-pair", null);', body)


if __name__ == "__main__":
    unittest.main()
