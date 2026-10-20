"""Research-only, two-stage check of one ALIKED/LightGlue candidate per pair.

Control correspondences come from spatially distributed LK/NCC measurements,
not the neural matcher. Whole left-image blocks separate selection from a
second confirmation set. Neither set trains or tunes the selector. These are
not manually measured ground truth or blocks excluded from the saved fits.
No application imports this module; no release files or sidecars are changed.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
from pathlib import Path
import sys

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stereofine.alignment import (
    _assess_spatial_holdout, _grid_zone_indices, _fit_vertical_ransac_filter,
    _analyze_matched_points, resize_pair_for_analysis,
)
from stereofine.alignment_refinement import (
    corrected_point_residuals, patch_correlations, refine_alignment,
)
from stereofine.geometry import apply_orientation
from stereofine.lens_refinement import refine_residual_field
from stereofine.sources import load_source, source_from_pair


PROTOCOL = {
    "version": "neural-selector-pilot-1",
    "candidate": "lightglue_aliked/raw only; existing RC3 geometry",
    "probe_width": 1500, "probe_grid": 5, "max_features_per_cell": 160,
    "min_distance_probe_px": 5, "lk_window": 31, "lk_levels": 5,
    "lk_fb_max_probe_px": .35, "lk_error_max": 10., "ncc_min": .90,
    "split_block_probe_px": 64,
    "split": "(block_x*73856093 + block_y*19349663) modulo 2",
    "gate": "unchanged RC3 strict global gain and regional guard on 3x3 AND 5x5",
    "corners": "TL20, TR20, BL20, BR20, BR10; >=6 points to assess",
    "corner_allowance": "max(0.10 analysis pixel, 10% of baseline metric)",
    "confirmation": "same gate on other blocks; no retuning or alternate candidate",
    "missing_evidence": "retain baseline if a stage lacks required support; sparse corners remain unverified",
}


def partition_blocks(points: np.ndarray) -> np.ndarray:
    """A deterministic split independent of image errors or candidate identity."""
    blocks = np.floor(np.asarray(points) / PROTOCOL["split_block_probe_px"]).astype(np.int64)
    return (blocks[:, 0] * 73856093 + blocks[:, 1] * 19349663) % 2


def control_points(left: np.ndarray, right: np.ndarray):
    """Measure on source images, with no initial flow or correction-based filter."""
    ratio = min(1., PROTOCOL["probe_width"] / left.shape[1])
    size = (round(left.shape[1] * ratio), round(left.shape[0] * ratio))
    a, b = [cv2.resize(im, size, interpolation=cv2.INTER_AREA) for im in (left, right)]
    found = []
    for iy in range(5):
        for ix in range(5):
            mask = np.zeros_like(a)
            mask[iy*size[1]//5:(iy+1)*size[1]//5,
                 ix*size[0]//5:(ix+1)*size[0]//5] = 255
            p = cv2.goodFeaturesToTrack(a, maxCorners=160, qualityLevel=.01,
                                       minDistance=5, blockSize=7, mask=mask)
            if p is not None:
                found.append(p)
    empty = np.empty((0, 2), dtype=np.float32)
    if not found:
        return empty, empty.copy(), np.empty(0, dtype=np.int64)
    p = np.concatenate(found)
    opts = dict(winSize=(31, 31), maxLevel=5,
                criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 40, .001))
    q, status, error = cv2.calcOpticalFlowPyrLK(a, b, p, None, **opts)
    if q is None:
        return empty, empty.copy(), np.empty(0, dtype=np.int64)
    back, status2, _ = cv2.calcOpticalFlowPyrLK(b, a, q, None, **opts)
    if back is None:
        return empty, empty.copy(), np.empty(0, dtype=np.int64)
    p, q = p[:, 0], q[:, 0]
    good = status[:, 0].astype(bool) & status2[:, 0].astype(bool)
    good &= (error[:, 0] < 10) & (np.linalg.norm(back[:, 0]-p, axis=1) < .35)
    good &= np.isfinite(p).all(axis=1) & np.isfinite(q).all(axis=1)
    for pts in (p, q):
        good &= ((pts[:, 0] > 16) & (pts[:, 0] < size[0]-16)
                 & (pts[:, 1] > 16) & (pts[:, 1] < size[1]-16))
    good &= patch_correlations(a, b, p, q) >= .90
    p, q = p[good], q[good]
    # Features on opposite sides of a cell boundary can be near duplicates.
    # One per four-pixel cell, before splitting, prevents duplicate votes.
    _, keep = np.unique(np.floor(p/4).astype(np.int64), axis=0, return_index=True)
    p, q = p[np.sort(keep)], q[np.sort(keep)]
    split = partition_blocks(p)
    return (p+.5)/ratio-.5, (q+.5)/ratio-.5, split


def summary(values):
    values = np.abs(np.asarray(values, dtype=float))
    keys = ("mean_abs", "median_abs", "p90_abs", "p95_abs", "max_abs")
    if not len(values) or not np.isfinite(values).all():
        return dict.fromkeys(keys)
    p95 = float(np.percentile(values, 95))
    return dict(mean_abs=float(np.minimum(values, p95).mean()),
                median_abs=float(np.median(values)), p90_abs=float(np.percentile(values, 90)),
                p95_abs=p95, max_abs=float(values.max()))


def spatial_summary(points, residuals, shape, grid):
    zones = _grid_zone_indices(points, shape, grid)
    return {"zones": [dict(label=str(i), count=int((zones == i).sum()),
                            **summary(residuals[zones == i])) for i in range(grid*grid)]}


def assess_measurements(points, before, after, shape, scale, *, region_quality_floor_analysis=(0., 0.)):
    """Compare identical measurements; never discard a candidate's bad points."""
    points, before, after = (np.asarray(x) for x in (points, before, after))
    result = dict(accepted=False, count=len(points), reason="invalid_measurements")
    if (points.shape != (len(before), 2) or before.shape != after.shape
            or before.ndim != 1 or not np.isfinite(points).all()
            or not np.isfinite(before).all() or not np.isfinite(after).all()
            or not np.isfinite(scale) or scale <= 0):
        return result
    result.update(baseline=summary(before), candidate=summary(after))
    result["grids"] = {}
    for grid in (3, 5):
        b = spatial_summary(points, before, shape, grid)
        a = spatial_summary(points, after, shape, grid)
        gate = _assess_spatial_holdout(result["baseline"], result["candidate"],
                                      b, a, scale, region_quality_floor_analysis=region_quality_floor_analysis)
        gate.update(baseline_regions=b, candidate_regions=a)
        result["grids"][str(grid)] = gate
    corners = []
    h, w = shape[:2]
    for label, x0, y0, fraction in [("TL20", 0, 0, .2), ("TR20", .8, 0, .2),
            ("BL20", 0, .8, .2), ("BR20", .8, .8, .2), ("BR10", .9, .9, .1)]:
        inside = ((points[:, 0] >= x0*w) & (points[:, 0] < (x0+fraction)*w)
                  & (points[:, 1] >= y0*h) & (points[:, 1] < (y0+fraction)*h))
        b, a = summary(before[inside]), summary(after[inside])
        passed = None
        if inside.sum() >= 6:
            passed = all(a[key] <= max(b[key]+max(.10/scale, .10*b[key]), floor/scale)
                         for key, floor in zip(("mean_abs", "p90_abs"), region_quality_floor_analysis))
        corners.append(dict(region=label, count=int(inside.sum()),
                            baseline=b, candidate=a, passed=passed))
    result["corners"] = corners
    result["unverified_corners"] = [c["region"] for c in corners if c["passed"] is None]
    failures = [g["reason"] for g in result["grids"].values() if not g["accepted"]]
    if any(c["passed"] is False for c in corners):
        failures.append("corner_regression")
    result.update(accepted=not failures, reason=failures[0] if failures else "two_grids_and_supported_corners_improved")
    return result


def select_candidate(points, before, after, split, shape, scale, *, region_quality_floor_analysis=(0., 0.)):
    """One candidate, frozen criteria, second group can only veto it."""
    split = np.asarray(split)
    if split.shape != (len(points),) or not np.isin(split, (0, 1)).all():
        return dict(selected="baseline", selection={"reason": "invalid_split"}, confirmation=None)
    decisions = []
    for fold in (0, 1):
        mask = split == fold
        decisions.append(assess_measurements(points[mask], before[mask], after[mask], shape, scale,
            region_quality_floor_analysis=region_quality_floor_analysis))
    return dict(selected="lightglue_aliked" if all(d["accepted"] for d in decisions) else "baseline",
                selection=decisions[0], confirmation=decisions[1])


def input_hashes(raw_file: Path):
    row = json.loads(raw_file.read_text())
    paths = dict(raw=raw_file, points=raw_file.with_name(raw_file.stem+"_points.npz"),
                 **{key: Path(row['case'][key]) for key in ('left', 'right', 'state')})
    hashes = {}
    for key, path in paths.items():
        with path.open('rb') as stream:
            hashes[key] = hashlib.file_digest(stream, 'sha256').hexdigest()
    return hashes


def evaluate_file(raw_file: Path, output: Path):
    row = json.loads(raw_file.read_text())
    case = row["case"]
    sd = json.loads(Path(case["state"]).read_text())
    t = sd["input_transform"]
    loaded = load_source(source_from_pair(Path(case["left"]), Path(case["right"]), Path(case["left"]).parent))
    a = apply_orientation(loaded.left, t["left_orientation"], t["left_mirror"])
    b = apply_orientation(loaded.right, t["right_orientation"], t["right_mirror"])
    if t["swap_eyes"]:
        a, b = b, a
    ga, gb, scale = resize_pair_for_analysis(a, b, 3000)
    z = np.load(raw_file.with_name(raw_file.stem + "_points.npz"))
    lp, rp = z["left"].astype(float), z["right"].astype(float)
    filt = _fit_vertical_ransac_filter(.5*(lp+rp), rp, lp, ga.shape)
    fit = _analyze_matched_points(lp, rp, ga.shape, scale, row["kind"], inlier_mask=filt["mask"])
    fit = refine_alignment(fit, lp, rp, filt["mask"], ga, gb, scale, row["kind"])
    fit = refine_residual_field(fit, lp, rp, ga, gb, scale)
    p, q, split = control_points(ga, gb)
    before = corrected_point_residuals(sd["alignment"]["correction"], p, q, ga.shape, scale)/scale
    after = corrected_point_residuals(fit["correction"], p, q, ga.shape, scale)/scale
    record = dict(name=case["name"].rsplit("_", 1)[0], protocol=PROTOCOL,
                  inputs_sha256=input_hashes(raw_file),
                  raw_points=len(lp), analysis_scale=scale, analysis_shape=ga.shape,
                  all_points=dict(count=len(p), baseline=summary(before), candidate=summary(after)),
                  **select_candidate(p, before, after, split, ga.shape, scale))
    # Private cache is separate from the public numeric record.
    np.savez_compressed(output/(record["name"]+"_controls.npz"),
                        left=p, right=q, split=split, before=before, after=after)
    (output/(record["name"]+"_correction.json")).write_text(json.dumps(fit["correction"], indent=2))
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--names", nargs="*")
    args = parser.parse_args()
    cv2.setNumThreads(4)
    args.output.mkdir(parents=True, exist_ok=True)
    print("PROTOCOL", hashlib.sha256(json.dumps(PROTOCOL, sort_keys=True).encode()).hexdigest(), flush=True)
    for path in sorted(args.results.glob("*_lightglue_aliked.json")):
        name = path.stem.removesuffix("_lightglue_aliked")
        if args.names and name not in args.names:
            continue
        dest = args.output/(name+"_selection.json")
        if dest.exists():
            saved = json.loads(dest.read_text())
            if saved.get('protocol') != PROTOCOL or saved.get('inputs_sha256') != input_hashes(path):
                raise RuntimeError('Stale results; use a new output directory: '+str(dest))
            continue
        try:
            record = evaluate_file(path, args.output)
            dest.write_text(json.dumps(record, indent=2, allow_nan=False))
            print(name, record["selected"], record["selection"]["reason"],
                  record["confirmation"]["reason"], flush=True)
        except Exception as exc:
            import traceback
            traceback.print_exc()
            print(name, "ERROR", str(exc), flush=True)
        gc.collect()


if __name__ == "__main__":
    main()
