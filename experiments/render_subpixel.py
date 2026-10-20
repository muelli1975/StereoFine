"""Native geometry-only raster checks using the existing production renderer."""
from __future__ import annotations
import argparse
import gc
import json
from pathlib import Path
import sys

import cv2

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from stereofine.alignment import warp_pair_symmetric
from stereofine.geometry import apply_orientation
from stereofine.sources import load_source, source_from_pair
from scripts.diagnose_rc3_field import rendered_checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--names', nargs='+', required=True)
    args = parser.parse_args()
    cv2.setNumThreads(4)
    for case in json.loads(args.manifest.read_text()):
        if not case['name'].endswith('_SIFT'):
            continue
        name = case['name'].removesuffix('_SIFT')
        if name not in args.names:
            continue
        dest = args.results/(name+'_subpixel_rasters.json')
        if dest.exists():
            continue
        path = args.results/(name+'_subpixel_corrections.json')
        if not path.exists():
            raise RuntimeError('Run source comparison first: '+name)
        corrections = json.loads(path.read_text())
        t = json.loads(Path(case['state']).read_text())['input_transform']
        loaded = load_source(source_from_pair(Path(case['left']), Path(case['right']), Path(case['left']).parent))
        a = apply_orientation(loaded.left, t['left_orientation'], t['left_mirror'])
        b = apply_orientation(loaded.right, t['right_orientation'], t['right_mirror'])
        if t['swap_eyes']:
            a, b = b, a
        row = dict(name=name, scope='native geometry only; unchanged production renderer, no window/near-point framing', variants={})
        for variant, correction in corrections.items():
            left, right = warp_pair_symmetric(a, b, correction)
            row['variants'][variant] = dict(shape=left.shape, checks=rendered_checks(left, right, include_grid=True))
            del left, right
            gc.collect()
        dest.write_text(json.dumps(row, indent=2, allow_nan=False))
        print(name, {k:v['checks'][0] for k,v in row['variants'].items()}, flush=True)
        del a, b, loaded
        gc.collect()


if __name__ == '__main__':
    main()
