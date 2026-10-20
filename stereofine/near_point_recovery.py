"""Bounded recovery of unconfirmed near edges with native same-point evidence.

Existing analysis/native patch checks and spatial-support rules are preserved.
Already confirmed results and unsuccessful recovery attempts retain the baseline.
"""
from __future__ import annotations

from copy import deepcopy
import numpy as np

from .near_point import supported_near_edge, verify_patch

PROTOCOL=dict(version='native-near-recovery-4', additional_probes=128,
    native_probes=24, minimum_native_scale=1.5, same_point_tolerance_analysis_px=1.,
    analysis_checks='unchanged RC3 17x17 NCC, uniqueness, reciprocity and spatial support',
    native_checks='existing 41x41 native NCC, global strip search +/-6 vertical, uniqueness and reciprocity',
    admission='both scales independently support the near edge; preserve original unsupported extremes and other uncertainty reasons')


def stratified_tail_probe(left, right, disparity, confidence, baseline):
    """Bounded seed selection with the unchanged analysis patch verifier.

    Only runs for an unconfirmed near edge. At most 128 additional probes;
    one representative near each 16-pixel cell center in the confident P98
    tail. Spatial subsampling limits cost without privileging one component's
    largest disparity. No NCC, contrast, uniqueness or reciprocal gate changes.
    The caller must additionally confirm the same points at native resolution.
    """
    if baseline["confirmed"] or not np.any(confidence):
        return baseline
    threshold = float(np.percentile(disparity[confidence], 98))
    ys, xs = np.where(confidence & (disparity >= threshold))
    cells = np.column_stack((ys // 16, xs // 16))
    distance = (ys % 16 - 7.5) ** 2 + (xs % 16 - 7.5) ** 2
    order = np.argsort(distance, kind="stable")
    _, unique = np.unique(cells[order], axis=0, return_index=True)
    selected = order[unique]
    selected = selected[np.linspace(0, len(selected)-1, min(128, len(selected)), dtype=int)]
    points = deepcopy(baseline["verified_points"])
    attempted = []
    for index in selected:
        x, y = int(xs[index]), int(ys[index])
        if any((x-p["x"])**2 + (y-p["y"])**2 < 64 for p in points):
            continue
        attempted.append((x, y))
        point = verify_patch(left, right, x, y)
        if point is not None:
            points.append(point)
    width = left.shape[1]
    result = supported_near_edge(points, baseline["baseline_percentile_permille"]*width/1000, width)
    result.update(probed_points=baseline["probed_points"]+len(attempted),
                  additional_probes=len(attempted),
                  baseline_percentile_permille=baseline["baseline_percentile_permille"],
                  diagnostic_only=True, selection="16px_cells_at_most_128")
    return result


def native_patch_checks(left, right, analysis_shape, points):
    """Separate 41x41 native-pixel NCC, global strip search and reciprocal check.

    Uses neither the SGBM disparity nor the analysis-scale NCC match as a
    horizontal search restriction. Reports rejected/missing evidence honestly.
    """
    import cv2
    from .disparity import _rgb_to_luma_uint8
    from .inputs import master_to_uint8
    a, b = _rgb_to_luma_uint8(master_to_uint8(left)), _rgb_to_luma_uint8(master_to_uint8(right))
    h, w = a.shape
    ah, aw = analysis_shape
    radius, vertical = 20, 6
    checked = []
    for point in sorted(points, key=lambda p: p["disparity_px"], reverse=True)[:24]:
        x = round((point["x"]+.5)*w/aw-.5)
        y = round((point["y"]+.5)*h/ah-.5)
        if not (radius <= x < w-radius and radius+vertical <= y < h-radius-vertical):
            continue
        template = a[y-radius:y+radius+1, x-radius:x+radius+1]
        if float(template.std()) < 6:
            continue
        scores = cv2.matchTemplate(b[y-radius-vertical:y+radius+vertical+1], template, cv2.TM_CCOEFF_NORMED)
        _, peak, _, position = cv2.minMaxLoc(scores)
        px, py = position
        other = scores.copy()
        other[max(0, py-2):py+3, max(0, px-4):px+5] = -1
        uniqueness = peak-float(other.max())
        if peak < .85 or uniqueness < .05:
            continue
        rx, ry = px+radius, y-vertical+py
        if not radius+vertical <= ry < h-radius-vertical:
            continue
        template = b[ry-radius:ry+radius+1, rx-radius:rx+radius+1]
        if float(template.std()) < 6:
            continue
        back = cv2.matchTemplate(a[ry-radius-vertical:ry+radius+vertical+1], template, cv2.TM_CCOEFF_NORMED)
        _, reverse_peak, _, reverse_position = cv2.minMaxLoc(back)
        if reverse_peak < .85 or np.hypot(reverse_position[0]+radius-x, ry-vertical+reverse_position[1]-y) > 1:
            continue
        checked.append(dict(x=x, y=y, disparity_permille=1000*(x-rx)/w,
                            vertical_px=y-ry, correlation=float(peak), uniqueness=uniqueness))
    return checked


def recover_near_edge(left,right,disparity,confidence,baseline,native_left,native_right):
    audit=dict(protocol=PROTOCOL.copy(),accepted=False,reason='already_confirmed',
               additional_probes=0,native_checked=0,native_verified=0,same_point_agreement=0)
    if baseline['confirmed']:return baseline,audit
    if not np.any(confidence):
        audit['reason']='no_confident_data';return baseline,audit
    h,w=left.shape
    nh,nw=native_left.shape[:2]
    if min(nh/h,nw/w)<PROTOCOL['minimum_native_scale']:
        audit['reason']='no_finer_native_measurement';return baseline,audit
    candidate=stratified_tail_probe(left,right,disparity,confidence,baseline)
    audit['additional_probes']=candidate.get('additional_probes',0)
    audit['analysis_supported_maximum_px']=candidate['maximum_supported_px']
    if not candidate['confirmed'] or candidate['unsupported_extreme']:
        audit['reason']='analysis_confirmation_failed';return baseline,audit
    ranked=sorted(candidate['verified_points'],key=lambda p:p['disparity_px'],reverse=True)[:24]
    associations={}
    for p in ranked:
        x=round((p['x']+.5)*nw/w-.5);y=round((p['y']+.5)*nh/h-.5)
        associations[(x,y)]=p
    audit['native_checked']=len(ranked)
    checks=native_patch_checks(native_left,native_right,left.shape,ranked)
    audit['native_verified']=len(checks)
    native_points=[];agreed=set()
    for check in checks:
        point=associations[(check['x'],check['y'])]
        measured=check['disparity_permille']*w/1000.
        if abs(measured-point['disparity_px'])>1.:continue
        agreed.add((point['x'],point['y']))
        native_points.append(dict(x=point['x'],y=point['y'],disparity_px=float(measured)))
    audit['same_point_agreement']=len(native_points)
    native_support=supported_near_edge(native_points,baseline['baseline_percentile_permille']*w/1000.,w)
    audit['native_support']={k:native_support[k] for k in ('confirmed','unsupported_extreme',
                               'supported_points','maximum_supported_px','edge_permille')}
    if not native_support['confirmed'] or native_support['unsupported_extreme']:
        audit['reason']='native_confirmation_failed';return baseline,audit
    # Do not replace an unresolved, analysis-supported near surface with a
    # farther surface just because only that farther surface passed natively.
    if candidate['maximum_supported_px']>native_support['maximum_supported_px']+1.:
        audit['reason']='unresolved_nearer_analysis_surface';return baseline,audit
    # Original evidence, including a possibly unsupported extreme, is retained.
    # Only additional points with matching native evidence may join it.
    original=deepcopy(baseline['verified_points'])
    original_positions={(p['x'],p['y']) for p in original}
    points=original+[p for p in candidate['verified_points']
                     if (p['x'],p['y']) in agreed and (p['x'],p['y']) not in original_positions]
    result=supported_near_edge(points,baseline['baseline_percentile_permille']*w/1000.,w)
    if (not result['confirmed'] or result['unsupported_extreme']
            or result['maximum_supported_px']>native_support['maximum_supported_px']+1.):
        audit['reason']='combined_confirmation_failed';return baseline,audit
    audit.update(accepted=True,reason='same_points_supported_at_both_scales')
    # Retain the established half-analysis-pixel reserve for the nearer of
    # the independently supported measurements, including native localization.
    result['maximum_supported_px']=max(candidate['maximum_supported_px'],result['maximum_supported_px'],native_support['maximum_supported_px'])
    result['edge_permille']=max(candidate['edge_permille'],result['edge_permille'],native_support['edge_permille'])
    result.update(probed_points=candidate['probed_points'],
                  baseline_percentile_permille=baseline['baseline_percentile_permille'],
                  method='percentile_99_plus_native_confirmed_recovery',recovery_validation=audit)
    return result,audit
