"""Native raster countercheck for the isolated rectification experiment.

Geometry-only common valid crops, no near-point framing or application writes.
Raster probes are newly detected and therefore differ between output variants.
"""
from __future__ import annotations
import argparse
import gc
import json
from pathlib import Path
import sys

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from stereofine.alignment import _largest_all_valid_rectangle, warp_pair_symmetric
from stereofine.geometry import apply_orientation
from stereofine.sources import load_source, source_from_pair
from scripts.diagnose_rc3_field import rendered_checks


def native_matrix(matrix, analysis_scale):
    scale = analysis_scale
    basis = np.array([[scale, 0, (scale-1)/2], [0, scale, (scale-1)/2], [0, 0, 1.]])
    return np.linalg.inv(basis) @ np.array(matrix) @ basis


def render_homographies(left, right, h1, h2):
    height, width = left.shape[:2]
    size = (width, height)
    valid = np.ones((height, width), dtype=bool)
    for image, matrix in ((left, h1), (right, h2)):
        mask = np.zeros(image.shape[:2], dtype=np.uint8)
        mask[4:-4, 4:-4] = 255
        valid &= cv2.warpPerspective(mask, matrix, size, flags=cv2.INTER_NEAREST) > 0
    rect = _largest_all_valid_rectangle(valid)
    if rect is None:
        raise ValueError('No common valid crop')
    x0, y0, x1, y1 = rect
    images = [cv2.warpPerspective(im, matrix, size, flags=cv2.INTER_LANCZOS4)[y0:y1, x0:x1].copy()
              for im, matrix in ((left, h1), (right, h2))]
    return *images, list(rect)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--names', nargs='+', required=True)
    args = parser.parse_args()
    cv2.setNumThreads(4)
    for case in json.loads(args.manifest.read_text()):
        name = case['name'].removesuffix('_SIFT')
        if not case['name'].endswith('_SIFT') or name not in args.names:
            continue
        dest = args.results/(name+'_rasters.json')
        if dest.exists():
            continue
        result = json.loads((args.results/(name+'_rectification.json')).read_text())
        sd = json.loads(Path(case['state']).read_text())
        t = sd['input_transform']
        loaded = load_source(source_from_pair(Path(case['left']), Path(case['right']), Path(case['left']).parent))
        left = apply_orientation(loaded.left, t['left_orientation'], t['left_mirror'])
        right = apply_orientation(loaded.right, t['right_orientation'], t['right_mirror'])
        if t['swap_eyes']:
            left, right = right, left
        output = dict(name=name, input_shape=left.shape, scope='native geometry only; no near-point/window framing', variants={})
        matrices = json.loads((args.results/(name+'_common_inliers_matrices.json')).read_text())
        a, b = warp_pair_symmetric(left, right, matrices['baseline'])
        output['variants']['baseline'] = dict(shape=a.shape, checks=rendered_checks(a, b, include_grid=True))
        del a, b
        for variant in ('common_inliers', 'raw_training'):
            path = args.results/(name+'_'+variant+'_matrices.json')
            if not path.exists():
                continue
            matrices = json.loads(path.read_text())
            h1, h2 = [native_matrix(matrices[k], result['analysis_scale']) for k in ('h1', 'h2')]
            a, b, crop = render_homographies(left, right, h1, h2)
            output['variants'][variant] = dict(shape=a.shape, crop=crop,
                area_fraction=a.shape[0]*a.shape[1]/(left.shape[0]*left.shape[1]),
                checks=rendered_checks(a, b, include_grid=True))
            del a, b
            gc.collect()
        dest.write_text(json.dumps(output, indent=2))
        print(name, {k:v['checks'][0] for k,v in output['variants'].items()}, flush=True)
        del loaded, left, right
        gc.collect()


if __name__ == '__main__':
    main()
