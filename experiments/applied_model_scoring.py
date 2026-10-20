"""Compare the historical quadratic score with the actually applied geometry.

Research only. Model degrees, coefficients, displacement caps and admission
thresholds are unchanged. Both eyes and the renderer's inverse-map convention
must be represented when predicting the vertical residual of a candidate.
"""
from __future__ import annotations

import numpy as np

from stereofine.alignment import _y_residual_design_matrix
from stereofine.alignment_refinement import corrected_point_residuals


def legacy_candidate_residuals(candidate, left, right, image_shape):
    """Frozen RC3 left-coordinate approximation, for baseline reproduction."""
    matrix, labels = _y_residual_design_matrix(left, right, image_shape, candidate['terms'])
    coefficients = {row['term']:row['coefficient_analysis_px'] for row in candidate['coefficients']}
    model = matrix @ np.array([coefficients[label] for label in labels], dtype=np.float64)
    limit = candidate['max_abs_model_analysis_px']
    return right[:, 1]-left[:, 1]-np.clip(model, -limit, limit)


def applied_candidate_residuals(candidate, left, right, image_shape):
    """Predict the same symmetric, clipped destination field used for output."""
    scale = float(candidate['analysis_scale'])
    payload = dict(enabled=True, terms=list(candidate['terms']),
        coefficients=[dict(term=r['term'], coefficient_fullres_px=r['coefficient_fullres_px_approx'])
                      for r in candidate['coefficients']],
        normalization=dict(candidate['normalization']),
        max_abs_correction_px=float(candidate['max_abs_model_fullres_px']))
    correction = dict(scale=1., rotation_deg=0., vertical_shift_px=0., y_residual_apply=payload)
    return corrected_point_residuals(correction, left, right, image_shape, scale)
