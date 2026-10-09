import sys
from pathlib import Path
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from diagnose_rife_edge_profiles import edge_profiles


class EdgeProfileTest(unittest.TestCase):
    def scene(self):
        y,x=np.mgrid[:16,:40]
        def edge(center):
            coverage=np.clip(x+.5-center,0,1)
            return 20+coverage[...,None]*np.array([200.,100.,60.])
        return edge(12.5),edge(15.5),edge(14.)

    def test_true_halfway_edge_has_correct_position_and_spread(self):
        left,right,midpoint=self.scene()
        report=edge_profiles(left,right,{'midpoint':midpoint},3)
        self.assertGreater(report['selected_edge_rows'],0)
        row=report['candidates']['midpoint']
        self.assertAlmostEqual(row['phase']['median'],.5)
        self.assertAlmostEqual(row['position_error']['maximum'],0)
        self.assertAlmostEqual(row['excess_spread']['maximum'],0)

    def test_copy_and_crossfade_cannot_masquerade_as_good_midpoint(self):
        left,right,_=self.scene()
        q=edge_profiles(left,right,{'copy':left,'blend':(left+right)/2},3)['candidates']
        self.assertAlmostEqual(q['copy']['position_error']['median'],1.5)
        self.assertAlmostEqual(q['blend']['position_error']['median'],0)
        self.assertGreater(q['blend']['excess_spread']['median'],1.9)

    def test_blank_edge_and_wrong_colors_are_visible_in_metrics(self):
        left,right,midpoint=self.scene()
        wrong=midpoint+np.array([0.,25.,-25.])
        q=edge_profiles(left,right,{'blank':np.full_like(left,20.),'wrong':wrong},3)['candidates']
        self.assertEqual(q['blank']['missing'],q['blank']['edge_rows'])
        self.assertGreater(q['wrong']['off_color_line']['median'],10.)

    def test_selection_is_independent_of_candidate_and_rejects_unmatched_endpoints(self):
        left,right,midpoint=self.scene()
        a=edge_profiles(left,right,{'good':midpoint},3)
        b=edge_profiles(left,right,{'bad':np.zeros_like(left)},3)
        self.assertEqual(a['selected_edge_rows'],b['selected_edge_rows'])
        self.assertEqual(edge_profiles(left,left,{'good':midpoint},3)['selected_edge_rows'],0)

    def test_faded_edge_cannot_pass_on_position_and_spread_alone(self):
        left,right,midpoint=self.scene()
        faded=20+(midpoint-20)*.5
        q=edge_profiles(left,right,{'faded':faded},3)['candidates']['faded']
        self.assertAlmostEqual(q['position_error']['maximum'],0)
        self.assertAlmostEqual(q['excess_spread']['maximum'],0)
        self.assertAlmostEqual(q['contrast_error']['median'],.5)
