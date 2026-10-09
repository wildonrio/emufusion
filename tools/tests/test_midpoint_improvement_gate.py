import copy
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from score_native_backend_comparison import midpoint_improvement_gate


class MidpointImprovementGateTest(unittest.TestCase):
    def test_controls_static_damage_and_no_motion(self):
        base = dict(changing_rgb_mae=10.0, changing_severe_pixels=5,
                    spatial={'regions': {'stable': {'pixels_error_over_1': 0}}})
        scores = {name: copy.deepcopy(base) for name in
                  ('generated', 'hold_left', 'hold_right', 'crossfade')}
        # Duplicate/control-level quality cannot pass by merely being distinct.
        self.assertFalse(midpoint_improvement_gate(scores, 100)['useful_midpoint_gate_passed'])
        scores['generated']['changing_rgb_mae'] = 2.0
        scores['generated']['changing_severe_pixels'] = 1
        gate = midpoint_improvement_gate(scores, 100)
        self.assertTrue(gate['useful_midpoint_gate_passed'])
        self.assertFalse(gate['artifact_free_qualified'])
        self.assertFalse(midpoint_improvement_gate(scores, 0)['useful_midpoint_gate_passed'])
        scores['generated']['spatial']['regions']['stable']['pixels_error_over_1'] = 1
        self.assertFalse(midpoint_improvement_gate(scores, 100)['useful_midpoint_gate_passed'])
        scores['generated']['spatial']['regions']['stable']['pixels_error_over_1'] = 0
        scores['generated']['changing_rgb_mae'] = float('nan')
        self.assertFalse(midpoint_improvement_gate(scores, 100)['useful_midpoint_gate_passed'])
