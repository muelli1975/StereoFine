"""Publish compact numeric evidence without private images, paths or coordinates."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

def comparison(value):
    result = {k:value[k] for k in ('selected', 'reason')}
    for stage in ('selection', 'confirmation', 'pooled'):
        assessment = value[stage]
        row = {k:assessment[k] for k in ('accepted', 'reason', 'count')}
        row['unverified_corners'] = assessment.get('unverified_corners', [])
        row['supported_corners'] = [c for c in assessment.get('corners', []) if c['passed'] is not None]
        row['failed_regions'] = []
        for grid,gate in assessment.get('grids', {}).items():
            for region in gate.get('regions', []):
                if all(region.get('checks', {}).values()):
                    continue
                failure = dict(grid=grid, **region)
                for key in ('baseline_regions', 'candidate_regions'):
                    failure[key] = next((z for z in gate.get(key, {}).get('zones', [])
                                         if z['label']==region['label']), None)
                row['failed_regions'].append(failure)
        result[stage] = row
    return result


def load_complete(manifest, folder, suffix):
    cases = json.loads(manifest.read_text())
    names = [case['name'] for case in cases]
    if len(set(names)) != len(names) or not names:
        raise ValueError('Manifest must contain unique cases')
    records = []
    for name in names:
        path = folder/(name+suffix+'.json')
        row = json.loads(path.read_text())
        if row['name'] != name or row['status'] != 'measured' or not row['reference_reproduced']:
            raise ValueError('Incomplete or nonreproduced reference: '+name)
        row = dict(row, private_audit_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        records.append(row)
    return records


def summarize(manifest, native_dir, bounded_dir):
    native = load_complete(manifest, native_dir, '_native')
    bounded = load_complete(manifest, bounded_dir, '_bounded')
    records = []
    for d in native:
        r = {k:d[k] for k in ('name', 'inputs_sha256', 'private_audit_sha256',
             'reference_reproduced', 'native_shape', 'analysis_shape', 'analysis_scale',
             'raw_matches', 'training_matches', 'reserved_controls', 'native_measurement',
             'native_control_measurement', 'models', 'admitted')}
        r['metrics'] = {key:{region:value for region,value in regions.items()
                            if region in ('all', 'TL20', 'TR20', 'BL20', 'BR20', 'BR10')}
                        for key,regions in d['metrics'].items()}
        for key in ('native_measurement', 'native_control_measurement'):
            r[key] = {k:v for k,v in r[key].items() if k != 'protocol'}
        for key in ('independent_comparison', 'full_reference_veto', 'full_fit_diagnostic'):
            r[key] = comparison(d[key])
        records.append(r)
    fields = []
    for d in bounded:
        r = {k:d[k] for k in ('name', 'inputs_sha256', 'private_audit_sha256',
            'reference_reproduced', 'changed', 'proposed_function_sha256', 'analysis_scale')}
        for key in ('original_audit', 'candidate_audit'):
            r[key] = {k:v for k,v in d[key].items() if k != 'design'}
        if d['changed']:
            r.update(native_controls=d['native_controls'], native_rc3=d['native_rc3'],
                     native_candidate=d['native_candidate'],
                     independent_native_gate=comparison(d['independent_native_gate']))
        fields.append(r)
    rasters = []
    for folder,kind in ((native_dir, 'native'), (bounded_dir, 'bounded')):
        for path in sorted(folder.glob('*_'+kind+'_rasters.json')):
            row = json.loads(path.read_text())
            if row['name'] not in {d['name'] for d in native}:
                raise ValueError('Raster case outside the manifest')
            rasters.append(row)
    return dict(
        protocol=native[0]['protocol'],
        scope='Research only; no application algorithm, schema, pipeline version or release asset changed',
        summary=dict(cases=len(native), pairs=len({d['name'].rsplit('_',1)[0] for d in native}),
            full_reference_reproduced=sum(d['reference_reproduced'] for d in native),
            full_fit_lower_p95=sum(d['metrics']['full_candidate']['all']['p95_px'] <
                                  d['metrics']['rc3']['all']['p95_px'] for d in native),
            independent_stages_passed=sum(d['independent_comparison']['selected']=='subpixel' for d in native),
            admitted=sum(d['admitted'] for d in native),
            full_fit_diagnostic_passed=sum(d['full_fit_diagnostic']['selected']=='subpixel' for d in native),
            independent_failure_reasons=dict(Counter(d['independent_comparison']['reason'] for d in native)),
            changed_bounded_candidates=sum(d['changed'] for d in bounded),
            admitted_bounded_candidates=sum(d.get('independent_native_gate',{}).get('selected')=='subpixel' for d in bounded)),
        native_cases=records, bounded_cases=fields, raster_and_sidecar_checks=rasters)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--native', type=Path, required=True)
    parser.add_argument('--bounded', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = summarize(args.manifest, args.native, args.bounded)
    args.output.write_text(json.dumps(result, separators=(',', ':'), allow_nan=False)+'\n')
    print(json.dumps(result['summary'], indent=2))


if __name__ == '__main__':
    main()
