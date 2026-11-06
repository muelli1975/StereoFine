"""Read-only audit of the released automatic near reserve; synthetic data only."""
import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import numpy as np
import cv2
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from stereofine.state import PairState
from stereofine.framing import compute_auto_near_framing
from stereofine.render import render_final_pair
from stereofine.disparity import analyze_horizontal_disparity, render_pair_for_disparity_analysis_from_arrays
from stereofine.processing import _store_disparity_result, _disparity_basis, refresh_current_disparity

cv2.setNumThreads(4)
records=[]

for aspect in ('original','1:1','16:9'):
    for near_px in (180,600,1200):
        canvas=np.zeros((4000,6000,3),np.uint8)
        loaded=SimpleNamespace(left=canvas,right=canvas,icc_profile=None)
        state=PairState()
        state.framing.aspect=aspect
        before,_,_=render_final_pair(loaded,copy.deepcopy(state),apply_color=False,apply_floating_window=False)
        width=before.shape[1]
        frame=compute_auto_near_framing(high_edge_permille=1000*near_px/width,
            base_width_px=width,ready=True)
        state.framing.auto_near_offset_x_px=frame.offset_x_px
        state.framing.auto_near_base_width_px=width
        after,_,_=render_final_pair(loaded,state,apply_color=False,apply_floating_window=False)
        final_width=after.shape[1]
        reserve=(frame.offset_x_px-near_px)*1000/final_width
        # The selected integer shift must be the smallest one that attains
        # the reserve on the actual final width; no image measurement is mocked.
        solved=None
        for shift in range(max(0,frame.offset_x_px-40),frame.offset_x_px+2):
            candidate=copy.deepcopy(state)
            candidate.framing.auto_near_offset_x_px=shift
            final,_,_=render_final_pair(loaded,candidate,apply_color=False,apply_floating_window=False)
            candidate_reserve=(shift-near_px)*1000/final.shape[1]
            if candidate_reserve>=3.-1e-10:
                solved=dict(offset_px=shift,final_width=final.shape[1],reserve_permille=candidate_reserve)
                break
        records.append(dict(kind='geometry_only_known_edge',aspect=aspect,near_px=near_px,
            initial_selected_width=width,offset_px=frame.offset_x_px,final_width=final_width,
            actual_reserve_permille=reserve,requested_reserve_permille=3.,
            final_width_solution=solved))

rng=np.random.default_rng(20261106)
for texture in ('strong','weak'):
    mono=rng.integers(0,256,(800,1200),np.uint8)
    if texture=='weak':
        mono=cv2.GaussianBlur(mono,(31,31),8)
        mono[:600]=128
    left=np.repeat(mono[...,None],3,axis=2)
    right=np.zeros_like(left)
    right[:,:-24]=left[:,24:]
    loaded=SimpleNamespace(left=left,right=right,icc_profile=None)
    for aspect in ('original','1:1'):
        state=PairState()
        state.framing.aspect=aspect
        a,b=render_pair_for_disparity_analysis_from_arrays(left,right,None,
            output_aspect=aspect,input_aspect_ratio=1.5)
        initial=analyze_horizontal_disparity(a,b,1500)
        _store_disparity_result(state,initial,basis=_disparity_basis(state),base_width_px=a.shape[1])
        old_display=state.current_scene_positions_permille()[0]
        final_a,_,_=render_final_pair(loaded,state,apply_color=False,apply_floating_window=False)
        real_near=(24-state.effective_offset_x_px)*1000/final_a.shape[1]
        refresh_current_disparity(loaded,state)
        new_display=state.current_scene_positions_permille()[0]
        records.append(dict(kind='actual_sgbm_plane',texture=texture,aspect=aspect,
            initial_width=a.shape[1],final_width=final_a.shape[1],
            initial_near=initial.get('high_edge_permille'),
            previous_displayed_near=old_display,final_measured_near=new_display,
            geometric_true_near=real_near,uncertain=state.disparity.uncertain,
            reasons=state.disparity.uncertain_reasons,
            auto_offset_px=state.auto_offset_x_px,
            display_equals_final_measurement=(new_display==state.disparity.high_edge_permille)))

print('NEAR_AUDIT_JSON_BEGIN',flush=True)
print(json.dumps(records,indent=2),flush=True)
print('NEAR_AUDIT_JSON_END',flush=True)
Path('build').mkdir(exist_ok=True)
Path('build/final-near-audit-20261106.json').write_text(json.dumps(records,indent=2)+'\n')
