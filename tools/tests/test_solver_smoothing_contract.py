"""Wiring check; behavioral proof is the Thor solver-smoothing shader test."""
from pathlib import Path
import unittest


class SmoothingContractTest(unittest.TestCase):
    def test_copy_bypass_preserves_requested_guidance(self):
        root=Path(__file__).resolve().parents[2]
        source=(root/'unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java').read_text()
        shader=source.split('private static final String DENSE_SOLVE_SHADER =',1)[1].split('private static final String DENSE_CYCLE_SHADER',1)[0]
        self.assertIn('uBypassSearch>.5&&uUseTemporalGuide<.5&&uUseReciprocalGuide<.5&&uUseGlobalSeed<.5&&uUseNeighborProposal<.5',shader)
        self.assertNotIn('uBypassSearch>.5&&uUseTemporalGuide<.5){',shader)

    def test_runtime_uses_device_tested_guard(self):
        root=Path(__file__).resolve().parents[2]
        source=(root/'unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java').read_text()
        shader=source.split('private static final String DENSE_SOLVE_SHADER =',1)[1].split('private static final String DENSE_CYCLE_SHADER',1)[0]
        guard='vec2 proposed=floor(mix(b,smooth,w)*256.0+.5)/256.0;if(objective(proposed)+.000001<objective(b))b=proposed;gl_FragColor=enc(b);'
        self.assertIn(guard,shader)
        self.assertNotIn('b=mix(b,smooth,w);',shader)
        self.assertIn(guard,(root/'tools/qa/DenseSolverSmoothingTest.java').read_text())


if __name__=='__main__':unittest.main()
