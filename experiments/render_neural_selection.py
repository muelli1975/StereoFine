"""Check actual native rasters for candidates admitted by the offline selector.

Recompute the candidate's near point and crop using unchanged RC3 processing.
Write numeric checks only; never export or alter original images/sidecars.
"""
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

from stereofine.disparity import render_pair_for_disparity_analysis_from_arrays, analyze_horizontal_disparity
from stereofine.geometry import apply_orientation
from stereofine.processing import _store_disparity_result, _disparity_basis
from stereofine.render import render_final_pair
from stereofine.sources import load_source, source_from_pair
from stereofine.state import PairState, AlignmentState, FramingState, InputTransformState
from scripts.diagnose_rc3_field import rendered_checks


def render_case(raw_file, selection_dir):
    row = json.loads(raw_file.read_text())
    case = row['case']
    name = case['name'].rsplit('_', 1)[0]
    sd = json.loads(Path(case['state']).read_text())
    t = sd['input_transform']
    loaded = load_source(source_from_pair(Path(case['left']), Path(case['right']), Path(case['left']).parent))
    result = dict(name=name, variants={})
    for variant in ['baseline', 'lightglue_aliked']:
        state = PairState(input_transform=InputTransformState(**t),
                          alignment=AlignmentState(**sd['alignment']),
                          framing=FramingState(**sd['framing']))
        if variant == 'lightglue_aliked':
            state.alignment.correction = json.loads((selection_dir/(name+'_correction.json')).read_text())
        # Recompute BOTH references with exactly the same current window code.
        a = apply_orientation(loaded.left, t['left_orientation'], t['left_mirror'])
        b = apply_orientation(loaded.right, t['right_orientation'], t['right_mirror'])
        if t['swap_eyes']:
            a, b = b, a
        dl, dr = render_pair_for_disparity_analysis_from_arrays(a, b, state.alignment.correction)
        dense = analyze_horizontal_disparity(dl, dr, 1500)
        _store_disparity_result(state, dense, basis=_disparity_basis(state), base_width_px=dl.shape[1])
        left, right, _ = render_final_pair(loaded, state, apply_color=False, apply_floating_window=False)
        result['variants'][variant] = dict(shape=left.shape, rendered=rendered_checks(left, right, include_grid=True),
            near=state.disparity.high_edge_permille, uncertain=state.disparity.uncertain_reasons)
        del dl, dr, dense, left, right, a, b
        gc.collect()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('results', type=Path)
    parser.add_argument('--selection', type=Path, required=True)
    parser.add_argument('--names', nargs='*', help='Explicit counterfactual raster checks, including rejected candidates')
    args = parser.parse_args()
    cv2.setNumThreads(4)
    for selected in sorted(args.selection.glob('*_selection.json')):
        row = json.loads(selected.read_text())
        if args.names and row['name'] not in args.names:
            continue
        if not args.names and row['selected'] != 'lightglue_aliked':
            continue
        output = selected.with_name(row['name']+'_rendered.json')
        if output.exists():
            continue
        result = render_case(args.results/(row['name']+'_lightglue_aliked.json'), args.selection)
        result['admitted_by_selector'] = row['selected'] == 'lightglue_aliked'
        output.write_text(json.dumps(result, indent=2, allow_nan=False))
        print(row['name'], result['variants']['baseline']['rendered'][0],
              result['variants']['lightglue_aliked']['rendered'][0], flush=True)


if __name__ == '__main__':
    main()
