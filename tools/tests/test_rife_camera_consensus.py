import sys
from pathlib import Path
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from evaluate_rife_camera_consensus import correct, cubic_support, cubic_mask_overlap, camera_motion


class CameraConsensusTest(unittest.TestCase):
    def test_wider_filter_support_rejects_extra_border_and_overlay_taps(self):
        self.assertTrue(cubic_support(np.array(1.5),np.array(4.),20,20))
        self.assertFalse(cubic_support(np.array(1.5),np.array(4.),20,20,3))
        mask=np.zeros((10,12),bool);mask[4,7]=True
        self.assertFalse(cubic_mask_overlap(mask,np.array(4.5),np.array(4.)))
        self.assertTrue(cubic_mask_overlap(mask,np.array(4.5),np.array(4.),3))

    def test_opt_in_sharp_reconstruction_improves_independent_texture(self):
        from qa_rife_texture_translation import render
        left=render(0,(3,3),.38);right=render(1,(3,3),.38)
        truth=render(.5,(3,3),.38);baseline=(left+right)/2
        old,_=correct(left,right,baseline)
        sharp,_=correct(left,right,baseline,reconstruction='plateau')
        self.assertLess(abs(sharp-truth)[8:-8,8:-8].mean(),10)
        self.assertGreater(abs(old-truth)[8:-8,8:-8].mean(),18)

    def test_native_integer_steps_are_not_assumed_to_be_halfway(self):
        world=np.random.default_rng(114).integers(10,245,(40,90,3)).astype(float)
        left=world[:,12:72];middle=world[:,10:70];right=world[:,9:69]
        np.testing.assert_array_equal(camera_motion(left,right),[3,0])
        np.testing.assert_array_equal(camera_motion(left,middle),[2,0])
        np.testing.assert_array_equal(camera_motion(middle,right),[1,0])

    def test_cubic_layer_overlap_checks_used_taps_only(self):
        mask=np.zeros((5,8),bool);mask[2,3]=True
        self.assertFalse(cubic_mask_overlap(mask,np.array(2.),np.array(2.)))
        self.assertTrue(cubic_mask_overlap(mask,np.array(2.5),np.array(2.)))
        self.assertFalse(cubic_mask_overlap(mask,np.array(2.),np.array(1.)))

    def test_temporal_sides_reconstruct_world_around_fixed_overlay(self):
        world=np.random.default_rng(62).integers(10,180,(60,110,3)).astype(float)
        previous=world[:,14:94].copy();left=world[:,12:92].copy()
        right=world[:,10:90].copy();following=world[:,8:88].copy()
        expected=world[:,11:91]
        mask=np.zeros(left.shape[:2],bool);mask[10:18,20:35]=True
        for frame in (previous,left,right,following):frame[mask]=[250,240,30]
        generated=np.zeros_like(left)
        result,selected=correct(left,right,generated,following,True,mask,previous)
        for column in (19,35):
            self.assertTrue(selected[12:16,column].all())
            np.testing.assert_array_equal(result[12:16,column],expected[12:16,column])
        self.assertFalse(selected[mask].any())
        np.testing.assert_array_equal(result[mask],generated[mask])

    def test_integer_axis_does_not_require_unused_cubic_taps(self):
        self.assertTrue(cubic_support(np.array(0.),np.array(0.),20,20))
        self.assertFalse(cubic_support(np.array(.5),np.array(0.),20,20))
        self.assertTrue(cubic_support(np.array(1.5),np.array(0.),20,20))

    def test_lookahead_reconstructs_entering_midpoint_not_endpoint(self):
        world=np.random.default_rng(23).integers(10,245,(40,90,3)).astype(float)
        left=world[:,10:70];right=world[:,8:68];following=world[:,6:66]
        result,mask=correct(left,right,np.zeros_like(left),following,True)
        expected=world[:,9:69]
        self.assertTrue(mask[5:35,0].all())
        np.testing.assert_allclose(result[5:35,0],expected[5:35,0])
        self.assertTrue((abs(result[5:35,0]-right[5:35,0])>1).any())

    def test_acceleration_does_not_authorize_one_sided_reconstruction(self):
        world=np.random.default_rng(24).integers(10,245,(40,90,3)).astype(float)
        left=world[:,10:70];right=world[:,8:68];following=world[:,4:64]
        base,base_mask=correct(left,right,np.zeros_like(left))
        candidate,mask=correct(left,right,np.zeros_like(left),following,True)
        np.testing.assert_array_equal(candidate,base)
        np.testing.assert_array_equal(mask,base_mask)

    def test_local_future_disagreement_keeps_entering_model_pixels(self):
        world=np.random.default_rng(46).integers(10,180,(60,110,3)).astype(float)
        left=world[:,12:92];right=world[:,10:90];following=world[:,8:88].copy()
        following[10:20,:8]=[250,0,0]
        generated=np.full_like(left,77.)
        result,mask=correct(left,right,generated,following,True)
        self.assertFalse(mask[12:18,0].any())
        np.testing.assert_array_equal(result[12:18,0],generated[12:18,0])

    def test_local_past_disagreement_keeps_leaving_model_pixels(self):
        world=np.random.default_rng(47).integers(10,180,(60,110,3)).astype(float)
        previous=world[:,14:94].copy();left=world[:,12:92]
        right=world[:,10:90];following=world[:,8:88]
        previous[10:20,72:80]=[250,0,0]
        generated=np.full_like(left,77.)
        result,mask=correct(left,right,generated,following,True,previous=previous)
        self.assertFalse(mask[12:18,-1].any())
        np.testing.assert_array_equal(result[12:18,-1],generated[12:18,-1])

    def test_integer_midpoint_translation(self):
        left=np.random.default_rng(83).integers(10,245,(40,60,3)).astype(float)
        right=np.roll(left,2,axis=1)
        generated=np.zeros_like(left)
        result,mask=correct(left,right,generated)
        self.assertGreater(int(mask.sum()),500)
        np.testing.assert_allclose(result[mask],np.roll(left,1,axis=1)[mask])
        self.assertFalse(generated.any())

    def test_stationary_scene_has_no_camera_correction(self):
        source=np.random.default_rng(9).integers(0,255,(30,40,3)).astype(float)
        generated=source+1
        result,mask=correct(source,source,generated)
        self.assertFalse(mask.any())
        np.testing.assert_array_equal(result,generated)

    def test_camera_does_not_move_stationary_overlay_interior(self):
        left=np.random.default_rng(37).integers(10,245,(60,80,3)).astype(float)
        right=np.roll(left,2,axis=1)
        left[12:22,20:40]=[250,30,80]
        right[12:22,20:40]=[250,30,80]
        generated=np.full_like(left,77.)
        result,mask=correct(left,right,generated)
        self.assertGreater(int(mask.sum()),1000)
        self.assertFalse(mask[14:20,22:38].any())
        np.testing.assert_array_equal(result[14:20,22:38],generated[14:20,22:38])


if __name__=='__main__': unittest.main()
