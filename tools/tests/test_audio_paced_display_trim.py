"""Audio-paced hardware cores (Flycast) follow the measured panel with FG Off."""
from pathlib import Path
import unittest
from tools.tests.test_framegen_startup_fallback import method

ROOT = Path(__file__).resolve().parents[2]
LOOP = ROOT / "unified-android/src/com/thorium/preview/ExperimentalGlesRenderLoop.java"


class AudioPacedDisplayTrimTest(unittest.TestCase):
    def test_audio_paced_core_is_trimmed_not_ticked(self):
        source = LOOP.read_text()
        await_clock = method(source, "    private double awaitDisplayClockHz()")
        # Display ticks still never run a render-driven core...
        self.assertIn("if (audioPaced) {", await_clock)
        self.assertIn("trimAudioPacedToDisplay(clock);\n            return 0.0;", await_clock)
        trim = method(source, "    private void trimAudioPacedToDisplay(DisplayClock clock)")
        # ...but its rate follows the measured panel through the same trim
        # the frame generator's lock uses, measured against the synchronized
        # clock and only re-trimmed for 100 ppm.
        self.assertIn("clock.configure(declaredCoreHz, synchronizedCoreHz, direct);", trim)
        self.assertIn("setPacedVideoHz(measuredHz);", trim)
        self.assertIn("Math.abs(measuredHz / pacedCoreHz - 1.0) < 1.0e-4", trim)
        self.assertIn("!FrameGenerationRendererRegistry.isFrameGenerationInput(attachedSurface)", trim)


if __name__ == "__main__":
    unittest.main()
