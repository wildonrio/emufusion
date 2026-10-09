"""Source guard for optional diagnostic readbacks, not a runtime cadence test."""
from pathlib import Path
import unittest


class DenseFlowDumpThrottleTest(unittest.TestCase):
    def test_rejected_capture_is_also_throttled(self):
        source = (Path(__file__).resolve().parents[2] /
                  "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java").read_text()
        method = source.split("private void maybeDumpDenseFlow(", 1)[1].split(
            "private void dumpDensePlane(", 1)[0]
        # Disabled/exhausted capture must not add readbacks. Both successful
        # and rejected attempts must advance the timestamp before readback.
        ordered = ["!DENSE_FLOW_DUMP_MARKER.exists()",
                   "!contiguousCapture && now - denseFlowDumpLastNs < 700_000_000L",
                   "denseFlowDumpCount >= DENSE_FLOW_DUMP_LIMIT",
                   "denseFlowDumpLastNs = now;",
                   "readDenseCoarseDifference()",
                   "coarseDifference < DENSE_FLOW_DUMP_MIN_COARSE_DIFFERENCE",
                   "readDenseGlobalSeedPixels(0)"]
        positions = [method.index(fragment) for fragment in ordered]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(method.count("denseFlowDumpLastNs = now;"), 1)
        self.assertIn('"Dense flow dump waiting generator="', method)
        self.assertIn("coarseDifference < DENSE_FLOW_DUMP_MIN_COARSE_DIFFERENCE &&\n"
                      "                !DENSE_FLOW_DUMP_LOW_MOTION_MARKER.exists() && !contiguousCapture", method)
        # The override cannot arm capture on its own or bypass rate/burst caps.
        self.assertGreater(method.index("!DENSE_FLOW_DUMP_LOW_MOTION_MARKER.exists()"),
                           method.index("denseFlowDumpCount >= DENSE_FLOW_DUMP_LIMIT"))
        self.assertIn("out.writeInt(10);", method)
        self.assertEqual(method.count("dumpDensePlane(out,"), 10)
        for name, index in [("previousFull", "previousIndex"), ("currentFull", "currentIndex")]:
            self.assertIn('"'+name+'", historyTextures['+index+'],\n'
                          '                        historyWidth, historyHeight)', method)


if __name__ == "__main__":
    unittest.main()
