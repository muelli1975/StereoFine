"""Research-only coverage audit; never select a new correction or write sidecars.

Use a private JSON manifest of name/left/right/left_orientation rows. Names end
in AKAZE or SIFT. Existing measurement thresholds and blocked-training masks
are reused without relaxation. Counts refer to LEFT source-image coordinates;
they are not unique physical surfaces or calibrated confidence intervals.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
from pathlib import Path
import sys

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.compare_native_subpixel import fit, matches
from experiments.compare_rectification import training_mask, withheld
from experiments.native_subpixel import map_pixel_centers, refine_native_correspondences
from experiments.select_neural_candidate import control_points
from stereofine.alignment import _fit_vertical_ransac_filter, resize_pair_for_analysis
from stereofine.alignment_refinement import corrected_point_residuals, patch_correlations
from stereofine.geometry import apply_orientation
from stereofine.inputs import master_to_uint8
from stereofine.sources import load_source, source_from_pair

PROTOCOL = dict(version='coverage-audit-1', seed=1337, analysis_width=3000,
    reference='fresh current-core fit, not a replay of lost historical states',
    measurement='unchanged native-lk-1 and source LK/NCC control detector',
    regions='left source coordinates; corners 20%, BR10 and 5x5 grid',
    blocked_fit='unchanged 128px reserved blocks and 16px halo in both eyes',
    purpose='coverage diagnosis only; no candidate admission or production change',
    limitations='controls may overlap full-fit training; no ground truth or new quality claim')


def regions(points, shape):
    p = np.asarray(points)
    h, w = shape[:2]
    result = {'all': np.ones(len(p), dtype=bool)}
    for name, x, y, fraction in [('TL20', 0, 0, .2), ('TR20', .8, 0, .2),
            ('BL20', 0, .8, .2), ('BR20', .8, .8, .2), ('BR10', .9, .9, .1)]:
        result[name] = ((p[:, 0] >= x*w) & (p[:, 0] < (x+fraction)*w)
                       & (p[:, 1] >= y*h) & (p[:, 1] < (y+fraction)*h))
    for iy in range(5):
        for ix in range(5):
            result[f'grid5_{iy}_{ix}'] = ((p[:, 0] >= ix*w/5) & (p[:, 0] < (ix+1)*w/5)
                & (p[:, 1] >= iy*h/5) & (p[:, 1] < (iy+1)*h/5))
    return result


def counts(points, shape, masks):
    return {region: {name: int((inside & mask).sum()) for name, mask in masks.items()}
            for region, inside in regions(points, shape).items()}


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def evaluate_pair(cases, output):
    first = cases[0]
    loaded = load_source(source_from_pair(Path(first['left']), Path(first['right']), Path(first['left']).parent))
    images = [master_to_uint8(apply_orientation(image, first.get(eye+'_orientation', '0'), False))
              for eye, image in [('left', loaded.left), ('right', loaded.right)]]
    ga, gb, scale = resize_pair_for_analysis(*images, 3000)
    na, nb = [np.asarray(Image.fromarray(image).convert('L'), dtype=np.uint8) for image in images]
    del loaded, images
    cp, cq, _ = control_points(ga, gb)
    cn, qn = [map_pixel_centers(p, ga.shape, na.shape) for p in (cp, cq)]
    refined_controls, confirmed, caudit = refine_native_correspondences(na, nb, cn, qn)
    reserve = withheld(cp)
    control_counts = counts(cp, ga.shape, dict(source=np.ones(len(cp), bool),
        native_confirmed=confirmed, reserved_source=reserve, reserved_native=reserve & confirmed))
    for case in cases:
        cv2.setRNGSeed(PROTOCOL['seed'])
        method = case['name'].rsplit('_', 1)[1]
        case = dict(case, state=str(output/(case['name']+'_state.json')),
                    points=str(output/(case['name']+'_points.npz')))
        p, q, mask, point_path = matches(case, ga, gb, output)
        native_p, native_q = [map_pixel_centers(x, ga.shape, na.shape) for x in (p, q)]
        _, accepted, audit = refine_native_correspondences(na, nb, native_p, native_q)
        scores = patch_correlations(ga, gb, p, q)
        training = training_mask(p, q)
        full = fit(p, q, mask, ga, gb, scale, method)
        blocked_mask = _fit_vertical_ransac_filter(.5*(p[training]+q[training]), q[training],
            p[training], ga.shape)['mask']
        blocked = fit(p[training], q[training], blocked_mask, ga, gb, scale, method)
        row = dict(name=case['name'], protocol=PROTOCOL, native_shape=list(na.shape),
            analysis_shape=list(ga.shape), native_measurement=audit, native_control_measurement=caudit,
            features=counts(p, ga.shape, dict(raw=np.ones(len(p), bool), inlier=mask,
                ncc90=scores >= .90, inlier_ncc90=mask & (scores >= .90), native_accepted=accepted,
                inlier_native_accepted=mask & accepted, blocked_training=training,
                original_inlier_retained=mask & training)), controls=control_counts,
            models=dict(full=full['model'], blocked=blocked['model']),
            cubic_audits={key: value['correction'].get('lens_refinement_validation')
                          for key, value in [('full', full), ('blocked', blocked)]},
            inputs_sha256={key: digest(case[key]) for key in ['left', 'right']},
            points_sha256=digest(point_path), versions=dict(opencv=cv2.__version__, numpy=np.__version__))
        selected = reserve & confirmed
        checks, check_right = cn[selected], refined_controls[selected]
        # Descriptive only: these frozen controls do not admit any correction.
        row['reserved_native_residuals'] = {}
        for key, result in [('full', full), ('blocked', blocked)]:
            residual = np.abs(corrected_point_residuals(result['correction'], checks, check_right, na.shape, 1.))
            row['reserved_native_residuals'][key] = {
                region: dict(count=int(inside.sum()), mean_px=float(residual[inside].mean()) if inside.any() else None,
                    p95_px=float(np.percentile(residual[inside], 95)) if inside.any() else None)
                for region, inside in regions(checks, na.shape).items()}
        (output/(case['name']+'_coverage.json')).write_text(json.dumps(row, indent=2, allow_nan=False))
        print(case['name'], row['models'], 'BR10', row['features']['BR10'],
              'controls', row['controls']['BR10'], flush=True)
    gc.collect()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    cv2.setNumThreads(4)
    groups = {}
    for case in json.loads(args.manifest.read_text()):
        groups.setdefault(case['name'].rsplit('_', 1)[0], []).append(case)
    for cases in groups.values():
        evaluate_pair(cases, args.output)


if __name__ == '__main__':
    main()
