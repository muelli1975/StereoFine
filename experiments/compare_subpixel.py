"""Research-only measurement refinement within the unchanged RC3 geometry.

Subpixel LK refines correspondence measurements, not image geometry. Failed
refinements retain original SIFT coordinates. No horizontal zero-disparity fit.
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
from experiments.compare_rectification import get_points, metrics, training_mask, withheld
from experiments.select_neural_candidate import control_points
from stereofine.alignment import _analyze_matched_points, _fit_vertical_ransac_filter, resize_pair_for_analysis
from stereofine.alignment_refinement import corrected_point_residuals, patch_correlations, refine_alignment
from stereofine.geometry import apply_orientation
from stereofine.lens_refinement import refine_residual_field
from stereofine.sources import load_source, source_from_pair

PROTOCOL = dict(version='subpixel-block-pilot-1', analysis_width=3000,
    external_split='same 128px reserved blocks and 16px training margin as rectification pilot',
    lk='SIFT-initialized LK, 21x21, levels=1, 40 iterations, epsilon=.001',
    guards='NCC before>=.85, after>=.90 and not decreased, FB<=.25, shift<=1.5 analysis px',
    horizontal='measured freely within 1.5px neighborhood; never fitted toward zero disparity',
    fallback='retain original coordinates when refinement is unconfirmed',
    geometry='unchanged RC3 fit/recovery/cubic guards, original training-only y-inlier mask',
    controls='same frozen external LK/NCC source points, no candidate-based error filtering')


def refine_measurements(left_gray, right_gray, p, q):
    p, q = np.asarray(p, float), np.asarray(q, float)
    updated = q.copy()
    before = patch_correlations(left_gray, right_gray, p, q)
    indices = np.flatnonzero(before >= .85)
    if not len(indices):
        return updated, np.zeros(len(p), bool)
    a, b = [x[indices].astype(np.float32).reshape(-1, 1, 2) for x in (p, q)]
    options = dict(winSize=(21, 21), maxLevel=1,
        criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 40, .001),
        flags=cv2.OPTFLOW_USE_INITIAL_FLOW)
    forward, status, _ = cv2.calcOpticalFlowPyrLK(left_gray, right_gray, a, b.copy(), **options)
    if forward is None:
        return updated, np.zeros(len(p), bool)
    back, status2, _ = cv2.calcOpticalFlowPyrLK(right_gray, left_gray, forward, a.copy(), **options)
    if back is None:
        return updated, np.zeros(len(p), bool)
    candidate = forward[:, 0].astype(float)
    good = status[:, 0].astype(bool) & status2[:, 0].astype(bool)
    good &= np.isfinite(candidate).all(axis=1) & np.isfinite(back[:, 0]).all(axis=1)
    good &= np.linalg.norm(back[:, 0]-a[:, 0], axis=1) <= .25
    good &= np.linalg.norm(candidate-q[indices], axis=1) <= 1.5
    after = patch_correlations(left_gray, right_gray, p[indices], candidate)
    good &= (after >= .90) & (after >= before[indices])
    # A measurement change must not cross into external test blocks.
    good &= training_mask(p[indices], candidate)
    changed = np.zeros(len(p), bool)
    changed[indices[good]] = True
    updated[changed] = candidate[good]
    return updated, changed


def fit(p, q, mask, ga, gb, scale):
    result = _analyze_matched_points(p, q, ga.shape, scale, 'SIFT', inlier_mask=mask)
    result = refine_alignment(result, p, q, mask, ga, gb, scale, 'SIFT')
    return refine_residual_field(result, p, q, ga, gb, scale)


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
    p, q = p[train], q[train]
    cp, cq, _ = control_points(ga, gb)
    check = withheld(cp)
    cp, cq = cp[check].astype(float), cq[check].astype(float)
    mask = np.asarray(_fit_vertical_ransac_filter(.5*(p+q), q, p, ga.shape)['mask'], bool)
    refined, changed = refine_measurements(ga, gb, p, q)
    record = dict(name=case['name'].removesuffix('_SIFT'), protocol=PROTOCOL,
        training_matches=len(p), refined_matches=int(changed.sum()), control_points=len(cp),
        analysis_shape=list(ga.shape), analysis_scale=scale, variants={})
    corrections = {}
    for name, points in [('baseline', q), ('subpixel', refined)]:
        result = fit(p, points, mask, ga, gb, scale)
        dy = corrected_point_residuals(result['correction'], cp, cq, ga.shape, scale)/scale
        record['variants'][name] = dict(model=result['model'], metrics=metrics(cp, dy, ga.shape))
        corrections[name] = result['correction']
    (output/(record['name']+'_subpixel_corrections.json')).write_text(json.dumps(corrections, indent=2))
    record['inputs_sha256'] = {}
    for key, path in dict(left=case['left'], right=case['right'], state=case['state'], points=point_file).items():
        with open(path, 'rb') as stream:
            record['inputs_sha256'][key] = hashlib.file_digest(stream, 'sha256').hexdigest()
    record['seconds'] = time.perf_counter()-start
    return record


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
        dest = args.output/(name+'_subpixel.json')
        if dest.exists():
            continue
        try:
            row = evaluate(case, args.output)
            dest.write_text(json.dumps(row, indent=2, allow_nan=False))
            print(name, row['refined_matches'], {k:v['metrics']['all'] for k,v in row['variants'].items()}, flush=True)
        except Exception:
            import traceback
            traceback.print_exc()
        gc.collect()


if __name__ == '__main__':
    main()
