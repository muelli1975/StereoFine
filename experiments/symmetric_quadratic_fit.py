"""Research: fit the existing quadratic to both applied eye positions.

Uses the same two relinearizations already used by the cubic refinement. No
new field terms, horizontal target, displacement allowance or admission rule.
"""
from __future__ import annotations

import numpy as np

from stereofine.alignment import (_pipeline_design_quality, _weighted_lstsq,
    _zone_capped_weights, _vertical_residual_zone_stats, _holdout_mask_for_residual_basis)
from stereofine.alignment_refinement import corrected_point_residuals


def basis(points, shape, terms, normalization):
    h,w=shape[:2]
    x=(points[:,0]-(w-1)/2)/w
    y=(points[:,1]-(h-1)/2)/h
    values=dict(constant=np.ones(len(points)),x=x,y=y,xy=x*y,
                x2=x*x-normalization.get('x2_mean',0.),
                y2=y*y-normalization.get('y2_mean',0.))
    return np.column_stack([values[t] for t in terms])


def refine_quadratic_candidate(candidate, left, right, residual, shape, scale, holdout_mask=None):
    """Refit a supported legacy candidate; retain all prior support requirements."""
    if not candidate['ready']: return candidate
    candidate=dict(candidate)
    terms=candidate['terms'];norm=candidate['normalization']
    held=(_holdout_mask_for_residual_basis(left) if holdout_mask is None
          else np.asarray(holdout_mask,dtype=bool))
    train=~held
    # The legacy fitter falls back to training-only evaluation if necessary.
    # Such a candidate cannot pass the existing automatic holdout gate.
    if candidate['eval_mode']!='spatial_holdout':return candidate
    weights=_zone_capped_weights(left,shape)
    matrix=.5*(basis(left,shape,terms,norm)+basis(right,shape,terms,norm))
    quality=_pipeline_design_quality(matrix[train],weights[train])
    if not quality['supported']:
        candidate.update(ready=False,design_quality=quality)
        return candidate
    beta=_weighted_lstsq(matrix[train],residual[train],weights[train])
    limit=candidate['max_abs_model_analysis_px']
    for _ in range(2):
        dl,dr=left.copy(),right.copy()
        for _ in range(4):
            dl[:,1]=left[:,1]+.5*np.clip(basis(dl,shape,terms,norm)@beta,-limit,limit)
            dr[:,1]=right[:,1]-.5*np.clip(basis(dr,shape,terms,norm)@beta,-limit,limit)
        matrix=.5*(basis(dl,shape,terms,norm)+basis(dr,shape,terms,norm))
        quality=_pipeline_design_quality(matrix[train],weights[train])
        if not quality['supported']:
            candidate.update(ready=False,design_quality=quality)
            return candidate
        beta=_weighted_lstsq(matrix[train],residual[train],weights[train])
    candidate.update(coefficients=[dict(term=t,coefficient_analysis_px=float(v),
        coefficient_fullres_px_approx=float(v/scale)) for t,v in zip(terms,beta)],
        design_quality=quality,fit_evaluation='symmetric_destination',fit_relinearizations=2)
    payload=dict(enabled=True,terms=terms,normalization=norm,
        coefficients=[dict(term=t,coefficient_fullres_px=float(v/scale)) for t,v in zip(terms,beta)],
        max_abs_correction_px=limit/scale)
    corrected=corrected_point_residuals(dict(scale=1.,rotation_deg=0.,vertical_shift_px=0.,
        y_residual_apply=payload),left,right,shape,scale)
    def summary(values):
        values=np.asarray(values)/scale;a=np.abs(values)
        return dict(mean_signed=float(values.mean()),mean_abs=float(a.mean()),
                    median_abs=float(np.median(a)),p90_abs=float(np.percentile(a,90)),
                    p95_abs=float(np.percentile(a,95)),max_abs=float(a.max()))
    candidate.update(model_summary=summary(residual-corrected),vertical=summary(corrected),
        vertical_holdout=summary(corrected[held]),
        zone3x3=_vertical_residual_zone_stats(left,corrected,shape,scale),
        zone3x3_holdout=_vertical_residual_zone_stats(left[held],corrected[held],shape,scale))
    return candidate
