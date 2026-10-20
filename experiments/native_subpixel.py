"""Conservative sparse correspondence measurement; no image or depth warp.

The caller decides where measurements may train a model and supplies independent
validation. This module alone never admits an alignment or changes a sidecar.
"""
from __future__ import annotations
import numpy as np
from stereofine.alignment_refinement import patch_correlations


NATIVE_MEASUREMENT_PROTOCOL = {
    'version': 'native-lk-1', 'window': 21, 'pyramid_levels': 1,
    'ncc_before_min': .85, 'ncc_after_min': .90,
    'forward_backward_max_px': .25, 'movement_max_px': 1.5,
    'iterations': 40, 'epsilon': .001,
}


def map_pixel_centers(points, source_shape, target_shape):
    """Map actual resized dimensions, including independently rounded height."""
    p = np.asarray(points, dtype=np.float64)
    if p.ndim != 2 or p.shape[1] != 2:
        raise ValueError('Expected an N by 2 coordinate array')
    if min(*source_shape[:2], *target_shape[:2]) <= 0:
        raise ValueError('Image dimensions must be positive')
    ratio = np.array([target_shape[1]/source_shape[1], target_shape[0]/source_shape[0]])
    return (p+.5)*ratio-.5


def refine_native_correspondences(left_gray, right_gray, left_points, right_points):
    """Refine right positions near observed matches, retaining every failed seed.

    Coordinates and all thresholds are in native pixels. Horizontal displacement
    remains a measured scene quantity; it is never optimized toward zero.
    """
    import cv2
    if (left_gray.ndim != 2 or right_gray.ndim != 2
            or left_gray.dtype != np.uint8 or right_gray.dtype != np.uint8
            or left_gray.shape != right_gray.shape):
        raise ValueError('Expected equal-size native uint8 grayscale images')
    p, q = np.asarray(left_points, float), np.asarray(right_points, float)
    if p.ndim != 2 or p.shape[1] != 2 or p.shape != q.shape:
        raise ValueError('Expected matching N by 2 correspondence arrays')
    result = q.copy()
    accepted = np.zeros(len(p), dtype=bool)
    audit = dict(protocol=dict(NATIVE_MEASUREMENT_PROTOCOL), points=len(p),
                 attempted=0, accepted=0, reason='no_supported_seeds')
    finite = np.isfinite(p).all(axis=1) & np.isfinite(q).all(axis=1)
    h, w = left_gray.shape
    margin = NATIVE_MEASUREMENT_PROTOCOL['window']//2+2
    for pts in (p, q):
        finite &= ((pts[:, 0] >= margin) & (pts[:, 0] < w-margin)
                   & (pts[:, 1] >= margin) & (pts[:, 1] < h-margin))
    indices = np.flatnonzero(finite)
    if not len(indices):
        return result, accepted, audit
    before = patch_correlations(left_gray, right_gray, p[indices], q[indices])
    selected = before >= NATIVE_MEASUREMENT_PROTOCOL['ncc_before_min']
    indices, before = indices[selected], before[selected]
    if not len(indices):
        return result, accepted, audit
    audit['attempted'] = len(indices)
    a, b = [x[indices].astype(np.float32).reshape(-1, 1, 2) for x in (p, q)]
    options = dict(winSize=(21, 21), maxLevel=1,
        criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 40, .001),
        flags=cv2.OPTFLOW_USE_INITIAL_FLOW)
    forward, status, _ = cv2.calcOpticalFlowPyrLK(left_gray, right_gray, a, b.copy(), **options)
    if forward is None:
        audit['reason'] = 'forward_measurement_failed'
        return result, accepted, audit
    good = status[:, 0].astype(bool) & np.isfinite(forward[:, 0]).all(axis=1)
    # Do not feed undefined tracker outputs back into OpenCV.
    safe_forward = forward.copy()
    safe_forward[~good] = b[~good]
    backward, status2, _ = cv2.calcOpticalFlowPyrLK(right_gray, left_gray, safe_forward, a.copy(), **options)
    if backward is None:
        audit['reason'] = 'backward_measurement_failed'
        return result, accepted, audit
    candidate = safe_forward[:, 0].astype(float)
    good &= status2[:, 0].astype(bool) & np.isfinite(backward[:, 0]).all(axis=1)
    good &= np.linalg.norm(backward[:, 0]-a[:, 0], axis=1) <= .25
    good &= np.linalg.norm(candidate-q[indices], axis=1) <= 1.5
    good &= ((candidate[:, 0] >= margin) & (candidate[:, 0] < w-margin)
             & (candidate[:, 1] >= margin) & (candidate[:, 1] < h-margin))
    after = patch_correlations(left_gray, right_gray, p[indices], candidate)
    good &= (after >= .90) & (after >= before)
    accepted[indices[good]] = True
    result[indices[good]] = candidate[good]
    audit.update(accepted=int(accepted.sum()), reason='confirmed_local_measurements' if accepted.any() else 'no_confirmed_refinements')
    return result, accepted, audit
