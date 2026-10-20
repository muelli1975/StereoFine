"""Two-stage external selection of the single frozen classical subpixel candidate.

Reuses saved fits, then remeasures source controls and reproduces the earlier
numeric baseline. Both control stages occupy blocks excluded from every fit.
No application imports, pipeline changes, image writes or model downloads.
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
from experiments.compare_rectification import metrics, withheld
from experiments.select_neural_candidate import assess_measurements, control_points
from stereofine.alignment_refinement import corrected_point_residuals
from stereofine.geometry import apply_orientation
from stereofine.sources import load_source, source_from_pair
from stereofine.state import reproducible_alignment_correction

PROTOCOL = dict(version='subpixel-external-selector-2', candidate='subpixel-block-pilot-1 only',
    fitting='unchanged saved fits trained outside all reserved 128px blocks plus 16px margins',
    selection='reserved block hash modulo 10 equals 0',
    confirmation='reserved block hash modulo 10 equals 5; can only veto, no refit',
    gate='unchanged strict RC3 gain + regional checks on 3x3 AND 5x5, no quality ceiling relaxation',
    pooled='additional veto over the union; prevents split from hiding regional loss',
    sparse_corners='explicitly unverified, never count as checked; production admission not established',
    persistence='serialized supported correction payload must reproduce control residuals exactly',
    reference_veto='candidate must also improve actual saved full-data RC3 reference; conservative veto only, not an independent baseline fit')


def confirmation_split(points):
    blocks = np.floor(np.asarray(points)/128).astype(np.int64)
    code = (blocks[:, 0]*73856093+blocks[:, 1]*19349663) % 10
    if not np.isin(code, [0, 5]).all():
        raise ValueError('Controls must belong to reserved blocks')
    return (code == 5).astype(np.int64)


def select(points, before, after, split, shape, scale):
    split = np.asarray(split)
    if split.shape != (len(points),) or not np.isin(split, [0, 1]).all():
        return dict(selected='baseline', reason='invalid_split', selection=None, confirmation=None, pooled=None)
    stages = []
    for fold in (0, 1):
        keep = split == fold
        stages.append(assess_measurements(points[keep], before[keep], after[keep], shape, scale))
    pooled = assess_measurements(points, before, after, shape, scale)
    admitted = all(s['accepted'] for s in stages) and pooled['accepted']
    failures = [s['reason'] for s in [*stages, pooled] if not s['accepted']]
    return dict(selected='subpixel' if admitted else 'baseline',
        reason='independent_stages_and_pooled_guard_passed' if admitted else failures[0],
        selection=stages[0], confirmation=stages[1], pooled=pooled)


def apply_reference_veto(decision, points, reference, candidate, split, shape, scale):
    reference_decision = select(points, reference, candidate, split, shape, scale)
    admitted = decision['selected'] == 'subpixel' and reference_decision['selected'] == 'subpixel'
    return dict(experimental_selected=decision['selected'],
        selected='subpixel' if admitted else 'baseline',
        independent_comparison=decision, full_data_reference=reference_decision,
        reason=decision['reason'] if decision['selected'] != 'subpixel' else (
            'independent_and_actual_reference_passed' if admitted else 'actual_rc3_reference_not_improved'))


def evaluate(case, results, output):
    name = case['name'].removesuffix('_SIFT')
    previous = json.loads((results/(name+'_subpixel.json')).read_text())
    corrections = json.loads((results/(name+'_subpixel_corrections.json')).read_text())
    sd = json.loads(Path(case['state']).read_text())
    t = sd['input_transform']
    loaded = load_source(source_from_pair(Path(case['left']), Path(case['right']), Path(case['left']).parent))
    a = apply_orientation(loaded.left, t['left_orientation'], t['left_mirror'])
    b = apply_orientation(loaded.right, t['right_orientation'], t['right_mirror'])
    if t['swap_eyes']:
        a, b = b, a
    from stereofine.alignment import resize_pair_for_analysis
    ga, gb, scale = resize_pair_for_analysis(a, b, 3000)
    cp, cq, _ = control_points(ga, gb)
    keep = withheld(cp)
    cp, cq = cp[keep].astype(float), cq[keep].astype(float)
    split = confirmation_split(cp)
    values = {}
    roundtrips = {}
    for variant, correction in corrections.items():
        residual = corrected_point_residuals(correction, cp, cq, ga.shape, scale)/scale
        if metrics(cp, residual, ga.shape) != previous['variants'][variant]['metrics']:
            raise RuntimeError('Earlier independent metrics do not reproduce: '+name+'/'+variant)
        # Emulate the actual supported-parameter serializer, not a raw dict dump.
        restored = json.loads(json.dumps(reproducible_alignment_correction(correction)))
        remeasured = corrected_point_residuals(restored, cp, cq, ga.shape, scale)/scale
        if not np.array_equal(residual, remeasured):
            raise RuntimeError('Supported correction payload loses applied geometry')
        roundtrips[variant] = True
        values[variant] = residual
    reference = corrected_point_residuals(sd['alignment']['correction'], cp, cq, ga.shape, scale)/scale
    comparison = select(cp, values['baseline'], values['subpixel'], split, ga.shape, scale)
    row = dict(name=name, protocol=PROTOCOL, inputs_sha256=previous['inputs_sha256'],
        baseline_reproduced=True, supported_geometry_roundtrip=roundtrips,
        analysis_scale=scale, controls=len(cp),
        reference_metrics=metrics(cp, reference, ga.shape),
        **apply_reference_veto(comparison, cp, reference, values['subpixel'], split, ga.shape, scale))
    np.savez_compressed(output/(name+'_controls.npz'), left=cp, right=cq, split=split,
                        before=values['baseline'], after=values['subpixel'], full_data_reference=reference)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    cv2.setNumThreads(4)
    args.output.mkdir(parents=True, exist_ok=True)
    for case in json.loads(args.manifest.read_text()):
        if not case['name'].endswith('_SIFT'):
            continue
        name = case['name'].removesuffix('_SIFT')
        destination = args.output/(name+'_selection.json')
        if destination.exists():
            continue
        row = evaluate(case, args.results, args.output)
        destination.write_text(json.dumps(row, indent=2, allow_nan=False))
        print(name, row['selected'], row['reason'], 'selection', row['independent_comparison']['selection']['reason'],
              'confirmation', row['independent_comparison']['confirmation']['reason'], flush=True)
        gc.collect()


if __name__ == '__main__':
    main()
