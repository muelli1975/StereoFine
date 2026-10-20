"""Real .sfin write/read and native geometry-render check, private temporary files.

This checks the existing correction contract, not process_source cache admission
or the correctness of a newly estimated near point. It never calls analysis.
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
from stereofine.alignment import warp_pair_symmetric
from stereofine.geometry import apply_orientation
from stereofine.sidecar import save_sidecar, load_sidecar, source_stamp_to_dict, SidecarStatus
from stereofine.sources import load_source, source_from_pair, build_source_stamp
from stereofine.state import PairState, InputTransformState


def raster_digest(left, right, correction):
    a, b = warp_pair_symmetric(left, right, correction)
    result = dict(shape=list(a.shape), dtype=str(a.dtype),
        left_sha256=hashlib.sha256(a.tobytes()).hexdigest(),
        right_sha256=hashlib.sha256(b.tobytes()).hexdigest())
    del a, b
    return result


def evaluate(case, results):
    name = case['name'].removesuffix('_SIFT')
    correction = json.loads((results/(name+'_subpixel_corrections.json')).read_text())['subpixel']
    t = json.loads(Path(case['state']).read_text())['input_transform']
    source = source_from_pair(Path(case['left']), Path(case['right']), Path(case['left']).parent)
    loaded = load_source(source)
    stamp = build_source_stamp(source, loaded)
    left = apply_orientation(loaded.left, t['left_orientation'], t['left_mirror'])
    right = apply_orientation(loaded.right, t['right_orientation'], t['right_mirror'])
    if t['swap_eyes']:
        left, right = right, left
    state = PairState(favorite=True, input_transform=InputTransformState(**t))
    state.alignment.method = 'SIFT'
    state.alignment.valid = True
    state.alignment.correction = correction
    state.manual.delta_x_px = 7
    before = raster_digest(left, right, correction)
    with tempfile.TemporaryDirectory(prefix='stereofine-subpixel-sidecar-') as td:
        path = Path(td)/(name+'.sfin')
        save_sidecar(path, state.to_sidecar(source=source_stamp_to_dict(stamp)))
        read = load_sidecar(path, expected_source=stamp)
        if read.status != SidecarStatus.VALID or read.pipeline_mismatches:
            raise RuntimeError('Sidecar is not valid under current pipeline')
        restored = PairState.from_sidecar(read.document)
        if not restored.favorite or restored.manual.delta_x_px != 7:
            raise RuntimeError('User state did not survive roundtrip')
        if restored.input_transform != state.input_transform:
            raise RuntimeError('Input transforms changed')
        after = raster_digest(left, right, restored.alignment.correction)
        if before != after:
            raise RuntimeError('Rendered geometry changed on disk roundtrip')
    return dict(name=name, native_raster=before, sidecar_valid=True,
        native_pixels_identical=True, favorite_and_manual_preserved=True,
        scope='existing .sfin contract and geometry raster only; no process_source cache or new near-point claim')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--selection', type=Path, required=True)
    parser.add_argument('--experimental', action='store_true', help='Check the pre-reference experimental shortlist, without admitting it to production')
    args = parser.parse_args()
    cv2.setNumThreads(4)
    for case in json.loads(args.manifest.read_text()):
        if not case['name'].endswith('_SIFT'):
            continue
        name = case['name'].removesuffix('_SIFT')
        selection = json.loads((args.selection/(name+'_selection.json')).read_text())
        chosen = selection.get('experimental_selected', selection['selected']) if args.experimental else selection['selected']
        if chosen != 'subpixel':
            continue
        result = evaluate(case, args.results)
        (args.selection/(name+'_sidecar.json')).write_text(json.dumps(result, indent=2))
        print(json.dumps(result), flush=True)
        gc.collect()


if __name__ == '__main__':
    main()
