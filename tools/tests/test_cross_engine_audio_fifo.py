import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PHASE2 = (ROOT / "unified-android" / "src" / "com" / "thorium" /
          "preview" / "game" / "PpssppGlesEngineSession.java")
ADAPTER = (ROOT / "unified-android" / "src" / "com" / "thorium" /
           "preview" / "game" / "NativeAdapterEngineSession.java")


class CrossEngineAudioFifoTests(unittest.TestCase):
    def test_phase2_drains_each_core_frame_and_retains_partial_writes(self):
        source = PHASE2.read_text(encoding="utf-8")
        self.assertIn("new PcmAudioQueue(audioQueueCapacitySamples(sampleRate))",
                      source)
        self.assertIn("presentAudio(active.drainAudio(2048));", source)
        self.assertNotIn("pendingAudio", source)
        present = source.split("private void presentAudio", 1)[1].split(
            "private void applySteadyAudioBuffer", 1)[0]
        self.assertIn("queue.offer(samples)", present)
        self.assertIn("queue.headOffset()", present)
        self.assertIn("queue.consume(written)", present)
        self.assertIn("marker=audio-pcm-drop", present)
        self.assertIn("droppedAudioFrames += rejected / 2L", present)
        self.assertIn("if (!audioDropLogged)", present)
        health = source.split("private void recordFrameHealth", 1)[1].split(
            "private void releaseAudio", 1)[0]
        self.assertIn('" audioDropped=" + droppedAudioFrames', health)

    def test_phase2_restore_expands_track_before_repriming(self):
        source = PHASE2.read_text(encoding="utf-8")
        flush = source.split("private void flushAudioAfterRestore", 1)[1].split(
            "private AudioTrack createAudioTrack", 1)[0]
        pause = flush.index("audio.pause()")
        clear = flush.index("audio.flush()")
        startup = flush.index("startupAudioBufferBytes(")
        resize = flush.index("audio.setBufferSizeInFrames(startupFrames)")
        self.assertLess(pause, clear)
        self.assertLess(clear, startup)
        self.assertLess(startup, resize)
        self.assertIn("Build.VERSION.SDK_INT >= 24", flush)
        # This bug was specific to restoring/resetting after the five-second
        # steady-state shrink.  Reusing the small target would hide the loss
        # by reducing latency evidence rather than restoring a reachable
        # startup prime.
        self.assertNotIn("audioPrimeSamplesTarget =", flush)

    def test_ppsspp_steady_buffer_covers_thor_scheduler_tail(self):
        source = PHASE2.read_text(encoding="utf-8")
        steady = source.split(
            "private int steadyAudioBufferBytes", 1
        )[1].split("private int audioQueueCapacitySamples", 1)[0]
        self.assertIn('(\"ppsspp\".equals(entry.id) ? 10 : 20)', steady)

    def test_native_adapters_prime_and_retain_partial_writes(self):
        source = ADAPTER.read_text(encoding="utf-8")
        self.assertIn("new PcmAudioQueue(Math.max(8_192", source)
        self.assertIn("short[] samples = active.drainAudio(2048);", source)
        drain = source.split("private void drainAudioToTrack", 1)[1].split(
            "private static int adapterAudioBufferBytes", 1)[0]
        self.assertIn("queue.offer(samples)", drain)
        self.assertIn("queue.headOffset()", drain)
        self.assertIn("queue.consume(written)", drain)
        self.assertLess(drain.index("queue.consume(written)"),
                        drain.index("audio.play()"))
        self.assertIn("marker=audio-pcm-drop", drain)


if __name__ == "__main__":
    unittest.main()
