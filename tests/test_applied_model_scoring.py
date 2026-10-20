"""Independent analytic checks of the renderer-consistent model predictor."""
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from stereofine.alignment import _candidate_vertical_residuals as applied_candidate_residuals
from stereofine.alignment import warp_pair_symmetric


def candidate(coefficients, scale=1., limit=24., normalization=None):
    return dict(terms=list(coefficients), analysis_scale=scale,
        coefficients=[dict(term=k,coefficient_analysis_px=v,
                           coefficient_fullres_px_approx=v/scale) for k,v in coefficients.items()],
        normalization=normalization or {}, max_abs_model_analysis_px=limit,
        max_abs_model_fullres_px=limit/scale)


class AppliedModelScoringTests(unittest.TestCase):
    def setUp(self):
        self.shape=(600,800)
        self.left=np.array([[100.,100.],[250.,200.],[500.,300.],[700.,480.]])
        self.right=self.left+[80.,4.]

    def test_both_eye_positions_are_used_without_zeroing_horizontal_depth(self):
        c=candidate({'x':40.})
        expected=4.-40.*((self.left[:,0]+self.right[:,0])/2.-399.5)/800.
        actual=applied_candidate_residuals(c,self.left,self.right,self.shape)
        np.testing.assert_allclose(actual,expected,atol=1e-12)
        # A nonzero 80px scene disparity exposes the old single-eye shortcut.
        left_only=4.-40.*(self.left[:,0]-399.5)/800.
        np.testing.assert_allclose(left_only-actual,2.)
        np.testing.assert_array_equal(self.right[:,0]-self.left[:,0],np.full(4,80.))

    def test_destination_coordinate_solution_matches_closed_form(self):
        c=candidate({'constant':2.,'x':10.,'y':20.})
        lx,ly=self.left.T;rx,ry=self.right.T
        common=2.-20.*299.5/600.
        left_y=(ly+.5*(common+10.*(lx-399.5)/800.))/(1.-.5*20./600.)
        right_y=(ry-.5*(common+10.*(rx-399.5)/800.))/(1.+.5*20./600.)
        # The shared predictor uses four fixed-point steps. The resulting
        # error is below two micro-pixels for this known contraction.
        np.testing.assert_allclose(applied_candidate_residuals(c,self.left,self.right,self.shape),
                                   right_y-left_y,atol=2e-6,rtol=0)

    def test_clipping_is_applied_separately_at_each_eye(self):
        left=np.array([[0.,200.],[300.,200.],[799.,200.]])
        right=left+[80.,4.]
        c=candidate({'x':200.},limit=24.)
        lf=np.clip(200.*(left[:,0]-399.5)/800.,-24.,24.)
        rf=np.clip(200.*(right[:,0]-399.5)/800.,-24.,24.)
        np.testing.assert_allclose(applied_candidate_residuals(c,left,right,self.shape),4.-.5*(lf+rf),atol=1e-12)

    def test_scoring_uses_frozen_normalization_not_new_control_distribution(self):
        c=candidate({'x2':32.,'y2':-12.},normalization={'x2_mean':.04,'y2_mean':.07})
        p,q=self.left,self.right
        together=applied_candidate_residuals(c,p,q,self.shape)
        separate=np.concatenate([applied_candidate_residuals(c,p[i:i+1],q[i:i+1],self.shape) for i in range(len(p))])
        np.testing.assert_array_equal(together,separate)

    def test_analysis_scale_does_not_change_analysis_pixel_prediction(self):
        p,q=self.left,self.right
        for scale in (.25,.7,1.):
            actual=applied_candidate_residuals(candidate({'constant':2.,'x':10.},scale),p,q,self.shape)
            np.testing.assert_allclose(actual,applied_candidate_residuals(candidate({'constant':2.,'x':10.}),p,q,self.shape),atol=1e-12)

    def test_empty_and_identity_fields_preserve_input_residuals(self):
        c=candidate({'constant':0.})
        np.testing.assert_allclose(applied_candidate_residuals(c,self.left,self.right,self.shape),4.)
        result=applied_candidate_residuals(c,np.empty((0,2)),np.empty((0,2)),self.shape)
        self.assertEqual(result.shape,(0,))

    def test_prediction_inverts_the_actual_native_renderer_maps(self):
        c=candidate({'constant':2.,'x':10.,'y':12.,'xy':5.,'x2':32.,'y2':-12.},
                    normalization={'x2_mean':.04,'y2_mean':.07})
        payload=dict(enabled=True,model_name='y_quad',terms=c['terms'],
            coefficients=[dict(term=r['term'],coefficient_fullres_px=r['coefficient_fullres_px_approx'])
                          for r in c['coefficients']],normalization=c['normalization'],max_abs_correction_px=24.)
        correction=dict(scale=1.,rotation_deg=0.,vertical_shift_px=0.,y_residual_apply=payload)
        real_remap=cv2.remap
        maps=[]
        def capture(image,map_x,map_y,*args,**kwargs):
            maps.append((map_x.copy(),map_y.copy()))
            return real_remap(image,map_x,map_y,*args,**kwargs)
        image=np.zeros((*self.shape,3),dtype=np.uint16)
        with patch('cv2.remap',side_effect=capture):
            left,right=warp_pair_symmetric(image,image,correction)
        self.assertEqual(len(maps),2)
        self.assertEqual(left.dtype,np.uint16)
        self.assertEqual(left.shape,right.shape)
        x=np.array([80,200,400,650]);y=np.array([80,200,400,500])
        # Pick pairs on the same destination scanline, with true horizontal
        # depth differences, then retrieve their actual master coordinates.
        p=np.column_stack([m[y,x] for m in maps[0]]).astype(float)
        q=np.column_stack([m[y,x+80] for m in maps[1]]).astype(float)
        np.testing.assert_allclose(applied_candidate_residuals(c,p,q,self.shape),0.,atol=1e-3,rtol=0)


if __name__=='__main__':unittest.main()
