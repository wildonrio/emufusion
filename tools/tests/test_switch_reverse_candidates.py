"""Switch (Eden) sessions: the per-phase search also starts from C's flow (2026-11-04).

The candidates sit behind the uPropagateCa uniform, so other systems run the
same search as before; the host sets it for Eden sessions and the replay
bench for captures recorded on the Switch."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
GAME = ROOT / 'unified-android/src/com/thorium/preview/game'
sys.path.insert(0, str(ROOT / 'tools/learned_framegen'))
import dis_gles


class SwitchReverseCandidatesTest(unittest.TestCase):
    def test_candidates_are_gated_by_the_uniform(self):
        search = dis_gles.shaders()['PHASE_SEARCH']
        self.assertEqual(dis_gles.PHASE_PROPAGATE_CA, ())
        self.assertEqual(dis_gles.PHASE_PROPAGATE_CA_SWITCH, (8, 16))
        self.assertIn('uniform float uPropagateCa;', search)
        block = search[search.index('if(uPropagateCa>0.5){'):]
        block = block[:block.index(' }\n') + 3]
        self.assertEqual(block.count('vec2 c=-fca(x+vec2('), 8)
        self.assertIn('float ec=ssdc(o,c);', block)

    def test_host_and_replay_set_it_for_switch_only(self):
        host = (GAME / 'InWindowGameHost.java').read_text(encoding='utf-8')
        self.assertEqual(host.count('layer.setSwitchContent("eden".equals(request.engineId));'), 2)
        replay = (GAME / 'HoldoutReplay.java').read_text()
        self.assertIn('generator.setSwitchContent("switch".equals(system));', replay)
        generator = (GAME / 'DisplayFrameGenerator.java').read_text()
        self.assertIn('flow.setPropagateCa(switchContent && TimelineSchedulerSwitch.switchReverseCandidates());',
                      generator)
        flow = (GAME / 'DenseInverseSearchFlow.java').read_text()
        self.assertIn('GLES20.glUniform1f(location(phaseSearch, "uPropagateCa"), propagateCa ? 1f : 0f);', flow)

    def test_switch_defaults_on(self):
        switch = (GAME / 'TimelineSchedulerSwitch.java').read_text()
        self.assertIn('SWITCH_REVERSE_GLOBAL = "emufusion_framegen_switch_reverse_candidates"', switch)
        self.assertIn('private static volatile boolean switchReverseCandidates = true;', switch)


if __name__ == '__main__':
    unittest.main()
