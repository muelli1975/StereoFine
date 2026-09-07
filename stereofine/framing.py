from __future__ import annotations

import math
from dataclasses import dataclass

from .config import AUTO_NEAR_WINDOW_BACK_PERMILLE


@dataclass(frozen=True)
class AutoNearFraming:
    offset_x_px: int | None
    shift_permille: float | None
    base_width_px: int | None
    near_after_permille: float | None
    status: str

    @property
    def available(self) -> bool:
        return self.offset_x_px is not None and self.base_width_px is not None


def compute_auto_near_framing(
    *,
    high_edge_permille: float | None,
    base_width_px: int,
    ready: bool,
    uncertain: bool = False,
    back_permille: float = AUTO_NEAR_WINDOW_BACK_PERMILLE,
) -> AutoNearFraming:
    """Compute StereoFine's automatic post-analysis horizontal baseline.

    Positive disparity is in front of the window.  Moving the right image to
    the right reduces that disparity.  The required shift is therefore the
    robust near edge plus the fixed 3‰ back offset.  ``ceil`` deliberately keeps
    the quantized pixel result on or just behind the requested position.

    The established behaviour is preserved: an analysis that is numerically
    ready may still frame automatically when it carries a warning/uncertainty
    note.  The status records that distinction for the UI/report.
    """

    width = int(base_width_px)
    if not ready:
        return AutoNearFraming(None, None, width if width > 0 else None, None, "uncertain")
    if high_edge_permille is None or width <= 0:
        return AutoNearFraming(None, None, width if width > 0 else None, None, "uncertain")

    high = float(high_edge_permille)
    if not math.isfinite(high):
        return AutoNearFraming(None, None, width, None, "uncertain")

    required_permille = high + float(back_permille)
    offset_px = int(math.ceil(width * required_permille / 1000.0 - 1e-9))
    shift_permille = 1000.0 * float(offset_px) / float(width)
    near_after = high - shift_permille
    status = "set_with_note" if uncertain else "set"
    return AutoNearFraming(offset_px, shift_permille, width, near_after, status)


def framed_edges_permille(
    *,
    low_edge_permille: float | None,
    high_edge_permille: float | None,
    offset_x_px: int,
    base_width_px: int | None,
) -> tuple[float | None, float | None]:
    """Return raw far/near disparity edges after a horizontal x framing shift."""

    if low_edge_permille is None or high_edge_permille is None or not base_width_px:
        return None, None
    shift = 1000.0 * float(offset_x_px) / float(base_width_px)
    return float(low_edge_permille) - shift, float(high_edge_permille) - shift
