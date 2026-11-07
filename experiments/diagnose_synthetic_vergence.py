"""Separate known-coordinate experiment; not an automatic matcher benchmark.

Fits use only the training subset. The held-out world points are checked by
numerically inverting actual native renderer maps, as in synthetic_vergence.
No production mask, acceptance threshold or image setting is changed.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from synthetic_vergence import WIDTH, HEIGHT, alignment, measured_render, stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cases', nargs='+', default=['02_convergent_2', '03_convergent_4', '04_convergent_8_stress'])
    args = parser.parse_args()
    cv2.setNumThreads(4)
    out = args.output.resolve()
    rows = []
    for name in args.cases:
        data = np.load(out/'results'/f'{name}_AKAZE_controls.npz')
        lp, rp = data['left'], data['right']
        # Known geometry has no correspondence error. A deterministic subset
        # is withheld from every fit, including the vertical first-stage fit.
        check = np.arange(len(lp)) % 5 == 0
        train = ~check
        image = np.asarray(Image.open(out/'inputs'/f'{name}_sbs.png').convert('RGB'))
        a, b = np.ascontiguousarray(image[:, :WIDTH]), np.ascontiguousarray(image[:, WIDTH:])
        records, rendered = [], []
        for mode in ('existing_first_filter', 'all_known_training_points'):
            mask = None if mode == 'existing_first_filter' else np.ones(int(train.sum()), bool)
            result = alignment._analyze_matched_points(lp[train], rp[train], (HEIGHT, WIDTH), 1., 'KNOWN', inlier_mask=mask)
            pair, p, q, good = measured_render(a, b, result['correction'], lp[check], rp[check])
            del pair
            records.append(dict(mode=mode, training_points=int(train.sum()),
                                training_inliers=result['inliers'], model=result['model'],
                                selection_audit=result['correction']['pipeline_basis']['selection_audit']))
            rendered.append((p, q, good))
        common = rendered[0][2] & rendered[1][2]
        anchor = .5*(lp[check]+rp[check])
        edge = ((anchor[:, 0] < .15*WIDTH) | (anchor[:, 0] > .85*WIDTH)
                | (anchor[:, 1] < .15*HEIGHT) | (anchor[:, 1] > .85*HEIGHT))
        for record, (p, q, good) in zip(records, rendered):
            record.update(held_out_controls=int(common.sum()),
                          all=stats((q[:, 1]-p[:, 1])[common]),
                          outer_15_percent=stats((q[:, 1]-p[:, 1])[common & edge]))
        rows.append(dict(case=name, variants=records))
        print(name, [(r['mode'], r['model'], r['training_inliers'], round(r['all']['p95'], 4))
                     for r in records], flush=True)
    report = dict(scope='Known-coordinate diagnostic only; ground truth supplied to training, never to original AKAZE/SIFT runs',
                  purpose='Isolate the existing first-stage inlier filter from correspondence errors',
                  limitation='Removing the filter is justified only by exact synthetic correspondences; it is not a proposed production change',
                  cases=rows)
    (out/'known_coordinate_diagnostic.json').write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')


if __name__ == '__main__':
    main()
