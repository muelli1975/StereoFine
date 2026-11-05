from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from .alignment import resize_pair_for_preview, warp_pair_symmetric
from .color_transfer import (
    COLOR_METHOD,
    SymmetricColorTransfer,
    apply_symmetric_color_transfer,
)
from .config import CROP_ZOOM_LEVELS
from .geometry import (
    apply_floating_window_masks,
    apply_orientation,
    center_crop_to_common_size,
    crop_pair_to_aspect_and_framing,
    crop_shifted_pair_to_overlap,
)
from .inputs import LoadedStereoPair, master_to_uint8
from .state import PairState, reproducible_alignment_correction


@dataclass(frozen=True)
class PreviewBasePair:
    """Reduced oriented and aligned working-space images, before colour/crop.

    Interactive geometry uses this cached base immediately. Native colour fits
    are prepared separately from the final master crop and applied afterwards.
    """

    left: np.ndarray
    right: np.ndarray
    scale: float
    original_aspect: float
    color_applied: bool = False
    icc_profile: bytes | None = None


@dataclass(frozen=True)
class PreviewPair:
    left: np.ndarray
    right: np.ndarray
    scale: float


def scale_correction_for_preview(correction: dict | None, scale: float) -> dict | None:
    """Scale only pixel-valued correction terms for a reduced preview copy."""
    if not correction:
        return None
    scaled = dict(correction)
    scaled["vertical_shift_px"] = float(scaled.get("vertical_shift_px", 0.0) or 0.0) * scale
    scaled["vergence_v_px"] = float(scaled.get("vergence_v_px", 0.0) or 0.0) * scale
    scaled["vergence_h_px"] = float(scaled.get("vergence_h_px", 0.0) or 0.0) * scale

    payload = dict(scaled.get("y_residual_apply") or {})
    if payload:
        coefficients = []
        for row in payload.get("coefficients", []) or []:
            item = dict(row)
            item["coefficient_fullres_px"] = float(item.get("coefficient_fullres_px", 0.0) or 0.0) * scale
            coefficients.append(item)
        payload["coefficients"] = coefficients
        payload["max_abs_correction_px"] = float(payload.get("max_abs_correction_px", 0.0) or 0.0) * scale
        scaled["y_residual_apply"] = payload
    return scaled


def _oriented_proxy_pair(loaded: LoadedStereoPair, state: PairState) -> tuple[np.ndarray, np.ndarray]:
    t = state.input_transform
    left = apply_orientation(master_to_uint8(loaded.left), t.left_orientation, t.left_mirror)
    right = apply_orientation(master_to_uint8(loaded.right), t.right_orientation, t.right_mirror)
    if t.swap_eyes:
        left, right = right, left
    left, right, _changed = center_crop_to_common_size(left, right)
    return np.ascontiguousarray(left), np.ascontiguousarray(right)


def build_preview_base_from_oriented_pair(
    left: np.ndarray,
    right: np.ndarray,
    state: PairState,
    *,
    max_width: int,
    max_height: int,
    apply_color: bool = True,
    icc_profile: bytes | None = None,
) -> PreviewBasePair:
    """Build a reduced preview base from an already oriented/cropped pair.

    Batch processing uses this entry point while the analysis proxies are still
    in memory. That avoids re-reading/re-orienting the master images merely to
    show progress; all geometry is applied only after the pair was reduced.
    """

    original_aspect = left.shape[1] / max(1, left.shape[0])
    left, right, scale = resize_pair_for_preview(left, right, max_width, max_height)

    if state.alignment.valid and state.alignment.correction:
        correction = scale_correction_for_preview(state.alignment.correction, scale)
        left, right = warp_pair_symmetric(left, right, correction)

    return PreviewBasePair(
        np.ascontiguousarray(left),
        np.ascontiguousarray(right),
        float(scale),
        float(original_aspect),
        color_applied=False,
        icc_profile=icc_profile,
    )


def build_preview_base(
    loaded: LoadedStereoPair,
    state: PairState,
    *,
    max_width: int,
    max_height: int,
    apply_color: bool = True,
) -> PreviewBasePair:
    """Prepare a reduced geometry base, optionally fitting native colour first.

    GUI callers disable the synchronous fit and use their coalesced background
    renderer. Other callers receive curves based on the same final master crop.
    """

    if apply_color and state.color.enabled:
        # Fit on the exact final master crop. GUI callers request an uncoloured
        # base and prepare these same parameters on their background renderer.
        from .render import render_final_pair
        render_final_pair(loaded, state, apply_floating_window=False)
    left, right = _oriented_proxy_pair(loaded, state)
    base = build_preview_base_from_oriented_pair(
        left,
        right,
        state,
        max_width=max_width,
        max_height=max_height,
        apply_color=False,
    )
    from dataclasses import replace
    return replace(base, icc_profile=loaded.icc_profile)


def render_preview_from_base(
    base: PreviewBasePair,
    state: PairState,
    *,
    apply_color: bool = True,
    apply_floating_window: bool = True,
) -> PreviewPair:
    """Apply the inexpensive interactive layers to a cached preview base."""

    left = base.left
    right = base.right
    scale = base.scale

    offset_x = int(round(state.effective_offset_x_px * scale))
    offset_y = int(round(state.effective_offset_y_px * scale))
    left, right, _changed = crop_shifted_pair_to_overlap(left, right, offset_x, offset_y)

    zoom_index = max(0, min(len(CROP_ZOOM_LEVELS) - 1, int(state.framing.crop_zoom_index)))
    left, right, _changed = crop_pair_to_aspect_and_framing(
        left,
        right,
        state.framing.aspect,
        CROP_ZOOM_LEVELS[zoom_index],
        int(state.framing.pan_x_permille),
        int(state.framing.pan_y_permille),
        base.original_aspect,
    )

    # Keep the last prepared curves during crop/offset edits. Their final-crop
    # validity still remains false, so the native renderer/export refits them.
    # Never carry per-eye curves across an eye swap or changed registration.
    if apply_color and state.color.enabled and not base.color_applied:
        transfer: SymmetricColorTransfer | None = None
        from .render import _stable_digest
        basis = state.color.basis or {}
        compatible = (basis.get('input_transform') == asdict(state.input_transform)
                      and basis.get('alignment_correction_sha256') == _stable_digest(
                          reproducible_alignment_correction(state.alignment.correction) or {}))
        if state.color.method == COLOR_METHOD and (state.color.valid or compatible):
            try:
                transfer = SymmetricColorTransfer.from_dict(state.color.parameters)
            except Exception:
                transfer = None
        if transfer is not None:
            left, right = apply_symmetric_color_transfer(left, right, transfer, strength=state.color.strength)

    from .color_profiles import transform_rgb
    left = transform_rgb(left, base.icc_profile)
    right = transform_rgb(right, base.icc_profile)

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

    return PreviewPair(np.ascontiguousarray(left), np.ascontiguousarray(right), float(scale))


def render_preview_pair(
    loaded: LoadedStereoPair,
    state: PairState,
    *,
    max_width: int,
    max_height: int,
    apply_color: bool = True,
    apply_floating_window: bool = True,
) -> PreviewPair:
    """Compatibility wrapper for callers that do not keep a preview cache."""

    base = build_preview_base(
        loaded, state, max_width=max_width, max_height=max_height, apply_color=apply_color
    )
    return render_preview_from_base(
        base,
        state,
        apply_color=apply_color,
        apply_floating_window=apply_floating_window,
    )

