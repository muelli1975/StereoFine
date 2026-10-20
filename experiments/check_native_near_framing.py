"""Check recovered near points in final native pixels and real temporary sidecars."""
from __future__ import annotations
import argparse
import gc
import hashlib
import json
from pathlib import Path
import sys
import tempfile

import cv2

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from stereofine.disparity import analyze_horizontal_disparity,render_pair_for_disparity_analysis_from_arrays
from stereofine.geometry import apply_orientation
from stereofine.inputs import master_to_uint8
from stereofine.near_point_recovery import native_patch_checks
from stereofine.processing import _store_disparity_result,_disparity_basis
from stereofine.render import render_final_pair
from stereofine.sidecar import load_sidecar,save_sidecar,source_stamp_to_dict,SidecarStatus
from stereofine.sources import source_from_pair,load_source,build_source_stamp
from stereofine.state import PairState,InputTransformState,AlignmentState,FramingState


def digest(left,right):
    return dict(shape=list(left.shape),dtype=str(left.dtype),
        left_sha256=hashlib.sha256(left.tobytes()).hexdigest(),right_sha256=hashlib.sha256(right.tobytes()).hexdigest())


def evaluate(case,measurement):
    sd=json.loads(Path(case['state']).read_text());t=sd['input_transform']
    source=source_from_pair(Path(case['left']),Path(case['right']),Path(case['left']).parent)
    loaded=load_source(source);stamp=build_source_stamp(source,loaded)
    state=PairState(favorite=True,input_transform=InputTransformState(**t),
        alignment=AlignmentState(**sd['alignment']),framing=FramingState(**sd['framing']))
    if (state.framing.aspect!='maximum' or state.framing.crop_zoom_index!=0
            or state.framing.pan_x_permille or state.framing.pan_y_permille):
        raise ValueError('This fixed-correspondence framing check requires the full maximum crop')
    a=master_to_uint8(apply_orientation(loaded.left,t['left_orientation'],t['left_mirror']))
    b=master_to_uint8(apply_orientation(loaded.right,t['right_orientation'],t['right_mirror']))
    if t['swap_eyes']:a,b=b,a
    a,b=render_pair_for_disparity_analysis_from_arrays(a,b,state.alignment.correction)
    dense=analyze_horizontal_disparity(a,b,1500)
    if dense['near_confirmation']!=measurement['candidate']:
        raise RuntimeError('Integrated confirmation does not reproduce')
    _store_disparity_result(state,dense,basis=_disparity_basis(state),base_width_px=a.shape[1])
    left,right,_=render_final_pair(loaded,state,apply_color=False,apply_floating_window=False)
    h,w=a.shape[:2];ah,aw=measurement['analysis_shape'];offset=state.effective_offset_x_px
    points=[]
    for p in dense['near_confirmation']['verified_points']:
        points.append(dict(x=round((p['x']+.5)*w/aw-.5)-max(0,offset),
            y=round((p['y']+.5)*h/ah-.5),disparity_px=p['disparity_px']*w/aw-offset))
    checks=native_patch_checks(left,right,left.shape[:2],points)
    if not checks:raise RuntimeError('No native foreground checks survived final framing')
    maximum=max(p['disparity_permille'] for p in checks)
    if maximum>-state.framing.auto_near_back_permille:
        raise RuntimeError('Verified foreground point is in front of the requested back offset')
    del left,right,a,b,dense
    state.manual.delta_x_px=7
    left,right,_=render_final_pair(loaded,state,apply_color=False,apply_floating_window=False)
    before=digest(left,right);del left,right
    with tempfile.TemporaryDirectory(prefix='sf-native-near-sidecar-') as td:
        path=Path(td)/(case['name']+'.sfin')
        doc=state.to_sidecar(source=source_stamp_to_dict(stamp));save_sidecar(path,doc)
        read=load_sidecar(path,expected_source=stamp)
        if read.status!=SidecarStatus.VALID or read.pipeline_mismatches:raise RuntimeError('New sidecar is not valid')
        restored=PairState.from_sidecar(read.document)
        if (not restored.favorite or restored.manual.delta_x_px!=7
                or restored.framing.auto_near_offset_x_px!=state.framing.auto_near_offset_x_px
                or restored.disparity.high_edge_permille!=state.disparity.high_edge_permille):
            raise RuntimeError('Near framing or user state did not survive persistence')
        left,right,_=render_final_pair(loaded,restored,apply_color=False,apply_floating_window=False)
        if digest(left,right)!=before:raise RuntimeError('Native pixels changed on .sfin roundtrip')
        del left,right
        doc.pipeline['disparity']='sf-disparity-2';save_sidecar(path,doc)
        old=load_sidecar(path,expected_source=stamp)
        if not old.alignment_cache_valid or old.disparity_cache_valid:
            raise RuntimeError('Disparity update invalidates the wrong calculation cache')
    return dict(name=case['name'],status='verified',near_edge_permille=state.disparity.high_edge_permille,
        automatic_offset_x_px=state.framing.auto_near_offset_x_px,
        requested_back_permille=state.framing.auto_near_back_permille,
        fixed_native_framing_checks=len(checks),maximum_measured_after_framing_permille=maximum,
        sidecar_native_pixels_identical=True,favorite_and_manual_shift_preserved=True,
        old_disparity_invalidated_alignment_retained=True,native_raster_with_manual_shift=before,
        scope='fixed source locations rechecked in final native geometry; photometric evidence, not depth ground truth')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest',type=Path);parser.add_argument('--results',type=Path,required=True)
    args=parser.parse_args();cv2.setNumThreads(4)
    for case in json.loads(args.manifest.read_text()):
        path=args.results/(case['name']+'_native_near.json')
        if not path.exists():continue
        measured=json.loads(path.read_text())
        if not measured.get('audit',{}).get('accepted'):continue
        dest=args.results/(case['name']+'_native_near_framing.json')
        if dest.exists():continue
        result=evaluate(case,measured);dest.write_text(json.dumps(result,indent=2,allow_nan=False))
        print(case['name'],'native foreground max',result['maximum_measured_after_framing_permille'],
              'points',result['fixed_native_framing_checks'],'sidecar identical',True,flush=True)
        gc.collect()


if __name__=='__main__':main()
