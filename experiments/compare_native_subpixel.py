"""Native-resolution correspondence refinement within the existing RC3 geometry.

Full-data fits are operational diagnostics only. Blocked fits provide separate
selection/confirmation controls and a conservative veto against actual RC3.
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
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from experiments.compare_rectification import metrics, training_mask, withheld
from experiments.select_neural_candidate import control_points
from experiments.select_subpixel_candidate import select, confirmation_split
from stereofine.alignment import _analyze_matched_points, _fit_vertical_ransac_filter, resize_pair_for_analysis
from stereofine.alignment_refinement import corrected_point_residuals, refine_alignment
from stereofine.feature_matching import sift_ratio_matches
from stereofine.geometry import apply_orientation
from stereofine.inputs import master_to_uint8
from stereofine.lens_refinement import refine_residual_field
from stereofine.sources import load_source, source_from_pair
from stereofine.state import reproducible_alignment_correction
from experiments.native_subpixel import map_pixel_centers, refine_native_correspondences, NATIVE_MEASUREMENT_PROTOCOL

PROTOCOL = dict(version='native-subpixel-pilot-1', measurement=NATIVE_MEASUREMENT_PROTOCOL,
    geometry='unchanged RC3 model/refinement/cubic guards; original inlier masks retained',
    controls='source LK/NCC detector at 1500px, locally confirmed at native resolution before any fit',
    split='original reserved 128 analysis-pixel blocks with 16px margins in both eyes, hash modulo10 0/5',
    reference='saved full-data RC3 correction must reproduce before candidate testing',
    full_candidate='all data, diagnostic only; controls are not spatially withheld from this fit',
    blocked_candidate='spatially independent training and frozen two-stage controls',
    admission='blocked candidate must pass both reduced-fit comparison and actual-full-RC3 veto',
    metrics='native point-coordinate vertical residuals, no arbitrary output shrink or horizontal zero-depth fit')


def matches(case, ga, gb, output):
    basename = Path(case['state']).name.replace('_state.json', '_points.npz')
    found = sorted(Path(case['state']).parent.parent.rglob(basename))
    path = Path(case['points']) if case.get('points') else (found[0] if found else output/(case['name']+'_points.npz'))
    if path.exists():
        z = np.load(path)
        if 'shape' in z and tuple(z['shape']) != ga.shape:
            raise ValueError('Correspondence cache has different analysis dimensions')
        p, q = z['left'].astype(float), z['right'].astype(float)
        mask = z['mask'].astype(bool) if 'mask' in z else _fit_vertical_ransac_filter(.5*(p+q), q, p, ga.shape)['mask']
        return p, q, mask, path
    method = case['name'].rsplit('_', 1)[1]
    detector = cv2.SIFT_create() if method == 'SIFT' else cv2.AKAZE_create()
    k1, d1 = detector.detectAndCompute(ga, None)
    k2, d2 = detector.detectAndCompute(gb, None)
    if method == 'SIFT':
        paired = sift_ratio_matches(d2, d1)
    else:
        raw = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(d2, d1, k=2)
        paired = [a for pair in raw if len(pair) == 2 for a, b in [pair] if a.distance < .75*b.distance]
    p = np.array([k1[m.trainIdx].pt for m in paired], float)
    q = np.array([k2[m.queryIdx].pt for m in paired], float)
    mask = _fit_vertical_ransac_filter(.5*(p+q), q, p, ga.shape)['mask']
    np.savez_compressed(path, left=p, right=q, mask=mask, shape=ga.shape)
    return p, q, mask, path


def fit(p, q, mask, ga, gb, scale, method):
    result = _analyze_matched_points(p, q, ga.shape, scale, method, inlier_mask=mask)
    result = refine_alignment(result, p, q, mask, ga, gb, scale, method)
    return refine_residual_field(result, p, q, ga, gb, scale)


def evaluate(case, output):
    start = time.perf_counter()
    method = case['name'].rsplit('_', 1)[1]
    sd = json.loads(Path(case['state']).read_text())
    t = sd['input_transform']
    loaded = load_source(source_from_pair(Path(case['left']), Path(case['right']), Path(case['left']).parent))
    a = master_to_uint8(apply_orientation(loaded.left, t['left_orientation'], t['left_mirror']))
    b = master_to_uint8(apply_orientation(loaded.right, t['right_orientation'], t['right_mirror']))
    if t['swap_eyes']:
        a, b = b, a
    ga, gb, scale = resize_pair_for_analysis(a, b, 3000)
    na, nb = [np.asarray(Image.fromarray(im).convert('L'), dtype=np.uint8) for im in (a, b)]
    del loaded, a, b
    p, q, mask, match_path = matches(case, ga, gb, output)
    original = fit(p, q, mask, ga, gb, scale, method)
    if reproducible_alignment_correction(original['correction']) != reproducible_alignment_correction(sd['alignment']['correction']):
        return dict(name=case['name'], status='excluded_reference_not_reproduced', protocol=PROTOCOL)
    cp, cq, _ = control_points(ga, gb)
    cp_native, cq_native = [map_pixel_centers(x, ga.shape, na.shape) for x in (cp, cq)]
    confirmed_q, confirmed, control_audit = refine_native_correspondences(na, nb, cp_native, cq_native)
    cp, cq = cp[confirmed], cq[confirmed]
    cp_native, cq_native = cp_native[confirmed], confirmed_q[confirmed]
    reserved = withheld(cp)
    checks, checks_right = cp_native[reserved], cq_native[reserved]
    split = confirmation_split(cp[reserved])
    np_native, nq_native = [map_pixel_centers(x, ga.shape, na.shape) for x in (p, q)]
    updated, accepted, audit = refine_native_correspondences(na, nb, np_native, nq_native)
    new_q = q.copy()
    new_q[accepted] = map_pixel_centers(updated[accepted], na.shape, ga.shape)
    train = training_mask(p, q)
    # Failed or cross-boundary updates keep original seeds; no silent data drop.
    blocked_q = new_q.copy()
    keep_update = training_mask(p, new_q)
    blocked_q[~keep_update] = q[~keep_update]
    blocked_mask = _fit_vertical_ransac_filter(.5*(p[train]+q[train]), q[train], p[train], ga.shape)['mask']
    variants = dict(full_candidate=fit(p, new_q, mask, ga, gb, scale, method),
        blocked_baseline=fit(p[train], q[train], blocked_mask, ga, gb, scale, method),
        blocked_candidate=fit(p[train], blocked_q[train], blocked_mask, ga, gb, scale, method))
    corrections = dict(rc3=original['correction'], **{k:v['correction'] for k,v in variants.items()})
    residuals = {key:corrected_point_residuals(c, checks, checks_right, na.shape, 1.) for key,c in corrections.items()}
    independence = select(checks, residuals['blocked_baseline'], residuals['blocked_candidate'], split, na.shape, scale)
    reference = select(checks, residuals['rc3'], residuals['blocked_candidate'], split, na.shape, scale)
    operational = select(checks, residuals['rc3'], residuals['full_candidate'], split, na.shape, scale)
    row = dict(name=case['name'], status='measured', protocol=PROTOCOL, reference_reproduced=True,
        native_shape=list(na.shape), analysis_shape=list(ga.shape), analysis_scale=scale,
        raw_matches=len(p), training_matches=int(train.sum()), native_measurement=audit,
        native_control_measurement=control_audit, reserved_controls=len(checks),
        metrics={k:metrics(checks,v,na.shape) for k,v in residuals.items()},
        models=dict(rc3=original['model'], **{k:v['model'] for k,v in variants.items()}),
        independent_comparison=independence, full_reference_veto=reference,
        full_fit_diagnostic=operational,
        admitted=(independence['selected']=='subpixel' and reference['selected']=='subpixel'))
    np.savez_compressed(output/(case['name']+'_native_controls.npz'), left=checks, right=checks_right,
        split=split, **residuals)
    (output/(case['name']+'_native_corrections.json')).write_text(json.dumps(corrections, indent=2))
    row['inputs_sha256'] = {}
    for key,path in dict(left=case['left'],right=case['right'],state=case['state'],points=match_path).items():
        with open(path,'rb') as f:
            row['inputs_sha256'][key] = hashlib.file_digest(f,'sha256').hexdigest()
    row['seconds'] = time.perf_counter()-start
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--names', nargs='*')
    args = parser.parse_args()
    cv2.setNumThreads(4)
    args.output.mkdir(parents=True,exist_ok=True)
    for case in json.loads(args.manifest.read_text()):
        stem=case['name'].rsplit('_',1)[0]
        if args.names and stem not in args.names:
            continue
        path=args.output/(case['name']+'_native.json')
        if path.exists() and json.loads(path.read_text()).get('status') == 'measured':
            continue
        row=evaluate(case,args.output)
        path.write_text(json.dumps(row,indent=2,allow_nan=False))
        print(case['name'],row['status'],{k:round(v['all']['p95_px'],3) if v['all']['p95_px'] is not None else None for k,v in row.get('metrics',{}).items()},'admitted',row.get('admitted'),flush=True)
        gc.collect()


if __name__=='__main__':
    main()
