"""Compare same-point native near recovery with exact saved RC3 diagnostics.

Private images and state files remain read-only. No user sidecar is written.
"""
from __future__ import annotations
import argparse
import gc
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import patch

import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from stereofine.near_point_recovery import recover_near_edge
from stereofine.disparity import (analyze_horizontal_disparity,_resize_pair_for_disparity,
    _rgb_to_luma_uint8,render_pair_for_disparity_analysis_from_arrays)
from stereofine.geometry import apply_orientation
from stereofine.inputs import master_to_uint8
from stereofine.sources import load_source,source_from_pair


def evaluate(case,output):
    saved=json.loads(Path(case['state']).read_text());t=saved['input_transform']
    loaded=load_source(source_from_pair(Path(case['left']),Path(case['right']),Path(case['left']).parent))
    a=master_to_uint8(apply_orientation(loaded.left,t['left_orientation'],t['left_mirror']))
    b=master_to_uint8(apply_orientation(loaded.right,t['right_orientation'],t['right_mirror']))
    if t['swap_eyes']:a,b=b,a
    a,b=render_pair_for_disparity_analysis_from_arrays(a,b,saved['alignment']['correction'])
    del loaded
    # Reproduce the saved pre-recovery reference with the old confirmation
    # path; then run the real current production path below.
    with patch('stereofine.near_point_recovery.recover_near_edge',
               side_effect=lambda l,r,d,c,base,*native:(base,{})):
        result=analyze_horizontal_disparity(a,b,1500)
    reference=result['near_confirmation']
    if (reference!=saved['disparity']['diagnostics']['near_confirmation']
            or result['uncertain_reasons']!=saved['disparity']['uncertain_reasons']
            or abs(result['high_edge_permille']-saved['disparity']['high_edge_permille'])>1e-6):
        return dict(name=case['name'],status='excluded_reference_not_reproduced')
    small_a,small_b,_=_resize_pair_for_disparity(a,b,1500)
    small_a,small_b=[_rgb_to_luma_uint8(x) for x in (small_a,small_b)]
    disparity=result['_disp_permille']*small_a.shape[1]/1000.
    candidate,audit=recover_near_edge(small_a,small_b,disparity,result['_confidence_mask'],reference,a,b)
    proposed=result
    if not reference['confirmed']:
        proposed=analyze_horizontal_disparity(a,b,1500)
        if proposed['near_confirmation']!=candidate:
            raise RuntimeError('Integrated recovery differs from the measured candidate')
        if (not np.array_equal(result['_disp_permille'],proposed['_disp_permille'])
                or not np.array_equal(result['_confidence_mask'],proposed['_confidence_mask'])):
            raise RuntimeError('Dense measurements changed between comparisons')
    row=dict(name=case['name'],status='measured',reference_reproduced=True,integrated_path_verified=True,
        analysis_shape=list(small_a.shape),native_shape=list(a.shape[:2]),audit=audit,
        baseline=reference,candidate=candidate,unchanged=candidate is reference,
        baseline_uncertain_reasons=result['uncertain_reasons'],candidate_uncertain_reasons=proposed['uncertain_reasons'],
        baseline_edge_permille=result['high_edge_permille'],candidate_edge_permille=proposed['high_edge_permille'])
    row['inputs_sha256']={}
    for key in ('left','right','state'):
        with open(case[key],'rb') as f:row['inputs_sha256'][key]=hashlib.file_digest(f,'sha256').hexdigest()
    return row


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest',type=Path);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--names',nargs='*')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True);cv2.setNumThreads(4)
    for case in json.loads(args.manifest.read_text()):
        if args.names and case['name'].rsplit('_',1)[0] not in args.names:continue
        dest=args.output/(case['name']+'_native_near.json')
        if dest.exists():
            previous=json.loads(dest.read_text())
            if previous['status']=='measured' and previous.get('integrated_path_verified'):continue
        row=evaluate(case,args.output);dest.write_text(json.dumps(row,indent=2,allow_nan=False))
        print(case['name'],row['status'],'accepted',row.get('audit',{}).get('accepted'),
            'reason',row.get('audit',{}).get('reason'),'edge',row.get('baseline_edge_permille'),
            '->',row.get('candidate_edge_permille'),'uncertain',row.get('candidate_uncertain_reasons'),flush=True)
        gc.collect()


if __name__=='__main__':main()
