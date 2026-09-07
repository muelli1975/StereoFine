from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np

from .alignment import analyze_pair_features
from .config import ALIGNMENT_ANALYSIS_MAX_WIDTH, CROP_ZOOM_LEVELS, DISPARITY_ANALYSIS_MAX_WIDTH
from .disparity import (
    analyze_horizontal_disparity,
    json_safe_disparity_summary,
    render_pair_for_disparity_analysis_from_arrays,
)
from .framing import compute_auto_near_framing
from .geometry import apply_orientation, center_crop_to_common_size
from .inputs import LoadedStereoPair, master_to_uint8
from .models import AnalysisRecord, SourceStamp
from .preview_render import build_preview_base_from_oriented_pair, render_preview_from_base
from .sidecar import SidecarLoadResult, SidecarStatus, load_sidecar, save_sidecar, source_stamp_to_dict
from .sources import StereoSource, build_source_stamp, load_source
from .state import AlignmentState, DisparityState, PairState, reproducible_alignment_correction
from .worker import CancellationToken


@dataclass(frozen=True)
class ProcessingDefaults:
    """GUI/session defaults used only when a source has no reusable sidecar."""

    left_orientation: str = "0"
    right_orientation: str = "0"
    left_mirror: bool = False
    right_mirror: bool = False
    swap_eyes: bool = False
    aspect: str = "maximum"
    color_enabled: bool = False


@dataclass(frozen=True)
class ProcessingOptions:
    analysis_method: str = "AKAZE"
    force_alignment: bool = False
    force_disparity: bool = False
    save_sidecar: bool = True
    keep_loaded_pair: bool = False
    preview_max_width: int | None = None
    preview_max_height: int | None = None
    defaults: ProcessingDefaults = ProcessingDefaults()


@dataclass
class ProcessedSource:
    source: StereoSource
    source_stamp: SourceStamp
    state: PairState
    sidecar_status: SidecarStatus
    alignment_from_cache: bool
    disparity_from_cache: bool
    loaded_pair: LoadedStereoPair | None = None
    preview_pair: tuple[np.ndarray, np.ndarray] | None = None
    messages: list[str] = field(default_factory=list)

    @property
    def analysis_record(self) -> AnalysisRecord:
        d = self.state.disparity
        near_position, far_position = self.state.current_scene_positions_permille()
        correction = self.state.alignment.correction or {}
        trapez = correction.get("trapez_apply") or {}
        vergence_applied = None
        vergence_v = None
        vergence_h = None
        if bool(trapez.get("enabled", False)):
            value = trapez.get("max_relative_y_correction_px_fullres")
            if value is not None:
                vergence_applied = float(value)
        elif bool(correction.get("vergence_ready", False)):
            if correction.get("vergence_v_px") is not None:
                vergence_v = float(correction.get("vergence_v_px"))
            if correction.get("vergence_h_px") is not None:
                vergence_h = float(correction.get("vergence_h_px"))
        return AnalysisRecord(
            source_name=self.source.display_name,
            model=self.state.alignment.model,
            matches=self.state.alignment.matches,
            inliers=self.state.alignment.inliers,
            vertical_error_mean_px=self.state.alignment.vertical_error_mean_px,
            near_permille=near_position,
            far_permille=far_position,
            total_permille=d.total_permille,
            traffic=d.traffic,
            favorite=bool(self.state.favorite),
            status=d.status if d.valid else "unavailable",
            notes="; ".join(self.messages + list(self.state.disparity.uncertain_reasons) + list(self.state.disparity.warning_reasons)),
            rotation_deg=correction.get("rotation_deg"),
            vergence_applied_px=vergence_applied,
            vergence_v_px=vergence_v,
            vergence_h_px=vergence_h,
            uncertain=bool(d.uncertain) if d.valid else False,
        )


@dataclass(frozen=True)
class BatchProgress:
    index: int
    total: int
    source_name: str
    stage: str
    preview_rgb: np.ndarray | None = None


@dataclass
class BatchAnalysisResult:
    processed: list[ProcessedSource] = field(default_factory=list)
    failed: list[tuple[StereoSource, str]] = field(default_factory=list)

    @property
    def records(self) -> list[AnalysisRecord]:
        return [item.analysis_record for item in self.processed]


class _NullCancellationToken:
    def raise_if_cancelled(self) -> None:
        return None


def _stable_digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _alignment_basis(state: PairState, method: str) -> dict[str, Any]:
    return {
        "input_transform": asdict(state.input_transform),
        "method": str(method).upper(),
        "max_width": int(ALIGNMENT_ANALYSIS_MAX_WIDTH),
    }


def _disparity_basis(state: PairState) -> dict[str, Any]:
    return {
        "input_transform": asdict(state.input_transform),
        "alignment_correction_sha256": _stable_digest(reproducible_alignment_correction(state.alignment.correction) or {}),
        "aspect": state.framing.aspect,
        "crop_zoom_index": int(state.framing.crop_zoom_index),
        "pan_x_permille": int(state.framing.pan_x_permille),
        "pan_y_permille": int(state.framing.pan_y_permille),
        "max_width": int(DISPARITY_ANALYSIS_MAX_WIDTH),
    }


def _oriented_master_pair(loaded: LoadedStereoPair, state: PairState) -> tuple[np.ndarray, np.ndarray]:
    t = state.input_transform
    left = apply_orientation(loaded.left, t.left_orientation, t.left_mirror)
    right = apply_orientation(loaded.right, t.right_orientation, t.right_mirror)
    if t.swap_eyes:
        left, right = right, left
    left, right, _changed = center_crop_to_common_size(left, right)
    return np.ascontiguousarray(left), np.ascontiguousarray(right)


def _state_from_sidecar(load_result: SidecarLoadResult) -> PairState:
    if load_result.document is None:
        return PairState()
    if load_result.status in {SidecarStatus.VALID, SidecarStatus.MIGRATED}:
        return PairState.from_sidecar(load_result.document)
    # Stale/invalid sidecars must never silently leak edits into a different or
    # changed source.  The file remains untouched until a successful new save.
    return PairState()


def _apply_processing_defaults(state: PairState, defaults: ProcessingDefaults) -> None:
    state.input_transform.left_orientation = defaults.left_orientation
    state.input_transform.right_orientation = defaults.right_orientation
    state.input_transform.left_mirror = defaults.left_mirror
    state.input_transform.right_mirror = defaults.right_mirror
    state.input_transform.swap_eyes = defaults.swap_eyes
    state.framing.aspect = defaults.aspect
    state.color.enabled = defaults.color_enabled
    state.color.strength = 1.0


def _store_alignment_result(state: PairState, result: dict[str, Any], basis: dict[str, Any]) -> None:
    state.alignment = AlignmentState(
        method=str(result.get("method") or state.alignment.method or "AKAZE"),
        model=result.get("model"),
        matches=int(result["matches"]) if result.get("matches") is not None else None,
        inliers=int(result["inliers"]) if result.get("inliers") is not None else None,
        coverage_percent=float(result["coverage_percent"]) if result.get("coverage_percent") is not None else None,
        vertical_error_mean_px=float(result["residual_vertical_mean"]) if result.get("residual_vertical_mean") is not None else None,
        vertical_error_median_px=float(result["residual_vertical_median"]) if result.get("residual_vertical_median") is not None else None,
        vertical_error_p90_px=float(result["residual_vertical_p90"]) if result.get("residual_vertical_p90") is not None else None,
        vertical_error_p95_px=float(result["residual_vertical_p95"]) if result.get("residual_vertical_p95") is not None else None,
        vertical_error_max_px=float(result["residual_vertical_max"]) if result.get("residual_vertical_max") is not None else None,
        correction=result.get("correction"),
        basis=dict(basis),
        valid=True,
    )


def _store_disparity_result(
    state: PairState,
    result: dict[str, Any],
    *,
    basis: dict[str, Any],
    base_width_px: int,
) -> None:
    summary = json_safe_disparity_summary(result)
    ready = bool(result.get("ready"))
    low = result.get("low_edge_permille")
    high = result.get("high_edge_permille")
    total = result.get("deviation_permille")
    uncertain_reasons = list(result.get("uncertain_reasons") or [])
    warning_reasons = list(result.get("warning_reasons") or [])
    valid = ready and low is not None and high is not None and total is not None

    state.disparity = DisparityState(
        low_edge_permille=float(low) if low is not None else None,
        high_edge_permille=float(high) if high is not None else None,
        total_permille=float(total) if total is not None else None,
        uncertain=bool(uncertain_reasons) or str(result.get("status")) == "uncertain",
        uncertain_reasons=uncertain_reasons,
        warning_reasons=warning_reasons,
        traffic=str(result.get("traffic") or "gray"),
        status=str(result.get("status") or ("ok" if valid else "uncertain")),
        basis=dict(basis),
        valid=bool(valid),
        stale=False,
        diagnostics=summary,
    )

    near = compute_auto_near_framing(
        high_edge_permille=state.disparity.high_edge_permille,
        base_width_px=int(base_width_px),
        ready=ready,
        uncertain=state.disparity.uncertain,
        back_permille=state.framing.auto_near_back_permille,
    )
    state.framing.auto_near_offset_x_px = near.offset_x_px
    state.framing.auto_near_shift_permille = near.shift_permille
    state.framing.auto_near_base_width_px = near.base_width_px
    state.framing.auto_near_status = near.status


def _alignment_cache_usable(
    load_result: SidecarLoadResult,
    state: PairState,
    basis: dict[str, Any],
    options: ProcessingOptions,
) -> bool:
    if options.force_alignment:
        return False
    return (
        load_result.alignment_cache_valid
        and state.alignment.valid
        and state.alignment.correction is not None
        and state.alignment.basis == basis
    )


def _disparity_cache_usable(
    load_result: SidecarLoadResult,
    state: PairState,
    basis: dict[str, Any],
    options: ProcessingOptions,
    *,
    alignment_recomputed: bool,
) -> bool:
    if options.force_disparity or alignment_recomputed:
        return False
    return (
        load_result.disparity_cache_valid
        and state.disparity.valid
        and not state.disparity.stale
        and state.disparity.basis == basis
    )


def process_source(
    source: StereoSource,
    options: ProcessingOptions = ProcessingOptions(),
    *,
    cancellation: CancellationToken | None = None,
) -> ProcessedSource:
    """Load/analyse one source using the same GUI-independent 1.0 core.

    This is intentionally the shared primitive for single-image work, batch
    analysis and later batch export.  It never touches Tk/CustomTkinter.
    """

    token = cancellation or _NullCancellationToken()
    token.raise_if_cancelled()
    loaded = load_source(source)
    token.raise_if_cancelled()
    source_stamp = build_source_stamp(source, loaded)
    load_result = load_sidecar(source.sidecar_path, expected_source=source_stamp)
    state = _state_from_sidecar(load_result)
    if load_result.document is None or load_result.status not in {SidecarStatus.VALID, SidecarStatus.MIGRATED}:
        _apply_processing_defaults(state, options.defaults)
    # Pipeline mismatches invalidate only the affected calculated cache.  User
    # intent (favorite, manual framing, floating window, color enabled flag) is
    # retained.
    if not load_result.color_cache_valid:
        state.color.valid = False
    messages: list[str] = []
    if load_result.message:
        messages.append(load_result.message)

    # The requested method is a processing choice.  A sidecar produced with a
    # different method is re-analysed rather than silently overriding the UI.
    method = str(options.analysis_method or state.alignment.method or "AKAZE").upper()
    state.alignment.method = method

    left_master, right_master = _oriented_master_pair(loaded, state)
    left_proxy = master_to_uint8(left_master)
    right_proxy = master_to_uint8(right_master)

    alignment_basis = _alignment_basis(state, method)
    alignment_from_cache = _alignment_cache_usable(load_result, state, alignment_basis, options)
    if not alignment_from_cache:
        token.raise_if_cancelled()
        result = analyze_pair_features(left_proxy, right_proxy, method, ALIGNMENT_ANALYSIS_MAX_WIDTH)
        token.raise_if_cancelled()
        _store_alignment_result(state, result, alignment_basis)

    disparity_basis = _disparity_basis(state)
    disparity_from_cache = _disparity_cache_usable(
        load_result,
        state,
        disparity_basis,
        options,
        alignment_recomputed=not alignment_from_cache,
    )
    if not disparity_from_cache:
        token.raise_if_cancelled()
        zoom_index = max(0, min(len(CROP_ZOOM_LEVELS) - 1, int(state.framing.crop_zoom_index)))
        state.framing.crop_zoom_index = zoom_index
        input_aspect = left_proxy.shape[1] / max(1, left_proxy.shape[0])
        dleft, dright = render_pair_for_disparity_analysis_from_arrays(
            left_proxy,
            right_proxy,
            state.alignment.correction,
            # Automatic near framing is a baseline calculation. User x/y
            # nudges are deliberately not part of the automatic analysis.
            manual_offset_x=0,
            manual_offset_y=0,
            output_aspect=state.framing.aspect,
            crop_zoom=CROP_ZOOM_LEVELS[zoom_index],
            crop_pan_x_permille=state.framing.pan_x_permille,
            crop_pan_y_permille=state.framing.pan_y_permille,
            input_aspect_ratio=input_aspect,
        )
        if dleft is None or dright is None:
            result = {"ready": False, "status": "error", "message": "Kein vollständiges Bildpaar für Deviation-Analyse."}
            base_width = 0
        else:
            base_width = int(dleft.shape[1])
            result = analyze_horizontal_disparity(dleft, dright, DISPARITY_ANALYSIS_MAX_WIDTH)
        token.raise_if_cancelled()
        _store_disparity_result(state, result, basis=disparity_basis, base_width_px=base_width)
    elif state.framing.auto_near_offset_x_px is None and state.disparity.valid:
        # Defensive recovery for early schema-3 drafts: cached raw disparity is
        # enough to reconstruct the automatic 3‰ baseline without recomputing SGBM.
        width = int(state.framing.auto_near_base_width_px or 0)
        near = compute_auto_near_framing(
            high_edge_permille=state.disparity.high_edge_permille,
            base_width_px=width,
            ready=state.disparity.valid,
            uncertain=state.disparity.uncertain,
                back_permille=state.framing.auto_near_back_permille,
        )
        state.framing.auto_near_offset_x_px = near.offset_x_px
        state.framing.auto_near_shift_permille = near.shift_permille
        state.framing.auto_near_base_width_px = near.base_width_px
        state.framing.auto_near_status = near.status
    
    preview_pair: tuple[np.ndarray, np.ndarray] | None = None
    if options.preview_max_width and options.preview_max_height:
        token.raise_if_cancelled()
        base = build_preview_base_from_oriented_pair(
            left_proxy,
            right_proxy,
            state,
            max_width=max(1, int(options.preview_max_width)),
            max_height=max(1, int(options.preview_max_height)),
            apply_color=True,
        )
        preview = render_preview_from_base(
            base,
            state,
            apply_color=True,
            apply_floating_window=True,
        )
        preview_pair = (preview.left, preview.right)

    if options.save_sidecar:
        token.raise_if_cancelled()
        document = state.to_sidecar(source=source_stamp_to_dict(source_stamp))
        save_sidecar(source.sidecar_path, document)

    return ProcessedSource(
        source=source,
        source_stamp=source_stamp,
        state=state,
        sidecar_status=load_result.status,
        alignment_from_cache=alignment_from_cache,
        disparity_from_cache=disparity_from_cache,
        loaded_pair=loaded if options.keep_loaded_pair else None,
        preview_pair=preview_pair,
        messages=messages,
    )


def process_batch_analysis(
    sources: Iterable[StereoSource],
    options: ProcessingOptions = ProcessingOptions(),
    *,
    cancellation: CancellationToken | None = None,
    progress: Callable[[BatchProgress], None] | None = None,
) -> BatchAnalysisResult:
    """Run the shared core over a folder without writing image outputs."""

    token = cancellation or _NullCancellationToken()
    source_list = list(sources)
    result = BatchAnalysisResult()
    total = len(source_list)
    for index, source in enumerate(source_list, start=1):
        token.raise_if_cancelled()
        if progress:
            progress(BatchProgress(index, total, source.display_name, "analysis"))
        try:
            item = process_source(source, options, cancellation=token)  # type: ignore[arg-type]
            result.processed.append(item)
        except Exception as exc:
            result.failed.append((source, str(exc)))
    token.raise_if_cancelled()
    return result
