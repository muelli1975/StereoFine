from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

from .alignment import warp_pair_symmetric
from .color_transfer import COLOR_METHOD, SymmetricColorTransfer, apply_symmetric_color_transfer, fit_symmetric_color_transfer
from .config import CROP_ZOOM_LEVELS
from .geometry import (
    apply_floating_window_masks,
    apply_orientation,
    center_crop_to_common_size,
    crop_pair_to_aspect_and_framing,
    crop_shifted_pair_to_overlap,
)
from .inputs import LoadedStereoPair
from .state import PairState, reproducible_alignment_correction


@dataclass(frozen=True)
class RenderInfo:
    effective_offset_x_px: int
    effective_offset_y_px: int
    color_refit: bool
    color_applied: bool


def _stable_digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _oriented_pair(loaded: LoadedStereoPair, state: PairState) -> tuple[np.ndarray, np.ndarray]:
    t = state.input_transform
    left = apply_orientation(loaded.left, t.left_orientation, t.left_mirror)
    right = apply_orientation(loaded.right, t.right_orientation, t.right_mirror)
    if t.swap_eyes:
        left, right = right, left
    left, right, _changed = center_crop_to_common_size(left, right)
    return np.ascontiguousarray(left), np.ascontiguousarray(right)


def _color_basis(state: PairState, left: np.ndarray, right: np.ndarray) -> dict[str, Any]:
    return {
        "input_transform": asdict(state.input_transform),
        "alignment_correction_sha256": _stable_digest(reproducible_alignment_correction(state.alignment.correction) or {}),
        "effective_offset_x_px": int(state.effective_offset_x_px),
        "effective_offset_y_px": int(state.effective_offset_y_px),
        "aspect": state.framing.aspect,
        "crop_zoom_index": int(state.framing.crop_zoom_index),
        "pan_x_permille": int(state.framing.pan_x_permille),
        "pan_y_permille": int(state.framing.pan_y_permille),
        "shape": [int(left.shape[0]), int(left.shape[1]), 3],
        "dtype": str(left.dtype),
    }


def render_final_pair(
    loaded: LoadedStereoPair,
    state: PairState,
    *,
    apply_color: bool = True,
    apply_floating_window: bool = True,
) -> tuple[np.ndarray, np.ndarray, RenderInfo]:
    """Render the current reproducible StereoFine pair from master data.

    Order is deliberate:
      input orientation -> automatic geometry -> auto+manual x/y -> crop/framing
      -> optional symmetric color match -> optional floating-window masks.

    Color never feeds back into registration/disparity. Floating-window masks are
    last because they are presentation masks, not scene content.
    """

    left, right = _oriented_pair(loaded, state)
    left, right = warp_pair_symmetric(left, right, state.alignment.correction)

    left, right, _changed = crop_shifted_pair_to_overlap(
        left,
        right,
        int(state.effective_offset_x_px),
        int(state.effective_offset_y_px),
    )

    zoom_index = max(0, min(len(CROP_ZOOM_LEVELS) - 1, int(state.framing.crop_zoom_index)))
    state.framing.crop_zoom_index = zoom_index
    input_aspect = left.shape[1] / max(1, left.shape[0])
    left, right, _changed = crop_pair_to_aspect_and_framing(
        left,
        right,
        state.framing.aspect,
        CROP_ZOOM_LEVELS[zoom_index],
        int(state.framing.pan_x_permille),
        int(state.framing.pan_y_permille),
        input_aspect,
    )

    color_refit = False
    color_applied = False
    if apply_color and state.color.enabled:
        basis = _color_basis(state, left, right)
        transfer: SymmetricColorTransfer | None = None
        if state.color.valid and state.color.method == COLOR_METHOD and state.color.basis == basis:
            try:
                transfer = SymmetricColorTransfer.from_dict(state.color.parameters)
            except Exception:
                transfer = None
        if transfer is None:
            transfer = fit_symmetric_color_transfer(left, right)
            state.color.method = transfer.method
            state.color.parameters = transfer.to_dict()
            state.color.basis = basis
            state.color.valid = True
            color_refit = True
        strength = max(0.0, min(1.0, float(state.color.strength)))
        state.color.strength = strength
        left, right = apply_symmetric_color_transfer(left, right, transfer, strength=strength)
        color_applied = True

    if apply_floating_window:
        fw = state.floating_window.normalize()
        left, right = apply_floating_window_masks(
            left,
            right,
            fw.left_permille,
            fw.right_permille,
            fw.top_permille,
            fw.bottom_permille,
        )

    return left, right, RenderInfo(
        effective_offset_x_px=int(state.effective_offset_x_px),
        effective_offset_y_px=int(state.effective_offset_y_px),
        color_refit=color_refit,
        color_applied=color_applied,
    )
