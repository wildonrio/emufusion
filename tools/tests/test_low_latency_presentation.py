"""Low-latency presentation (owner, 2026-10-14: about half a second of input
lag in Ocarina of Time with frame generation on) and the corner readout."""
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.tests.test_framegen_startup_fallback import JAVA

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

    def test_latency_no_recent_pair_needed_is_trimmed(self):
        # 3.2.87 (owner, 2026-10-15: latency is the biggest problem): each
        # pair's first generated output reports how long its right image had
        # been ready; latency every recent pair could do without comes off.
        generator = GENERATOR.read_text()
        self.assertIn("recordAdmission(endpointSequence);", generator)
        self.assertIn("timeline.setRightReadyNs(timeline.arrivalPacing() ?\n"
                      "                callbackReadyClock.readyNs(admissionNs(activeRightSequence), callbackNs) :\n"
                      "                admissionNs(activeRightSequence));", generator)
        self.assertIn("callbackReadyClock.callback(frameTimeNanos, System.nanoTime());", generator)
        self.assertIn("timeline.setReadyTrimEnabled(TimelineSchedulerSwitch.lowLatency());", generator)
        self.assertIn("observeFirstGeneratedOutput(deadline.contentPresentationTimeNs());", generator)
        self.assertIn('" firstGeneratedLagMeanUs="', generator)
        scheduler = SCHEDULER.read_text()
        self.assertIn("public static final int READY_WINDOW = 16;", scheduler)
        self.assertIn("public static final int READY_TOLERATED_LATE = 1;", scheduler)
        # A late pair puts back what it lacked; the old fixed slack steps
        # stay for renderers without readiness (QA low_latency=0).
        self.assertIn("long add = readySlackToAddNs(leftTimestampNs, rightTimestampNs);", scheduler)
        self.assertIn("if (consecutiveLatePairs >= 2 && pairsSinceGenerated <= 4 && primed && !readyTrimEnabled) {",
                      scheduler)
        self.assertIn("return wait >= outputPeriodNs - outputPeriodNs / READY_TRIM_DIVISOR ? outputPeriodNs : 0L;",
                      scheduler)
        # Latency added for a late or long pair is recorded, so it is not
        # trimmed straight back off by older waits.
        self.assertIn("shiftReadySlack(added);", scheduler)
        self.assertIn("shiftReadySlack(add);", scheduler)
        test = (ROOT / "unified-android" / "test" / "com" / "thorium" / "emufusion" / "video" /
                "TimelineFrameSchedulerTest.java").read_text()
        for name in ("readinessTrimsLatencyNoPairNeeds();", "readinessFollowsIrregularSpans();",
                     "readinessUndoesHeldLatency();"):
            self.assertIn(name, test)

    def test_arrival_pacing_and_doubling_only(self):
        # 3.2.88 (owner, 2026-10-22): Lossless Scaling's order of work and
        # doubling only. Each new image's generated midpoint is shown as soon
        # as its pair is complete, the real image half the pair's span later.
        scheduler = SCHEDULER.read_text()
        self.assertIn("if (arrivalPacing)\n            return decideArrival(", scheduler)
        self.assertIn("arrivalRealDueNs = displayNs + span / 2L;", scheduler)
        self.assertIn("if (excessQueued >= 1 || (!arrivalGeneratedShown && (arrivalLateStart || !motionReady))) {",
                      scheduler)
        self.assertIn("arrivalLateStart = waited > span / 2L - panel / 2L;", scheduler)
        self.assertIn("int kind = propose(GENERATED, ARRIVAL_PHASE, leftTimestampNs + span / 2L, 0L, leftSequence,", scheduler)
        self.assertIn("public static final float ARRIVAL_PHASE = 0.5f;", scheduler)
        self.assertIn("public static final double ARRIVAL_SPAN_ALPHA = 0.2;", scheduler)
        self.assertIn("public static final double ARRIVAL_OUTLIER_RATIO = 3.0;", scheduler)
        generator = GENERATOR.read_text()
        self.assertIn("timeline.setArrivalPacing(TimelineSchedulerSwitch.arrivalPacing(), panelPeriodNs);", generator)
        self.assertIn("if (timeline.arrivalPacing()) return deadline;", generator)
        switch = SWITCH.read_text()
        self.assertIn('ARRIVAL_PACING_GLOBAL = "emufusion_framegen_arrival_pacing";', switch)
        self.assertIn("private static volatile boolean arrivalPacing = true;", switch)
        settings = (GAME / "FrameGenerationSettings.java").read_text()
        self.assertIn("public static final int MAX_MULTIPLIER = 2;", settings)
        test = (ROOT / "unified-android" / "test" / "com" / "thorium" / "emufusion" / "video" /
                "TimelineFrameSchedulerTest.java").read_text()
        for name in ("arrivalPacingShowsEachImageAsItArrives();", "arrivalPacingKeepsLatencyAtHalfTheSpan();",
                     "arrivalPacingAtSixtyFps();", "arrivalPacingCatchesUpAtSixtyFps();"):
            self.assertIn(name, test)

    def test_motion_is_solved_before_the_callback(self):
        # 3.2.89: the pair forms when its right image is admitted and its
        # motion is solved then, so the vsync callback that shows the
        # midpoint only runs the generate pass; a finished duplicate check is
        # polled ~1 ms after arrival instead of at the next vsync.
        generator = GENERATOR.read_text()
        self.assertIn("if (disPhaseOnly && disDefault && timelineActive && timeline.arrivalPacing())\n"
                      "                prepareDisFlow(TimelineFrameScheduler.ARRIVAL_PHASE, true);", generator)
        self.assertIn("DenseInverseSearchFlow flow = prepareDisFlow(phase, perPhase);", generator)
        self.assertEqual(generator.count("prepareArrivalPairEarly();\n"), 3)
        self.assertEqual(generator.count("scheduleSignatureEarlyPoll(false);"), 2)
        self.assertIn("handler.postDelayed(signatureEarlyPoll, 1L);", generator)
        self.assertIn("observedBufferedPresentationEpoch != schedulerPresentationEpoch()) return;", generator)
        for field in ("signatureEarlyCommits=", "arrivalEarlyPairs=", "disPrecomputeHits=",
                      "disPrecomputeMisses="):
            self.assertIn('" ' + field + '"', generator)

    def test_queue_reserve_recovers_from_short_disturbances(self):
        # 3.2.89: whole extra scans counted from the callback, deepened on a
        # burst of late frames and given back once frames show they would
        # have met the earlier latch (Thor: the recorder's start had kept
        # Ocarina a scan deeper, 20.3 -> 26-29 ms, for the rest of the run).
        generator = GENERATOR.read_text()
        self.assertIn("builtinQueueReserveNs = builtinQueueReserve.reserveNs(callbackNs, planNowNs,\n"
                      "                    builtinCompositorTiming[1]);", generator)
        self.assertIn("latchKnown ? result.latchNs : 0L, result.panelPeriodNs);", generator)
        self.assertNotIn("BUILTIN_QUEUE_RESERVE_DECAY_FRAMES", generator)
        video = ROOT / "unified-android" / "src" / "com" / "thorium" / "emufusion" / "video"
        test = (ROOT / "unified-android" / "test" / "com" / "thorium" / "emufusion" / "video" /
                "BuiltinQueueReserveTest.java")
        with tempfile.TemporaryDirectory() as out:
            subprocess.run([str(JAVA / "javac"), "-d", out, "-sourcepath",
                            str(ROOT / "unified-android" / "src"), str(video / "BuiltinQueueReserve.java"),
                            str(test)], check=True)
            run = subprocess.run([str(JAVA / "java"), "-cp", out,
                                  "com.thorium.emufusion.video.BuiltinQueueReserveTest"],
                                 capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("BuiltinQueueReserveTest passed", run.stdout)

    def test_stale_real_image_is_passed_for_a_newer_one(self):
        # 3.2.91: a newer image while the active pair's real image still
        # waits (its generated image is up) passes that real image, so the
        # new pair's midpoint is shown at the next callback.
        generator = GENERATOR.read_text()
        early = generator[generator.index("    private void prepareArrivalPairEarly() {"):
                          generator.index("    private void pollSignatureOnVsync() {")]
        self.assertIn("boolean passing = activeRightSequence != 0L;", early)
        self.assertIn("if (passing && (!activePairSyntheticCommitted ||", early)
        self.assertIn("commitBufferedEndpointAdvance(AdaptiveFrameRateController.PRESENT_SYNTHETIC, 1);", early)
        self.assertIn("++verifyWindowPassed;", early)
        self.assertIn('" arrivalPassedReals="', generator)
        # The arrival trace is QA-only (marker file read once per generator).
        self.assertIn('new java.io.File("/data/local/tmp/emufusion-arrival-trace");', generator)
        self.assertIn("private final boolean arrivalTraceEnabled = ARRIVAL_TRACE_MARKER.exists();", generator)

    def test_late_starts_are_counted_in_callbacks(self):
        # 3.2.90: GameCube skipped the generated image for 500 of 820 pairs
        # once images were admitted ~1 ms after arrival (the wait for the next
        # callback passed the 60 -> 120 late-start threshold).
        video = ROOT / "unified-android" / "src" / "com" / "thorium" / "emufusion" / "video"
        test = (ROOT / "unified-android" / "test" / "com" / "thorium" / "emufusion" / "video" /
                "CallbackReadyClockTest.java")
        with tempfile.TemporaryDirectory() as out:
            subprocess.run([str(JAVA / "javac"), "-d", out, "-sourcepath", str(ROOT / "unified-android" / "src"),
                            str(test)], check=True)
            run = subprocess.run([str(JAVA / "java"), "-cp", out,
                                  "com.thorium.emufusion.video.CallbackReadyClockTest"],
                                 capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("CallbackReadyClockTest passed", run.stdout)
        self.assertTrue((video / "CallbackReadyClock.java").exists())

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
