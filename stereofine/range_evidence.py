"""Bounded observed-range evidence using existing point verification gates.

Reuses production patch, spatial-support and native same-point checks. Values
are an observed span, never a claim that unmeasurable surfaces are covered.
"""
from __future__ import annotations

import numpy as np

from .disparity import _resize_pair_for_disparity, _rgb_to_luma_uint8
from .near_point import verify_patch, supported_near_edge
from .near_point_recovery import native_patch_checks

PROTOCOL = dict(version="range-evidence-3", grid=[8, 6], seeds_per_cell=4,
                dense_tail_cell_px=16, dense_tail_seeds_per_end=64,
                endpoint_candidates=24, same_point_tolerance_analysis_px=1.,
                purpose="observed native-confirmed span, not scene completeness")


def supported(points, sign, width):
    signed = [dict(p, disparity_px=sign*p['disparity_px']) for p in points]
    return supported_near_edge(signed, -1e10, width)


def measure_range_evidence(left, right, max_width=1500, dense=None, *, include_dense_tail=True,
                           _native_checker=None):
    import cv2
    small_left, small_right, _ = _resize_pair_for_disparity(left, right, max_width)
    a, b = [_rgb_to_luma_uint8(x) for x in (small_left, small_right)]
    h, w = a.shape
    seeds = []
    seen = set()

    def add(x, y):
        x, y = int(x), int(y)
        if not (0 <= x < w and 0 <= y < h) or (x, y) in seen:
            return
        seen.add((x, y))
        seeds.append((x, y))

    # Per-cell feature detection: a globally strong foreground must not use up
    # the seed budget before a lower-contrast distant horizon gets sampled.
    for iy in range(6):
        for ix in range(8):
            y0, y1 = iy*h//6, (iy+1)*h//6
            x0, x1 = ix*w//8, (ix+1)*w//8
            corners = cv2.goodFeaturesToTrack(a[y0:y1, x0:x1], maxCorners=4,
                qualityLevel=.01, minDistance=8, blockSize=5)
            if corners is not None:
                for x, y in np.rint(corners[:, 0]).astype(int):
                    add(x+x0, y+y0)
    if dense and dense.get('ready'):
        # Percentiles only seed the search. Sample interiors throughout both
        # tails, rather than only the most extreme component boundary pixels.
        confidence, values = dense['_confidence_mask'], dense['_disp_permille']
        if include_dense_tail and np.any(confidence):
            for sign in [-1, 1]:
                signed = sign*values
                tail = confidence & (signed >= np.percentile(signed[confidence], 98))
                ys, xs = np.where(tail)
                cells = np.column_stack([ys//16, xs//16])
                distance = (ys % 16-7.5)**2+(xs % 16-7.5)**2
                order = np.argsort(distance, kind='stable')
                _, unique = np.unique(cells[order], axis=0, return_index=True)
                candidates = order[unique]
                # Keep both value coverage and spatial coverage. A rare true
                # surface can disappear in a uniformly subsampled P2 tail
                # whose remaining cells all belong to the background plane.
                ranked = sorted(candidates.tolist(), key=lambda i: -signed[ys[i], xs[i]])[:32]
                spread = candidates[np.linspace(0, len(candidates)-1, min(32, len(candidates)), dtype=int)]
                selected = dict.fromkeys(ranked + spread.tolist())
                for i in selected:
                    add(xs[i], ys[i])
        for key, reflected in [('near_confirmation', False), ('far_confirmation', True)]:
            points = dense.get(key, {}).get('verified_points', [])
            for p in sorted(points, key=lambda p: p['disparity_px'], reverse=True)[:24]:
                add(w-1-p['x'] if reflected else p['x'], p['y'])
    points = []
    for x, y in seeds.copy():
        p = verify_patch(a, b, x, y)
        if p is not None:
            points.append(p)
    # The same small neighbourhood search is used at BOTH ends. It cannot
    # create support on a constant patch because verify_patch still rejects it.
    for sign in (-1, 1):
        extremes = sorted(points.copy(), key=lambda p: sign*p['disparity_px'], reverse=True)[:6]
        for p in extremes:
            for dx, dy in [(-8, 0), (8, 0), (0, -8), (0, 8), (-8, 8), (8, 8), (-16, 0), (16, 0)]:
                before = len(seeds)
                add(p['x']+dx, p['y']+dy)
                if len(seeds) > before:
                    q = verify_patch(a, b, *seeds[-1])
                    if q is not None:
                        points.append(q)
    endpoints = {}
    nh, nw = left.shape[:2]
    for name, sign in [('far', -1), ('near', 1)]:
        analysis = supported(points, sign, w)
        ranked = sorted(points, key=lambda p: sign*p['disparity_px'], reverse=True)[:24]
        reflected = [dict(p, x=w-1-p['x'], disparity_px=-p['disparity_px']) for p in ranked]
        native_left = left if sign == 1 else left[:, ::-1].copy()
        native_right = right if sign == 1 else right[:, ::-1].copy()
        native_audit = []
        if _native_checker is None:
            checks = native_patch_checks(native_left, native_right, a.shape,
                                         ranked if sign == 1 else reflected, audit=native_audit)
        else:
            checks, native_audit = _native_checker(native_left, native_right,
                                                   a.shape, ranked if sign == 1 else reflected)
        associations = {}
        for p in ranked if sign == 1 else reflected:
            xy = (round((p['x']+.5)*nw/w-.5), round((p['y']+.5)*nh/h-.5))
            associations[xy] = p
        agreed = []
        for c in checks:
            p = associations[(c['x'], c['y'])]
            d = c['disparity_permille']*w/1000.
            if abs(d-p['disparity_px']) <= 1.:
                agreed.append(dict(x=p['x'], y=p['y'], disparity_px=d))
        native = supported(agreed, 1, w)
        maximum = native['maximum_supported_px']
        reasons = []
        if maximum is None:
            reasons.append('no_native_spatial_support')
        if maximum is not None:
            if any(p['disparity_px'] > maximum+1. for p in agreed):
                reasons.append('isolated_more_extreme_native_match')
            if (analysis['maximum_supported_px'] is not None
                    and analysis['maximum_supported_px'] > maximum+1.):
                reasons.append('unresolved_more_extreme_analysis_surface')
        endpoints[name] = dict(confirmed=not reasons, reasons=reasons,
            edge_permille=None if maximum is None else sign*maximum*1000/w,
            analysis_supported_points=analysis['supported_points'],
            native_checked=len(ranked), native_verified=len(checks),
            same_point_agreement=len(agreed), native_supported_points=native['supported_points'],
            native_locations=checks, native_audit=native_audit)
    far, near = endpoints['far'], endpoints['near']
    span = None
    if far['edge_permille'] is not None and near['edge_permille'] is not None:
        span = near['edge_permille'] - far['edge_permille']
    protocol = PROTOCOL.copy()
    if not include_dense_tail:
        protocol['version'] = 'range-evidence-1'
        protocol['dense_tail_seeds_per_end'] = 0
    return dict(protocol=protocol, analysis_shape=[h, w], native_shape=[nh, nw],
        probed_points=len(seeds), verified_analysis_points=len(points), endpoints=endpoints,
        observed_span_permille=span,
        endpoints_confirmed=far['confirmed'] and near['confirmed'],
        completeness='not_established')
