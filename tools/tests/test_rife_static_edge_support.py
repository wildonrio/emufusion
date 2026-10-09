import sys
from pathlib import Path
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from evaluate_rife_static_edge_support import correct, component_correct
from evaluate_rife_temporal_stationary import runtime_available_candidate


class StaticEdgeSupportTest(unittest.TestCase):
    def test_component_does_not_freeze_overlap_of_moving_rectangle(self):
        left=np.zeros((24,40,3));left[4:20,10:30]=200
        right=np.roll(left,2,axis=1);following=np.roll(left,4,axis=1)
        generated=np.full_like(left,75.)
        baseline,_=runtime_available_candidate(left,right,following,generated)
        candidate,_=component_correct(left,right,following,generated)
        np.testing.assert_array_equal(candidate,baseline)

    def test_component_restores_entire_stationary_hud_not_background(self):
        left=np.random.default_rng(17).integers(0,180,(40,60,3)).astype(float)
        right=np.roll(left,3,axis=1);following=np.roll(left,6,axis=1)
        for frame in (left,right,following):frame[10:20,10:40]=[250,240,30]
        generated=left+5
        candidate,mask=component_correct(left,right,following,generated)
        self.assertTrue(mask[10:20,10:40].all())
        np.testing.assert_array_equal(candidate[10:20,10:40],left[10:20,10:40])
        self.assertFalse(mask[:8].any())

    def test_component_rejects_growth_merging_into_neighbor(self):
        left=np.zeros((20,40,3));left[5:15,10:20]=200
        right=left.copy();right[5:15,20:21]=200
        following=right.copy();generated=left+20
        baseline,_=runtime_available_candidate(left,right,following,generated)
        candidate,_=component_correct(left,right,following,generated)
        np.testing.assert_array_equal(candidate[:,8:23],baseline[:,8:23])

    def test_recovers_solid_hud_edges_over_moving_background(self):
        left=np.random.default_rng(77).integers(10,180,(40,60,3)).astype(float)
        right=np.roll(left,3,axis=1);following=np.roll(left,6,axis=1)
        for frame in (left,right,following):
            frame[10:20,10:40]=[250,240,30]
        generated=left+5
        result,mask=correct(left,right,following,generated)
        self.assertTrue(mask[10:20,10:40].all())
        np.testing.assert_array_equal(result[10:20,10:40],left[10:20,10:40])
        self.assertFalse(mask[:8].any())
        np.testing.assert_array_equal(generated,left+5)

    def test_no_lookahead_preserves_model(self):
        left=np.zeros((10,10,3));generated=left+50
        result,mask=correct(left,left,None,generated)
        self.assertFalse(mask.any());np.testing.assert_array_equal(result,generated)

    def test_does_not_expand_through_disagreement_or_color_edge(self):
        left=np.zeros((20,20,3));right=left.copy();following=left.copy()
        right[:,10:]=100;following[:,10:]=120
        left[:,9]=[250,30,80];right[:,9]=left[:,9];following[:,9]=left[:,9]
        generated=left+20
        result,mask=correct(left,right,following,generated)
        self.assertFalse(mask[:,9:].any())
        np.testing.assert_array_equal(result[:,9:],generated[:,9:])

    def test_moving_edge_is_not_copied(self):
        frames=[]
        for shift in (0,3,6):
            frame=np.zeros((24,40,3));frame[4:20,10+shift:20+shift]=200;frames.append(frame)
        generated=np.full_like(frames[0],75.)
        result,mask=correct(*frames,generated)
        changing=abs(frames[0]-frames[1]).max(2)>1
        changing |= abs(frames[1]-frames[2]).max(2)>1
        self.assertFalse(mask[changing].any())
        np.testing.assert_array_equal(result[changing],generated[changing])
