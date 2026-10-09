from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
SESSION = ROOT / "unified-android/src/com/thorium/preview/game/LibretroEngineSession.java"
HOST = ROOT / "unified-android/src/com/thorium/preview/game/InWindowGameHost.java"
SIGNAL = ROOT / "unified-android/src/com/thorium/lucent/audio/PcmSignalTelemetry.java"


class NesRuntimeUxHardeningTest(unittest.TestCase):
    def test_libretro_audio_drains_each_frame_and_reports_loss(self):
        source = SESSION.read_text(encoding="utf-8")
        self.assertIn("drainAndPresentAudio(active);", source)
        self.assertIn("short[] samples = active.drainAudio(maxFrames);", source)
        self.assertNotIn("pendingAudio == null ? active.drainAudio", source)
        for field in (
            "audioProducedFrames=%d",
            "audioWrittenFrames=%d",
            "audioDroppedFrames=%d",
            "audioFocusDroppedFrames=%d",
            "audioQueuedFrames=%d",
            "audioPartialWrites=%d",
            "audioZeroWrites=%d",
            "audioWriteErrors=%d",
            "audioNativeDrainBoundHits=%d",
            "audioUnderruns=%d",
            "marker=audio-pcm-drop",
            "marker=audio-write-failure",
            "marker=audio-native-drain-bound",
        ):
            self.assertIn(field, source)

    def test_background_save_failure_is_visible_after_instant_return(self):
        session = SESSION.read_text(encoding="utf-8")
        save = session[session.index("private void saveQuickResume") :
                       session.index("private void restore(",
                                     session.index("private void saveQuickResume"))]
        self.assertGreaterEqual(save.count("reportQuickResumeSaveFailure("), 3)
        self.assertIn("marker=save-failure", save)
        source = HOST.read_text(encoding="utf-8")
        callback = source[source.index("onSessionStopRejected") :]
        returned = callback.index("if (libraryReturned)")
        toast = callback.index("Toast.makeText", returned)
        retire = callback.index("finishRetiringSession", returned)
        self.assertLess(returned, toast)
        self.assertLess(toast, retire)
        self.assertIn("marker=exit-save-failure-visible", callback[returned:retire])
        self.assertIn("previous Quick Resume", callback[returned:retire])

    def test_void_cheat_abi_is_never_logged_as_effect_acknowledgement(self):
        source = SESSION.read_text(encoding="utf-8")
        self.assertIn("marker=cheat-apply-attempt", source)
        self.assertIn("marker=cheat-apply-returned", source)
        self.assertIn("marker=cheat-apply-failure", source)
        self.assertIn("acknowledged=false", source)
        self.assertIn("effectProofRequired=true", source)
        self.assertIn("stage=pre-submit selectionRetained=false", source)
        self.assertIn("stage=session-unavailable", source)
        self.assertIn("source=stored selectionRetained=true", source)
        self.assertIn("selectionRetained=false", source)

    def test_audio_fifo_head_write_and_consume_are_atomic_against_focus_clear(self):
        source = SESSION.read_text(encoding="utf-8")
        drain = source[source.index("for (int attempt = 0; attempt < 8; attempt++) {") :]
        monitor = drain.index("synchronized (queue)")
        head = drain.index("short[] head = queue.head()")
        write = drain.index("audio.write(head", head)
        consume = drain.index("queue.consume(written)", write)
        close = drain.index("\n            }\n        }", consume)
        self.assertLess(monitor, head)
        self.assertLess(head, write)
        self.assertLess(write, consume)
        self.assertGreater(close, consume)

    def test_pcm_signal_contract_is_pre_sink_and_never_claims_audibility(self):
        source = SESSION.read_text(encoding="utf-8")
        present = source[source.index("private void presentAudio") :
                         source.index("private void drainAndPresentAudio")]
        self.assertLess(present.index("signal.accept(samples)"),
                        present.index("if (audio == null || queue == null)"))
        for field in (
            "audioSignalBoundary=pre-AudioTrack",
            "audioSignalAudibilityProven=false",
            "audioSignalSampleRateHz=%d",
            "audioSignalWindowFrames=%d",
            "audioSignalWindowSamples=%d",
            "audioSignalWindowFrequencyResolutionHz=%.6f",
            "audioSignalWindowOverflow=%s",
            "audioSignalWindowLeftMin=%d",
            "audioSignalWindowLeftMax=%d",
            "audioSignalWindowLeftPeak=%d",
            "audioSignalWindowLeftRms=%.3f",
            "audioSignalWindowLeftToneHz=%.3f",
            "audioSignalWindowLeftCrossings=%d",
            "audioSignalWindowRightMin=%d",
            "audioSignalWindowRightMax=%d",
            "audioSignalWindowRightPeak=%d",
            "audioSignalWindowRightRms=%.3f",
            "audioSignalWindowRightToneHz=%.3f",
            "audioSignalWindowRightCrossings=%d",
            "audioSignalTotalFrames=%d",
            "audioSignalTotalSamples=%d",
            "audioSignalTotalFrequencyResolutionHz=%.6f",
            "audioSignalTotalOverflow=%s",
            "marker=audio-pcm-signal",
        ):
            self.assertIn(field, source)

        analyzer = SIGNAL.read_text(encoding="utf-8")
        accept = analyzer[analyzer.index("public synchronized void accept") :
                          analyzer.index("public synchronized Snapshot snapshotWindowAndReset")]
        sample_loop = accept[accept.index("for (int sample = 0") :]
        self.assertNotIn("new ", sample_loop,
                         "the hot per-sample path must not allocate")
        self.assertIn("DC_BLOCK_POLE", analyzer)
        self.assertIn("CROSSING_THRESHOLD", analyzer)


if __name__ == "__main__":
    unittest.main()
