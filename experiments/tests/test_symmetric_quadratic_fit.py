"""Known stereo fields with varying horizontal depth and withheld checks."""
import unittest

import numpy as np

from stereofine.alignment import _fit_y_residual_candidate, _holdout_mask_for_residual_basis
from experiments.applied_model_scoring import applied_candidate_residuals
from experiments.symmetric_quadratic_fit import basis, refine_quadratic_candidate


class SymmetricQuadraticFitTests(unittest.TestCase):
    def scene(self):
        shape=(600,800)
        x,y=np.meshgrid(np.arange(30,700,12),np.arange(30,570,12))
        dl=np.column_stack([x.ravel(),y.ravel()]).astype(float)
        dr=dl.copy();dr[:,0]+=40+25*np.sin(dl[:,0]/71)
        terms=['constant','x','y','xy','x2','y2'];beta=np.array([0.,15.,3.,5.,20.,-8.])
        p,q=dl.copy(),dr.copy()
        p[:,1]-=.5*(basis(dl,shape,terms,{})@beta)
        q[:,1]+=.5*(basis(dr,shape,terms,{})@beta)
        return shape,terms,p,q

    def fit(self,shape,terms,p,q,held=None):
        r=q[:,1]-p[:,1]
        legacy=_fit_y_residual_candidate('y_quad',terms,p,q,r,shape,1.,holdout_mask=held)
        result=refine_quadratic_candidate(legacy,p,q,r,shape,1.,held)
        return legacy,result

    def test_known_symmetric_field_recovers_held_out_geometry(self):
        shape,terms,p,q=self.scene();held=_holdout_mask_for_residual_basis(p)
        legacy,result=self.fit(shape,terms,p,q,held)
        self.assertTrue(result['ready'])
        before=np.abs(applied_candidate_residuals(legacy,p[held],q[held],shape))
        after=np.abs(applied_candidate_residuals(result,p[held],q[held],shape))
        self.assertGreater(np.percentile(before,95),.5)
        self.assertLess(after.max(),1e-5)

    def test_held_out_vertical_errors_cannot_train_the_fit(self):
        shape,terms,p,q=self.scene();held=_holdout_mask_for_residual_basis(p)
        _,reference=self.fit(shape,terms,p,q,held)
        altered=q.copy();altered[held,1]+=10.
        _,result=self.fit(shape,terms,p,altered,held)
        np.testing.assert_array_equal([r['coefficient_analysis_px'] for r in result['coefficients']],
                                      [r['coefficient_analysis_px'] for r in reference['coefficients']])
        self.assertGreater(result['vertical_holdout']['mean_abs'],9.)

    def test_unsupported_candidate_is_preserved(self):
        value={'ready':False}
        result=refine_quadratic_candidate(value,None,None,None,None,None)
        self.assertIs(result,value)

    def test_input_points_and_legacy_payload_are_unchanged(self):
        shape,terms,p,q=self.scene();before_p,before_q=p.copy(),q.copy()
        legacy=_fit_y_residual_candidate('y_quad',terms,p,q,q[:,1]-p[:,1],shape,1.)
        import copy
        original=copy.deepcopy(legacy)
        refine_quadratic_candidate(legacy,p,q,q[:,1]-p[:,1],shape,1.)
        self.assertEqual(legacy,original)
        np.testing.assert_array_equal(p,before_p);np.testing.assert_array_equal(q,before_q)


if __name__=='__main__':unittest.main()
