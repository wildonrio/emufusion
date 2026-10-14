"""Low-latency presentation (owner, 2026-10-14: about half a second of input
lag in Ocarina of Time with frame generation on) and the corner readout."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GAME = ROOT / "unified-android" / "src" / "com" / "thorium" / "preview" / "game"
GENERATOR = GAME / "DisplayFrameGenerator.java"
SWITCH = GAME / "TimelineSchedulerSwitch.java"
SCHEDULER = ROOT / "unified-android" / "src" / "com" / "thorium" / "emufusion" / "video" / "TimelineFrameScheduler.java"


class LowLatencyPresentationTest(unittest.TestCase):
    def test_low_latency_is_the_default_with_a_qa_off_switch(self):
        switch = SWITCH.read_text()
        self.assertIn('LOW_LATENCY_GLOBAL = "emufusion_framegen_low_latency"', switch)
        self.assertIn("private static volatile boolean lowLatency = true;", switch)
        self.assertIn("context.getContentResolver(), LOW_LATENCY_GLOBAL, 1) != 0;", switch)

    def test_duplicate_checks_commit_on_the_next_vsync(self):
        generator = GENERATOR.read_text()
        # Every vsync drains finished signature results, oldest first.
        self.assertIn("if (externalTransport == null) pollSignatureOnVsync();", generator)
        self.assertIn("for (int drained = 0; drained < SIGNATURE_CANDIDATE_SLOTS; ++drained) {", generator)
        self.assertIn("long[] row = signatureTimer.pollSignature(denseSignatureSequence);\n"
                      "                if (row.length == 0) break;", generator)
        self.assertIn("consumeClassifiedFrame(unique);", generator)

    def test_one_fewer_look_ahead_endpoint_and_earlier_trimming(self):
        generator = GENERATOR.read_text()
        self.assertIn("(TimelineSchedulerSwitch.lowLatency() ?\n"
                      "                                        ENDPOINT_FIFO_PRIME_DEPTH - 1 :", generator)
        self.assertIn("timeline.setTrimExcessQueued(TimelineSchedulerSwitch.lowLatency() ?\n"
                      "                1 : TimelineFrameScheduler.TRIM_EXCESS_QUEUED);", generator)
        scheduler = SCHEDULER.read_text()
        self.assertIn("excessQueued >= trimExcessQueued", scheduler)
        self.assertIn("public void setTrimExcessQueued(int images)", scheduler)

    def test_display_lag_is_measured(self):
        generator = GENERATOR.read_text()
        self.assertEqual(generator.count("recordArrival(submittedFrameCount);"), 2)
        self.assertIn("deadline.contentPresentationTimeNs());", generator)
        self.assertIn('" realDisplayLagMs33/67/100/150/200/300/more="', generator)

    def test_corner_counts_every_new_image_sent_to_the_screen(self):
        generator = GENERATOR.read_text()
        self.assertIn("++verifyWindowGenerated;", generator)
        self.assertIn("callback.onDisplayedFrameRate(real, shown + presentedGenerated);", generator)
        self.assertIn("motionVerifiedFps=%.1f", generator)


if __name__ == "__main__":
    unittest.main()
