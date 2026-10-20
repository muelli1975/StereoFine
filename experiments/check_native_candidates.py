"""Counterfactual raster and .sfin checks; never admits a research candidate.

Uses the existing native geometry renderer. Output measurements are redetected
per raster, so they supplement, rather than replace, the fixed source controls.
No original image, user sidecar, release, or production parameter is modified.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
from pathlib import Path
import sys
import tempfile

import cv2

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.diagnose_rc3_field import rendered_checks
from stereofine.alignment import warp_pair_symmetric
from stereofine.geometry import apply_orientation
from stereofine.sidecar import load_sidecar, save_sidecar, source_stamp_to_dict, SidecarStatus
from stereofine.sources import build_source_stamp, load_source, source_from_pair
from stereofine.state import InputTransformState, PairState


def digest(left, right):
    return dict(shape=list(left.shape), dtype=str(left.dtype),
                left_sha256=hashlib.sha256(left.tobytes()).hexdigest(),
                right_sha256=hashlib.sha256(right.tobytes()).hexdigest())


def evaluate(case, results, kind):
    name = case['name']
    variants = ['rc3', 'full_candidate'] if kind in ('native', 'applied') else ['rc3', 'bounded']
    corrections = json.loads((results/(name+'_'+kind+'_corrections.json')).read_text())
    transform = json.loads(Path(case['state']).read_text())['input_transform']
    source = source_from_pair(Path(case['left']), Path(case['right']), Path(case['left']).parent)
    loaded = load_source(source)
    stamp = build_source_stamp(source, loaded)
    a = apply_orientation(loaded.left, transform['left_orientation'], transform['left_mirror'])
    b = apply_orientation(loaded.right, transform['right_orientation'], transform['right_mirror'])
    if transform['swap_eyes']:
        a, b = b, a
    row = dict(name=name, kind=kind, production_admission=False,
               scope='native geometry only; no new near point, window framing or process_source cache claim',
               raster_controls='redetected per raster at 1500px; counts and locations can differ',
               variants={})
    for variant in variants:
        left, right = warp_pair_symmetric(a, b, corrections[variant])
        expected = digest(left, right)
        checks = rendered_checks(left, right, include_grid=True)
        del left, right
        record = dict(native_raster=expected, checks=checks)
        if variant != 'rc3':
            state = PairState(favorite=True, input_transform=InputTransformState(**transform))
            state.alignment.valid = True
            state.alignment.method = name.rsplit('_', 1)[1]
            state.alignment.correction = corrections[variant]
            state.manual.delta_x_px = 7
            with tempfile.TemporaryDirectory(prefix='sf-native-research-') as td:
                sidecar = Path(td)/(name+'.sfin')
                save_sidecar(sidecar, state.to_sidecar(source=source_stamp_to_dict(stamp)))
                read = load_sidecar(sidecar, expected_source=stamp)
                if read.status != SidecarStatus.VALID or read.pipeline_mismatches:
                    raise RuntimeError('Research payload does not roundtrip under the existing pipeline')
                restored = PairState.from_sidecar(read.document)
                if (not restored.favorite or restored.manual.delta_x_px != 7
                        or restored.input_transform != state.input_transform):
                    raise RuntimeError('User state was changed by the sidecar roundtrip')
                left, right = warp_pair_symmetric(a, b, restored.alignment.correction)
                if digest(left, right) != expected:
                    raise RuntimeError('Sidecar roundtrip changed native rendered pixels')
                del left, right
            record.update(sidecar_valid=True, native_pixels_identical=True,
                          favorite_manual_and_input_transform_preserved=True)
        row['variants'][variant] = record
        gc.collect()
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--kind', choices=['native', 'bounded', 'applied'], required=True)
    parser.add_argument('--names', nargs='+', required=True)
    args = parser.parse_args()
    cv2.setNumThreads(4)
    cases = {case['name']: case for case in json.loads(args.manifest.read_text())}
    for name in args.names:
        if name not in cases:
            raise ValueError('Unknown manifest case: '+name)
        path = args.results/(name+'_'+args.kind+'_rasters.json')
        row = evaluate(cases[name], args.results, args.kind)
        path.write_text(json.dumps(row, indent=2, allow_nan=False))
        print(name, args.kind, {k:v['checks'][0] for k,v in row['variants'].items()}, flush=True)
        gc.collect()


if __name__ == '__main__':
    main()
