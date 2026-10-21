"""Read-only real-image audit of bounded native-confirmed disparity spans.

Fresh production alignment is retained. No sidecar, output image or package is
written. Results intentionally do not assert scene completeness.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

import cv2

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.range_evidence import measure_range_evidence, PROTOCOL
from stereofine.disparity import analyze_horizontal_disparity, json_safe_disparity_summary, render_pair_for_disparity_analysis_from_arrays
from stereofine.geometry import apply_orientation, center_crop_to_common_size
from stereofine.inputs import master_to_uint8
from stereofine.processing import process_source, ProcessingOptions, ProcessingDefaults
from stereofine.sources import source_from_pair, load_source


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def evaluate(case, replay=None, include_dense_tail=True, native_footprint=False,
             widths=(1500, 1000)):
    start = time.perf_counter()
    fingerprints = {key: digest(case[key]) for key in ['left', 'right']}
    rows = {}

    def measure(left, right, width):
        result = None
        for size in widths:
            t = time.perf_counter()
            dense = analyze_horizontal_disparity(left, right, size)
            dense_time = time.perf_counter()-t
            t = time.perf_counter()
            observed = measure_range_evidence(left, right, size, dense, include_dense_tail=include_dense_tail,
                                             native_footprint=native_footprint)
            rows[str(size)] = dict(baseline=json_safe_disparity_summary(dense), evidence=observed,
                baseline_seconds=dense_time, evidence_seconds=time.perf_counter()-t)
            if size == width:
                result = dense
        if result is None:
            raise ValueError('Unexpected production disparity width')
        return result

    method = case['name'].rsplit('_', 1)[1]
    cv2.setRNGSeed(1337)
    if replay is None:
        with tempfile.TemporaryDirectory(prefix='sf-range-readonly-') as clean:
            source = source_from_pair(Path(case['left']), Path(case['right']), Path(clean))
            with patch('stereofine.processing.analyze_horizontal_disparity', side_effect=measure):
                processed = process_source(source, ProcessingOptions(analysis_method=method,
                    force_alignment=True, force_disparity=True, save_sidecar=False,
                    defaults=ProcessingDefaults(left_orientation=case.get('left_orientation', '0'))))
        model, correction = processed.state.alignment.model, processed.state.alignment.correction
        offset = processed.state.framing.auto_near_offset_x_px
    else:
        if replay['input_sha256'] != fingerprints:
            raise ValueError('Replay input fingerprint mismatch')
        source = load_source(source_from_pair(Path(case['left']), Path(case['right']), Path(case['left']).parent))
        left = apply_orientation(master_to_uint8(source.left), case.get('left_orientation', '0'), False)
        right = master_to_uint8(source.right)
        left, right, _ = center_crop_to_common_size(left, right)
        model, correction = replay['model'], replay['correction']
        left, right = render_pair_for_disparity_analysis_from_arrays(left, right, correction)
        measure(left, right, 1500)
        # New research searches must not perturb the production baseline.
        for width in [str(w) for w in widths if str(w) in replay['measurements']]:
            for key in ['low_edge_permille', 'high_edge_permille', 'deviation_permille', 'uncertain_reasons']:
                if rows[width]['baseline'].get(key) != replay['measurements'][width]['baseline'].get(key):
                    raise RuntimeError('Frozen geometry failed baseline replay: '+key)
        offset = replay['native_auto_offset_px']
    first, second = [rows[str(width)]['evidence'] for width in widths]
    spans = [x['observed_span_permille'] for x in (first, second)]
    delta = None if None in spans else abs(spans[0]-spans[1])
    endpoint_deltas = {}
    for end in ['far', 'near']:
        values = [x['endpoints'][end]['edge_permille'] for x in [first, second]]
        endpoint_deltas[end] = None if None in values else abs(values[0]-values[1])
    stable = (all(x['endpoints_confirmed'] for x in (first, second)) and delta <= 1.5
              and all(d is not None and d <= 1.5 for d in endpoint_deltas.values()))
    after = {key: digest(case[key]) for key in ['left', 'right']}
    if fingerprints != after:
        raise RuntimeError('Input files changed during evaluation')
    return dict(name=case['name'], protocol=first['protocol'], input_sha256=fingerprints,
        model=model, correction=correction, native_auto_offset_px=offset,
        analysis_widths=list(widths),
        geometry_replayed=replay is not None,
        measurements=rows, span_difference_permille=delta,
        endpoint_differences_permille=endpoint_deltas,
        endpoints_stable_at_two_scales=stable, elapsed_seconds=time.perf_counter()-start,
        input_files_unchanged=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--names', nargs='*')
    parser.add_argument('--partition', type=int)
    parser.add_argument('--replay-dir', type=Path)
    parser.add_argument('--initial-sampler', action='store_true',
                        help='Reproduce the initial pilot without interior tail seeds')
    parser.add_argument('--native-footprint', action='store_true')
    parser.add_argument('--widths', nargs=2, type=int, default=[1500, 1000])
    args = parser.parse_args()
    if args.widths[0] != 1500 or len(set(args.widths)) != 2 or min(args.widths) < 80:
        parser.error('Keep the production 1500px baseline first and choose one distinct control width')
    args.output.mkdir(parents=True, exist_ok=True)
    cv2.setNumThreads(2)
    for index, case in enumerate(json.loads(args.manifest.read_text())):
        if args.names and case['name'] not in args.names:
            continue
        if args.partition is not None and index % 2 != args.partition:
            continue
        dest = args.output/(case['name']+'_range.json')
        if dest.exists():
            continue
        previous = None
        if args.replay_dir:
            source = args.replay_dir/(case['name']+'_range.json')
            if not source.exists():
                continue
            previous = json.loads(source.read_text())
        row = evaluate(case, previous, include_dense_tail=not args.initial_sampler,
                       native_footprint=args.native_footprint, widths=tuple(args.widths))
        dest.write_text(json.dumps(row, indent=2, allow_nan=False))
        print(row['name'], row['model'], 'stable', row['endpoints_stable_at_two_scales'],
              'span', [None if (value := row['measurements'][str(s)]['evidence']['observed_span_permille']) is None
                       else round(value, 3) for s in args.widths],
              'seconds', round(row['elapsed_seconds'], 1), flush=True)
        gc.collect()


if __name__ == '__main__':
    main()
