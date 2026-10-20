"""Offline RC3 investigation; never imported by the application.

Usage: python scripts/diagnose_rc3.py manifest.json --output results.json
The private manifest is a list of {name, left, right, state} objects. State is
an analysis diagnostic JSON containing PairState fields, not a .sfin sidecar.
This script does not write inputs, sidecars, exports, or application settings.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
from unittest.mock import patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stereofine.disparity import (analyze_horizontal_disparity,
    render_pair_for_disparity_analysis_from_arrays, _rgb_to_luma_uint8)
from stereofine.geometry import apply_orientation
from stereofine.inputs import master_to_uint8
from stereofine.near_point_recovery import stratified_tail_probe, native_patch_checks
from stereofine.sources import load_source, source_from_pair




def audit_case(case):
    paths = {key: Path(case[key]).resolve() for key in ("left", "right", "state")}
    state = json.loads(paths["state"].read_text())
    loaded = load_source(source_from_pair(paths["left"], paths["right"], paths["left"].parent))
    transform = state["input_transform"]
    left = master_to_uint8(apply_orientation(loaded.left, transform["left_orientation"], transform["left_mirror"]))
    right = master_to_uint8(apply_orientation(loaded.right, transform["right_orientation"], transform["right_mirror"]))
    if transform["swap_eyes"]:
        left, right = right, left
    left, right = render_pair_for_disparity_analysis_from_arrays(left, right, state["alignment"]["correction"])
    with patch('stereofine.near_point_recovery.recover_near_edge',
               side_effect=lambda l,r,d,c,base,*native:(base,{})):
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
