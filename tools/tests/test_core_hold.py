"""QA: a paced hardware core holds after presenting, so the generated image its new frame completes reaches
the GPU first (2026-11-08, Ocarina wide: generated images finishing after the compositor's latch).

Checks the QA switch is off by default and bounded, that only a paced core's presented frames hold, and that
the hold comes from the frame generator attached to the core's Surface."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / 'unified-android/src/com/thorium/preview'


class CoreHoldTest(unittest.TestCase):
    def test_switch_is_off_by_default_and_bounded(self):
        switch = (SRC / 'game/TimelineSchedulerSwitch.java').read_text()
        self.assertIn('CORE_HOLD_GLOBAL = "emufusion_framegen_core_hold_us"', switch)
        self.assertIn('context.getContentResolver(), CORE_HOLD_GLOBAL, 0);', switch)
        self.assertIn('coreHoldUs = Math.max(0, Math.min(MAX_CORE_HOLD_US, hold));', switch)
        self.assertIn('static final int MAX_CORE_HOLD_US = 12_000;', switch)

    def test_only_a_paced_core_holds_after_presenting(self):
        loop = (SRC / 'ExperimentalGlesRenderLoop.java').read_text()
        body = loop[loop.index('hasPresentedSinceClockReset = true;'):]
        body = body[:body.index('} else if (host.didRunFrame())')]
        self.assertIn('long holdNs = pacedCoreHz > 0.0 ?', body)
        self.assertIn('FrameGenerationRendererRegistry.coreHoldAfterPresentNs(attachedSurface) : 0L;', body)
        self.assertIn('if (holdNs > 0L) java.util.concurrent.locks.LockSupport.parkNanos(holdNs);', body)

    def test_the_attached_generator_answers(self):
        renderer = (SRC / 'game/FrameGenerationRenderer.java').read_text()
        self.assertIn('default long coreHoldAfterPresentNs() { return 0L; }', renderer)
        generator = (SRC / 'game/DisplayFrameGenerator.java').read_text()
        self.assertIn('return closed.get() ? 0L : TimelineSchedulerSwitch.coreHoldNs();', generator)
        registry = (SRC / 'game/FrameGenerationRendererRegistry.java').read_text()
        self.assertIn('return renderer == null ? 0L : renderer.coreHoldAfterPresentNs();', registry)


if __name__ == '__main__':
    unittest.main()
