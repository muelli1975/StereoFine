"""Compact public evidence for a scoring fix and a rejected fitting proposal."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from experiments.summarize_native_subpixel import comparison


def load_cases(manifest,folder):
    names=[c['name'] for c in json.loads(manifest.read_text())]
    if not names or len(names)!=len(set(names)):raise ValueError('Unique cases required')
    rows=[]
    for name in names:
        path=folder/(name+'_applied.json')
        d=json.loads(path.read_text())
        if d['name']!=name or d['status']!='measured' or not d['reference_reproduced']:
            raise ValueError('Missing exact reference: '+name)
        row={k:d[k] for k in ('name','reference_reproduced','analysis_scale','native_shape',
             'analysis_shape','reserved_controls','models','changed','admitted','inputs_sha256')}
        row['private_audit_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
        row['prediction_differences']=d['prediction_differences']
        row['global_metrics']={k:v['all'] for k,v in d['metrics'].items()}
        for k in ('independent_comparison','full_reference_veto','full_fit_diagnostic'):
            row[k]=comparison(d[k])
        rows.append(row)
    return dict(protocol=d['protocol'],cases=rows,
        summary=dict(cases=len(rows),references_reproduced=len(rows),
            changed_geometry=sum(d['changed'] for d in rows),admitted=sum(d['admitted'] for d in rows),
            lower_full_fit_p95=sum(d['global_metrics']['full_candidate']['p95_px']<d['global_metrics']['rc3']['p95_px'] for d in rows),
            higher_full_fit_p95=sum(d['global_metrics']['full_candidate']['p95_px']>d['global_metrics']['rc3']['p95_px'] for d in rows),
            independent_comparison_passed=sum(d['independent_comparison']['selected']=='subpixel' for d in rows)))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest',type=Path)
    parser.add_argument('--scoring',type=Path,required=True)
    parser.add_argument('--refit',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    scoring=load_cases(args.manifest,args.scoring);refit=load_cases(args.manifest,args.refit)
    rasters=[json.loads(p.read_text()) for p in sorted(args.scoring.glob('*_applied_rasters.json'))]
    for row in rasters:
        if row['variants']['rc3']['native_raster']!=row['variants']['full_candidate']['native_raster']:
            raise ValueError('Unexpected native raster change')
        if not row['variants']['full_candidate']['native_pixels_identical']:
            raise ValueError('Sidecar roundtrip failed')
    result=dict(integrated='renderer-consistent quadratic complete-chain scoring only; sf-align-5',
        experimental='symmetric quadratic coefficient refit; not admitted',
        scoring=scoring,symmetric_refit=refit,native_raster_and_sidecar_checks=rasters)
    args.output.write_text(json.dumps(result,separators=(',',':'),allow_nan=False)+'\n')
    print(json.dumps(dict(scoring=scoring['summary'],refit=refit['summary'],native_roundtrips=len(rasters)),indent=2))


if __name__=='__main__':main()
