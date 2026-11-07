"""Reproducible pinhole stereo fixtures and a read-only alignment audit.

No photograph, production parameter, release or user sidecar is modified.
Scene points are independent geometric controls, not feature-fit measurements.
The output-map check numerically inverts the actual maps sent to cv2.remap.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import dataclass
import gc
import hashlib
import json
import math
from pathlib import Path
import sys
import time
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from stereofine import alignment
from stereofine.state import PairState
from stereofine.status import _vergence_text
from stereofine.i18n import Translator


WIDTH, HEIGHT = 3000, 2000
BASELINE_M = .065
HORIZONTAL_FOV_DEG = 60.
FOCAL = WIDTH / (2 * math.tan(math.radians(HORIZONTAL_FOV_DEG / 2)))
K = np.array([[FOCAL, 0, (WIDTH-1)/2], [0, FOCAL, (HEIGHT-1)/2], [0, 0, 1.]])
# Frozen before running the experiment. Angles are physical camera yaw in degrees.
CASES = [
    dict(name='00_parallel', left_yaw=0., right_yaw=0., right_pitch=0., right_roll=0.),
    dict(name='01_convergent_0p5', left_yaw=.25, right_yaw=-.25, right_pitch=0., right_roll=0.),
    dict(name='02_convergent_2', left_yaw=1., right_yaw=-1., right_pitch=0., right_roll=0.),
    dict(name='03_convergent_4', left_yaw=2., right_yaw=-2., right_pitch=0., right_roll=0.),
    dict(name='04_convergent_8_stress', left_yaw=4., right_yaw=-4., right_pitch=0., right_roll=0.),
    dict(name='05_asymmetric', left_yaw=.5, right_yaw=-2., right_pitch=.4, right_roll=.3),
    dict(name='06_divergent_2', left_yaw=-1., right_yaw=1., right_pitch=0., right_roll=0.),
]


def rotation(yaw=0., pitch=0., roll=0.):
    a, b, c = np.radians([yaw, pitch, roll])
    ry = np.array([[np.cos(a), 0, np.sin(a)], [0, 1, 0], [-np.sin(a), 0, np.cos(a)]])
    rx = np.array([[1, 0, 0], [0, np.cos(b), -np.sin(b)], [0, np.sin(b), np.cos(b)]])
    rz = np.array([[np.cos(c), -np.sin(c), 0], [np.sin(c), np.cos(c), 0], [0, 0, 1]])
    return ry @ rx @ rz


@dataclass
class Camera:
    center: np.ndarray
    camera_to_world: np.ndarray

    def project(self, world):
        p = (np.asarray(world) - self.center) @ self.camera_to_world
        return p[:, :2] / p[:, 2:3] * FOCAL + K[:2, 2], p[:, 2]


def cameras(case):
    return (Camera(np.array([-BASELINE_M/2, 0., 0.]), rotation(case['left_yaw'])),
            Camera(np.array([BASELINE_M/2, 0., 0.]), rotation(
                case['right_yaw'], case['right_pitch'], case['right_roll'])))


def texture(seed, label, width=768, height=512):
    rng = np.random.default_rng(seed)
    coarse = rng.integers(35, 218, (16, 24, 3), dtype=np.uint8)
    image = cv2.resize(coarse, (width, height), interpolation=cv2.INTER_CUBIC)
    for i in range(190):
        x, y = int(rng.integers(18, width-18)), int(rng.integers(18, height-18))
        color = tuple(int(x) for x in rng.integers(15, 245, 3))
        r = int(rng.integers(3, 16))
        if i % 3:
            cv2.circle(image, (x, y), r, color, -1, cv2.LINE_AA)
            cv2.circle(image, (x, y), max(1, r//3), (245, 245, 245), -1, cv2.LINE_AA)
        else:
            cv2.rectangle(image, (x-r, y-r), (x+r, y+r), color, 2, cv2.LINE_AA)
    # Distinct patterns at every grid location reduce repeated-texture ambiguity.
    for y in range(35, height-20, 70):
        for x in range(35, width-20, 70):
            bits = rng.integers(0, 2, (4, 4), dtype=np.uint8) * 220 + 15
            tile = cv2.resize(bits, (20, 20), interpolation=cv2.INTER_NEAREST)
            image[y:y+20, x:x+20] = tile[..., None]
    cv2.rectangle(image, (2, 2), (width-3, height-3), (245, 245, 245), 4)
    cv2.putText(image, label, (22, 35), cv2.FONT_HERSHEY_SIMPLEX, .8,
                (15, 15, 15), 5, cv2.LINE_AA)
    cv2.putText(image, label, (22, 35), cv2.FONT_HERSHEY_SIMPLEX, .8,
                (250, 250, 250), 2, cv2.LINE_AA)
    return image


@dataclass
class Plane:
    origin: np.ndarray
    u: np.ndarray
    v: np.ndarray
    pixels: np.ndarray
    label: str

    def points(self, nx=32, ny=22):
        a, b = np.meshgrid(np.linspace(.025, .975, nx), np.linspace(.025, .975, ny))
        return self.origin + a.reshape(-1, 1)*self.u + b.reshape(-1, 1)*self.v


def scene():
    specs = [
        ((-6., -4., 9.), (12., 0., 0.), (0., 8., 0.), 'BACK 9m'),
        ((-5., 1.8, 2.5), (10., 0., 0.), (0., 0., 8.), 'FLOOR'),
        ((-2.7, -1.7, 6.3), (1.3, 0., .2), (0., 1.05, .1), 'REAR LEFT 6.3m'),
        ((.7, .5, 6.2), (1.4, 0., -.3), (0., 1.1, .2), 'REAR RIGHT 6.2m'),
        ((.25, -1.05, 4.2), (1.2, 0., .2), (0., .85, .1), 'MID RIGHT 4.2m'),
        ((-1.8, .25, 4.7), (1.05, 0., .15), (0., .9, -.2), 'MID LEFT 4.7m'),
        ((-.6, -.25, 2.7), (.55, 0., 0.), (0., .75, .1), 'NEAR 2.7m'),
        ((.45, .3, 3.1), (.65, 0., -.15), (0., .55, .1), 'NEAR 3.1m'),
    ]
    return [Plane(np.array(o), np.array(u), np.array(v),
                  texture(1950+i, text, 1536 if i == 0 else 768,
                          1024 if i == 0 else 512), text)
            for i, (o, u, v, text) in enumerate(specs)]


def render_scene(planes, camera):
    image = np.zeros((HEIGHT, WIDTH, 3), np.uint8)
    depth = np.full((HEIGHT, WIDTH), np.inf, np.float32)
    surface = np.full((HEIGHT, WIDTH), -1, np.int16)
    world_to_camera = camera.camera_to_world.T
    for index, plane in enumerate(planes):
        th, tw = plane.pixels.shape[:2]
        basis = np.column_stack([plane.u/(tw-1), plane.v/(th-1), plane.origin-camera.center])
        hmat = K @ world_to_camera @ basis
        corners = np.array([[0, 0, 1], [tw-1, 0, 1], [0, th-1, 1], [tw-1, th-1, 1.]])
        projected = corners @ hmat.T
        if np.min(projected[:, 2]) <= 0:
            raise ValueError('Fixture surface crosses the camera plane.')
        corners2 = projected[:, :2]/projected[:, 2:3]
        x0, y0 = np.maximum([0, 0], np.floor(corners2.min(axis=0)).astype(int))
        x1, y1 = np.minimum([WIDTH, HEIGHT], np.ceil(corners2.max(axis=0)+1).astype(int))
        if x1 <= x0 or y1 <= y0:
            continue
        roi_h = np.array([[1., 0, -x0], [0, 1., -y0], [0, 0, 1.]]) @ hmat
        pixels = cv2.warpPerspective(plane.pixels, roi_h, (x1-x0, y1-y0), flags=cv2.INTER_LANCZOS4)
        yy, xx = np.indices((y1-y0, x1-x0), dtype=np.float32)
        inv = np.linalg.inv(roi_h)
        divisor = inv[2, 0]*xx + inv[2, 1]*yy + inv[2, 2]
        tx = (inv[0, 0]*xx + inv[0, 1]*yy + inv[0, 2])/divisor
        ty = (inv[1, 0]*xx + inv[1, 1]*yy + inv[1, 2])/divisor
        valid = (tx >= 0) & (tx <= tw-1) & (ty >= 0) & (ty <= th-1)
        zrow = (world_to_camera @ basis)[2]
        z = zrow[0]*tx + zrow[1]*ty + zrow[2]
        old = depth[y0:y1, x0:x1]
        valid &= (z > 0) & (z < old)
        image[y0:y1, x0:x1][valid] = pixels[valid]
        old[valid] = z[valid]
        surface[y0:y1, x0:x1][valid] = index
    return image, surface


def controls(planes, cams, surfaces):
    world = np.concatenate([p.points(60, 40) if i == 0 else p.points()
                            for i, p in enumerate(planes)])
    ids = np.concatenate([np.full(2400 if i == 0 else 704, i) for i in range(len(planes))])
    coords = [cam.project(world)[0] for cam in cams]
    valid = np.ones(len(world), bool)
    for points, surface in zip(coords, surfaces):
        valid &= ((points[:, 0] >= 12) & (points[:, 0] < WIDTH-12)
                  & (points[:, 1] >= 12) & (points[:, 1] < HEIGHT-12))
        for dx, dy in ((0, 0), (-5, -5), (-5, 5), (5, -5), (5, 5)):
            ix = np.clip(np.rint(points[:, 0]+dx).astype(int), 0, WIDTH-1)
            iy = np.clip(np.rint(points[:, 1]+dy).astype(int), 0, HEIGHT-1)
            valid &= surface[iy, ix] == ids
    return world[valid], coords[0][valid], coords[1][valid], ids[valid]


def self_checks():
    world = np.array([[-1., -.7, 3.], [1., .8, 7.], [0., 0., 9.]])
    a, b = cameras(CASES[0])
    p, q = a.project(world)[0], b.project(world)[0]
    assert np.max(np.abs(p[:, 1]-q[:, 1])) < 1e-10
    assert np.max(np.abs((p[:, 0]-q[:, 0])-FOCAL*BASELINE_M/world[:, 2])) < 1e-10
    for case in CASES:
        for cam in cameras(case):
            rvec = cv2.Rodrigues(cam.camera_to_world.T)[0]
            expected = cv2.projectPoints(world, rvec, -cam.camera_to_world.T@cam.center,
                                         K, np.zeros(5))[0][:, 0]
            assert np.max(np.abs(expected-cam.project(world)[0])) < 1e-8
    a, b = cameras(CASES[3])
    crossing = BASELINE_M/(2*math.tan(math.radians(2.)))
    for cam in (a, b):
        assert np.max(np.abs(cam.project([[0., 0., crossing]])[0][0]-K[:2, 2])) < 1e-9
    # Independently known coupled affine map: checks the numerical raster-map
    # inverse, including off-diagonal terms, against a closed-form answer.
    yy, xx = np.indices((80, 100), dtype=np.float32)
    m = np.array([[1.01, .02], [-.01, .995]])
    t = np.array([-2., 1.2])
    src = np.array([[20., 20.], [45., 30.], [70., 65.]])
    q, valid = inverse_points(m[0, 0]*xx+m[0, 1]*yy+t[0],
                              m[1, 0]*xx+m[1, 1]*yy+t[1], src)
    assert np.all(valid)
    assert np.max(np.abs(q-(src-t)@np.linalg.inv(m).T)) < 1e-4


def inverse_points(mx, my, source):
    """Invert the real raster maps by bilinear Newton steps, independently of fits."""
    h, w = mx.shape
    q = np.asarray(source, np.float64).copy()
    good = np.ones(len(q), bool)
    error = np.full(len(q), np.inf)
    for _ in range(12):
        good &= np.all(np.isfinite(q), axis=1)
        good &= (q[:, 0] >= 1) & (q[:, 0] < w-2) & (q[:, 1] >= 1) & (q[:, 1] < h-2)
        x = np.clip(np.floor(np.nan_to_num(q[:, 0])).astype(int), 0, w-2)
        y = np.clip(np.floor(np.nan_to_num(q[:, 1])).astype(int), 0, h-2)
        dx, dy = q[:, 0]-x, q[:, 1]-y
        values, gx, gy = [], [], []
        for array in (mx, my):
            aa, bb, cc, dd = [v.astype(np.float64) for v in
                              (array[y, x], array[y, x+1], array[y+1, x], array[y+1, x+1])]
            values.append((1-dy)*((1-dx)*aa+dx*bb)+dy*((1-dx)*cc+dx*dd))
            gx.append((1-dy)*(bb-aa)+dy*(dd-cc))
            gy.append((1-dx)*(cc-aa)+dx*(dd-bb))
        residual = np.stack(values, axis=1)-source
        error = np.max(np.abs(residual), axis=1)
        det = gx[0]*gy[1]-gy[0]*gx[1]
        good &= np.abs(det) > .1
        safe = np.where(np.abs(det) > .1, det, 1.)
        step = np.stack([(gy[1]*residual[:, 0]-gy[0]*residual[:, 1])/safe,
                         (-gx[1]*residual[:, 0]+gx[0]*residual[:, 1])/safe], axis=1)
        q[good] -= step[good]
        if np.all(error[good] < .0005):
            break
    return q, good & (error < .002)


def measured_render(left, right, correction, lp, rp):
    original_remap = cv2.remap
    original_crop = alignment._largest_all_valid_rectangle
    maps, crops = [], []

    def capture(image, mx, my, *args, **kwargs):
        maps.append((mx, my))
        return original_remap(image, mx, my, *args, **kwargs)

    def capture_crop(mask):
        result = original_crop(mask)
        crops.append(result)
        return result

    with patch.object(cv2, 'remap', capture), patch.object(alignment, '_largest_all_valid_rectangle', capture_crop):
        a, b = alignment.warp_pair_symmetric(left, right, correction)
    if not maps:
        return (a, b), lp.copy(), rp.copy(), np.ones(len(lp), bool)
    assert len(maps) == 2 and len(crops) == 1
    p, pg = inverse_points(*maps[0], lp)
    q, qg = inverse_points(*maps[1], rp)
    x0, y0, x1, y1 = crops[0] or (0, 0, left.shape[1], left.shape[0])
    good = pg & qg
    for pts in (p, q):
        good &= (pts[:, 0] >= x0+5) & (pts[:, 0] < x1-5)
        good &= (pts[:, 1] >= y0+5) & (pts[:, 1] < y1-5)
    return (a, b), p-[x0, y0], q-[x0, y0], good


def stats(values):
    values = np.abs(np.asarray(values))
    if not len(values):
        return dict(count=0, mean=None, p95=None, maximum=None)
    return dict(count=len(values), mean=float(values.mean()), p95=float(np.percentile(values, 95)),
                maximum=float(values.max()))


def variants(result):
    cor = result['correction']
    base = {k: deepcopy(cor[k]) for k in ('scale', 'rotation_deg', 'vertical_shift_px')}
    out = {'selected': deepcopy(cor), 'affine_only': deepcopy(base)}
    quad = cor.get('y_residual_apply_affine') or {}
    if quad.get('terms') and quad.get('coefficients'):
        out['affine_quad'] = {**deepcopy(base), 'y_residual_apply': {**deepcopy(quad), 'enabled': True}}
    trap = cor.get('trapez_apply') or {}
    if trap.get('params') and (trap.get('plausibility') or {}).get('plausible'):
        out['affine_vergence'] = {**deepcopy(base), 'trapez_apply': {**deepcopy(trap), 'enabled': True}}
        after = cor.get('y_residual_apply_after_trapez') or {}
        if after.get('terms') and after.get('coefficients'):
            out['affine_vergence_quad'] = {**deepcopy(out['affine_vergence']),
                                         'y_residual_apply': {**deepcopy(after), 'enabled': True}}
    return out


def evaluate(case, planes, out, methods):
    name = case['name']
    path = out/'inputs'/(name+'_sbs.png')
    pixels = np.asarray(Image.open(path).convert('RGB'))
    left, right = np.ascontiguousarray(pixels[:, :WIDTH]), np.ascontiguousarray(pixels[:, WIDTH:])
    cams = cameras(case)
    surfaces = [render_scene(planes, cam)[1] for cam in cams]
    world, lp, rp, ids = controls(planes, cams, surfaces)
    del surfaces, pixels
    oracle = [Camera(cam.center, np.eye(3)).project(world)[0] for cam in cams]
    assert np.max(np.abs(oracle[0][:, 1]-oracle[1][:, 1])) < 1e-9
    region_points = .5*(lp+rp)
    edge = ((region_points[:, 0] < .15*WIDTH) | (region_points[:, 0] > .85*WIDTH)
            | (region_points[:, 1] < .15*HEIGHT) | (region_points[:, 1] > .85*HEIGHT))
    zones = np.clip((region_points[:, 0]/WIDTH*3).astype(int), 0, 2)
    zones += 3*np.clip((region_points[:, 1]/HEIGHT*3).astype(int), 0, 2)
    records = []
    for method in methods:
        started = time.perf_counter()
        print(name, method, 'analyzing', flush=True)
        try:
            result = alignment.analyze_pair_features(left, right, method, 3000)
        except Exception as exc:
            row = dict(case=case, method=method, error=repr(exc), seconds=time.perf_counter()-started)
            (out/'results'/f'{name}_{method}.json').write_text(json.dumps(row, indent=2), encoding='utf-8')
            records.append(row)
            print(name, method, 'FAILED', repr(exc), flush=True)
            continue
        elapsed = time.perf_counter()-started
        fitted = variants(result)
        measured = {'input': dict(p=lp, q=rp, valid=np.ones(len(lp), bool))}
        for key, cor in fitted.items():
            (a, b), p, q, good = measured_render(left, right, cor, lp, rp)
            measured[key] = dict(p=p, q=q, valid=good, shape=list(a.shape))
            if key == 'selected':
                # These are labelled viewing copies; geometry metrics precede JPEG encoding.
                small_a = Image.fromarray(a); small_b = Image.fromarray(b)
                scale = min(1., 1500/a.shape[1])
                size = (round(a.shape[1]*scale), round(a.shape[0]*scale))
                view = Image.new('RGB', (2*size[0], size[1]))
                view.paste(small_a.resize(size, Image.Resampling.LANCZOS), (0, 0))
                view.paste(small_b.resize(size, Image.Resampling.LANCZOS), (size[0], 0))
                view.save(out/'aligned_viewing_copies'/f'{name}_{method}_sbs.jpg', quality=95, subsampling=0)
            del a, b
            gc.collect()
        common = np.logical_and.reduce([m['valid'] for m in measured.values()])
        metrics = {}
        for key, m in measured.items():
            residual = m['q'][:, 1]-m['p'][:, 1]
            metrics[key] = dict(all=stats(residual[common]), outer_15_percent=stats(residual[common & edge]),
                                zones=[stats(residual[common & (zones == i)]) for i in range(9)],
                                retained_controls=int(m['valid'].sum()), output_shape=m.get('shape'))
        state = PairState()
        state.alignment.valid = True
        state.alignment.model = result['model']
        state.alignment.correction = result['correction']
        status = _vergence_text(state, Translator('en'))
        applied = bool((result['correction'].get('trapez_apply') or {}).get('enabled'))
        assert applied == ('Vergence' in result['model'])
        if applied:
            assert status.endswith(' px')
        restored = PairState.from_sidecar(state.to_sidecar(source={}))
        assert _vergence_text(restored, Translator('en')) == status
        row = dict(case=case, method=method, model=result['model'], seconds=elapsed,
                   input_width=WIDTH, input_height=HEIGHT, evaluation_controls=len(world),
                   common_controls=int(common.sum()), depth_planes=int(len(np.unique(ids[common]))),
                   matching=dict(matches=result['matches'], inliers=result['inliers']),
                   status_vergence=status, status_sidecar_roundtrip_identical=True,
                   metrics=metrics, known_camera_oracle=stats(oracle[1][:, 1]-oracle[0][:, 1]),
                   correction=result['correction'])
        (out/'results'/f'{name}_{method}.json').write_text(json.dumps(row, indent=2, allow_nan=False), encoding='utf-8')
        np.savez_compressed(out/'results'/f'{name}_{method}_controls.npz', world=world, surface_ids=ids,
                            left=lp, right=rp, common=common,
                            **{key+'_output': np.stack([m['p'], m['q']]) for key, m in measured.items()})
        print(name, method, row['model'], 'status', row['status_vergence'],
              'P95', {key: round(m['all']['p95'], 4) if m['all']['p95'] is not None else None
                      for key, m in metrics.items()}, 'common', int(common.sum()), flush=True)
        records.append({k: v for k, v in row.items() if k != 'correction'})
        gc.collect()
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--generate-only', action='store_true')
    parser.add_argument('--reuse-inputs', action='store_true')
    parser.add_argument('--cases', nargs='*')
    parser.add_argument('--methods', nargs='+', default=['AKAZE', 'SIFT'], choices=['AKAZE', 'SIFT'])
    args = parser.parse_args()
    cv2.setNumThreads(4)
    cv2.setRNGSeed(1950)
    self_checks()
    out = args.output.resolve()
    for name in ('inputs', 'results', 'aligned_viewing_copies'):
        (out/name).mkdir(parents=True, exist_ok=True)
    planes = scene()
    selected = [case for case in CASES if not args.cases or case['name'] in args.cases]
    if not selected or args.cases and set(args.cases)-{x['name'] for x in selected}:
        raise ValueError('Unknown case name.')
    if not args.reuse_inputs:
        for case in selected:
            print(case['name'], 'rendering physical scene', flush=True)
            images = [render_scene(planes, cam)[0] for cam in cameras(case)]
            # Fix the fixture luminance explicitly. Lossless grayscale PNG
            # avoids color-profile ambiguity in this geometry-only experiment.
            gray = cv2.cvtColor(np.concatenate(images, axis=1), cv2.COLOR_RGB2GRAY)
            Image.fromarray(gray).save(out/'inputs'/(case['name']+'_sbs.png'), compress_level=6)
            del images
        manifest = dict(scene='Eight textured finite planes at multiple physical depths, with z-buffer occlusion',
                        baseline_m=BASELINE_M, horizontal_fov_deg=HORIZONTAL_FOV_DEG,
                        half_image_size=[WIDTH, HEIGHT], intrinsics=K.tolist(), cases=CASES,
                        lens_distortion=False, random_seed=1950, encoding='Lossless 8-bit grayscale PNG',
                        source='https://docs.opencv.org/4.13.0/d9/d0c/group__calib3d.html',
                        hashes={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (out/'inputs').glob('*.png')})
        (out/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    if args.generate_only:
        return
    rows = []
    for case in selected:
        rows.extend(evaluate(case, planes, out, args.methods))
    summary = dict(scope='Synthetic geometry experiment only; no production changes',
                   ground_truth='Visible world points projected with known pinhole cameras; never supplied to fitting',
                   measurement='Numerical inverse of the actual native cv2.remap maps, common controls across variants per case/method',
                   excluded='Camera calibration from real photographs, lens distortion, photometric noise, motion, SGBM/framing/export performance',
                   cases=rows)
    (out/'summary.json').write_text(json.dumps(summary, indent=2, allow_nan=False), encoding='utf-8')


if __name__ == '__main__':
    main()
