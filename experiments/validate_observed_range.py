"""Validate production range recovery against saved, frozen real-image geometry."""
import argparse
import gc
import json
from pathlib import Path
import sys
import time

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.compare_range_evidence import digest
from stereofine.disparity import analyze_horizontal_disparity, _analyze_horizontal_disparity, render_pair_for_disparity_analysis_from_arrays
from stereofine.geometry import apply_orientation, center_crop_to_common_size
from stereofine.inputs import master_to_uint8
from stereofine.sources import load_source, source_from_pair


def evaluate(case, saved):
    start = time.perf_counter()
    fingerprints = {k: digest(case[k]) for k in ['left', 'right']}
    if fingerprints != saved['input_sha256']:
        raise RuntimeError('Original input fingerprint changed')
    loaded = load_source(source_from_pair(Path(case['left']), Path(case['right']), Path(case['left']).parent))
    a = apply_orientation(master_to_uint8(loaded.left), case.get('left_orientation', '0'), False)
    b = master_to_uint8(loaded.right)
    a, b, _ = center_crop_to_common_size(a, b)
    a, b = render_pair_for_disparity_analysis_from_arrays(a, b, saved['correction'])
    baseline = _analyze_horizontal_disparity(a, b, 1500)
    for key in ['low_edge_permille', 'high_edge_permille', 'deviation_permille', 'uncertain_reasons', 'status']:
        if baseline.get(key) != saved['measurements']['1500']['baseline'].get(key):
            raise RuntimeError('Dense baseline did not reproduce: '+key)
    result = analyze_horizontal_disparity(a, b, 1500)
    for key in ['_disp_permille', '_confidence_mask', '_left_preview']:
        if not np.array_equal(baseline[key], result[key]):
            raise RuntimeError('Dense arrays changed: '+key)
    audit = result.get('range_recovery', {})
    if not audit.get('accepted'):
        for key in ['low_edge_permille', 'high_edge_permille', 'deviation_permille', 'uncertain_reasons', 'status']:
            if result.get(key) != baseline.get(key):
                raise RuntimeError('Rejected recovery changed baseline: '+key)
    if not baseline['uncertain_reasons'] and audit.get('accepted'):
        raise RuntimeError('Already confirmed result was changed')
    for k in fingerprints:
        if digest(case[k]) != fingerprints[k]:
            raise RuntimeError('Source file changed')
    return dict(name=case['name'], recovery_accepted=bool(audit.get('accepted')),
        reason=audit.get('reason', 'unchanged_confirmed_or_ineligible'),
        baseline_total_permille=baseline['deviation_permille'], total_permille=result['deviation_permille'],
        baseline_near_permille=baseline['high_edge_permille'], near_permille=result['high_edge_permille'],
        baseline_far_permille=baseline['low_edge_permille'], far_permille=result['low_edge_permille'],
        uncertain_reasons=result['uncertain_reasons'], baseline_uncertain_reasons=baseline['uncertain_reasons'],
        baseline_reproduced=True, dense_arrays_unchanged=True, input_files_unchanged=True,
        elapsed_seconds=time.perf_counter()-start)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('manifest', type=Path)
    p.add_argument('--baseline', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--partition', type=int)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    cv2.setNumThreads(2)
    for i, case in enumerate(json.loads(args.manifest.read_text())):
        if args.partition is not None and i % 2 != args.partition:
            continue
        target = args.output/(case['name']+'_validated.json')
        if target.exists():
            continue
        saved = json.loads((args.baseline/(case['name']+'_range.json')).read_text())
        row = evaluate(case, saved)
        target.write_text(json.dumps(row, indent=2, allow_nan=False))
        print(case['name'], row['recovery_accepted'], row['baseline_total_permille'], '->', row['total_permille'], row['reason'], flush=True)
        gc.collect()


if __name__ == '__main__':
    main()
