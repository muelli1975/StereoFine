"""Located disparity evidence, independent of view zoom and presentation masks."""
from __future__ import annotations

from .config import CROP_ZOOM_LEVELS
from .geometry import framing_crop_box, clamp_offset_for_size

ENDPOINT_MARKER_VERSION = 3


def normalized_marker(x, y, disparity_px, width, height, *, tentative, target_permille):
    return dict(left=[(x + .5) / width, (y + .5) / height],
                right=[(x - disparity_px + .5) / width, (y + .5) / height],
                tentative=tentative, target_permille=target_permille)


def locate_endpoints(analysis_shape, near_confirmation, far_confirmation, low_edge, high_edge):
    h, w = analysis_shape
    candidates = {}
    for name, confirmation, target in (
        ('near', near_confirmation, high_edge), ('far', far_confirmation, low_edge)):
        if not confirmation.get('confirmed'):
            continue
        target_px = target * w / 1000
        points = []
        for point in confirmation['supported_matches']:
            x, y, d = float(point['x']), float(point['y']), float(point['disparity_px'])
            if name == 'far':
                x, d = w - 1 - x, -d
            distance = abs(d - target_px)
            # The confirmation allows 1.5 analysis pixels. The reported
            # edge may add half a pixel of reserve to a verified surface.
            if distance <= 2.0 and 0 <= x < w and 0 <= x-d < w and 0 <= y < h:
                points.append((distance, x, y, d))
        if points:
            candidates[name] = sorted(points)[:8]

    chosen = {name: values[0] for name, values in candidates.items()}
    if 'near' in candidates and 'far' in candidates:
        ordered = [(n[0] + f[0], n, f) for n in candidates['near'] for f in candidates['far']
                   if n[3] >= f[3]]
        if ordered:
            _, chosen['near'], chosen['far'] = min(ordered)
        else:
            chosen.clear()

    markers = {name: normalized_marker(x, y, d, w, h, tentative=False,
                                       target_permille=high_edge if name == 'near' else low_edge)
               for name, (_, x, y, d) in chosen.items()}
    return dict(version=ENDPOINT_MARKER_VERSION, coordinate_system='normalized_final_crop', markers=markers)


def crop_geometry(state, aligned_shape, input_aspect):
    h, w = aligned_shape[:2]
    dx, dy = clamp_offset_for_size(w, h, state.effective_offset_x_px, state.effective_offset_y_px)
    zoom = CROP_ZOOM_LEVELS[max(0, min(len(CROP_ZOOM_LEVELS)-1, int(state.framing.crop_zoom_index)))]
    box = framing_crop_box(w-abs(dx), h-abs(dy), state.framing.aspect, zoom,
                          state.framing.pan_x_permille, state.framing.pan_y_permille, input_aspect)
    return dx, dy, box


def to_master(endpoints, state, aligned_shape, input_aspect):
    if not endpoints:
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
    return dict(version=ENDPOINT_MARKER_VERSION, coordinate_system='aligned_master', aligned_shape=list(aligned_shape[:2]),
                input_aspect=float(input_aspect), markers=markers)


def current_markers(state):
    evidence = state.disparity.endpoints
    if (state.disparity.stale or not state.disparity.valid
            or evidence.get('version', 0) < ENDPOINT_MARKER_VERSION
            or evidence.get('coordinate_system') != 'aligned_master'):
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
