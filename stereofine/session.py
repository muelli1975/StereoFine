from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .inputs import LoadedStereoPair, find_pair_for_image
from .models import SourceStamp
from .processing import ProcessingDefaults
from .sidecar import SidecarLoadResult, SidecarStatus, load_sidecar, save_sidecar, source_stamp_to_dict
from .sources import StereoSource, build_source_stamp, load_source, source_from_pair, source_from_stereo_file
from .state import PairState


@dataclass
class BrowsedSource:
    """A loaded image pair plus any reusable user state, without running analysis."""

    source: StereoSource
    loaded_pair: LoadedStereoPair
    source_stamp: SourceStamp
    state: PairState
    sidecar: SidecarLoadResult


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


def _apply_defaults(state: PairState, defaults: ProcessingDefaults) -> None:
    state.input_transform.left_orientation = defaults.left_orientation
    state.input_transform.right_orientation = defaults.right_orientation
    state.input_transform.left_mirror = defaults.left_mirror
    state.input_transform.right_mirror = defaults.right_mirror
    state.input_transform.swap_eyes = defaults.swap_eyes
    state.framing.aspect = defaults.aspect
    state.color.enabled = defaults.color_enabled
    state.color.strength = 1.0


def browse_source(source: StereoSource, defaults: ProcessingDefaults = ProcessingDefaults()) -> BrowsedSource:
    """Load a source transactionally and restore sidecar state without analysis.

    This is the lightweight path used while browsing. A valid schema-3 sidecar
    restores the exact per-image state. New/stale/invalid sources use the
    current GUI defaults and remain unanalysed until the user starts processing.
    """

    loaded = load_source(source)
    stamp = build_source_stamp(source, loaded)
    sidecar = load_sidecar(source.sidecar_path, expected_source=stamp)

    if sidecar.document is not None and sidecar.status in {SidecarStatus.VALID, SidecarStatus.MIGRATED}:
        state = PairState.from_sidecar(sidecar.document)
        # Cached calculations may be obsolete while user intent remains useful.
        if not sidecar.alignment_cache_valid:
            state.alignment.valid = False
        if not sidecar.disparity_cache_valid:
            state.disparity.valid = False
            state.disparity.stale = True
        if not sidecar.color_cache_valid:
            state.color.valid = False
    else:
        state = PairState()
        _apply_defaults(state, defaults)

    return BrowsedSource(source, loaded, stamp, state, sidecar)


def save_browsed_state(session: BrowsedSource) -> Path:
    """Persist the exact current per-image state using the already verified stamp."""
    return save_sidecar(
        session.source.sidecar_path,
        session.state.to_sidecar(source=source_stamp_to_dict(session.source_stamp)),
    )
