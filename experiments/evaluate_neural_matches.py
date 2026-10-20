"""Research only: identical source checks, existing fit stages and real rasters.

LK source checks are independent of the candidate fit but are not measured
ground-truth correspondences. Render probes can differ after crop changes.
No candidate is automatically admitted to the application.
"""
from pathlib import Path
from dataclasses import asdict
import sys, json, time, gc, cv2, numpy as np, argparse
parser = argparse.ArgumentParser(description='Evaluate saved neural matches without importing neural dependencies')
parser.add_argument('results', type=Path)
args = parser.parse_args()
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from stereofine.sources import source_from_pair, load_source
from stereofine.geometry import apply_orientation
from stereofine.alignment import resize_pair_for_analysis, _fit_vertical_ransac_filter, _analyze_matched_points
from stereofine.alignment_refinement import refine_alignment, corrected_point_residuals, patch_correlations
from stereofine.lens_refinement import refine_residual_field
from stereofine.disparity import render_pair_for_disparity_analysis_from_arrays, analyze_horizontal_disparity
from stereofine.processing import _store_disparity_result, _disparity_basis
from stereofine.state import PairState, AlignmentState, FramingState, InputTransformState
from stereofine.render import render_final_pair
from scripts.diagnose_rc3_field import rendered_checks
cv2.setNumThreads(4)
root = args.results.resolve()
for f in sorted(root.glob('*_lightglue_*.json')) + sorted(root.glob('*_roma_*.json')):
    if f.name.endswith('_quality.json'):
        continue
    dest = f.with_name(f.stem + '_quality.json')
    if dest.exists():
        continue
    row = json.loads(f.read_text())
    if row.get('status') == 'deferred':
        continue
    case = row['case']
    sd = json.loads(Path(case['state']).read_text())
    t = sd['input_transform']
    loaded = load_source(source_from_pair(Path(case['left']), Path(case['right']), Path(case['left']).parent))
    baseline_file = root / (case['name'] + '_baseline.json')
    if not baseline_file.exists():
        baseline_state = PairState(input_transform=InputTransformState(**t), alignment=AlignmentState(**sd['alignment']), framing=FramingState(**sd['framing']))
        baseline_left, baseline_right, _ = render_final_pair(loaded, baseline_state, apply_color=False, apply_floating_window=False)
        baseline_file.write_text(json.dumps({'case': case['name'], 'rendered': rendered_checks(baseline_left, baseline_right)}, indent=2))
        del baseline_left, baseline_right
    a = apply_orientation(loaded.left, t['left_orientation'], t['left_mirror'])
    b = apply_orientation(loaded.right, t['right_orientation'], t['right_mirror'])
    ga, gb, scale = resize_pair_for_analysis(a, b, 3000)
    z = np.load(f.with_name(f.stem + '_points.npz'))
    p, q = (z['left'].astype(float), z['right'].astype(float))
    width = 1500
    ratio = width / ga.shape[1]
    size = (width, round(ga.shape[0] * ratio))
    sa = cv2.resize(ga, size, interpolation=cv2.INTER_AREA)
    sb = cv2.resize(gb, size, interpolation=cv2.INTER_AREA)
    cp = cv2.goodFeaturesToTrack(sa, maxCorners=3000, qualityLevel=0.01, minDistance=8, blockSize=7)
    opts = dict(winSize=(31, 31), maxLevel=5, criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 40, 0.001))
    cq, s, e = cv2.calcOpticalFlowPyrLK(sa, sb, cp, None, **opts)
    back, s2, _ = cv2.calcOpticalFlowPyrLK(sb, sa, cq, None, **opts)
    cp, cq = (cp[:, 0], cq[:, 0])
    good = s[:, 0].astype(bool) & s2[:, 0].astype(bool) & (np.linalg.norm(back[:, 0] - cp, axis=1) < 0.35) & (patch_correlations(sa, sb, cp, cq) >= 0.9)
    cp, cq = ((cp[good] + 0.5) / ratio - 0.5, (cq[good] + 0.5) / ratio - 0.5)

    def source_quality(correction):
        dy = np.abs(corrected_point_residuals(correction, cp, cq, ga.shape, scale)) / scale
        return dict(count=len(dy), mean=float(dy.mean()), p95=float(np.percentile(dy, 95)))
    result = {'name': row['name'], 'matcher_seconds': row['seconds'], 'source_baseline': source_quality(sd['alignment']['correction']), 'baseline_rendered': json.loads(baseline_file.read_text())['rendered'], 'variants': []}
    for variant in ['raw', 'lk']:
        lp, rp = (p.copy(), q.copy())
        try:
            if variant == 'lk':
                valid = patch_correlations(ga, gb, lp, rp) >= 0.85
                lp, rp = (lp[valid].astype(np.float32).reshape(-1, 1, 2), rp[valid].astype(np.float32).reshape(-1, 1, 2))
                op = dict(winSize=(21, 21), maxLevel=1, criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 40, 0.001), flags=cv2.OPTFLOW_USE_INITIAL_FLOW)
                rq, st, _ = cv2.calcOpticalFlowPyrLK(ga, gb, lp, rp.copy(), **op)
                bk, st2, _ = cv2.calcOpticalFlowPyrLK(gb, ga, rq, lp.copy(), **op)
                valid = st[:, 0].astype(bool) & st2[:, 0].astype(bool) & (np.linalg.norm(bk[:, 0] - lp[:, 0], axis=1) < 0.35) & (np.linalg.norm(rq[:, 0] - rp[:, 0], axis=1) <= 2) & (patch_correlations(ga, gb, lp[:, 0], rq[:, 0]) >= 0.9)
                lp, rp = (lp[:, 0][valid].astype(float), rq[:, 0][valid].astype(float))
            filt = _fit_vertical_ransac_filter(0.5 * (lp + rp), rp, lp, ga.shape)
            fit = _analyze_matched_points(lp, rp, ga.shape, scale, row['kind'], inlier_mask=filt['mask'])
            fit = refine_alignment(fit, lp, rp, filt['mask'], ga, gb, scale, row['kind'])
            fit = refine_residual_field(fit, lp, rp, ga, gb, scale)
            state = PairState(input_transform=InputTransformState(**t), alignment=AlignmentState(**sd['alignment']), framing=FramingState(**sd['framing']))
            state.alignment.correction = fit['correction']
            dl, dr = render_pair_for_disparity_analysis_from_arrays(a, b, fit['correction'])
            dense = analyze_horizontal_disparity(dl, dr, 1500)
            _store_disparity_result(state, dense, basis=_disparity_basis(state), base_width_px=dl.shape[1])
            left, right, _ = render_final_pair(loaded, state, apply_color=False, apply_floating_window=False)
            quality = rendered_checks(left, right)
            record = {'variant': variant, 'points': len(lp), 'model': fit['model'], 'source_quality': source_quality(fit['correction']), 'rendered': quality, 'near': state.disparity.high_edge_permille, 'uncertain': state.disparity.uncertain_reasons, 'correction': fit['correction']}
            result['variants'].append(record)
            print(row['name'], variant, 'src', result['source_baseline'], record['source_quality'], 'render', quality[0], quality[-1], flush=True)
            del dl, dr, dense, left, right
        except Exception as exc:
            import traceback
            traceback.print_exc()
            result['variants'].append({'variant': variant, 'error': str(exc)})
        gc.collect()
    dest.write_text(json.dumps(result, indent=2))
    del loaded, a, b, ga, gb
    gc.collect()
