from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .config import AUTO_NEAR_WINDOW_BACK_PERMILLE, normalize_aspect_code, normalize_orientation_code
from .sidecar import SidecarDocument


@dataclass
class InputTransformState:
    left_orientation: str = "0"
    right_orientation: str = "0"
    left_mirror: bool = False
    right_mirror: bool = False
    swap_eyes: bool = False


@dataclass
class AlignmentState:
    method: str = "AKAZE"
    model: str | None = None
    matches: int | None = None
    inliers: int | None = None
    coverage_percent: float | None = None
    vertical_error_mean_px: float | None = None
    vertical_error_median_px: float | None = None
    vertical_error_p90_px: float | None = None
    vertical_error_p95_px: float | None = None
    vertical_error_max_px: float | None = None
    correction: dict[str, Any] | None = None
    basis: dict[str, Any] = field(default_factory=dict)
    valid: bool = False


@dataclass
class ManualState:
    """User edits relative to the automatic post-analysis state.

    The automatic near-point framing is deliberately *not* stored here.  A
    horizontal delta of zero therefore means exactly "automatic state": the
    robust near point is at the fixed StereoFine back offset (normally 3‰)
    whenever automatic near framing was available.
    """

    delta_x_px: int = 0
    delta_y_px: int = 0

    def reset(self) -> None:
        self.delta_x_px = 0
        self.delta_y_px = 0


@dataclass
class FramingState:
    aspect: str = "maximum"
    crop_zoom_index: int = 0
    pan_x_permille: int = 0
    pan_y_permille: int = 0

    # Automatic near-point framing.  This is the reproducible baseline to which
    # Ctrl+R returns; it is not a user nudge and not a floating-window mask.
    auto_near_back_permille: float = AUTO_NEAR_WINDOW_BACK_PERMILLE
    auto_near_offset_x_px: int | None = None
    auto_near_shift_permille: float | None = None
    auto_near_base_width_px: int | None = None
    auto_near_status: str = "none"

    def clear_auto_near(self, *, status: str = "none") -> None:
        self.auto_near_offset_x_px = None
        self.auto_near_shift_permille = None
        self.auto_near_base_width_px = None
        self.auto_near_status = status


@dataclass
class FloatingWindowState:
    left_permille: int = 0
    right_permille: int = 0
    top_permille: int = 0
    bottom_permille: int = 0

    def reset(self) -> None:
        self.left_permille = 0
        self.right_permille = 0
        self.top_permille = 0
        self.bottom_permille = 0

    def normalize(self) -> "FloatingWindowState":
        self.left_permille = max(0, min(30, int(self.left_permille)))
        self.right_permille = max(0, min(30, int(self.right_permille)))
        self.top_permille = max(0, min(30, int(self.top_permille)))
        self.bottom_permille = max(0, min(30, int(self.bottom_permille)))
        # Vertical and lateral masks are mutually exclusive in the established UI model.
        if self.top_permille > 0:
            self.bottom_permille = 0
            self.left_permille = 0
            self.right_permille = 0
        elif self.bottom_permille > 0:
            self.top_permille = 0
            self.left_permille = 0
            self.right_permille = 0
        elif self.left_permille > 0 or self.right_permille > 0:
            self.top_permille = 0
            self.bottom_permille = 0
        return self


@dataclass
class DisparityState:
    # Raw robust edges before automatic/user horizontal framing.  Positive
    # disparity is in front of the screen/window, negative is behind it.
    low_edge_permille: float | None = None
    high_edge_permille: float | None = None
    total_permille: float | None = None
    uncertain: bool = False
    uncertain_reasons: list[str] = field(default_factory=list)
    warning_reasons: list[str] = field(default_factory=list)
    traffic: str = "gray"
    status: str = "none"
    basis: dict[str, Any] = field(default_factory=dict)
    valid: bool = False
    stale: bool = False
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def invalidate(self) -> None:
        self.stale = True
        self.valid = False


@dataclass
class ColorState:
    enabled: bool = False
    strength: float = 1.0
    method: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    basis: dict[str, Any] = field(default_factory=dict)
    valid: bool = False




def reproducible_alignment_correction(correction: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return only the correction payload required to reproduce rendering.

    The feature-analysis core intentionally keeps extensive diagnostics in
    memory for validation.  A .sfin sidecar is a reproducible image state, not
    a development report, so candidate models, zone statistics and holdout
    diagnostics are deliberately not serialized.
    """
    if not correction:
        return None

    compact: dict[str, Any] = {
        "vertical_shift_px": float(correction.get("vertical_shift_px", 0.0) or 0.0),
        "rotation_deg": float(correction.get("rotation_deg", 0.0) or 0.0),
        "scale": float(correction.get("scale", 1.0) or 1.0),
    }

    # Compatibility with the older first-order Vergence apply path.  The new
    # 1.0 pipeline normally uses the controlled projective trapez payload below.
    if bool(correction.get("vergence_ready", False)):
        compact["vergence_ready"] = True
        compact["vergence_v_px"] = float(correction.get("vergence_v_px", 0.0) or 0.0)
        compact["vergence_h_px"] = float(correction.get("vergence_h_px", 0.0) or 0.0)

    # v41 also kept the two compact V/H residual measurements used by the
    # user-facing status.  They are tiny summary values, not the large analysis
    # diagnostics dropped below.  Preserve them so a freshly analysed image and
    # the same image reloaded from .sfin show the same informative status instead
    # of alternating between legacy 0/0 placeholders and merely "active".
    if (
        correction.get("vergence_v_candidate_px") is not None
        or correction.get("vergence_h_candidate_px") is not None
    ):
        compact["vergence_candidate_ready"] = bool(correction.get("vergence_candidate_ready", False))
        if correction.get("vergence_v_candidate_px") is not None:
            compact["vergence_v_candidate_px"] = float(correction.get("vergence_v_candidate_px"))
        if correction.get("vergence_h_candidate_px") is not None:
            compact["vergence_h_candidate_px"] = float(correction.get("vergence_h_candidate_px"))

    trapez = correction.get("trapez_apply") or {}
    if bool(trapez.get("enabled", False)):
        params = trapez.get("params") or {}
        compact_trapez = {
            "enabled": True,
            "params": {
                "a_projective_x": float(params.get("a_projective_x", 0.0) or 0.0),
                "b_projective_y": float(params.get("b_projective_y", 0.0) or 0.0),
            },
        }
        # User-facing magnitude of the actually applied projective Vergence
        # correction. Preserve it only when it genuinely exists; never create a
        # misleading 0 px value for older sidecars that did not store it.
        if trapez.get("max_relative_y_correction_px_fullres") is not None:
            compact_trapez["max_relative_y_correction_px_fullres"] = float(
                trapez.get("max_relative_y_correction_px_fullres")
            )
        compact["trapez_apply"] = compact_trapez

    y_payload = correction.get("y_residual_apply") or {}
    if bool(y_payload.get("enabled", False)):
        coefficients = []
        for row in y_payload.get("coefficients") or []:
            term = str(row.get("term") or "")
            if not term:
                continue
            coefficients.append({
                "term": term,
                "coefficient_fullres_px": float(row.get("coefficient_fullres_px", 0.0) or 0.0),
            })
        norm = y_payload.get("normalization") or {}
        compact["y_residual_apply"] = {
            "enabled": True,
            "model_name": str(y_payload.get("model_name") or "y_quad"),
            "terms": [str(term) for term in (y_payload.get("terms") or [])],
            "coefficients": coefficients,
            "normalization": {
                "x2_mean": float(norm.get("x2_mean", 0.0) or 0.0),
                "y2_mean": float(norm.get("y2_mean", 0.0) or 0.0),
            },
            "max_abs_correction_px": float(y_payload.get("max_abs_correction_px", 0.0) or 0.0),
        }

    return compact


@dataclass
class PairState:
    favorite: bool = False
    input_transform: InputTransformState = field(default_factory=InputTransformState)
    alignment: AlignmentState = field(default_factory=AlignmentState)
    manual: ManualState = field(default_factory=ManualState)
    framing: FramingState = field(default_factory=FramingState)
    floating_window: FloatingWindowState = field(default_factory=FloatingWindowState)
    disparity: DisparityState = field(default_factory=DisparityState)
    color: ColorState = field(default_factory=ColorState)
    warnings: list[str] = field(default_factory=list)

    @property
    def auto_offset_x_px(self) -> int:
        value = self.framing.auto_near_offset_x_px
        return int(value) if value is not None else 0

    @property
    def effective_offset_x_px(self) -> int:
        return self.auto_offset_x_px + int(self.manual.delta_x_px)

    @property
    def effective_offset_y_px(self) -> int:
        return int(self.manual.delta_y_px)

    def effective_horizontal_shift_permille(self) -> float | None:
        width = self.framing.auto_near_base_width_px
        if width is None or int(width) <= 0:
            return None
        return 1000.0 * float(self.effective_offset_x_px) / float(width)

    def current_disparity_edges_permille(self) -> tuple[float | None, float | None]:
        """Return (far/low, near/high) after the current horizontal framing.

        Both values use the same signed disparity convention: positive = in
        front of the window, negative = behind it.  This keeps the model
        mathematically unambiguous; the GUI may format the values in the most
        readable stereoscopic wording.
        """

        low = self.disparity.low_edge_permille
        high = self.disparity.high_edge_permille
        shift = self.effective_horizontal_shift_permille()
        if low is None or high is None or shift is None:
            return None, None
        return float(low) - shift, float(high) - shift

    def current_scene_positions_permille(self) -> tuple[float | None, float | None]:
        """Return the established StereoFine status values (Nahpunkt, Fernpunkt).

        This intentionally preserves the established semantics behind the renamed UI
        rows: Nahpunkt is the signed near-edge disparity after framing
        (positive=in front, negative=behind); Fernpunkt is the positive depth
        behind the window, i.e. ``-far_edge`` after framing.
        """

        far_edge, near_edge = self.current_disparity_edges_permille()
        if far_edge is None or near_edge is None:
            return None, None
        return float(near_edge), float(-far_edge)

    def reset_manual_to_auto(self) -> None:
        """Implement the Ctrl+R semantic of StereoFine 1.0.

        Input orientation/mirroring, the automatic geometric correction,
        automatic 3‰ near-point framing, analysis results and the selected
        output aspect remain intact.  User nudge, crop zoom/pan and floating
        window masks return to their post-auto defaults.
        """

        self.manual.reset()
        self.framing.crop_zoom_index = 0
        self.framing.pan_x_permille = 0
        self.framing.pan_y_permille = 0
        self.floating_window.reset()
        # Raw disparity may only be revalidated when the reset truly returns to
        # the exact framing basis on which it was measured.  In particular,
        # Ctrl+R deliberately keeps the selected output aspect; therefore a
        # disparity made stale by an aspect change must stay stale until the
        # shared processing core recomputes it.
        basis = self.disparity.basis or {}
        framing_matches_basis = bool(basis) and (
            basis.get("aspect") == self.framing.aspect
            and int(basis.get("crop_zoom_index", -1)) == int(self.framing.crop_zoom_index)
            and int(basis.get("pan_x_permille", 999999)) == int(self.framing.pan_x_permille)
            and int(basis.get("pan_y_permille", 999999)) == int(self.framing.pan_y_permille)
        )
        if (
            framing_matches_basis
            and self.disparity.low_edge_permille is not None
            and self.disparity.high_edge_permille is not None
            and self.disparity.total_permille is not None
        ):
            self.disparity.valid = True
            self.disparity.stale = False
            if self.disparity.status == "stale":
                self.disparity.status = "ok"

    def invalidate_for_input_transform(self) -> None:
        """Invalidate calculated geometry after orientation/mirror/eye changes."""
        method = self.alignment.method
        self.alignment = AlignmentState(method=method)
        self.disparity = DisparityState(stale=True, status="stale")
        self.framing.clear_auto_near(status="stale")
        self.manual.reset()
        self.color.valid = False

    def invalidate_disparity_for_framing(self, _reason: str = "crop_changed") -> None:
        """Keep alignment but mark disparity/auto-near values as stale."""
        self.disparity.invalidate()
        self.disparity.status = "stale"
        # Keep the last automatic 3‰ baseline so Ctrl+R can return exactly to
        # it. A fresh analysis may replace it after the manual framing is kept.
        self.color.valid = False

    def to_sidecar(self, *, source: dict[str, Any]) -> SidecarDocument:
        alignment = {
            "method": self.alignment.method,
            "model": self.alignment.model,
            "matches": self.alignment.matches,
            "inliers": self.alignment.inliers,
            "vertical_error_mean_px": self.alignment.vertical_error_mean_px,
            "correction": reproducible_alignment_correction(self.alignment.correction),
            "basis": dict(self.alignment.basis),
            "valid": bool(self.alignment.valid),
        }
        disparity = {
            "low_edge_permille": self.disparity.low_edge_permille,
            "high_edge_permille": self.disparity.high_edge_permille,
            "total_permille": self.disparity.total_permille,
            "uncertain": bool(self.disparity.uncertain),
            "uncertain_reasons": list(self.disparity.uncertain_reasons),
            "warning_reasons": list(self.disparity.warning_reasons),
            "traffic": self.disparity.traffic,
            "status": self.disparity.status,
            "basis": dict(self.disparity.basis),
            "valid": bool(self.disparity.valid),
            "stale": bool(self.disparity.stale),
        }

        return SidecarDocument(
            source=source,
            favorite=bool(self.favorite),
            input_state=asdict(self.input_transform),
            alignment=alignment,
            manual=asdict(self.manual),
            framing=asdict(self.framing),
            floating_window=asdict(self.floating_window.normalize()),
            disparity=disparity,
            color=asdict(self.color),
        )

    @classmethod
    def from_sidecar(cls, document: SidecarDocument) -> "PairState":
        def filtered(dc_type, values: dict[str, Any]):
            allowed = dc_type.__dataclass_fields__.keys()
            return dc_type(**{k: v for k, v in values.items() if k in allowed})

        manual_values = dict(document.manual)
        # Compatibility with early schema-3 sidecars that stored an effective
        # x/y offset. New sidecars always write explicit manual deltas.
        if "delta_x_px" not in manual_values and "offset_x_px" in manual_values:
            auto = int((document.framing or {}).get("auto_near_offset_x_px") or 0)
            manual_values["delta_x_px"] = int(manual_values.get("offset_x_px") or 0) - auto
        if "delta_y_px" not in manual_values and "offset_y_px" in manual_values:
            manual_values["delta_y_px"] = int(manual_values.get("offset_y_px") or 0)

        input_values = dict(document.input_state)
        input_values["left_orientation"] = normalize_orientation_code(input_values.get("left_orientation"))
        input_values["right_orientation"] = normalize_orientation_code(input_values.get("right_orientation"))
        framing_values = dict(document.framing)
        framing_values["aspect"] = normalize_aspect_code(framing_values.get("aspect"))

        state = cls(
            favorite=bool(document.favorite),
            input_transform=filtered(InputTransformState, input_values),
            alignment=filtered(AlignmentState, document.alignment),
            manual=filtered(ManualState, manual_values),
            framing=filtered(FramingState, framing_values),
            floating_window=filtered(FloatingWindowState, document.floating_window),
            disparity=filtered(DisparityState, document.disparity),
            color=filtered(ColorState, document.color),
        )
        state.floating_window.normalize()
        return state
