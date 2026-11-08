from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
from pathlib import Path

from .inputs import LoadedStereoPair, find_pair_for_image
from .models import FileStamp, SourceStamp
from .preferences import inherit_missing_preferences, with_series_input
from .processing import ProcessingDefaults
from .sidecar import SidecarLoadResult, SidecarStatus, load_sidecar, save_sidecar, source_matches, source_stamp_to_dict
from .sources import StereoSource, build_source_stamp, load_source, source_from_pair, source_from_stereo_file
from .state import InputTransformState, PairState


@dataclass
class BrowsedSource:
    """A loaded image pair plus any reusable user state, without running analysis."""

    source: StereoSource
    loaded_pair: LoadedStereoPair
    source_stamp: SourceStamp
    state: PairState
    sidecar: SidecarLoadResult
    loaded_input_transform: InputTransformState | None = None


def pair_input_root(left: Path, right: Path) -> Path:
    """Return the established input root for sibling _l/_r or l/r layouts."""
    if left.parent.name.casefold() == "l" and right.parent.name.casefold() == "r":
        if left.parent.parent == right.parent.parent:
            return left.parent.parent
    return left.parent


def source_from_selected_pair_image(path: Path) -> StereoSource:
    pair = find_pair_for_image(path)
    if pair is None:
        raise ValueError(
            "Kein passendes Links/Rechts-Bildpaar gefunden. Erwartet werden "
            "l/r-Unterordner oder Dateien mit _l/_r im selben Ordner."
        )
    left, right = pair
    return source_from_pair(left, right, pair_input_root(left, right))


def source_from_selected_stereo_file(path: Path) -> StereoSource:
    return source_from_stereo_file(path, path.parent)


def is_saved_favorite(source: StereoSource) -> bool:
    """Read the favorite flag without decoding the stereo image."""
    saved = load_sidecar(source.sidecar_path)
    if saved.status != SidecarStatus.VALID or saved.document is None or not saved.document.favorite:
        return False
    try:
        left = FileStamp.from_path(source.left_path, relative_to=source.input_root, width=0, height=0)
        right = left if source.right_path == source.left_path else FileStamp.from_path(
            source.right_path, relative_to=source.input_root, width=0, height=0)
        return source_matches(saved.document.source, SourceStamp(source.kind, left, right), header_only=True)
    except (OSError, TypeError, ValueError):
        return False


def _apply_defaults(state: PairState, defaults: ProcessingDefaults) -> None:
    state.input_transform.left_orientation = defaults.left_orientation
    state.input_transform.right_orientation = defaults.right_orientation
    state.input_transform.left_mirror = defaults.left_mirror
    state.input_transform.right_mirror = defaults.right_mirror
    state.input_transform.swap_eyes = defaults.swap_eyes
    state.framing.aspect = defaults.aspect
    state.color.enabled = defaults.color_enabled
    state.color.strength = 1.0
    from .state import LookState
    state.look = LookState(defaults.look_enabled, defaults.look_preset_id,
                           defaults.look_path, defaults.look_strength).normalize()


def browse_source(source: StereoSource, defaults: ProcessingDefaults = ProcessingDefaults()) -> BrowsedSource:
    """Load a source transactionally and restore sidecar state without analysis.

    This is the lightweight path used while browsing. A valid schema-3 sidecar
    restores the exact per-image state. New/stale/invalid sources use the
    current GUI defaults and remain unanalysed until the user starts processing.
    """

    defaults = with_series_input(defaults, source)
    loaded = load_source(source)
    stamp = build_source_stamp(source, loaded)
    sidecar = load_sidecar(source.sidecar_path, expected_source=stamp)

    if sidecar.document is not None and sidecar.status == SidecarStatus.VALID:
        state = PairState.from_sidecar(sidecar.document)
        inherit_missing_preferences(state, defaults, sidecar.document)
        # Cached calculations may be obsolete while user intent remains useful.
        if not sidecar.alignment_cache_valid:
            state.alignment.valid = False
        if not sidecar.disparity_cache_valid:
            state.disparity.valid = False
            state.disparity.stale = True
            if "disparity" in sidecar.pipeline_mismatches:
                state.framing.clear_auto_near(status="stale")
        elif state.disparity.valid and not state.disparity.basis.get("rendered_pair"):
            # Earlier releases stored the automatic pre-framing estimate. Keep
            # the saved framing, but let the background worker measure the
            # exact final crop before displaying its values and confidence.
            state.disparity.invalidate()
            state.disparity.status = "stale"
        if not sidecar.color_cache_valid:
            state.color.valid = False
        if {"input", "alignment"}.intersection(sidecar.pipeline_mismatches):
            # Old geometry and automatic shifts refer to different decoded
            # pixels. Keep explicit user edits, but do not preview or re-save
            # those calculations as if they belonged to the corrected input.
            state.alignment.correction = None
            state.framing.clear_auto_near(status="stale")
        if (state.disparity.valid and not state.disparity.stale
                and state.disparity.basis.get("rendered_pair")
                and state.disparity.reference_width_px is None):
            # Older sidecars omit the measured crop width. Recover geometry
            # once while loading, without running a new disparity measurement.
            from .render import render_final_pair
            reference = deepcopy(state)
            basis = state.disparity.basis
            reference.manual.delta_x_px = int(basis["offset_x_px"]) - reference.auto_offset_x_px
            reference.manual.delta_y_px = int(basis["offset_y_px"])
            left, _right, _ = render_final_pair(loaded, reference, apply_color=False,
                                               apply_floating_window=False)
            state.disparity.reference_width_px = int(left.shape[1])
    else:
        state = PairState()
        _apply_defaults(state, defaults)

    return BrowsedSource(source, loaded, stamp, state, sidecar, deepcopy(state.input_transform))


def save_browsed_state(session: BrowsedSource, *, save_orientation: bool = False) -> Path:
    """Save edits without turning a display default into an image setting."""
    existing = session.sidecar.document if session.sidecar.status == SidecarStatus.VALID else None
    transform_changed = (session.loaded_input_transform is not None
                         and session.state.input_transform != session.loaded_input_transform)
    previous_manual = existing.manual if existing else {}
    manual_changed = any(getattr(session.state.manual, key) != previous_manual.get(key, 0)
                         for key in ("delta_x_px", "delta_y_px"))
    document = session.state.to_sidecar(
        source=source_stamp_to_dict(session.source_stamp),
        save_orientation=(save_orientation or transform_changed or manual_changed
                          or bool(existing and existing.input_state)),
    )
    return save_sidecar(session.source.sidecar_path, document)
