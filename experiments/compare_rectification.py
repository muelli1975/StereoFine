"""Research only: blocked external checks of RC3 and OpenCV rectification.

No production imports, sidecar writes, calibration assumptions or neural code.
Raw SIFT matches are fixed before splitting; no test residual filters are used.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
from pathlib import Path
import sys
import time

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stereofine.alignment import (_analyze_matched_points, _fit_vertical_ransac_filter,
                                 resize_pair_for_analysis)
from stereofine.alignment_refinement import corrected_point_residuals, refine_alignment
from stereofine.lens_refinement import refine_residual_field
from stereofine.geometry import apply_orientation
from stereofine.sources import load_source, source_from_pair
from experiments.select_neural_candidate import control_points

PROTOCOL = {
    'version': 'rectification-block-pilot-1',
    'analysis_width': 3000, 'seed': 1337,
    'block_analysis_px': 128, 'training_margin_analysis_px': 16,
    'withheld': '(block_x*73856093 + block_y*19349663) modulo 5 == 0',
    'training': 'left AND right outside withheld blocks, including 16px margin',
    'checks': 'fixed LK/NCC source measurements with left point in withheld block',
    'controls': 'same 5x5 distributed, FB<.35 at 1500px, NCC>=.90 as neural pilot',
    'baseline': 'RC3 fit + recovery + bounded cubic, training arrays only',
    'common': 'F MAGSAC on same training-only legacy y-RANSAC inliers as baseline seed',
    'raw': 'F MAGSAC on all training SIFT matches: separate filter ablation',
    'fundamental': 'USAC_MAGSAC, threshold=1 analysis px, confidence=.999, maxIters=10000',
    'gauge': 'common isotropic postscale: geometric mean center Jacobian area = 1',
    'metrics': 'native-equivalent source point y residuals, true untrimmed mean and P95',
    'limits': 'no ground truth, no release integration, raster validation separate',
}


def withheld(points):
    block = np.floor(np.asarray(points) / 128).astype(np.int64)
    return (block[:, 0]*73856093 + block[:, 1]*19349663) % 5 == 0


def training_mask(left, right, margin=16):
    good = np.ones(len(left), dtype=bool)
    for p in (left, right):
        for dx in (-margin, 0, margin):
            for dy in (-margin, 0, margin):
                good &= ~withheld(p + [dx, dy])
    return good


def transform(matrix, points):
    p = np.column_stack([np.asarray(points, float), np.ones(len(points))]) @ matrix.T
    if not np.isfinite(p).all() or np.any(np.abs(p[:, 2]) < 1e-10):
        raise ValueError('Projective horizon or nonfinite point')
    return p[:, :2]/p[:, 2:]


def jacobian(matrix, point):
    x, y = point
    h = np.asarray(matrix, float)
    d = h[2] @ [x, y, 1.]
    n = h[:2] @ [x, y, 1.]
    if abs(d) < 1e-10:
        raise ValueError('Projective horizon')
    return (h[:2, :2]*d - np.outer(n, h[2, :2]))/(d*d)


def normalize_gauge(h1, h2, shape):
    center = np.array([(shape[1]-1)/2, (shape[0]-1)/2])
    areas = [abs(np.linalg.det(jacobian(h, center))) for h in (h1, h2)]
    if not np.isfinite(areas).all() or min(areas) <= 1e-10:
        raise ValueError('Degenerate center Jacobian')
    scale = float(np.prod(areas)**(-.25))
    centers = [transform(h, center[None])[0] for h in (h1, h2)]
    offset = center - scale*np.mean(centers, axis=0)
    post = np.array([[scale, 0, offset[0]], [0, scale, offset[1]], [0, 0, 1.]])
    return post @ h1, post @ h2, scale


def warp_diagnostics(h1, h2, shape):
    height, width = shape[:2]
    xx, yy = np.meshgrid(np.linspace(0, width-1, 9), np.linspace(0, height-1, 9))
    probes = np.column_stack([xx.ravel(), yy.ravel()])
    result = []
    for h in (h1, h2):
        denominators = np.column_stack([probes, np.ones(len(probes))]) @ h[2]
        horizon = bool(denominators.min() <= 0 <= denominators.max())
        jac = np.array([jacobian(h, p) for p in probes])
        singular = np.linalg.svd(jac, compute_uv=False)
        area = np.linalg.det(jac)
        result.append(dict(horizon=horizon, min_signed_area=float(area.min()),
            max_signed_area=float(area.max()), max_anisotropy=float((singular[:, 0]/singular[:, 1]).max()),
            min_local_scale=float(singular.min()), max_local_scale=float(singular.max())))
    return result


def fit_rectification(left, right, shape):
    if len(left) < 16:
        raise ValueError('Fewer than 16 training points')
    cv2.setRNGSeed(PROTOCOL['seed'])
    f, mask = cv2.findFundamentalMat(left, right, cv2.USAC_MAGSAC, 1., .999, 10000)
    if f is None or f.shape != (3, 3) or not np.isfinite(f).all() or mask is None:
        raise ValueError('No finite fundamental matrix')
    good = mask.ravel().astype(bool)
    if good.sum() < 16 or np.linalg.matrix_rank(f) != 2:
        raise ValueError('Insufficient support or degenerate fundamental matrix')
    ok, h1, h2 = cv2.stereoRectifyUncalibrated(left[good], right[good], f,
                                             (shape[1], shape[0]), threshold=0)
    if not ok or h1 is None or h2 is None:
        raise ValueError('Rectification failed')
    h1, h2, scale = normalize_gauge(h1, h2, shape)
    diagnostic = warp_diagnostics(h1, h2, shape)
    if any(x['horizon'] or x['min_signed_area'] <= 0 for x in diagnostic):
        raise ValueError('Rectification folds or crosses image horizon')
    return h1, h2, dict(inliers=int(good.sum()), training_points=len(left),
                       gauge_postscale=scale, warps=diagnostic)


def summary(values):
    a = np.abs(np.asarray(values))
    if not len(a):
        return dict(count=0, mean_px=None, p95_px=None)
    if not np.isfinite(a).all():
        raise ValueError('Nonfinite validation residuals')
    return dict(count=len(a), mean_px=float(a.mean()), p95_px=float(np.percentile(a, 95)))


def metrics(p, dy, shape):
    h, w = shape[:2]
    rows = dict(all=summary(dy))
    for label, x, y, fraction in [('TL20', 0, 0, .2), ('TR20', .8, 0, .2),
            ('BL20', 0, .8, .2), ('BR20', .8, .8, .2), ('BR10', .9, .9, .1)]:
        keep = ((p[:, 0] >= x*w) & (p[:, 0] < (x+fraction)*w)
                & (p[:, 1] >= y*h) & (p[:, 1] < (y+fraction)*h))
        rows[label] = summary(dy[keep])
    for iy in range(5):
        for ix in range(5):
            keep = ((p[:, 0] >= ix*w/5) & (p[:, 0] < (ix+1)*w/5)
                    & (p[:, 1] >= iy*h/5) & (p[:, 1] < (iy+1)*h/5))
            rows[f'grid5_{iy}_{ix}'] = summary(dy[keep])
    return rows


def get_points(case, ga, gb, cache):
    basename = Path(case['state']).name.replace('_state.json', '_points.npz')
    candidates = sorted(Path(case['state']).parent.parent.rglob(basename))
    path = Path(case['points']) if case.get('points') else (candidates[0] if candidates else cache/(case['name']+'_points.npz'))
    if case.get('points') and not path.is_file():
        raise ValueError('Explicit correspondence file does not exist')
    if path.exists():
        z = np.load(path)
        if 'shape' in z and tuple(z['shape']) != ga.shape:
            raise ValueError('Cached analysis shape differs')
        return z['left'].astype(float), z['right'].astype(float), path
    from stereofine.feature_matching import sift_ratio_matches
    detector = cv2.SIFT_create()
    a, da = detector.detectAndCompute(ga, None)
    b, db = detector.detectAndCompute(gb, None)
    matches = sift_ratio_matches(db, da)
    p = np.array([a[m.trainIdx].pt for m in matches], dtype=float)
    q = np.array([b[m.queryIdx].pt for m in matches], dtype=float)
    np.savez_compressed(path, left=p, right=q, shape=ga.shape)
    return p, q, path


def evaluate(case, output):
    start = time.perf_counter()
    sd = json.loads(Path(case['state']).read_text())
    t = sd['input_transform']
    loaded = load_source(source_from_pair(Path(case['left']), Path(case['right']), Path(case['left']).parent))
    a = apply_orientation(loaded.left, t['left_orientation'], t['left_mirror'])
    b = apply_orientation(loaded.right, t['right_orientation'], t['right_mirror'])
    if t['swap_eyes']:
        a, b = b, a
    ga, gb, scale = resize_pair_for_analysis(a, b, 3000)
    del a, b, loaded
    p, q, point_file = get_points(case, ga, gb, output)
    train = training_mask(p, q)
    lp, rp = p[train], q[train]
    # Fixed source controls are measured before fitting; no candidate-based filter.
    cp, cq, _ = control_points(ga, gb)
    check = withheld(cp)
    cp, cq = cp[check].astype(float), cq[check].astype(float)
    initial = _fit_vertical_ransac_filter(.5*(lp+rp), rp, lp, ga.shape)
    mask = np.asarray(initial['mask'], bool)
    baseline = _analyze_matched_points(lp, rp, ga.shape, scale, 'SIFT', inlier_mask=mask)
    baseline = refine_alignment(baseline, lp, rp, mask, ga, gb, scale, 'SIFT')
    baseline = refine_residual_field(baseline, lp, rp, ga, gb, scale)
    base = corrected_point_residuals(baseline['correction'], cp, cq, ga.shape, scale)/scale
    result = dict(name=case['name'].removesuffix('_SIFT'), protocol=PROTOCOL,
        analysis_shape=list(ga.shape), analysis_scale=scale, raw_matches=len(p),
        training_matches=len(lp), initial_inliers=int(mask.sum()), control_points=len(cp),
        baseline=dict(model=baseline['model'], metrics=metrics(cp, base, ga.shape)), variants={})
    for name, keep in [('common_inliers', mask), ('raw_training', np.ones(len(lp), bool))]:
        try:
            h1, h2, details = fit_rectification(lp[keep], rp[keep], ga.shape)
            dy = (transform(h2, cq)[:, 1]-transform(h1, cp)[:, 1])/scale
            result['variants'][name] = dict(**details, metrics=metrics(cp, dy, ga.shape))
            (output/(result['name']+'_'+name+'_matrices.json')).write_text(json.dumps(
                dict(h1=h1.tolist(), h2=h2.tolist(), baseline=baseline['correction']), indent=2))
        except (ValueError, cv2.error, np.linalg.LinAlgError) as exc:
            result['variants'][name] = dict(error=str(exc))
    result['inputs_sha256'] = {}
    for key, path in dict(left=case['left'], right=case['right'], state=case['state'], points=str(point_file)).items():
        with open(path, 'rb') as f:
            result['inputs_sha256'][key] = hashlib.file_digest(f, 'sha256').hexdigest()
    result['seconds'] = time.perf_counter()-start
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--names', nargs='*')
    args = parser.parse_args()
    cv2.setNumThreads(4)
    args.output.mkdir(parents=True, exist_ok=True)
    for case in json.loads(args.manifest.read_text()):
        if not case['name'].endswith('_SIFT'):
            continue
        name = case['name'].removesuffix('_SIFT')
        if args.names and name not in args.names:
            continue
        dest = args.output/(name+'_rectification.json')
        if dest.exists():
            continue
        try:
            result = evaluate(case, args.output)
            dest.write_text(json.dumps(result, indent=2))
            print(name, result['baseline']['metrics']['all'],
                  {k: v.get('metrics', {}).get('all', v.get('error')) for k, v in result['variants'].items()}, flush=True)
        except Exception as exc:
            import traceback
            traceback.print_exc()
            print('FAILED', name, str(exc), flush=True)
        gc.collect()


if __name__ == '__main__':
    main()
