"""Measure symmetric RGB fitting from the correspondence data StereoFine already computes."""
from contextlib import ExitStack
from copy import deepcopy
import argparse
import json
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
from time import perf_counter
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image

from stereofine import alignment, alignment_refinement
from stereofine.color_profiles import transform_rgb
from stereofine.color_transfer import apply_symmetric_color_transfer, fit_symmetric_color_transfer
from stereofine.config import CROP_ZOOM_LEVELS
from stereofine.geometry import framing_crop_box
from stereofine.inputs import master_to_uint8
from stereofine.manual_geometry import GeometryAdjustment, geometry_matrix
from stereofine.native_preview import native_key, prepare_native_preview
from stereofine.processing import ProcessingOptions, process_source
from stereofine.render import _color_basis, _oriented_pair, render_final_pair
from stereofine.session import BrowsedSource
from stereofine.sidecar import load_sidecar, save_sidecar
from stereofine.sources import discover_pair_sources, discover_stereo_file_sources, source_from_pair
from stereofine.worker import CancellationToken
from tools.benchmark_color_preview import patch_matches, scaled_pair, synthetic_pairs
from tools.benchmark_cpu_batch import make_sources, prepare

GRID = (8, 6)
PATCH_SIZE = 7


def fit_capture(source, method, geometry):
    captured = {}
    refine = alignment_refinement.refine_alignment

    def capture(baseline, left, right, inliers, left_gray, right_gray, scale, method):
        captured['points'] = np.stack((left[inliers], right[inliers]))
        captured['shape'] = left_gray.shape
        return refine(baseline, left, right, inliers, left_gray, right_gray, scale, method)

    options = ProcessingOptions(analysis_method=method, save_sidecar=False,
                                keep_loaded_pair=True, force_alignment=True, geometry=geometry)
    with patch.object(alignment_refinement, 'refine_alignment', capture):
        started = perf_counter()
        processed = process_source(source, options)
    return processed, captured, (perf_counter() - started) * 1000


def crop_capture(loaded, state):
    remap = cv2.remap
    valid_rectangle = alignment._largest_all_valid_rectangle
    maps, rectangles = [], []

    def capture_map(image, mx, my, *args, **kwargs):
        maps.append((mx, my))
        return remap(image, mx, my, *args, **kwargs)

    def capture_rectangle(valid):
        box = valid_rectangle(valid)
        rectangles.append(box)
        return box

    with ExitStack() as stack:
        stack.enter_context(patch.object(cv2, 'remap', capture_map))
        stack.enter_context(patch.object(alignment, '_largest_all_valid_rectangle', capture_rectangle))
        raw = render_final_pair(loaded, state, apply_color=False, apply_floating_window=False)
    assert len(maps) in (0, 2), len(maps)
    assert len(rectangles) == len(maps) // 2
    return raw, maps, (rectangles[0] or (0, 0, 0, 0))[:2] if rectangles else (0, 0)


def sample_map(field, xy):
    h, w = field.shape
    xy = np.clip(xy, [0, 0], [w - 1.001, h - 1.001])
    x, y = np.floor(xy).astype(np.intp).T
    fx, fy = xy[:, 0] - x, xy[:, 1] - y
    return ((field[y, x] * (1 - fx) + field[y, x + 1] * fx) * (1 - fy)
            + (field[y + 1, x] * (1 - fx) + field[y + 1, x + 1] * fx) * fy)


def to_crop(points, maps, origins):
    points = points.astype(np.float64, copy=False)
    if not maps:
        return points - origins[:, None, :]
    projected = []
    for eye, (mx, my), origin in zip(points, maps, origins, strict=True):
        output = eye.copy()
        for _ in range(8):
            output += eye - np.column_stack((sample_map(mx, output), sample_map(my, output)))
        error = eye - np.column_stack((sample_map(mx, output), sample_map(my, output)))
        output[np.max(np.abs(error), axis=1) > .12] = np.nan
        projected.append(output - origin)
    return np.stack(projected)


def inside(points, shape, margin):
    h, w = shape[:2]
    return ((points >= margin) & (points < [w - margin, h - margin])).all(axis=(0, 2))


def patch_pixels(eyes, points, step):
    if points.shape[1] == 0:
        return tuple(np.empty((0, PATCH_SIZE, PATCH_SIZE, 3), eye.dtype) for eye in eyes)
    delta = np.arange(-(PATCH_SIZE // 2), PATCH_SIZE // 2 + 1, dtype=np.float32) * step
    dx, dy = np.meshgrid(delta, delta)
    batches = []
    for eye, (x, y) in zip(eyes, points.astype(np.float32).transpose(0, 2, 1), strict=True):
        mx = (x[:, None, None] + dx).reshape(-1, PATCH_SIZE)
        my = (y[:, None, None] + dy).reshape(-1, PATCH_SIZE)
        sampled = cv2.remap(eye, mx, my, cv2.INTER_LINEAR)
        batches.append(sampled.reshape(-1, PATCH_SIZE, PATCH_SIZE, 3))
    return tuple(batches)


def tiles(points, shape):
    h, w = shape[:2]
    return np.clip((points.mean(axis=0) / [w, h] * GRID).astype(int), 0, np.subtract(GRID, 1))


def select_balanced(points, shape):
    counts = {}
    fine = set()
    keep = []
    for i, (tile, point) in enumerate(zip(tiles(points, shape), points.mean(axis=0), strict=True)):
        tile = tuple(tile)
        cell = tuple(np.floor(point / max(6., shape[1] / 240)).astype(int))
        if cell not in fine and counts.get(tile, 0) < 20:
            keep.append(i)
            fine.add(cell)
            counts[tile] = counts.get(tile, 0) + 1
    return points[:, keep, :]


def packed(patches):
    return tuple(eye.reshape(-1, PATCH_SIZE, 3) for eye in patches)


def patch_means(patches):
    return np.stack([master_to_uint8(eye.reshape(-1, PATCH_SIZE, 3)).reshape(eye.shape).mean(axis=(1, 2))
                     for eye in patches])


def error_rows(patches, transfer):
    if patches[0].shape[0] == 0:
        return np.empty(0)
    if transfer is not None:
        images = apply_symmetric_color_transfer(*packed(patches), transfer)
        patches = tuple(eye.reshape(patches[0].shape) for eye in images)
    means = patch_means(patches)
    return np.abs(means[0] - means[1]).mean(axis=1)


def score(patches, transfers):
    return {name: round(float(rows.mean()), 3) if len(rows) else None
            for name, transfer in transfers.items() for rows in [error_rows(patches, transfer)]}


def choose(raw, points, baseline):
    shape = raw[0].shape
    step = max(1., shape[1] / 1440)
    points = points[:, inside(points, shape, 4 * step), :]
    points = points[:, np.abs(points[0, :, 1] - points[1, :, 1]) <= 2.5 * step, :]
    points = select_balanced(points, shape)
    samples = patch_pixels(raw, points, step)
    means = patch_means(samples) if points.shape[1] else np.empty((2, 0, 3))
    usable = ((means > 10) & (means < 245)).all(axis=(0, 2))
    points = points[:, usable, :]
    samples = tuple(eye[usable] for eye in samples)
    gx, gy = tiles(points, shape).T
    group = (gx + 2 * gy) % 3
    train, validation = group == 0, group == 1
    train_tiles = len(set(zip(gx[train], gy[train])))
    validation_tiles = len(set(zip(gx[validation], gy[validation])))
    luma = means[:, usable].mean(axis=(0, 2))
    tone_span = float(np.ptp(np.percentile(luma[train], (10, 90)))) if train.any() else 0.
    details = dict(retained=len(points[0]), train=int(train.sum()), validation=int(validation.sum()),
                   train_tiles=train_tiles, validation_tiles=validation_tiles,
                   tone_span=round(tone_span, 2))
    transfers = {'original': None, 'current': baseline}
    if (train.sum() < 24 or validation.sum() < 20 or train_tiles < 6
            or validation_tiles < 5 or tone_span < 32):
        return 'current', transfers, details, samples, group
    transfers['reuse'] = fit_symmetric_color_transfer(*packed(tuple(eye[train] for eye in samples)))
    validation_samples = tuple(eye[validation] for eye in samples)
    validation_rows = {name: error_rows(validation_samples, transfer)
                       for name, transfer in transfers.items()}
    details['validation_error'] = {name: round(float(np.median(rows)), 3)
                                   for name, rows in validation_rows.items()}
    # A moderate margin reduces changes driven by a handful of ambiguous patches.
    chosen = 'current'
    if details['validation_error']['original'] <= details['validation_error']['current'] + .25:
        chosen = 'original'
    if details['validation_error']['reuse'] + .35 < details['validation_error'][chosen]:
        chosen = 'reuse'
    return chosen, transfers, details, samples, group


def external_matches(raw):
    proxy = tuple(master_to_uint8(eye) for eye in raw)
    reduced = scaled_pair(proxy)
    first, second = patch_matches(reduced)
    if not first and not second:
        return np.empty((2, 0, 2))
    h, w = raw[0].shape[:2]
    rh, rw = reduced[0].shape[:2]
    points = (np.asarray(first + second, dtype=float).transpose(1, 0, 2) + .5) * [w / rw, h / rh] - .5
    gx, gy = tiles(points, raw[0].shape).T
    return points[:, (gx + 2 * gy) % 3 == 2, :]


def verify_render(processed, state, raw, transfer):
    loaded = processed.loaded_pair
    if transfer is None:
        # Identity expressed with the existing curve schema, preserving the toggle.
        transfer = fit_symmetric_color_transfer(raw[0], raw[0])
    state.color.method = transfer.method
    state.color.parameters = transfer.to_dict()
    state.color.basis = _color_basis(state, *raw)
    state.color.valid = state.color.enabled = True
    from stereofine.sidecar import source_stamp_to_dict

    source = processed.source
    save_sidecar(source.sidecar_path, state.to_sidecar(source=source_stamp_to_dict(processed.source_stamp)))
    reloaded = process_source(source, ProcessingOptions(analysis_method=state.alignment.method,
                                                        save_sidecar=False, keep_loaded_pair=True))
    assert reloaded.alignment_from_cache and reloaded.state.color.valid
    cached = reloaded.state
    reference = apply_symmetric_color_transfer(*raw, transfer, strength=state.color.strength)
    export = render_final_pair(reloaded.loaded_pair, deepcopy(cached), apply_floating_window=False)
    assert all(np.array_equal(a, b) for a, b in zip(reference, export[:2], strict=True))
    if not state.geometry.active:
        sidecar = load_sidecar(source.sidecar_path, expected_source=processed.source_stamp)
        session = BrowsedSource(source, reloaded.loaded_pair, reloaded.source_stamp, cached, sidecar)
        preview = prepare_native_preview(session.loaded_pair, deepcopy(cached), native_key(session),
                                         (960, 640), CancellationToken())
        display = tuple(master_to_uint8(transform_rgb(eye, loaded.icc_profile)) for eye in reference)
        assert all(np.array_equal(a, b) for a, b in zip(display, preview[1:3], strict=True))
    source.sidecar_path.unlink()


def benchmark(label, source, method, known=None, geometry=None, verify=False):
    processed, captured, analysis_ms = fit_capture(source, method, geometry)
    loaded, state = processed.loaded_pair, processed.state
    master_shape = _oriented_pair(loaded, state)[0].shape[:2]
    if geometry is not None:
        state.framing.crop_zoom_index = 3
        state.framing.pan_x_permille = 350
    (left, right, info), maps, warp_origin = crop_capture(loaded, state)
    raw = left, right
    dx, dy = state.effective_offset_x_px, state.effective_offset_y_px
    ah, aw = info.aligned_shape
    box = framing_crop_box(aw - abs(dx), ah - abs(dy), state.framing.aspect,
                           CROP_ZOOM_LEVELS[state.framing.crop_zoom_index],
                           state.framing.pan_x_permille, state.framing.pan_y_permille, info.input_aspect)
    origins = np.asarray(((max(0, dx), max(0, dy)), (max(0, -dx), max(0, -dy))))
    origins += np.asarray(box[:2]) + warp_origin
    assert (box[3] - box[1], box[2] - box[0]) == raw[0].shape[:2]
    source_points = captured['points']
    if state.geometry.active:
        matrix = np.linalg.inv(geometry_matrix(captured['shape'], state.geometry))
        source_points = np.stack([cv2.perspectiveTransform(p[None], matrix)[0] for p in source_points])
    source_points = ((source_points + .5) * (np.asarray(master_shape[::-1]) / captured['shape'][::-1]) - .5)
    baseline_ms, candidate_ms = [], []
    for _ in range(3):
        start = perf_counter()
        baseline = fit_symmetric_color_transfer(*raw)
        baseline_ms.append((perf_counter() - start) * 1000)
        start = perf_counter()
        in_crop = to_crop(source_points, maps, origins)
        chosen, transfers, details, patches, groups = choose(raw, in_crop, baseline)
        candidate_ms.append((perf_counter() - start) * 1000)
    audit = score(tuple(eye[groups == 2] for eye in patches), transfers)
    external = external_matches(raw)
    external = external[:, inside(external, left.shape, 5 * max(1., left.shape[1] / 1440)), :]
    external_score = score(patch_pixels(raw, external, max(1., left.shape[1] / 1440)), transfers)
    known_score = None
    if known is not None:
        shift, mask = known
        interior = cv2.erode(mask.astype(np.uint8), np.ones((7, 7), np.uint8)).astype(bool)
        y, x = np.where(interior & (np.indices(mask.shape) % 12 == 5).all(axis=0))
        known_points = to_crop(np.stack((np.column_stack((x, y)), np.column_stack((x + shift, y)))),
                               maps, origins)
        known_points = known_points[:, inside(known_points, left.shape, 4), :]
        known_score = score(patch_pixels(raw, known_points, 1.), transfers)
    if verify:
        verify_render(processed, state, raw, transfers[chosen])
    result = dict(label=label, method=method, size=list(left.shape[:2][::-1]),
                  matches=source_points.shape[1], chosen=chosen, **details,
                  independent_reuse_audit=audit, independent_sift_points=external.shape[1],
                  independent_sift_audit=external_score, known=known_score,
                  analysis_ms=round(analysis_ms, 2), current_fit_ms=round(median(baseline_ms), 2),
                  reuse_extra_ms=round(median(candidate_ms), 2), roundtrip=verify)
    print('REUSE', json.dumps(result), flush=True)
    return result


def synthetic_sources(root):
    for name, pair, known in synthetic_pairs():
        left, right = [root / f'{name}_{eye}.png' for eye in ('L', 'R')]
        for path, eye in zip((left, right), pair, strict=True):
            Image.fromarray(eye).save(path)
        yield name, source_from_pair(left, right, root), known


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--camera', nargs=2, metavar=('NAME', 'DIRECTORY'), action='append')
    parser.add_argument('--limit', default=6, type=int)
    args = parser.parse_args()
    cv2.setNumThreads(2)
    cv2.ocl.setUseOpenCL(False)
    rows = []
    with TemporaryDirectory(prefix='stereofine-color-reuse-') as temporary:
        root = Path(temporary) / 'inputs'
        if args.camera:
            for label, directory in args.camera:
                path = Path(directory)
                sources = discover_pair_sources(path)
                if not sources:
                    sources = discover_stereo_file_sources(path)
                print('CAMERA', label, 'sources', len(sources), flush=True)
                for index in np.linspace(0, len(sources) - 1, min(args.limit, len(sources)), dtype=int):
                    source = sources[index]
                    rows.append(benchmark(f'{label}/{source.base_name}', source, 'AKAZE'))
        else:
            prepare(root)
            for source in make_sources(root):
                for method in ('AKAZE', 'SIFT'):
                    rows.append(benchmark(source.base_name, source, method, verify=method == 'AKAZE'))
                if source.base_name == 'Foundation':
                    rows.append(benchmark('Foundation/H+crop', source, 'AKAZE',
                                          geometry=GeometryAdjustment(15, 8), verify=True))
            for label, source, known in synthetic_sources(root):
                rows.append(benchmark(label, source, 'AKAZE', known=known, verify=True))
    assert rows, 'No stereo pairs were tested'
    Path('color-reuse-results.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
