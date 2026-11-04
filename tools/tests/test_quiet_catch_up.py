"""QA opt-in: compositor catch-up skips timed by quiet pairs (2026-11-04, off by default).

The DIS flow measures, once per pair, whether at most 0.5% of a 160x90 grid
changed between the two real frames, as an ANY_SAMPLES_PASSED query polled
without waiting (a pixel-pack readback stalled the Thor's frame thread). The callback feeds the newest share to
CompositorBacklogCatchUp before it asks for a skip."""
from pathlib import Path
import sys
import unittest
from tools.tests.test_framegen_startup_fallback import method

ROOT = Path(__file__).resolve().parents[2]
GAME = ROOT / 'unified-android/src/com/thorium/preview/game'
sys.path.insert(0, str(ROOT / 'tools/learned_framegen'))
import dis_gles


class QuietCatchUpTest(unittest.TestCase):
    def test_switch_defaults_off(self):
        switch = (GAME / 'TimelineSchedulerSwitch.java').read_text()
        self.assertIn('QUIET_SKIP_GLOBAL = "emufusion_framegen_quiet_skip"', switch)
        self.assertIn('private static volatile boolean quietSkip = false;', switch)
        self.assertIn('context.getContentResolver(), QUIET_SKIP_GLOBAL, 0) != 0;', switch)
        flow = (GAME / 'DenseInverseSearchFlow.java').read_text()
        self.assertIn('if (quietMeasure && quietSumProgram != 0 && quietQuery[0] != 0 &&', flow)
        generator = (GAME / 'DisplayFrameGenerator.java').read_text()
        self.assertIn('disPhaseFlow.setQuietMeasure(TimelineSchedulerSwitch.quietSkip());', generator)

    def test_shaders_count_changed_samples_without_motion(self):
        rows = dis_gles.shaders()['QUIET_ROWS']
        self.assertEqual(dis_gles.QUIET_GRID, (160, 90))
        self.assertIn('for(int x=0;x<160;++x)', rows)
        self.assertIn('n+=step(8.0/255.0,md(abs(texture(uFrameA,u).rgb-texture(uFrameC,u).rgb)));', rows)
        total = dis_gles.shaders()['QUIET_SUM']
        self.assertIn('for(int y=0;y<90;++y)', total)
        self.assertIn('if(n>72.0)discard;o0=vec4(1.0);', total)

    def test_measured_once_per_pair_and_read_back_without_waiting(self):
        flow = (GAME / 'DenseInverseSearchFlow.java').read_text()
        self.assertIn('static final int QUIET_ROWS = 90;', flow)
        self.assertIn('(phaseKeyA != quietKeyA || phaseKeyB != quietKeyB)', flow)
        measure = method(flow, '    private void measureQuiet(')
        self.assertIn('GLES30.glBeginQuery(GLES30.GL_ANY_SAMPLES_PASSED, quietQuery[slot]);', measure)
        self.assertIn('GLES30.glEndQuery(GLES30.GL_ANY_SAMPLES_PASSED);', measure)
        self.assertIn('++quietDropped;', measure)
        self.assertNotIn('glReadPixels', flow)
        self.assertNotIn('glMapBufferRange', flow)
        poll = method(flow, '    double pollQuietShare(')
        self.assertLess(poll.index('GL_QUERY_RESULT_AVAILABLE'), poll.index('GL_QUERY_RESULT, '))
        self.assertIn('if (quietResult[0] == 0) continue;', poll)
        self.assertIn('share = quietResult[0] != 0 ? 0.0 : 1.0;', poll)

    def test_callback_feeds_the_share_before_the_skip(self):
        generator = (GAME / 'DisplayFrameGenerator.java').read_text()
        poll = generator.index('double changed = disPhaseFlow.pollQuietShare();')
        skip = generator.index('builtinBacklogCatchUp.takeSkip(deadlineNowNs)')
        self.assertLess(poll, skip)
        self.assertIn('builtinBacklogCatchUp.setQuietEnabled(TimelineSchedulerSwitch.quietSkip());', generator)
        self.assertIn('if (changed >= 0.0) builtinBacklogCatchUp.observeChange(changed, deadlineNowNs);', generator)
        self.assertIn('" quietSkips=" + builtinBacklogCatchUp.quietSkips() +', generator)


if __name__ == '__main__':
    unittest.main()
