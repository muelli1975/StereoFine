"""Research-only audit of dense far-tail evidence and applied shape changes.

The audit adds no correction or sidecar of its own. It runs the current
production measurement, including conditional observed-range recovery.
Outputs are private diagnostics; original images are read only. A separate source
input root prevents a user's existing sidecar from influencing the fresh fit.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stereofine.alignment import _affine_from_center_params, _y_residual_field_from_payload
from stereofine.disparity import analyze_horizontal_disparity, json_safe_disparity_summary, _rgb_to_luma_uint8
from stereofine.near_point import verify_patch
from stereofine.processing import process_source, ProcessingOptions
from stereofine.render import render_final_pair
from stereofine.sources import source_from_pair


def far_tail_evidence(result, right_rgb, maximum=96):
    """Freeze a spatial sample before asking the existing patch verifier.

    A failure to verify is missing evidence, not by itself known ground truth.
    The diagnostic records whether the production status acknowledges it.
    """
    if not result.get('ready'):
        return dict(status='no_dense_result')
    a = _rgb_to_luma_uint8(result['_left_preview'])
    h, w = a.shape
    b = _rgb_to_luma_uint8(np.asarray(Image.fromarray(right_rgb).resize((w, h), Image.Resampling.LANCZOS)))
    values = result['_disp_permille']
    ys, xs = np.where(result['_confidence_mask'] & (values <= result['low_edge_permille']))
    cells = np.column_stack([ys // 16, xs // 16])
    _, indices = np.unique(cells, axis=0, return_index=True)
    selected = indices[np.linspace(0, len(indices)-1, min(maximum, len(indices)), dtype=int)] if len(indices) else []
    probes = []
    for index in selected:
        x, y = int(xs[index]), int(ys[index])
        measurement = verify_patch(a, b, x, y)
        probes.append(dict(x=x, y=y, sgbm_permille=float(values[y, x]),
            patch_std=float(a[y-8:y+9, x-8:x+9].std()), verification=measurement))
    return dict(tail_pixels=len(xs), tail_above_image_half=int((ys < h/2).sum()),
        probes=len(probes), verified=sum(p['verification'] is not None for p in probes),
        production_status=result['status'], production_uncertain_reasons=result['uncertain_reasons'],
        observations=probes)


def shape_diagnostics(correction, shape):
    """Sample the applied affine + Y-field inverse Jacobian, with native units.

    This helper deliberately declines other horizontal geometry stages. It
    estimates image deformation, not optical calibration or scene-depth truth.
    """
    if correction.get('vergence_ready') or (correction.get('trapez_apply') or {}).get('enabled'):
        return dict(status='unsupported_horizontal_stage')
    h, w = shape[:2]
    field = _y_residual_field_from_payload(h, w, correction.get('y_residual_apply'))
    if field is None:
        field = np.zeros((h, w), np.float32)
    ys, xs = np.meshgrid(np.linspace(0, h-1, 129).astype(int),
                         np.linspace(0, w-1, 129).astype(int), indexing='ij')
    x0, x1 = np.maximum(0, xs-8), np.minimum(w-1, xs+8)
    y0, y1 = np.maximum(0, ys-8), np.minimum(h-1, ys+8)
    fx = ((field[ys, x1]-field[ys, x0])/(x1-x0)).ravel()
    fy = ((field[y1, xs]-field[y0, xs])/(y1-y0)).ravel()
    scale = float(correction.get('scale', 1)) ** .5
    rotation = float(correction.get('rotation_deg', 0))
    result = dict(status='sampled', grid=129, derivative_half_step_native_px=8,
        field_min_px=float(field.min()), field_max_px=float(field.max()),
        max_per_eye_y_polish_px=float(np.abs(field).max()/2), eyes={})
    for eye, sign, angle, factor in [('left', 1, -rotation/2, 1/scale),
                                    ('right', -1, rotation/2, scale)]:
        inverse = cv2.invertAffineTransform(_affine_from_center_params(w, h, angle, factor, 0, 0))[:, :2]
        jacobian = np.tile(np.eye(2), (len(fx), 1, 1))
        jacobian[:, 1, 0] = -sign*.5*fx
        jacobian[:, 1, 1] = 1-sign*.5*fy
        singular = np.linalg.svd(np.linalg.inv(inverse @ jacobian), compute_uv=False)
        result['eyes'][eye] = dict(uniform_scale=factor,
            local_scale_min=float(singular.min()), local_scale_max=float(singular.max()),
            maximum_anisotropy_percent=float(((singular[:, 0]/singular[:, 1]).max()-1)*100))
    return result


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('left', type=Path)
    parser.add_argument('right', type=Path)
    parser.add_argument('--stereofine-export', type=Path, required=True)
    parser.add_argument('--comparison-export', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--methods', nargs='+', choices=['AKAZE', 'SIFT'], default=['AKAZE', 'SIFT'])
    args = parser.parse_args()
    cv2.setNumThreads(4)
    args.output.mkdir(parents=True, exist_ok=True)
    report = dict(scope='measurement/geometry diagnosis only; no candidate admission',
        versions=dict(opencv=cv2.__version__, numpy=np.__version__),
        inputs_sha256={name: digest(getattr(args, name)) for name in
            ['left', 'right', 'stereofine_export', 'comparison_export']}, cases={})

    def measure(left, right, width, label):
        result = analyze_horizontal_disparity(left, right, width)
        report['cases'][label] = dict(disparity=json_safe_disparity_summary(result),
                                    far_tail=far_tail_evidence(result, right))
        return result

    for label, path in [('export_stereofine', args.stereofine_export),
                        ('export_comparison', args.comparison_export)]:
        whole = np.asarray(Image.open(path).convert('RGB'))
        if whole.shape[1] % 2:
            raise ValueError('Expected a full-SBS export with equal eye widths')
        left, right = np.split(whole, 2, axis=1)
        measure(left, right, 1500, label)

    for method in args.methods:
        cv2.setRNGSeed(1337)
        label = 'current_'+method
        with tempfile.TemporaryDirectory(prefix='sf-depth-evidence-') as clean_root:
            source = source_from_pair(args.left, args.right, Path(clean_root))
            def probe(left, right, width):
                return measure(left, right, width, label)
            with patch('stereofine.processing.analyze_horizontal_disparity', side_effect=probe):
                processed = process_source(source, ProcessingOptions(analysis_method=method,
                    force_alignment=True, force_disparity=True, save_sidecar=False, keep_loaded_pair=True))
        state = processed.state
        (args.output/(method+'_state.json')).write_text(json.dumps(asdict(state), indent=2))
        report['cases'][label].update(model=state.alignment.model,
            geometry=shape_diagnostics(state.alignment.correction, processed.loaded_pair.left.shape))
        left, right, _ = render_final_pair(processed.loaded_pair, state, apply_color=False, apply_floating_window=False)
        supplied = np.asarray(Image.open(args.stereofine_export).convert('RGB'))
        native = np.concatenate([left, right], axis=1)
        report['cases'][label]['render'] = dict(shape=list(native.shape),
            matches_supplied_shape=native.shape == supplied.shape,
            uncompressed_mean_absolute_difference=float(np.abs(native.astype(float)-supplied).mean())
                if native.shape == supplied.shape else None)
        print(label, state.alignment.model, report['cases'][label]['disparity']['deviation_permille'], flush=True)
    (args.output/'depth_geometry_evidence.json').write_text(json.dumps(report, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
