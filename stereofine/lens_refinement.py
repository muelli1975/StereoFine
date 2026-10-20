"""Validate one bounded cubic vertical field against the complete prior alignment.

This addresses smooth edge residuals without estimating depth or changing x.
It is an image-pair correction, not a calibrated camera/lens profile.
"""
from __future__ import annotations

from copy import deepcopy

import numpy as np

from .alignment import (
    _assess_spatial_holdout, _grid_zone_counts, _pipeline_design_quality,
    _transform_points_by_center_params, _weighted_lstsq, _zone_capped_weights,
    apply_pipeline_trapez_projective_to_points,
)
from .alignment_refinement import corrected_point_residuals, patch_correlations, point_quality

TERMS = ["constant", "x", "y", "xy", "x2", "y2", "x3", "x2y", "xy2", "y3"]


def cubic_design(points: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    h, w = shape[:2]
    x = (points[:, 0] - (w - 1) / 2) / w
    y = (points[:, 1] - (h - 1) / 2) / h
    return np.column_stack([
        np.ones(len(x)), x, y, x * y, x * x, y * y,
        x ** 3, x * x * y, x * y * y, y ** 3,
    ])


def _candidate(baseline: dict, left: np.ndarray, right: np.ndarray,
               left_gray: np.ndarray, right_gray: np.ndarray,
               scale: float) -> tuple[dict, dict]:
    correction = baseline["correction"]
    shape = left_gray.shape
    audit = {"accepted": False, "reason": "insufficient_support"}
    scores = patch_correlations(left_gray, right_gray, left, right)
    residual = corrected_point_residuals(correction, left, right, shape, scale)
    blocks = np.floor(left / 32).astype(np.int64)
    holdout = (blocks[:, 0] * 73856093 + blocks[:, 1] * 19349663) % 5 == 0
    good = (scores >= .90) & (np.abs(residual) <= 6)
    train = good & ~holdout & (np.abs(residual) <= 3)

    # Withhold whole blocks, then thin correlated check features by image cell.
    order = np.flatnonzero(good & holdout)
    order = order[np.argsort(-scores[order], kind="stable")]
    cells = np.floor(left[order] / 4).astype(np.int64)
    _, unique = np.unique(cells, axis=0, return_index=True)
    check = order[np.sort(unique)]
    counts = _grid_zone_counts(left[train], shape)
    audit.update(
        train_points=int(train.sum()), validation_points=len(check),
        validation_blocks=int(len(np.unique(blocks[check], axis=0))),
        photometric_threshold=.90, block_size=32,
    )
    if train.sum() < 120 or len(check) < 48 or sum(n >= 10 for n in counts) < 5:
        return baseline, audit

    half = float(correction["scale"]) ** .5
    rotation = float(correction["rotation_deg"])
    dy = float(correction["vertical_shift_px"]) * scale
    l = _transform_points_by_center_params(left, shape, -rotation / 2, 1 / half, 0, -dy / 2)
    r = _transform_points_by_center_params(right, shape, rotation / 2, half, 0, dy / 2)
    trapez = correction.get("trapez_apply") or {}
    if trapez.get("enabled"):
        l, r = apply_pipeline_trapez_projective_to_points(l, r, shape, trapez["params"])
    target = r[:, 1] - l[:, 1]
    matrix = (cubic_design(l, shape) + cubic_design(r, shape)) / 2
    weights = _zone_capped_weights(left[train], shape)
    quality = _pipeline_design_quality(matrix[train], weights)
    audit["design"] = quality
    if not quality["supported"]:
        audit["reason"] = "unstable_design"
        return baseline, audit
    beta = _weighted_lstsq(matrix[train], target[train], weights)
    # The raster evaluates the symmetric field at destination coordinates.
    # Two relinearizations account for that convention at both eye positions.
    for _ in range(2):
        dl, dr = l.copy(), r.copy()
        dl[:, 1] += .5 * (cubic_design(dl, shape) @ beta)
        dr[:, 1] -= .5 * (cubic_design(dr, shape) @ beta)
        matrix = (cubic_design(dl, shape) + cubic_design(dr, shape)) / 2
        beta = _weighted_lstsq(matrix[train], target[train], weights)

    h, w = shape
    gx, gy = np.meshgrid(np.linspace(0, w - 1, 33), np.linspace(0, h - 1, 33))
    grid = np.column_stack([gx.ravel(), gy.ravel()])
    field = cubic_design(grid, shape) @ beta
    limit = min(24, .018 * min(shape))
    if not np.isfinite(field).all() or np.abs(field).max() > limit:
        audit["reason"] = "field_limit"
        return baseline, audit
    # Additional edge-stretch check over the whole grid, including areas
    # without observations. The raster also clips displacement to the limit.
    f = field.reshape(33, 33)
    gradient = max(np.abs(np.diff(f, axis=0)).max() / ((h - 1) / 32),
                   np.abs(np.diff(f, axis=1)).max() / ((w - 1) / 32))
    if gradient > .10:
        audit["reason"] = "gradient_limit"
        return baseline, audit
    payload = {
        "enabled": True, "model_name": "y_cubic", "terms": TERMS.copy(),
        "normalization": {},
        "coefficients": [{"term": term, "coefficient_fullres_px": float(value / scale)}
                         for term, value in zip(TERMS, beta)],
        "max_abs_correction_px": limit / scale,
        "source": "blocked_photometric_cubic_v1",
    }
    candidate_correction = deepcopy(correction)
    candidate_correction["y_residual_apply"] = payload
    new = corrected_point_residuals(candidate_correction, left[check], right[check], shape, scale)
    before, before_zones = point_quality(left[check], residual[check], shape, scale)
    after, after_zones = point_quality(left[check], new, shape, scale)
    decision = _assess_spatial_holdout(
        before, after, before_zones, after_zones, scale,
        region_quality_floor_analysis=(.5, 1.5),
    )
    audit.update(decision, before=before, after=after, outer_corners=[])
    # Outer 20% corner checks complement the larger 3x3 regions. Sparse
    # corners never establish improvement, and supported corners cannot regress.
    for x0, y0 in [(0, 0), (.8, 0), (0, .8), (.8, .8)]:
        selected = ((left[check, 0] >= x0 * w) & (left[check, 0] < (x0 + .2) * w)
                    & (left[check, 1] >= y0 * h) & (left[check, 1] < (y0 + .2) * h))
        if selected.sum() < 6:
            continue
        b, v = np.abs(residual[check][selected]), np.abs(new[selected])
        okay = (v.mean() <= max(.5, b.mean() + .10)
                and np.percentile(v, 90) <= max(1.5, np.percentile(b, 90) + .10))
        audit["outer_corners"].append({
            "x_fraction": x0, "y_fraction": y0, "count": int(selected.sum()),
            "before_mean_analysis_px": float(b.mean()),
            "after_mean_analysis_px": float(v.mean()), "passed": bool(okay),
        })
        if not okay:
            audit.update(accepted=False, reason="outer_corner_worse")
            break
    if not audit["accepted"]:
        return baseline, audit

    result = deepcopy(baseline)
    result["correction"] = candidate_correction
    old_label = str(result.get("model") or "Affine")
    label = (old_label.replace("yQuad", "yCubic") if "yQuad" in old_label
             else old_label + " + yCubic")
    result["model"] = label
    for key in ["mean", "median", "p90", "p95", "max"]:
        result["residual_vertical_" + key] = after[key + "_abs"]
    for name in ("y_residual_model_basis", "vergence_model_basis"):
        if name in candidate_correction:
            candidate_correction[name]["actual_output_model"] = label
    if "pipeline_basis" in candidate_correction:
        candidate_correction["pipeline_basis"]["pipeline_model_label"] = label
    if "y_residual_model_basis" in candidate_correction:
        candidate_correction["y_residual_model_basis"]["model_policy"].update(
            applied_candidate="y_cubic", visible_model_status=label)
    return result, audit


def refine_residual_field(baseline: dict, left_points: np.ndarray, right_points: np.ndarray,
                          left_gray: np.ndarray, right_gray: np.ndarray,
                          analysis_scale: float) -> dict:
    """Keep the prior result unless independently checked improvement is useful."""
    try:
        result, audit = _candidate(baseline, left_points, right_points, left_gray, right_gray, analysis_scale)
    except np.linalg.LinAlgError:
        result, audit = baseline, {"accepted": False, "reason": "numerical_fit_failed"}
    result["correction"]["lens_refinement_validation"] = audit
    return result
