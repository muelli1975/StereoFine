"""Isolated color preview and stereo color matching measurements."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
from time import perf_counter
from types import SimpleNamespace
import hashlib
import json
import os

import cv2
import numpy as np

from stereofine.color_profiles import transform_rgb
from stereofine.color_transfer import apply_symmetric_color_transfer, fit_symmetric_color_transfer
from stereofine.inputs import LoadedStereoPair, master_to_uint8
from stereofine.native_preview import (
    fit_display_pair, mask_preview_pair, native_key, prepare_native_preview, preview_image,
)
from stereofine.processing import ProcessingOptions, process_source
from stereofine.render import match_final_pair_color, render_final_pair
from stereofine.state import PairState
from stereofine.worker import CancellationToken
from tools.benchmark_cpu_batch import make_sources, prepare


BOUNDS = (1280, 800)
MODE = 'Farbig'
REPETITIONS = 3


def compose(eyes, state):
    return preview_image(*mask_preview_pair(*eyes, state, state.look), MODE)


def fit_display(eyes, profile):
    rgb = (master_to_uint8(transform_rgb(eye, profile)) for eye in eyes)
    return fit_display_pair(*rgb, BOUNDS)


def digest(image):
    return image.size, hashlib.sha256(image.tobytes()).hexdigest()


def timed_preview(loaded, base, first_only):
    state = deepcopy(base)
    token = CancellationToken()
    session = SimpleNamespace(state=state, loaded_pair=loaded)
    start = perf_counter()
    if first_only:
        left, right, _ = render_final_pair(loaded, state, apply_color=False,
                                           apply_floating_window=False, preview_bounds=BOUNDS,
                                           retain_aligned=True)
        raw = left, right

        def fitted(enabled):
            eyes = match_final_pair_color(*raw, state)[:2] if enabled else raw
            return fit_display(eyes, loaded.icc_profile)

        first = compose(fitted(state.color.enabled), state)
    else:
        result = prepare_native_preview(loaded, state, native_key(session), BOUNDS, token, MODE)
        variants = result[4][2]

        def fitted(enabled):
            return variants[enabled]

        first = compose(fitted(state.color.enabled), state)
    first_ready = perf_counter()
    second = compose(fitted(not state.color.enabled), state)
    second_ready = perf_counter()
    return np.array([first_ready - start, second_ready - first_ready]) * 1000, (digest(first), digest(second))


def preview_comparison(name, loaded, base):
    output = []
    for enabled in (False, True):
        for cached in (False, True):
            state = deepcopy(base)
            state.color.enabled = enabled
            if not cached:
                state.color.valid = False
            trials = {False: [], True: []}
            for repetition in range(REPETITIONS):
                expected = None
                for first_only in (False, True) if repetition % 2 == 0 else (True, False):
                    times, signature = timed_preview(loaded, state, first_only)
                    if expected is None:
                        expected = signature
                    else:
                        assert signature == expected, (name, enabled, cached)
                    trials[first_only].append(times.tolist())
            row = dict(name=name, depth=str(loaded.left.dtype), enabled=enabled, cached=cached,
                       baseline=np.median(trials[False], axis=0).tolist(),
                       candidate=np.median(trials[True], axis=0).tolist())
            output.append(row)
            print('PREVIEW', json.dumps(row), flush=True)
    return output


def histogram_distance(pair):
    channels = []
    equal = True
    for channel in range(3):
        counts = [np.bincount(eye[..., channel].ravel(), minlength=256) for eye in pair]
        equal &= np.array_equal(*counts)
        cumulative = [np.cumsum(x / x.sum()) for x in counts]
        channels.append(np.abs(cumulative[0] - cumulative[1]).sum())
    return float(np.mean(channels)), bool(equal)


def scaled_pair(pair):
    h, w = pair[0].shape[:2]
    scale = min(1., 1440 / w)
    if scale == 1.:
        return pair
    return tuple(cv2.resize(eye, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
                 for eye in pair)


def patch_matches(pair):
    sift = cv2.SIFT_create(nfeatures=2400)
    inputs = [sift.detectAndCompute(cv2.cvtColor(eye, cv2.COLOR_RGB2GRAY), None) for eye in pair]
    (lk, ld), (rk, rd) = inputs
    if ld is None or rd is None or min(len(ld), len(rd)) < 2:
        return [], []
    matcher = cv2.BFMatcher(cv2.NORM_L2)
    reverse = {m.queryIdx: m.trainIdx for m in matcher.match(rd, ld)}
    h, w = pair[0].shape[:2]
    train, test = [], []
    for first, second in matcher.knnMatch(ld, rd, k=2):
        if first.distance >= .72 * second.distance or reverse.get(first.trainIdx) != first.queryIdx:
            continue
        l, r = lk[first.queryIdx].pt, rk[first.trainIdx].pt
        if abs(l[1] - r[1]) > 1.25 or abs(l[0] - r[0]) > .20 * w:
            continue
        if any(not (5 <= x < w - 5 and 5 <= y < h - 5) for x, y in (l, r)):
            continue
        if (int(l[0] // 80) + int(l[1] // 80)) % 2:
            test.append((l, r))
        else:
            train.append((l, r))
    return train, test


def patches(pair, points):
    return tuple(np.stack([cv2.getRectSubPix(eye, (7, 7), x[side]) for x in points])
                 for side, eye in enumerate(pair))


def score_patches(pair, points):
    left, right = patches(scaled_pair(pair), points)
    return float(np.abs(left.mean(axis=(1, 2)) - right.mean(axis=(1, 2))).mean())


def known_mae(pair, known):
    shift, mask = known
    left = pair[0][:, :pair[0].shape[1] - shift][mask]
    right = pair[1][:, shift:][mask]
    return float(np.abs(left.astype(np.float32) - right).mean())


def quality_comparison(name, raw, known=None):
    raw = tuple(master_to_uint8(eye) for eye in raw)
    baseline = apply_symmetric_color_transfer(*raw, fit_symmetric_color_transfer(*raw))
    start = perf_counter()
    reduced = scaled_pair(raw)
    train, test = patch_matches(reduced)
    candidate = None
    if min(len(train), len(test)) >= 30:
        selected = patches(reduced, train)
        samples = tuple(eye.reshape(-1, 7, 3) for eye in selected)
        candidate = apply_symmetric_color_transfer(*raw, fit_symmetric_color_transfer(*samples))
    millis = (perf_counter() - start) * 1000
    variants = {'original': raw, 'current': baseline}
    if candidate is not None:
        variants['matched_patches'] = candidate
    rows = {}
    for key, pair in variants.items():
        distance, equal = histogram_distance(pair)
        rows[key] = dict(histogram_distance=distance, histograms_equal=equal,
                         heldout_mae=score_patches(pair, test) if len(test) >= 30 else None,
                         known_mae=known_mae(pair, known) if known is not None else None)
    result = dict(name=name, train=len(train), heldout=len(test),
                  matching_prototype_ms=millis, variants=rows)
    print('QUALITY', json.dumps(result), flush=True)
    return result


def synthetic_pairs():
    rng = np.random.default_rng(34)
    w, h = 900, 600
    x, y = np.meshgrid(np.linspace(0, 1, w), np.linspace(0, 1, h))
    noise = cv2.GaussianBlur(rng.integers(0, 256, (h, w), np.uint8), (3, 3), 0).astype(float) / 255
    base = np.stack([.12 + .25 * x + .21 * y + .36 * noise,
                     .15 + .18 * x + .29 * y + .31 * noise,
                     .09 + .31 * x + .20 * y + .33 * noise], axis=-1)
    base = np.rint(base * 255).astype(np.uint8)
    for _ in range(180):
        cx, cy = rng.integers((8, 8), (w - 8, h - 8))
        cv2.circle(base, (int(cx), int(cy)), int(rng.integers(2, 8)),
                   tuple(float(v) for v in rng.integers(35, 229, 3)), -1)
    cast = np.rint(np.clip(base * [1.13, .92, .80] + [11, 3, 5], 0, 255)).astype(np.uint8)
    yield 'known_cast', (base, cast), (0, np.ones((h, w), bool))

    shift = 61
    shifted = np.zeros_like(base)
    shifted[:, shift:] = base[:, :-shift]
    shifted[:, :shift] = (52, 126, 180)
    shifted[0:290, 520:880] = (228, 75, 48)
    common = np.ones((h, w - shift), bool)
    common[0:290, 520-shift:880-shift] = False
    yield 'known_occlusion', (base, shifted), (shift, common)


def main():
    cv2.setNumThreads(2)
    cv2.ocl.setUseOpenCL(False)
    rows, quality = [], []
    with TemporaryDirectory(prefix='stereofine-color-bench-') as temporary:
        root = Path(temporary) / 'inputs'
        prepare(root)
        for source in make_sources(root):
            result = process_source(source, ProcessingOptions(save_sidecar=False, keep_loaded_pair=True))
            loaded, state = result.loaded_pair, result.state
            raw = render_final_pair(loaded, deepcopy(state), apply_color=False,
                                    apply_floating_window=False)[:2]
            match_final_pair_color(*raw, state)
            rows.extend(preview_comparison(source.base_name, loaded, state))
            quality.append(quality_comparison(source.base_name, raw))
        for name, pair, known in synthetic_pairs():
            quality.append(quality_comparison(name, pair, known))
            if name == 'known_cast':
                left, right = (np.uint16(eye) * 257 for eye in pair)
                h, w = left.shape[:2]
                loaded = LoadedStereoPair(left, right, Path('l.tiff'), Path('r.tiff'), 'pair',
                                          w, h, w, h, w, h)
                state = PairState()
                match_final_pair_color(left, right, state)
                rows.extend(preview_comparison('synthetic_uint16', loaded, state))

    totals = {}
    for enabled in (False, True):
        for cached in (False, True):
            selected = [r for r in rows if r['enabled'] == enabled and r['cached'] == cached]
            totals[f'enabled={enabled},cached={cached}'] = {
                key: [median(r[key][i] for r in selected) for i in range(2)]
                for key in ('baseline', 'candidate')
            }
    print('TOTALS', json.dumps(totals), flush=True)
    Path('color-preview-results.json').write_text(json.dumps(
        dict(cpus=os.cpu_count(), cv_threads=cv2.getNumThreads(),
             repetitions=REPETITIONS, timings=rows, totals=totals, quality=quality),
        indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
