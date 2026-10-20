"""Frozen RC3 versus renderer-consistent quadratic model scoring.

No production mutation: patch only the candidate residual evaluator during each
counterfactual fit. Preserve all coefficient fits, model guards and source data.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
from pathlib import Path
import sys
from contextlib import ExitStack
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import stereofine.alignment as alignment
from experiments.applied_model_scoring import applied_candidate_residuals, legacy_candidate_residuals
from experiments.compare_native_subpixel import matches, fit
from experiments.compare_rectification import metrics, training_mask
from experiments.select_subpixel_candidate import select
from experiments.symmetric_quadratic_fit import refine_quadratic_candidate
from stereofine.alignment_refinement import corrected_point_residuals
from stereofine.geometry import apply_orientation
from stereofine.inputs import master_to_uint8
from stereofine.sources import load_source, source_from_pair
from stereofine.state import reproducible_alignment_correction

PROTOCOL = dict(version='applied-quadratic-score-1',
    change='quadratic complete-chain score evaluates the existing symmetric destination field at both eyes',
    unchanged='coefficient fitting, model terms, clipping, matching, inliers, model-selection and refinement guards',
    controls='frozen source controls confirmed at native resolution in native-subpixel-pilot-1',
    independence='blocked variant excludes reserved 128px blocks and 16px margins in both eyes',
    admission='same two-stage/pooled regional controls plus actual full-data RC3 veto',
    full_candidate='diagnostic only; training not spatially withheld from source controls')


def evaluate(case, output, native, refit=False):
    name=case['name']; method=name.rsplit('_',1)[1]
    saved=json.loads(Path(case['state']).read_text()); t=saved['input_transform']
    loaded=load_source(source_from_pair(Path(case['left']),Path(case['right']),Path(case['left']).parent))
    a=master_to_uint8(apply_orientation(loaded.left,t['left_orientation'],t['left_mirror']))
    b=master_to_uint8(apply_orientation(loaded.right,t['right_orientation'],t['right_mirror']))
    if t['swap_eyes']: a,b=b,a
    ga,gb,scale=alignment.resize_pair_for_analysis(a,b,3000)
    native_shape=a.shape[:2]
    del loaded,a,b
    p,q,mask,point_path=matches(case,ga,gb,native)
    with patch.object(alignment,'_candidate_vertical_residuals',legacy_candidate_residuals):
        original=fit(p,q,mask,ga,gb,scale,method)
    if reproducible_alignment_correction(original['correction']) != reproducible_alignment_correction(saved['alignment']['correction']):
        return dict(name=name,status='excluded_reference_not_reproduced')
    previous=json.loads((native/(name+'_native_corrections.json')).read_text())
    controls=np.load(native/(name+'_native_controls.npz'))
    audit=[]
    def measured(candidate,left,right,shape):
        before=legacy_candidate_residuals(candidate,left,right,shape)
        after=applied_candidate_residuals(candidate,left,right,shape)
        delta=np.abs(after-before)/scale
        audit.append(dict(points=len(left),mean_difference_native_px=float(delta.mean()),
                          p95_difference_native_px=float(np.percentile(delta,95)),
                          maximum_difference_native_px=float(delta.max())))
        return after
    legacy_fitter=alignment._fit_y_residual_candidate
    def symmetric_fitter(name,terms,left,right,residual,shape,scale,*,holdout_mask=None):
        candidate=legacy_fitter(name,terms,left,right,residual,shape,scale,holdout_mask=holdout_mask)
        return refine_quadratic_candidate(candidate,left,right,residual,shape,scale,holdout_mask)
    with ExitStack() as patches:
        patches.enter_context(patch.object(alignment,'_candidate_vertical_residuals',measured))
        if refit: patches.enter_context(patch.object(alignment,'_fit_y_residual_candidate',symmetric_fitter))
        full=fit(p,q,mask,ga,gb,scale,method)
        train=training_mask(p,q)
        blocked_mask=alignment._fit_vertical_ransac_filter(.5*(p[train]+q[train]),q[train],p[train],ga.shape)['mask']
        blocked=fit(p[train],q[train],blocked_mask,ga,gb,scale,method)
    corrections=dict(rc3=original['correction'],full_candidate=full['correction'],
                     blocked_baseline=previous['blocked_baseline'],blocked_candidate=blocked['correction'])
    cp,cq,split=controls['left'],controls['right'],controls['split']
    residuals={key:corrected_point_residuals(c,cp,cq,native_shape,1.) for key,c in corrections.items()}
    for key in ('rc3','blocked_baseline'):
        if not np.array_equal(residuals[key],controls[key]):
            raise RuntimeError('Frozen control reference changed: '+name+'/'+key)
    independent=select(cp,residuals['blocked_baseline'],residuals['blocked_candidate'],split,native_shape,scale)
    reference=select(cp,residuals['rc3'],residuals['blocked_candidate'],split,native_shape,scale)
    diagnostic=select(cp,residuals['rc3'],residuals['full_candidate'],split,native_shape,scale)
    protocol=dict(PROTOCOL)
    if refit:
        protocol.update(version='symmetric-quadratic-fit-1',
            change='existing quadratic fitted and scored at symmetric destination coordinates; two relinearizations',
            unchanged='model terms, clipping, matching, inliers, model-selection and refinement guards')
    row=dict(name=name,status='measured',protocol=protocol,reference_reproduced=True,
        analysis_scale=scale,native_shape=list(native_shape),analysis_shape=list(ga.shape),
        reserved_controls=len(cp),prediction_differences=audit,
        changed=reproducible_alignment_correction(original['correction'])!=reproducible_alignment_correction(full['correction']),
        metrics={k:metrics(cp,r,native_shape) for k,r in residuals.items()},
        models=dict(rc3=original['model'],full_candidate=full['model'],blocked_candidate=blocked['model']),
        independent_comparison=independent,full_reference_veto=reference,full_fit_diagnostic=diagnostic,
        admitted=independent['selected']=='subpixel' and reference['selected']=='subpixel')
    (output/(name+'_applied_corrections.json')).write_text(json.dumps(corrections,indent=2))
    np.savez_compressed(output/(name+'_applied_controls.npz'),left=cp,right=cq,split=split,**residuals)
    row['inputs_sha256']={}
    for key,path in dict(left=case['left'],right=case['right'],state=case['state'],points=point_path,
                         native_controls=native/(name+'_native_controls.npz')).items():
        with open(path,'rb') as f: row['inputs_sha256'][key]=hashlib.file_digest(f,'sha256').hexdigest()
    return row


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--native',type=Path,required=True)
    parser.add_argument('--names',nargs='*')
    parser.add_argument('--refit',action='store_true',help='Also fit the same quadratic at symmetric destination positions')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True);cv2.setNumThreads(4)
    for case in json.loads(args.manifest.read_text()):
        if args.names and case['name'].rsplit('_',1)[0] not in args.names: continue
        path=args.output/(case['name']+'_applied.json')
        if path.exists():
            previous=json.loads(path.read_text())
            expected='symmetric-quadratic-fit-1' if args.refit else PROTOCOL['version']
            if previous.get('protocol',{}).get('version') not in (None,expected):
                raise ValueError('Output directory contains a different experiment: '+str(path))
            if previous['status']=='measured':continue
        row=evaluate(case,args.output,args.native,args.refit)
        path.write_text(json.dumps(row,indent=2,allow_nan=False))
        print(case['name'],row['status'],'changed',row.get('changed'),
              {k:round(v['all']['p95_px'],4) for k,v in row.get('metrics',{}).items()},
              'admitted',row.get('admitted'),flush=True)
        gc.collect()


if __name__=='__main__':main()
