"""Publish numeric research evidence, excluding private paths and corrections."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re


PILOT = {
    's110_bild005', 's110_bild026', 's110_bild090', 'ixus_bild008',
    's95_bild038', 's95_bild067', 'nx1000_bild033', 'nx1000_bild045',
}


def stage_summary(stage):
    result = {key: stage[key] for key in ('accepted', 'reason', 'count', 'baseline', 'candidate', 'unverified_corners')}
    regressions = []
    for grid, gate in stage['grids'].items():
        before = {r['label']: r for r in gate['baseline_regions']['zones']}
        after = {r['label']: r for r in gate['candidate_regions']['zones']}
        for r in gate['regions']:
            if not all(r['checks'].values()):
                regressions.append(dict(grid=int(grid), cell=r['label'], count=r['count'],
                    baseline=before[r['label']], candidate=after[r['label']]))
    result['first_regression_per_grid'] = regressions
    result['corner_regressions'] = [r for r in stage['corners'] if r['passed'] is False]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('selection', type=Path)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--guard-sensitivity', type=Path)
    args = parser.parse_args()
    expected = {r['name'].rsplit('_', 1)[0] for r in json.loads(args.manifest.read_text()) if r['name'].endswith('_SIFT')}
    records = [json.loads(p.read_text()) for p in sorted(args.selection.glob('*_selection.json'))]
    if len(records) != len(expected) or {r['name'] for r in records} != expected:
        raise RuntimeError('Incomplete or mismatched evaluation; no public summary written')
    if not records:
        raise RuntimeError('Empty manifest')
    protocol = records[0]['protocol']
    rows = []
    for r in records:
        if r['protocol'] != protocol or not re.fullmatch(r'[a-z0-9]+_bild[0-9]+', r['name']):
            raise RuntimeError('Unexpected protocol or non-public case identifier')
        row = {key: r[key] for key in ('name', 'raw_points', 'analysis_scale', 'all_points', 'selected')}
        row['cohort'] = 'original_eight' if r['name'] in PILOT else 'additional_21'
        row.update({stage: stage_summary(r[stage]) for stage in ('selection', 'confirmation')})
        render = args.selection/(r['name']+'_rendered.json')
        if render.exists():
            row['raster_check'] = json.loads(render.read_text())
        rows.append(row)
    result = dict(protocol=protocol, reference='RC3 SIFT; original geometry and near-point code',
        counts=dict(pairs=len(rows), original_eight=sum(r['cohort']=='original_eight' for r in rows),
            additional=sum(r['cohort']=='additional_21' for r in rows),
            admitted=sum(r['selected']=='lightglue_aliked' for r in rows),
            baseline_retained=sum(r['selected']=='baseline' for r in rows),
            raster_pairs=sum('raster_check' in r for r in rows)),
        limitations=['LK/NCC correspondences are not measured ground truth',
            'Confirmation blocks do not tune or train the selector; saved geometry fits did not exclude those blocks',
            'Sparse corners are unverified, including for admitted candidates',
            'Raster probes may differ after changed crop; source checks use identical identities',
            'Twenty-one new neural comparisons share the existing four rigs, not an external camera holdout',
            'No GPU benchmark and no comparison runs of Cosima or StereoPhoto Maker'], cases=rows)
    if args.guard_sensitivity:
        sensitivity = json.loads(args.guard_sensitivity.read_text())
        if ({r['name'] for r in sensitivity['cases']} != expected
                or sensitivity['strict_results_reproduced'] != len(rows)):
            raise RuntimeError('Sensitivity results do not match the completed corpus')
        result['guard_sensitivity'] = sensitivity
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')
    print(json.dumps(result['counts']))


if __name__ == '__main__':
    main()
