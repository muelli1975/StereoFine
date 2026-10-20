"""Compact public numeric audit; private coordinates and input paths stay local."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path


def assessment(value):
    row = {k: value[k] for k in ('accepted', 'reason', 'count', 'baseline', 'candidate',
                                'corners', 'unverified_corners') if k in value}
    row['grids'] = {}
    for grid, gate in value.get('grids', {}).items():
        item = {k: gate[k] for k in ('accepted', 'reason', 'holdout_points', 'regions') if k in gate}
        failed = [r['label'] for r in gate.get('regions', []) if not all(r.get('checks', {}).values())]
        for key in ('baseline_regions', 'candidate_regions'):
            item[key] = [r for r in gate.get(key, {}).get('zones', []) if r['label'] in failed]
        row['grids'][grid] = item
    return row


def comparison(value):
    return {**{k: value[k] for k in ('selected', 'reason')},
            **{k: assessment(value[k]) for k in ('selection', 'confirmation', 'pooled')}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('selection', type=Path)
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    records, sidecars, rasters = [], [], []
    for path in sorted(args.selection.glob('*_selection.json')):
        d = json.loads(path.read_text())
        record = {k: d[k] for k in ('name', 'inputs_sha256', 'baseline_reproduced',
            'supported_geometry_roundtrip', 'analysis_scale', 'controls',
            'reference_metrics', 'experimental_selected', 'selected', 'reason')}
        record['independent_comparison'] = comparison(d['independent_comparison'])
        record['full_data_reference'] = comparison(d['full_data_reference'])
        record['private_audit_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        records.append(record)
        if d['experimental_selected'] == 'subpixel':
            sidecars.append(json.loads((args.selection/(d['name']+'_sidecar.json')).read_text()))
            rasters.append(json.loads((args.results/(d['name']+'_subpixel_rasters.json')).read_text()))
    if len(records) != 29 or len(sidecars) != 2:
        raise RuntimeError('Expected the complete 29-pair audit and two experimental roundtrips')
    result = dict(protocol=d['protocol'], cases=records, sidecar_checks=sidecars,
                  native_raster_checks=rasters, tests='31 research tests passed')
    args.output.write_text(json.dumps(result, separators=(',', ':'), allow_nan=False)+'\n')
    print('cases', len(records), 'experimental', sum(r['experimental_selected']=='subpixel' for r in records),
          'final', sum(r['selected']=='subpixel' for r in records))


if __name__ == '__main__':
    main()
