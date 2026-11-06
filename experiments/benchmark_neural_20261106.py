"""Isolated public-data research. Never imported by the application."""
from __future__ import annotations
import argparse
import gc
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import resource
import sys
import threading
import time
import traceback
import urllib.request

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from stereofine.alignment import (analyze_pair_features, resize_pair_for_analysis,
    _fit_vertical_ransac_filter, _analyze_matched_points, warp_pair_symmetric)
from stereofine.alignment_refinement import refine_alignment, corrected_point_residuals
from stereofine.lens_refinement import refine_residual_field

BASE = 'https://vision.middlebury.edu/stereo/data/scenes2014/datasets'
SCENES = ('Adirondack', 'Pipes', 'Playroom')
LONG_SIDE = 1600
SEED = 20261106
THREADS = 4


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def download(url, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        last = None
        for attempt in range(4):
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'StereoFine-research/1.2'})
                with urllib.request.urlopen(req, timeout=120) as response:
                    data = response.read()
                path.write_bytes(data)
                break
            except Exception as exc:
                last = exc
                if attempt == 3:
                    raise last
                time.sleep(2 * (attempt + 1))
    return dict(url=url, sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                bytes=path.stat().st_size)


def pfm(path):
    with path.open('rb') as stream:
        assert stream.readline().strip() == b'Pf'
        w, h = map(int, stream.readline().split())
        scale = float(stream.readline())
        array = np.frombuffer(stream.read(), dtype='<f4' if scale < 0 else '>f4')
        return np.flipud(array.reshape(h, w)).copy()


def transform(points, matrix):
    return np.asarray(points) @ matrix[:, :2].T + matrix[:, 2]


def prepare(root):
    manifest, stamps = [], {}
    for scene in SCENES:
        folder = root / 'download' / scene
        for name in ('im0.png', 'im1.png', 'im1L.png', 'disp0.pfm', 'disp1.pfm'):
            stamps[scene + '/' + name] = download(f'{BASE}/{scene}-perfect/{name}', folder / name)
        left_original = np.asarray(Image.open(folder / 'im0.png').convert('RGB'))
        oh, ow = left_original.shape[:2]
        scale = min(1., LONG_SIDE / max(oh, ow))
        w, h = round(ow * scale), round(oh * scale)
        sx, sy = w / ow, h / oh
        left = cv2.resize(left_original, (w, h), interpolation=cv2.INTER_LANCZOS4)
        d0, d1 = pfm(folder / 'disp0.pfm'), pfm(folder / 'disp1.pfm')
        # Independent dense GT points, never supplied to a matcher or fitter.
        yy, xx = np.mgrid[20:oh-20:12, 20:ow-20:12]
        xx, yy = xx.ravel(), yy.ravel()
        ds = d0[yy, xx]
        finite = np.isfinite(ds)
        rx = np.rint(xx - np.where(finite, ds, 0)).astype(int)
        valid = finite & (rx > 20) & (rx < ow-20)
        safe_x = np.clip(rx, 0, ow-1)
        other = d1[yy, safe_x]
        valid &= np.isfinite(other) & (np.abs(np.where(np.isfinite(other), other, 0)-np.where(finite, ds, 0)) < 1.)
        # Reject depth boundaries where image downsampling mixes surfaces.
        for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
            neighbor = d0[yy+dy, xx+dx]
            valid &= np.isfinite(neighbor) & (np.abs(np.where(np.isfinite(neighbor), neighbor, 0)-np.where(finite, ds, 0)) < 1.5)
        xx, yy, ds = xx[valid], yy[valid], ds[valid]
        p = np.column_stack(((xx+.5)*sx-.5, (yy+.5)*sy-.5))
        q0 = np.column_stack(((xx-ds+.5)*sx-.5, (yy+.5)*sy-.5))
        assert len(p) >= 1000
        for challenge in (False, True):
            name = scene + ('_light_affine' if challenge else '_aligned')
            right_original = np.asarray(Image.open(folder / ('im1L.png' if challenge else 'im1.png')).convert('RGB'))
            right = cv2.resize(right_original, (w, h), interpolation=cv2.INTER_LANCZOS4)
            matrix = (cv2.getRotationMatrix2D(((w-1)/2, (h-1)/2), .24, 1.003)
                      if challenge else np.array([[1., 0., 0.], [0., 1., 0.]]))
            if challenge:
                matrix[:, 2] += np.array([1.7, 3.6])
                right = cv2.warpAffine(right, matrix, (w, h), flags=cv2.INTER_LANCZOS4)
            q = transform(q0, matrix)
            keep = (q[:, 0] > 12) & (q[:, 0] < w-13) & (q[:, 1] > 12) & (q[:, 1] < h-13)
            assert np.max(np.abs(transform(q, cv2.invertAffineTransform(matrix))-q0)) < 1e-8
            case_dir = root / 'cases' / name
            case_dir.mkdir(parents=True, exist_ok=True)
            Image.fromarray(left).save(case_dir / 'left.png')
            Image.fromarray(right).save(case_dir / 'right.png')
            np.savez_compressed(case_dir / 'ground_truth.npz', left=p[keep], right=q[keep])
            manifest.append(dict(name=name, scene=scene, challenge=challenge, shape=[h, w],
                input_scale=[sx, sy], original_shape=[oh, ow], gt_count=int(keep.sum()),
                right_transform=matrix.tolist(), directory=str(case_dir)))
    write_json(root / 'manifest.json', dict(cases=manifest, inputs=stamps))
    return manifest


def metrics(values):
    a = np.abs(np.asarray(values, dtype=float))
    if not len(a):
        return dict(count=0)
    return dict(count=len(a), mean=float(a.mean()), median=float(np.median(a)),
        p90=float(np.percentile(a, 90)), p95=float(np.percentile(a, 95)),
        maximum=float(a.max()), over_05_percent=float(100*np.mean(a > .5)),
        over_1_percent=float(100*np.mean(a > 1.)))


def ground_truth_quality(correction, p, q, shape):
    residual = corrected_point_residuals(correction, p, q, shape, 1.)
    h, w = shape
    cells = np.clip((p[:, 1]/h*5).astype(int), 0, 4)*5 + np.clip((p[:, 0]/w*5).astype(int), 0, 4)
    regions = {str(i): metrics(residual[cells == i]) for i in range(25)}
    corners = {}
    for name, mask in {
        'top_left': (p[:, 0] < .2*w) & (p[:, 1] < .2*h),
        'top_right': (p[:, 0] > .8*w) & (p[:, 1] < .2*h),
        'bottom_left': (p[:, 0] < .2*w) & (p[:, 1] > .8*h),
        'bottom_right': (p[:, 0] > .8*w) & (p[:, 1] > .8*h),
    }.items():
        corners[name] = metrics(residual[mask])
    return dict(global_error=metrics(residual), grid_5x5=regions, corners=corners,
        worst_cell_p95=max((x['p95'] for x in regions.values() if x['count'] >= 20), default=None))


def fit_neural(left, right, lp, rp, label):
    ga, gb, scale = resize_pair_for_analysis(left, right, 3000)
    lp, rp = (lp+.5)*scale-.5, (rp+.5)*scale-.5
    selected = _fit_vertical_ransac_filter(.5*(lp+rp), rp, lp, ga.shape,
                                          threshold_analysis_px=3.)
    mask = np.asarray(selected['mask'], bool)
    fit = _analyze_matched_points(lp, rp, ga.shape, scale, label, inlier_mask=mask)
    fit = refine_alignment(fit, lp, rp, mask, ga, gb, scale, label)
    return refine_residual_field(fit, lp, rp, ga, gb, scale)


def match_quality(lp, rp, case, d0):
    h, w = case['shape']
    oh, ow = case['original_shape']
    sx, sy = case['input_scale']
    native = (lp + .5)/np.array([sx, sy])-.5
    ix, iy = np.rint(native).astype(int).T
    inside = (ix >= 2) & (ix < ow-2) & (iy >= 2) & (iy < oh-2)
    ii = np.flatnonzero(inside)
    ds = d0[iy[ii], ix[ii]]
    ok = np.isfinite(ds)
    # GT-based raw-match scores are diagnostic only, never an input filter.
    ii, ds = ii[ok], ds[ok]
    pred0 = transform(rp[ii], cv2.invertAffineTransform(np.asarray(case['right_transform'])))
    expected = lp[ii].copy()
    expected[:, 0] -= ds*sx
    error = np.linalg.norm(pred0-expected, axis=1)
    return dict(total_matches=len(lp), gt_available_matches=len(ii),
        precision_1px_percent=float(100*np.mean(error <= 1.)) if len(ii) else None,
        precision_3px_percent=float(100*np.mean(error <= 3.)) if len(ii) else None,
        vertical_error=metrics(pred0[:, 1]-expected[:, 1]))


def initialize(method):
    if method == 'baseline':
        return None
    import torch
    torch.set_num_threads(THREADS)
    torch.set_num_interop_threads(1)
    torch.manual_seed(SEED)
    if method == 'loma_b':
        from loma import LoMa, LoMaB
        return LoMa(LoMaB()).eval()
    from flexglue import FlexGlue
    return FlexGlue(mp=None, refine=method == 'flexglue_refined',
                    max_num_samples=4096).eval()


def matches(model, method, case):
    folder = Path(case['directory'])
    if method == 'loma_b':
        p, q = model.match(str(folder/'left.png'), str(folder/'right.png'), num_keypoints=2048)
        # LoMa's normalized grid uses align_corners=False; its public pixel
        # conversion returns corner coordinates, like FlexGlue. OpenCV uses centres.
        return np.asarray(p, float)-.5, np.asarray(q, float)-.5
    import torch
    from flexglue.utils import load_image, pack_matches, rbd
    with torch.inference_mode():
        pred = rbd(pack_matches(model.match_pair(load_image(str(folder/'left.png')),
                                                 load_image(str(folder/'right.png')))))
    idx = pred['matches']
    return (pred['keypoints0'][idx[:, 0]].cpu().numpy().astype(float)-.5,
            pred['keypoints1'][idx[:, 1]].cpu().numpy().astype(float)-.5)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--method', required=True, choices=['baseline', 'loma_b', 'flexglue', 'flexglue_refined'])
    parser.add_argument('--root', type=Path, default=Path('build/neural-20261106'))
    args = parser.parse_args()
    root = args.root
    root.mkdir(parents=True, exist_ok=True)
    cv2.setNumThreads(THREADS)
    cv2.setRNGSeed(SEED)
    np.random.seed(SEED)
    import psutil
    proc = psutil.Process()
    peak, stop = [0], threading.Event()
    def sample():
        while not stop.wait(.05):
            peak[0] = max(peak[0], proc.memory_info().rss)
    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    report = dict(method=args.method, source_commit=os.getenv('GITHUB_SHA'),
        cpu=platform.processor(), platform=platform.platform(), logical_cpus=os.cpu_count(),
        total_memory_bytes=psutil.virtual_memory().total, threads=THREADS,
        long_side=LONG_SIDE, seed=SEED, cases=[], dependency_versions={},
        model_settings={'loma_b': 'Official LoMa-B, 2048 keypoints, default mixed precision',
            'flexglue': 'Official sampled matching, 512x512, 4096 samples, fp32 on CPU',
            'flexglue_refined': 'As FlexGlue, plus official RoMa v2 refiners at 512x512',
            'baseline': 'Unchanged StereoFine 1.2 AKAZE and SIFT, analysis limit 3000'}[args.method])
    dest = root / (args.method + '.json')
    try:
        cases = prepare(root)
        report['inputs'] = json.loads((root/'manifest.json').read_text())['inputs']
        start = time.perf_counter()
        model = initialize(args.method)
        report['model_load_seconds_including_downloads'] = time.perf_counter()-start
        for case in cases:
            folder = Path(case['directory'])
            a = np.asarray(Image.open(folder/'left.png').convert('RGB'))
            b = np.asarray(Image.open(folder/'right.png').convert('RGB'))
            gt = np.load(folder/'ground_truth.npz')
            p, q = gt['left'], gt['right']
            identity = dict(scale=1., rotation_deg=0., vertical_shift_px=0.)
            for mode in (('AKAZE', 'SIFT') if args.method == 'baseline' else (args.method,)):
                row = dict(name=case['name'], method=mode, shape=case['shape'],
                    ground_truth_points=len(p), before=ground_truth_quality(identity, p, q, a.shape[:2]))
                print('BEGIN', case['name'], mode, flush=True)
                peak[0] = proc.memory_info().rss
                started = time.perf_counter()
                try:
                    if args.method == 'baseline':
                        fit = analyze_pair_features(a, b, mode, 3000)
                        row['total_seconds'] = time.perf_counter()-started
                    else:
                        lp, rp = matches(model, args.method, case)
                        row['matching_seconds'] = time.perf_counter()-started
                        row['match_quality'] = match_quality(lp, rp, case,
                            pfm(root/'download'/case['scene']/'disp0.pfm'))
                        np.savez_compressed(root/(case['name']+'_'+mode+'_matches.npz'), left=lp, right=rp)
                        fit = fit_neural(a, b, lp, rp, mode)
                        row['total_seconds'] = time.perf_counter()-started
                    row['after'] = ground_truth_quality(fit['correction'], p, q, a.shape[:2])
                    row['model'] = fit.get('model')
                    row['correction'] = fit['correction']
                    row['status'] = 'ok'
                    # Exercise the actual raster correction as well as point mapping.
                    l, r = warp_pair_symmetric(a, b, fit['correction'])
                    row['rendered_shape'] = list(l.shape)
                    if case['challenge']:
                        preview = np.dstack((l[:, :, 0], r[:, :, 1], r[:, :, 2]))
                        Image.fromarray(preview).resize((800, round(800*l.shape[0]/l.shape[1]))).save(
                            root/(case['name']+'_'+mode+'_anaglyph.png'))
                    del l, r
                except Exception as exc:
                    row.update(status='error', error=repr(exc), traceback=traceback.format_exc(),
                               total_seconds=time.perf_counter()-started)
                    traceback.print_exc()
                row['peak_rss_bytes'] = peak[0]
                report['cases'].append(row)
                write_json(dest, report)
                print('RESULT', json.dumps({k:v for k,v in row.items() if k not in ('correction','before','after','traceback')}),
                      'AFTER', row.get('after',{}).get('global_error'), flush=True)
                gc.collect()
        report['status'] = 'completed'
    except Exception as exc:
        report.update(status='error', error=repr(exc), traceback=traceback.format_exc())
        traceback.print_exc()
    finally:
        stop.set()
        import importlib.metadata as metadata
        for package in ('torch','torchvision','numpy','opencv-python','Pillow','einops','psutil','lomatch'):
            try:
                report['dependency_versions'][package] = metadata.version(package)
            except metadata.PackageNotFoundError:
                pass
        report['process_peak_rss_bytes'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024
        if (Path(os.environ.get('TORCH_HOME', str(Path.home()/'.cache/torch')))/'hub/checkpoints').exists():
            report['weight_files'] = {p.name:dict(bytes=p.stat().st_size,
                sha256=hashlib.file_digest(p.open('rb'), 'sha256').hexdigest())
                for p in (Path(os.environ.get('TORCH_HOME', str(Path.home()/'.cache/torch')))/'hub/checkpoints').glob('*') if p.is_file()}
        write_json(dest, report)
    if report['status'] != 'completed' or any(x['status'] != 'ok' for x in report['cases']):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
