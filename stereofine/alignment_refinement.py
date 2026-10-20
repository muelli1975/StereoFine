"""Recover genuine nonlinear correspondences without fitting the check points."""
from __future__ import annotations

import numpy as np


def patch_correlations(left_gray: np.ndarray, right_gray: np.ndarray,
                       left_points: np.ndarray, right_points: np.ndarray) -> np.ndarray:
    """Mean/contrast invariant checks at measured locations; no depth fitting."""
    import cv2
    scores = np.full(len(left_points), -1.0, dtype=np.float32)
    radius = 8
    offsets = np.stack(np.meshgrid(np.arange(-radius, radius + 1), np.arange(-radius, radius + 1)), axis=-1).reshape(-1, 2)
    valid = np.ones(len(left_points), dtype=bool)
    for points, gray in ((left_points, left_gray), (right_points, right_gray)):
        h, w = gray.shape
        valid &= (points[:, 0] >= radius + 1) & (points[:, 0] < w - radius - 1)
        valid &= (points[:, 1] >= radius + 1) & (points[:, 1] < h - radius - 1)
    indices = np.flatnonzero(valid)
    for start in range(0, len(indices), 512):
        batch = indices[start:start + 512]
        patches = []
        for gray, points in ((left_gray, left_points), (right_gray, right_points)):
            coords = (points[batch, None, :] + offsets[None, :, :]).astype(np.float32)
            values = cv2.remap(gray, coords[..., 0], coords[..., 1], cv2.INTER_LINEAR).astype(np.float32)
            values -= values.mean(axis=1, keepdims=True)
            patches.append(values)
        a, b = patches
        aa, bb = np.sum(a * a, axis=1), np.sum(b * b, axis=1)
        contrast = (aa >= 36 * a.shape[1]) & (bb >= 36 * b.shape[1])
        score = np.sum(a * b, axis=1) / np.maximum(np.sqrt(aa * bb), 1e-12)
        scores[batch[contrast]] = score[contrast]
    return scores


def corrected_point_residuals(correction: dict, left: np.ndarray, right: np.ndarray,
                              image_shape: tuple[int, int], analysis_scale: float) -> np.ndarray:
    from .alignment import _transform_points_by_center_params, apply_pipeline_trapez_projective_to_points
    relative_scale = float(correction["scale"]) ** .5
    rotation = float(correction["rotation_deg"])
    dy = float(correction["vertical_shift_px"]) * analysis_scale
    l = _transform_points_by_center_params(left, image_shape, -rotation / 2, 1 / relative_scale, 0, -dy / 2)
    r = _transform_points_by_center_params(right, image_shape, rotation / 2, relative_scale, 0, dy / 2)
    trapez = correction.get("trapez_apply") or {}
    if trapez.get("enabled"):
        l, r = apply_pipeline_trapez_projective_to_points(l, r, image_shape, trapez["params"])
    payload = correction.get("y_residual_apply") or {}
    if not payload.get("enabled"):
        return r[:, 1] - l[:, 1]
    h, w = image_shape[:2]
    norm = payload.get("normalization") or {}
    coefficients = {row["term"]: float(row["coefficient_fullres_px"]) * analysis_scale
                    for row in payload.get("coefficients", [])}

    def field(points, y_position):
        x = (points[:, 0] - (w - 1) / 2) / w
        y = (y_position - (h - 1) / 2) / h
        terms = {"constant": np.ones(len(x)), "x": x, "y": y, "xy": x * y,
                 "x2": x * x - norm.get("x2_mean", 0), "y2": y * y - norm.get("y2_mean", 0),
                 "x3": x ** 3, "x2y": x * x * y, "xy2": x * y * y, "y3": y ** 3}
        value = sum(coefficients.get(term, 0) * terms[term] for term in payload.get("terms", []))
        limit = float(payload.get("max_abs_correction_px", 0)) * analysis_scale
        return np.clip(value, -limit, limit) if limit > 0 else value

    ly, ry = l[:, 1].copy(), r[:, 1].copy()
    # The raster uses an inverse map evaluated at destination coordinates.
    # Solve its small vertical displacement at both eye positions, rather
    # than approximating a symmetric field at the left position alone.
    for _ in range(4):
        ly = l[:, 1] + .5 * field(l, ly)
        ry = r[:, 1] - .5 * field(r, ry)
    return ry - ly


def point_quality(points: np.ndarray, residuals: np.ndarray,
                  image_shape: tuple[int, int], analysis_scale: float) -> tuple[dict, dict]:
    from .alignment import _grid_zone_indices, ZONE3X3_LABELS

    def summary(values):
        values = np.abs(values) / analysis_scale
        if not len(values):
            return {key: None for key in ("mean_abs", "median_abs", "p90_abs", "p95_abs", "max_abs")}
        p95 = float(np.percentile(values, 95))
        return {"mean_abs": float(np.minimum(values, p95).mean()),
                "median_abs": float(np.median(values)), "p90_abs": float(np.percentile(values, 90)),
                "p95_abs": p95, "max_abs": float(values.max())}

    zones = _grid_zone_indices(points, image_shape, 3)
    rows = []
    for index, label in enumerate(ZONE3X3_LABELS):
        selected = zones == index
        rows.append({"label": label, "count": int(selected.sum()), **summary(residuals[selected])})
    return summary(residuals), {"zones": rows}


def refine_alignment(baseline: dict, left_points: np.ndarray, right_points: np.ndarray,
                     inlier_mask: np.ndarray, left_gray: np.ndarray, right_gray: np.ndarray,
                     analysis_scale: float, method: str) -> dict:
    from .alignment import _analyze_matched_points, _assess_spatial_holdout
    correction = baseline["correction"]
    audit = {"accepted": False, "reason": "no_nonlinear_model", "iterations": 1}
    correction["refinement_validation"] = audit
    if not ((correction.get("y_residual_apply") or {}).get("enabled")
            or (correction.get("trapez_apply") or {}).get("enabled")):
        return baseline
    residual = corrected_point_residuals(correction, left_points, right_points, left_gray.shape, analysis_scale)
    scores = patch_correlations(left_gray, right_gray, left_points, right_points)
    photo_good = scores >= .85
    # Entire 32-pixel blocks are withheld, including adjacent/duplicate feature
    # locations. These points never train the recovered candidate.
    blocks = np.floor(left_points / 32).astype(np.int64)
    holdout = (blocks[:, 0] * 73856093 + blocks[:, 1] * 19349663) % 5 == 0
    eligible = (np.abs(residual) <= 3.0) & (inlier_mask | photo_good)
    recovered = eligible & ~inlier_mask & ~holdout
    audit.update(original_inliers=int(inlier_mask.sum()), recovered_training_points=int(recovered.sum()))
    if int(recovered.sum()) < max(30, int(.05 * inlier_mask.sum())):
        audit["reason"] = "few_confirmed_recovered_points"
        return baseline
    # Thin correlated/duplicate keypoints for validation, keeping the strongest
    # photometric check in each four-pixel cell.
    check_indices = np.flatnonzero(photo_good & holdout)
    order = check_indices[np.argsort(-scores[check_indices], kind="stable")]
    cells = np.floor(left_points[order] / 4).astype(np.int64)
    _, unique = np.unique(cells, axis=0, return_index=True)
    check = order[np.sort(unique)]
    audit["validation_points"] = int(len(check))
    if len(check) < 24:
        audit["reason"] = "insufficient_independent_points"
        return baseline
    try:
        candidate = _analyze_matched_points(left_points, right_points, left_gray.shape,
                                            analysis_scale, method, inlier_mask=eligible & ~holdout)
    except (RuntimeError, np.linalg.LinAlgError) as exc:
        audit.update(reason="refit_failed", detail=str(exc))
        return baseline
    candidate_residual = corrected_point_residuals(candidate["correction"], left_points[check], right_points[check],
                                                  left_gray.shape, analysis_scale)
    before, before_zones = point_quality(left_points[check], residual[check], left_gray.shape, analysis_scale)
    after, after_zones = point_quality(left_points[check], candidate_residual, left_gray.shape, analysis_scale)
    # A region that was already subpixel may trade a fraction of a pixel for a
    # large improvement elsewhere, provided it remains below explicit good
    # quality ceilings. Otherwise the regional protection would repeat the
    # former maximum veto in another form. Global robust improvement is still
    # mandatory, and all comparison points are withheld from this refit.
    decision = _assess_spatial_holdout(before, after, before_zones, after_zones, analysis_scale,
                                       region_quality_floor_analysis=(.5, 1.5))
    audit["regional_quality_ceilings_analysis_px"] = {"mean_abs": .5, "p90_abs": 1.5}
    audit.update(decision, baseline_quality=before, candidate_quality=after,
                 baseline_regions=before_zones, candidate_regions=after_zones,
                 mean_policy="winsorized_at_p95")
    if not decision["accepted"]:
        return baseline
    candidate["correction"]["refinement_validation"] = audit
    return candidate
