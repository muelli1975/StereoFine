"""Public numeric audit of native-confirmed near recovery; no coordinates."""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def compact(value):
    return {k:value[k] for k in ('confirmed','unsupported_extreme','edge_permille',
        'maximum_supported_px','supported_points','probed_points','baseline_percentile_permille','method')}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest',type=Path);parser.add_argument('--results',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();cases=json.loads(args.manifest.read_text())
    names=[c['name'] for c in cases]
    if not names or len(names)!=len(set(names)):raise ValueError('Unique manifest cases required')
    rows=[];frames=[]
    for name in names:
        path=args.results/(name+'_native_near.json');d=json.loads(path.read_text())
        if (d['name']!=name or d['status']!='measured' or not d['reference_reproduced']
                or not d['integrated_path_verified']):raise ValueError('Incomplete integrated reference: '+name)
        row={k:d[k] for k in ('name','reference_reproduced','integrated_path_verified','analysis_shape',
            'native_shape','audit','unchanged','baseline_uncertain_reasons','candidate_uncertain_reasons',
            'baseline_edge_permille','candidate_edge_permille','inputs_sha256')}
        row['baseline']=compact(d['baseline']);row['candidate']=compact(d['candidate'])
        row['private_audit_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
        rows.append(row)
        if d['audit']['accepted']:
            frame=json.loads((args.results/(name+'_native_near_framing.json')).read_text())
            if frame['status']!='verified' or not frame['sidecar_native_pixels_identical']:
                raise ValueError('Missing native framing/persistence check: '+name)
            frames.append(frame)
    module=Path(__file__).resolve().parents[1]/'stereofine/near_point_recovery.py'
    result=dict(scope='Integrated native near recovery; unchanged alignment and published packages',
        recovery_source_sha256=hashlib.sha256(module.read_bytes()).hexdigest(),
        summary=dict(cases=len(rows),pairs=len({n.rsplit('_',1)[0] for n in names}),
            exact_references_reproduced=sum(d['reference_reproduced'] for d in rows),
            already_confirmed_unchanged=sum(d['audit']['reason']=='already_confirmed' and d['unchanged'] for d in rows),
            recovered=sum(d['audit']['accepted'] for d in rows),
            rejected_unconfirmed=sum(not d['audit']['accepted'] and d['audit']['reason']!='already_confirmed' for d in rows),
            decisions=dict(Counter(d['audit']['reason'] for d in rows))),
        cases=rows,native_framing_and_sidecar_checks=frames)
    args.output.write_text(json.dumps(result,separators=(',',':'),allow_nan=False)+'\n')
    print(json.dumps(result['summary'],indent=2))


if __name__=='__main__':main()
