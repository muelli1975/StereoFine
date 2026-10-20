"""Offline cubic-field counterfactuals, preserving every production file.

Manifest: [{name, left, right, state, points}], with a private saved raw-match
NPZ (left/right/mask) and full PairState diagnostic JSON. Optional --render
checks final native-resolution rasters with separate spatial LK/NCC features.
The bounded candidate is experimental and is never applied by StereoFine.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stereofine.alignment import resize_pair_for_analysis, _analyze_matched_points, _assess_spatial_holdout
from stereofine.alignment_refinement import (refine_alignment, patch_correlations,
    corrected_point_residuals, point_quality)
from stereofine.geometry import apply_orientation
from stereofine.lens_refinement import refine_residual_field, cubic_design, TERMS
import stereofine.lens_refinement as lens
from stereofine.render import render_final_pair
from stereofine.sources import load_source, source_from_pair
from stereofine.state import (PairState, AlignmentState, FramingState,
    InputTransformState, reproducible_alignment_correction)


def rendered_checks(left, right):
    h, w = left.shape[:2]
    scale = min(1., 1500/w)
    size = (round(w*scale), round(h*scale))
    a, b = [cv2.cvtColor(cv2.resize(im, size, interpolation=cv2.INTER_AREA), cv2.COLOR_RGB2GRAY)
            for im in (left, right)]
    features = []
    for iy in range(5):
        for ix in range(5):
            mask = np.zeros_like(a)
            mask[int(iy*size[1]/5):int((iy+1)*size[1]/5), int(ix*size[0]/5):int((ix+1)*size[0]/5)] = 255
            p = cv2.goodFeaturesToTrack(a, maxCorners=160, qualityLevel=.01, minDistance=5, blockSize=7, mask=mask)
            if p is not None:
                features.append(p)
    if not features:
        return {"points": 0}
    p = np.concatenate(features)
    options = dict(winSize=(31,31), maxLevel=4,
                   criteria=(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT,40,.001))
    q, status, error = cv2.calcOpticalFlowPyrLK(a, b, p, None, **options)
    back, status2, _ = cv2.calcOpticalFlowPyrLK(b, a, q, None, **options)
    p, q = p[:,0], q[:,0]
    good = status[:,0].astype(bool) & status2[:,0].astype(bool)
    good &= (error[:,0] < 10) & (np.linalg.norm(back[:,0]-p,axis=1)<.35)
    for points in (p,q):
        good &= (points[:,0]>16) & (points[:,0]<size[0]-16) & (points[:,1]>16) & (points[:,1]<size[1]-16)
    good &= patch_correlations(a,b,p,q)>=.90
    p,q = p[good],q[good]
    rows = []
    for label,x0,y0,fraction in [("all",0,0,1), ("TL20",0,0,.2), ("TR20",.8,0,.2),
                                 ("BL20",0,.8,.2),("BR20",.8,.8,.2),("BR10",.9,.9,.1)]:
        selected = (p[:,0]>=x0*size[0]) & (p[:,0]<(x0+fraction)*size[0]) & (p[:,1]>=y0*size[1]) & (p[:,1]<(y0+fraction)*size[1])
        dy = np.abs(q[selected,1]-p[selected,1])/scale
        rows.append(dict(region=label,count=int(selected.sum()),mean_px=float(dy.mean()) if len(dy) else None,
                         p95_px=float(np.percentile(dy,95)) if len(dy) else None))
    return rows


def audit(case, render=False):
    paths = {key: Path(case[key]).resolve() for key in ("left","right","state","points")}
    state = json.loads(paths["state"].read_text())
    loaded = load_source(source_from_pair(paths["left"],paths["right"],paths["left"].parent))
    t = state["input_transform"]
    left = apply_orientation(loaded.left,t["left_orientation"],t["left_mirror"])
    right = apply_orientation(loaded.right,t["right_orientation"],t["right_mirror"])
    if t["swap_eyes"]:
        left,right=right,left
    gl,gr,scale = resize_pair_for_analysis(left,right,3000)
    points = np.load(paths["points"])
    lp,rp,mask = points["left"],points["right"],points["mask"]
    method = state["alignment"]["method"]
    baseline = _analyze_matched_points(lp,rp,gl.shape,scale,method,inlier_mask=mask)
    baseline = refine_alignment(baseline,lp,rp,mask,gl,gr,scale,method)
    coefficients=[]
    original_fit=lens._weighted_lstsq
    def capture(matrix,target,weights):
        beta=original_fit(matrix,target,weights)
        coefficients.append(beta.copy())
        return beta
    with patch.object(lens,"_weighted_lstsq",side_effect=capture):
        production = refine_residual_field(deepcopy(baseline),lp,rp,gl,gr,scale)
    reproduced = reproducible_alignment_correction(production["correction"]) == reproducible_alignment_correction(state["alignment"]["correction"])
    if not reproduced:
        raise RuntimeError("Saved production correction not reproduced: "+case["name"])
    if not coefficients:
        return dict(name=case["name"],baseline_reproduced=True,
                    production=production["correction"]["lens_refinement_validation"],
                    note="Production guards rejected this case before a cubic fit; no field counterfactual.")
    h,w = gl.shape
    gx,gy = np.meshgrid(np.linspace(0,w-1,33),np.linspace(0,h-1,33))
    grid = np.column_stack((gx.ravel(),gy.ravel()))
    beta = coefficients[-1]
    raw_field = (cubic_design(grid,gl.shape)@beta).reshape(33,33)
    limit = min(24,.018*min(gl.shape))
    maximum = float(np.abs(raw_field).max())
    factor = min(1.,float(np.nextafter(limit/maximum,0))) if maximum>0 else 1.
    residual = corrected_point_residuals(baseline["correction"],lp,rp,gl.shape,scale)
    scores = patch_correlations(gl,gr,lp,rp)
    blocks = np.floor(lp/32).astype(np.int64)
    holdout = (blocks[:,0]*73856093+blocks[:,1]*19349663)%5==0
    good = (scores>=.9)&(np.abs(residual)<=6)
    order=np.flatnonzero(good&holdout)
    order=order[np.argsort(-scores[order],kind="stable")]
    _,unique=np.unique(np.floor(lp[order]/4).astype(np.int64),axis=0,return_index=True)
    check=order[np.sort(unique)]
    before,before_zones=point_quality(lp[check],residual[check],gl.shape,scale)
    result=dict(name=case["name"],baseline_reproduced=True,scale=scale,analysis_shape=gl.shape,
                inputs_sha256={k:hashlib.sha256(v.read_bytes()).hexdigest() for k,v in paths.items()},
                production=production["correction"]["lens_refinement_validation"],
                limit_analysis_px=limit,raw_max_analysis_px=maximum,
                maximum_grid_xy=grid[np.abs(raw_field).argmax()].tolist(),bounded_factor=factor,candidates=[])
    for label,f in [("unbounded_counterfactual",1.),("bounded_counterfactual",factor)]:
        correction=deepcopy(baseline["correction"])
        correction["y_residual_apply"]=dict(enabled=True,model_name="y_cubic",terms=TERMS.copy(),normalization={},
            coefficients=[dict(term=t,coefficient_fullres_px=float(v*f/scale)) for t,v in zip(TERMS,beta)],
            max_abs_correction_px=(1e6 if label.startswith("unbounded") else limit/scale),source="offline_diagnostic_only")
        after=corrected_point_residuals(correction,lp[check],rp[check],gl.shape,scale)
        quality,zones=point_quality(lp[check],after,gl.shape,scale)
        decision=_assess_spatial_holdout(before,quality,before_zones,zones,scale,region_quality_floor_analysis=(.5,1.5))
        regions=[]
        for name,x0,y0,frac in [("TL20",0,0,.2),("TR20",.8,0,.2),("BL20",0,.8,.2),("BR20",.8,.8,.2),("BR10",.9,.9,.1)]:
            inside=(lp[:,0]>=x0*w)&(lp[:,0]<(x0+frac)*w)&(lp[:,1]>=y0*h)&(lp[:,1]<(y0+frac)*h)
            selected=inside[check]
            b,a=np.abs(residual[check][selected]),np.abs(after[selected])
            passed=bool(a.mean()<=max(.5,b.mean()+.1) and np.percentile(a,90)<=max(1.5,np.percentile(b,90)+.1)) if len(a)>=6 else None
            regions.append(dict(region=name,raw=int(inside.sum()),photo_good=int((inside&good).sum()),
                ncc_only=int((inside&(scores>=.9)).sum()),
                train=int((inside&good&~holdout&(np.abs(residual)<=3)).sum()),check=int(selected.sum()),
                before_mean_px=float(b.mean()/scale) if len(b) else None,after_mean_px=float(a.mean()/scale) if len(a) else None,
                existing_corner_guard_passed=passed))
        field=raw_field*f
        row=dict(name=label,field_max_analysis_px=float(np.abs(field).max()),
                 gradient=float(max(np.abs(np.diff(field,axis=0)).max()/((h-1)/32),np.abs(np.diff(field,axis=1)).max()/((w-1)/32))),
                 baseline=before,quality=quality,decision=decision,regions=regions)
        if render and label.startswith("bounded"):
            renders={}
            for variant,c in [("rc3",production["correction"]),("bounded",correction)]:
                st=PairState(input_transform=InputTransformState(**t),alignment=AlignmentState(**state["alignment"]),framing=FramingState(**state["framing"]))
                st.alignment.correction=c
                a,b,_=render_final_pair(loaded,st,apply_color=False,apply_floating_window=False)
                renders[variant]=dict(shape=a.shape,checks=rendered_checks(a,b))
                del a,b
            row["renders_same_saved_framing"]=renders
        result["candidates"].append(row)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest",type=Path)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--render",action="store_true")
    args=parser.parse_args()
    cv2.setNumThreads(4)
    results=[]
    for case in json.loads(args.manifest.read_text()):
        result=audit(case,args.render)
        results.append(result)
        args.output.write_text(json.dumps(results,indent=2))
        print(result["name"],"reproduced",result["baseline_reproduced"],"raw field",result.get("raw_max_analysis_px"),
              "limit",result.get("limit_analysis_px"),"bounded factor",result.get("bounded_factor"),flush=True)


if __name__=="__main__":
    main()
