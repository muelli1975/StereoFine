from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .i18n import Translator
from .sidecar import SidecarLoadResult, SidecarStatus
from .state import PairState

StatusRole = Literal["normal", "deviation", "warning"]


@dataclass(frozen=True)
class StatusRow:
    label: str
    value: str
    role: StatusRole = "normal"


@dataclass(frozen=True)
class StatusSection:
    name: str
    rows: tuple[StatusRow, ...]


def _fmt(value: float | int | None, suffix: str = "", decimals: int = 2) -> str:
    if value is None:
        return "–"
    if isinstance(value, int):
        return f"{value}{suffix}"
    return f"{float(value):.{decimals}f}{suffix}"


def _analysis_status(state: PairState, tr: Translator) -> str:
    if state.alignment.valid and state.disparity.valid and not state.disparity.stale:
        return state.alignment.method or tr.t("status_ready")
    if state.alignment.valid:
        return f"{state.alignment.method or tr.t('status_analysis')} · {tr.t('status_deviation_open')}"
    return tr.t("status_not_analyzed")


def _fmt_sig(value: float | int | None, suffix: str = "", significant: int = 4) -> str:
    if value is None:
        return "–"
    return f"{float(value):.{significant}g}{suffix}"


def _vergence_text(state: PairState, tr: Translator) -> str:
    correction = state.alignment.correction or {}
    if not correction or "Vergence" not in str(state.alignment.model or ""):
        return "–"

    # Current StereoFine 1.0 applies the controlled projective Trapez/Vergence
    # stage.  Report the magnitude of the correction that is actually rendered,
    # not the legacy V/H diagnostic candidates or their compatibility 0/0
    # placeholders.
    trapez = correction.get("trapez_apply") or {}
    if bool(trapez.get("enabled", False)):
        applied = trapez.get("max_relative_y_correction_px_fullres")
        if applied is not None:
            return _fmt_sig(applied, " px")

    # Older first-order sidecars may genuinely apply V/H. Preserve their exact
    # semantics when that model is the active correction.
    if bool(correction.get("vergence_ready", False)):
        v = correction.get("vergence_v_px")
        h = correction.get("vergence_h_px")
        if v is not None or h is not None:
            return f"V {_fmt_sig(v, ' px')} · H {_fmt_sig(h, ' px')}"

    # Transitional sidecars from earlier 1.0 candidates may contain only the
    # diagnostic V/H summary. It is preferable to show that measured summary
    # than an invented 0/0, but new sidecars preserve the applied magnitude.
    v = correction.get("vergence_v_candidate_px")
    h = correction.get("vergence_h_candidate_px")
    if v is not None or h is not None:
        return f"V {_fmt_sig(v, ' px')} · H {_fmt_sig(h, ' px')}"

    return tr.t("status_active")


def _traffic_label(traffic: str, tr: Translator) -> str:
    return {
        "green": tr.t("traffic_green"),
        "orange": tr.t("traffic_orange"),
        "red": tr.t("traffic_red"),
        "gray": tr.t("traffic_gray"),
    }.get(traffic, tr.t("traffic_gray"))


def build_status_sections(
    state: PairState,
    *,
    input_text: str,
    language: str = "de",
) -> tuple[StatusSection, ...]:
    tr = Translator(language)
    correction = state.alignment.correction or {}
    near, far = state.current_scene_positions_permille()
    total = state.disparity.total_permille if state.disparity.valid and not state.disparity.stale else None

    # The normal UI intentionally exposes no percentile thresholds, diagnostic
    # reasons or stale-cache internals. Those remain in the sidecar/report.
    # Only a genuinely uncertain estimate gets one plain user-facing warning.
    warning = (
        tr.t("status_uncertain")
        if state.disparity.valid and not state.disparity.stale and state.disparity.uncertain
        else ""
    )

    sections = [
        StatusSection(tr.t("status_input"), (StatusRow("", input_text or "–"),)),
        StatusSection(
            tr.t("status_analysis"),
            (
                StatusRow(tr.t("status_analysis"), _analysis_status(state, tr)),
                StatusRow(tr.t("status_model"), state.alignment.model or "–"),
                StatusRow(tr.t("status_vertical_error"), _fmt(state.alignment.vertical_error_mean_px, " px", 3)),
                StatusRow(tr.t("status_vertical_shift"), _fmt(correction.get("vertical_shift_px"), " px", 3)),
                StatusRow(tr.t("status_rotation"), _fmt(correction.get("rotation_deg"), "°", 4)),
                StatusRow(tr.t("status_vergence"), _vergence_text(state, tr)),
            ),
        ),
        StatusSection(
            "Deviation",
            (
                StatusRow(
                    tr.t("status_total_deviation"),
                    f"{_fmt(total, '‰')} · {_traffic_label(state.disparity.traffic, tr) if total is not None else '–'}",
                    "deviation",
                ),
                StatusRow(tr.t("status_near"), _fmt(near if total is not None else None, "‰")),
                StatusRow(tr.t("status_far"), _fmt(far if total is not None else None, "‰")),
                *(() if not warning else (StatusRow("", warning, "warning"),)),
            ),
        ),
        StatusSection(
            tr.t("status_floating"),
            (
                StatusRow(tr.t("status_lr"), f"{state.floating_window.left_permille}‰ / {state.floating_window.right_permille}‰"),
                StatusRow(tr.t("status_tb"), f"{state.floating_window.top_permille}‰ / {state.floating_window.bottom_permille}‰"),
            ),
        ),
    ]
    return tuple(sections)


def sidecar_status_text(sidecar: SidecarLoadResult | None, language: str = "de") -> str:
    tr = Translator(language)
    if sidecar is None:
        return tr.t("settings_none")
    if sidecar.status == SidecarStatus.MISSING:
        return tr.t("sidecar_new")
    if sidecar.status == SidecarStatus.VALID:
        if sidecar.pipeline_mismatches:
            return tr.t("sidecar_partial")
        return tr.t("sidecar_loaded")
    if sidecar.status == SidecarStatus.MIGRATED:
        return tr.t("sidecar_legacy")
    if sidecar.status == SidecarStatus.STALE:
        return tr.t("sidecar_stale")
    return tr.t("sidecar_invalid")
