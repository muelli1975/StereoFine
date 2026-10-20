"""Counterfactual: constrain the existing cubic fit before unchanged guards.

The application source is not modified. The original function is cloned with
one asserted replacement; recorded source hashes make the proposal reviewable.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
import gc
import hashlib
import inspect
import json
from pathlib import Path
import sys
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from experiments.compare_native_subpixel import matches
from experiments.compare_rectification import metrics
from experiments.select_neural_candidate import control_points
from experiments.select_subpixel_candidate import select
from stereofine.alignment import _analyze_matched_points, resize_pair_for_analysis
from stereofine.alignment_refinement import refine_alignment, corrected_point_residuals
from stereofine.geometry import apply_orientation
from stereofine.inputs import master_to_uint8
import stereofine.lens_refinement as lens
from stereofine.sources import source_from_pair, load_source
from stereofine.state import reproducible_alignment_correction
from experiments.native_subpixel import map_pixel_centers, refine_native_correspondences

ORIGINAL = '''    if not np.isfinite(field).all() or np.abs(field).max() > limit:
        audit["reason"] = "field_limit"
        return baseline, audit
'''
PROPOSED = '''    if not np.isfinite(field).all():
        audit["reason"] = "field_limit"
        return baseline, audit
    raw_peak = float(np.abs(field).max())
    factor = 1.0
    if raw_peak > limit:
        factor = (limit / raw_peak) * (1.0 - 8 * np.finfo(float).eps)
        beta = beta * factor
        field = cubic_design(grid, shape) @ beta
    audit.update(raw_max_field_analysis_px=raw_peak,
                 field_scale_factor=float(factor),
                 max_field_analysis_px=float(np.abs(field).max()))
    if not np.isfinite(field).all() or np.abs(field).max() > limit:
        audit["reason"] = "field_limit"
        return baseline, audit
'''


def bounded_candidate():
    source = inspect.getsource(lens._candidate)
    if source.count(ORIGINAL) != 1:
        raise RuntimeError('RC3 source changed; review the proposal before running it')
    namespace = dict(vars(lens))
    proposed = source.replace(ORIGINAL, PROPOSED)
    exec(compile(proposed, '<bounded-field-proposal>', 'exec'), namespace)
    return namespace['_candidate'], hashlib.sha256(proposed.encode()).hexdigest()


def evaluate(case, output, caches):
    sd = json.loads(Path(case['state']).read_text())
    t = sd['input_transform']; method = case['name'].rsplit('_',1)[1]
    loaded = load_source(source_from_pair(Path(case['left']),Path(case['right']),Path(case['left']).parent))
    a = master_to_uint8(apply_orientation(loaded.left,t['left_orientation'],t['left_mirror']))
    b = master_to_uint8(apply_orientation(loaded.right,t['right_orientation'],t['right_mirror']))
    if t['swap_eyes']: a,b=b,a
    ga,gb,scale=resize_pair_for_analysis(a,b,3000)
    na,nb=[np.asarray(Image.fromarray(im).convert('L'),np.uint8) for im in (a,b)]
    del loaded,a,b
    p,q,mask,point_path=matches(case,ga,gb,caches)
    base=_analyze_matched_points(p,q,ga.shape,scale,method,inlier_mask=mask)
    base=refine_alignment(base,p,q,mask,ga,gb,scale,method)
    rc3=lens.refine_residual_field(deepcopy(base),p,q,ga,gb,scale)
    if reproducible_alignment_correction(rc3['correction']) != reproducible_alignment_correction(sd['alignment']['correction']):
        return dict(name=case['name'],status='excluded_reference_not_reproduced')
    replacement,source_hash=bounded_candidate()
    with patch.object(lens,'_candidate',replacement):
        candidate=lens.refine_residual_field(deepcopy(base),p,q,ga,gb,scale)
    audit=candidate['correction']['lens_refinement_validation']
    changed=(reproducible_alignment_correction(candidate['correction']) != reproducible_alignment_correction(rc3['correction']))
    result=dict(name=case['name'],status='measured',reference_reproduced=True,changed=changed,
        analysis_scale=scale,analysis_shape=list(ga.shape),native_shape=list(na.shape),
        proposed_function_sha256=source_hash,original_audit=rc3['correction']['lens_refinement_validation'],candidate_audit=audit)
    if changed:
        cp,cq,_=control_points(ga,gb)
        cpn,cqn=[map_pixel_centers(x,ga.shape,na.shape) for x in (cp,cq)]
        measured,valid,control_audit=refine_native_correspondences(na,nb,cpn,cqn)
        cp,cpn,cqn=cp[valid],cpn[valid],measured[valid]
        # These 32px blocks are excluded from the existing cubic coefficient fit.
        blocks=np.floor(cp/32).astype(np.int64)
        codes=(blocks[:,0]*73856093+blocks[:,1]*19349663)%10
        keep=np.isin(codes,[0,5]); split=(codes[keep]==5).astype(int)
        cpn,cqn=cpn[keep],cqn[keep]
        before=corrected_point_residuals(rc3['correction'],cpn,cqn,na.shape,1.)
        after=corrected_point_residuals(candidate['correction'],cpn,cqn,na.shape,1.)
        result.update(native_controls=len(cpn),control_audit=control_audit,
            native_rc3=metrics(cpn,before,na.shape),native_candidate=metrics(cpn,after,na.shape),
            independent_native_gate=select(cpn,before,after,split,na.shape,scale))
        (output/(case['name']+'_bounded_corrections.json')).write_text(json.dumps(
            dict(rc3=rc3['correction'],bounded=candidate['correction']),indent=2))
        np.savez_compressed(output/(case['name']+'_bounded_controls.npz'),left=cpn,right=cqn,split=split,before=before,after=after)
    result['inputs_sha256']={}
    for key,path in dict(left=case['left'],right=case['right'],state=case['state'],points=point_path).items():
        with open(path,'rb') as f:result['inputs_sha256'][key]=hashlib.file_digest(f,'sha256').hexdigest()
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--caches',type=Path,required=True)
    args=parser.parse_args();cv2.setNumThreads(2);args.output.mkdir(parents=True,exist_ok=True)
    for case in json.loads(args.manifest.read_text()):
        path=args.output/(case['name']+'_bounded.json')
        if path.exists() and json.loads(path.read_text()).get('status') == 'measured':continue
        d=evaluate(case,args.output,args.caches)
        path.write_text(json.dumps(d,indent=2,allow_nan=False))
        print(case['name'],d['status'],'changed',d.get('changed'),'factor',d.get('candidate_audit',{}).get('field_scale_factor'),'native_gate',d.get('independent_native_gate',{}).get('reason'),flush=True)
        gc.collect()


if __name__=='__main__':main()
