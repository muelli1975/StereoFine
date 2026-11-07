"""Located disparity evidence, independent of view zoom and presentation masks."""
from __future__ import annotations

import numpy as np

from .config import CROP_ZOOM_LEVELS
from .geometry import framing_crop_box, clamp_offset_for_size


def locate_endpoints(disparity, confidence, near_confirmation, far_confirmation,
                     low_edge, high_edge):
    h, w = disparity.shape
    candidates = {}
    ys, xs = np.nonzero(confidence & np.isfinite(disparity))
    dense = disparity[ys, xs]
    for name, confirmation, target in (
        ('near', near_confirmation, high_edge), ('far', far_confirmation, low_edge)):
        points = []
        for raw in confirmation.get('verified_points', []):
            x, y, d = float(raw['x']), float(raw['y']), float(raw['disparity_px'])
            if name == 'far':
                x, d = w-1-x, -d
            if 0 <= x < w and 0 <= x-d < w and 0 <= y < h:
                points.append((abs(d*1000/w-target), x, y, d,
                               not confirmation.get('confirmed', False)))
        if len(dense):
            distances = np.abs(dense*1000/w-target)
            count = min(8, len(dense))
            indices = np.argpartition(distances, count-1)[:count]
            for index in indices:
                x, y, d = float(xs[index]), float(ys[index]), float(dense[index])
                if 0 <= x-d < w:
                    points.append((float(distances[index]), x, y, d, True))
        if points:
            candidates[name] = sorted(points)[:8]
    chosen = {name: values[0] for name, values in candidates.items()}
    if 'near' in candidates and 'far' in candidates:
        ordered = [(n[0]+f[0], n, f) for n in candidates['near'] for f in candidates['far']
                   if n[3] >= f[3]]
        if ordered:
            _, chosen['near'], chosen['far'] = min(ordered)
        else:
            # Contradictory verifier evidence must not reverse physical depth.
            pair = sorted([chosen['near'], chosen['far']], key=lambda v: v[3])
            chosen['far'], chosen['near'] = pair
            chosen = {name: (*point[:4], True) for name, point in chosen.items()}
    markers = {}
    for name, (_, x, y, d, tentative) in chosen.items():
        markers[name] = dict(left=[(x+.5)/w, (y+.5)/h],
                             right=[(x-d+.5)/w, (y+.5)/h],
                             tentative=tentative,
                             target_permille=high_edge if name == 'near' else low_edge)
    return dict(version=2, coordinate_system='normalized_final_crop', markers=markers)


def crop_geometry(state, aligned_shape, input_aspect):
    h, w = aligned_shape[:2]
    dx, dy = clamp_offset_for_size(w, h, state.effective_offset_x_px, state.effective_offset_y_px)
    zoom = CROP_ZOOM_LEVELS[max(0, min(len(CROP_ZOOM_LEVELS)-1, int(state.framing.crop_zoom_index)))]
    box = framing_crop_box(w-abs(dx), h-abs(dy), state.framing.aspect, zoom,
                          state.framing.pan_x_permille, state.framing.pan_y_permille, input_aspect)
    return dx, dy, box


def to_master(endpoints, state, aligned_shape, input_aspect):
    if not endpoints.get('markers'):
        return {}
    dx, dy, box = crop_geometry(state, aligned_shape, input_aspect)
    x, y, x1, y1 = box
    markers = {}
    for name, marker in endpoints['markers'].items():
        item = dict(marker)
        for eye, ox, oy in [('left', max(0, dx), max(0, dy)),
                            ('right', max(0, -dx), max(0, -dy))]:
            px, py = marker[eye]
            item[eye] = [x+ox+px*(x1-x), y+oy+py*(y1-y)]
        markers[name] = item
    return dict(version=2, coordinate_system='aligned_master', aligned_shape=list(aligned_shape[:2]),
                input_aspect=float(input_aspect), markers=markers)


def current_markers(state):
    evidence = state.disparity.endpoints
    if (state.disparity.stale or not state.disparity.valid or
            evidence.get('coordinate_system') != 'aligned_master'):
        return {}
    dx, dy, box = crop_geometry(state, evidence['aligned_shape'], evidence['input_aspect'])
    x, y, x1, y1 = box
    result = {}
    near, far = state.current_scene_positions_permille()
    for name, marker in evidence.get('markers', {}).items():
        item = dict(marker)
        for eye, ox, oy in [('left', max(0, dx), max(0, dy)),
                            ('right', max(0, -dx), max(0, -dy))]:
            px, py = marker[eye]
            item[eye] = [(px-x-ox)/(x1-x), (py-y-oy)/(y1-y)]
        item['point_permille'] = 1000 * (item['left'][0]-item['right'][0])
        item['permille'] = near if name == 'near' else far
        item['tentative'] = bool(item.get('tentative') or state.disparity.uncertain)
        result[name] = item
    return result
