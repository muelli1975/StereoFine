"""Offline RC3 investigation; never imported by the application.

Usage: python scripts/diagnose_rc3.py manifest.json --output results.json
The private manifest is a list of {name, left, right, state} objects. State is
an analysis diagnostic JSON containing PairState fields, not a .sfin sidecar.
This script does not write inputs, sidecars, exports, or application settings.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stereofine.disparity import (analyze_horizontal_disparity,
    render_pair_for_disparity_analysis_from_arrays, _rgb_to_luma_uint8)
from stereofine.geometry import apply_orientation
from stereofine.near_point import supported_near_edge, verify_patch
from stereofine.sources import load_source, source_from_pair


def stratified_tail_probe(left, right, disparity, confidence, baseline):
    """Counterfactual seed selection with the UNCHANGED RC3 patch verifier.

    Only runs for an unconfirmed near edge. At most 128 additional probes;
    one representative near each 16-pixel cell center in the confident P98
    tail. Spatial subsampling limits cost without privileging one component's
    largest disparity. No NCC, contrast, uniqueness or reciprocal gate changes.
    This is a research candidate, not a production fallback.
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
    a, b = _rgb_to_luma_uint8(left), _rgb_to_luma_uint8(right)
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


def audit_case(case):
    paths = {key: Path(case[key]).resolve() for key in ("left", "right", "state")}
    state = json.loads(paths["state"].read_text())
    loaded = load_source(source_from_pair(paths["left"], paths["right"], paths["left"].parent))
    transform = state["input_transform"]
    left = apply_orientation(loaded.left, transform["left_orientation"], transform["left_mirror"])
    right = apply_orientation(loaded.right, transform["right_orientation"], transform["right_mirror"])
    if transform["swap_eyes"]:
        left, right = right, left
    left, right = render_pair_for_disparity_analysis_from_arrays(left, right, state["alignment"]["correction"])
    result = analyze_horizontal_disparity(left, right, 1500)
    old = result["near_confirmation"]
    # Use exactly the analysis images used by production, captured below by
    # resizing the same arrays with the production helper.
    from stereofine.disparity import _resize_pair_for_disparity
    a, b, _ = _resize_pair_for_disparity(left, right, 1500)
    a, b = _rgb_to_luma_uint8(a), _rgb_to_luma_uint8(b)
    disparity = result["_disp_permille"]*a.shape[1]/1000
    new = stratified_tail_probe(a, b, disparity, result["_confidence_mask"], old)
    old_state = state["disparity"]
    native = native_patch_checks(left, right, a.shape, new["verified_points"]) if not old["confirmed"] else []
    return dict(name=case["name"], inputs_sha256={k: hashlib.sha256(v.read_bytes()).hexdigest() for k,v in paths.items()},
                baseline_reproduced=(abs(result["high_edge_permille"]-old_state["high_edge_permille"]) < 1e-6
                    and old == old_state["diagnostics"]["near_confirmation"]
                    and result["uncertain_reasons"] == old_state["uncertain_reasons"]),
                baseline_uncertain_reasons=result["uncertain_reasons"], baseline=old, candidate=new,
                unchanged=new is old, native_checks=native,
                native_max_permille=max((p["disparity_permille"] for p in native), default=None))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cv2.setNumThreads(4)
    result = dict(python=platform.python_version(), opencv=cv2.__version__, numpy=np.__version__,
                  commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(), cases=[])
    for case in json.loads(args.manifest.read_text()):
        row = audit_case(case)
        result["cases"].append(row)
        args.output.write_text(json.dumps(result, indent=2))
        print(row["name"], "reproduced", row["baseline_reproduced"], "confirmed",
              row["baseline"]["confirmed"], "->", row["candidate"]["confirmed"],
              "edge", round(row["baseline"]["edge_permille"], 4), "->",
              round(row["candidate"]["edge_permille"], 4), "native", row["native_max_permille"], flush=True)


if __name__ == "__main__":
    main()
