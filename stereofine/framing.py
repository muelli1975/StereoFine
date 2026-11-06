from __future__ import annotations

import math
from dataclasses import dataclass

from .config import AUTO_NEAR_WINDOW_BACK_PERMILLE


@dataclass(frozen=True)
class AutoNearGeometry:
    """Final crop dimensions for an automatic shift, before manual edits."""

    aligned_shape: tuple[int, int]
    aspect: str
    crop_zoom: float = 1.0
    original_aspect: float | None = None

    def final_width(self, offset_x_px: int) -> int:
        from .geometry import clamp_offset_for_size, framing_crop_geometry

        h, w = self.aligned_shape
        dx, _ = clamp_offset_for_size(w, h, offset_x_px, 0)
        if h <= 2 or w - abs(dx) <= 2:
            return w - abs(dx)
        crop_w, _crop_h, _pan_x, _pan_y = framing_crop_geometry(
            w - abs(dx), h, self.aspect, self.crop_zoom, self.original_aspect)
        return int(crop_w)


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
    geometry: AutoNearGeometry | None = None,
) -> AutoNearFraming:
    """Compute StereoFine's automatic post-analysis horizontal baseline.

    Positive disparity is in front of the window.  Moving the right image to
    the right reduces that disparity.  The required shift is therefore the
    robust near edge plus the fixed 3‰ back offset.  ``ceil`` deliberately keeps
    the quantized pixel result on or just behind the requested position.

    When geometry is supplied, the reserve uses the width AFTER the shift and
    chosen aspect/zoom. Find the smallest integer shift satisfying that reserve;
    this is a bounded dimension calculation, not repeated disparity estimation.
    The measurement's original width remains its pixel conversion reference.

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
    limited = False
    final_width = width
    if geometry is not None:
        near_px = high * width / 1000.0
        max_offset = max(0, int(geometry.aligned_shape[1]) - 2)

        def reaches_reserve(offset: int) -> bool:
            return (offset - near_px + 1e-9 >=
                    float(back_permille) * geometry.final_width(offset) / 1000.0)

        low, upper = -max_offset, max_offset
        if not reaches_reserve(upper):
            # Match the renderer's existing overlap limit. Do not claim that
            # an impossible reserve was attained on a two-pixel overlap.
            offset_px, limited = upper, True
        else:
            # With the fixed small reserve, increasing the integer shift
            # increases the achieved back offset monotonically. Integer crop
            # rounding is included by the same geometry function as rendering.
            while low < upper:
                middle = (low + upper) // 2
                if reaches_reserve(middle):
                    upper = middle
                else:
                    low = middle + 1
            offset_px = low
        final_width = geometry.final_width(offset_px)
    shift_permille = 1000.0 * float(offset_px) / float(width)
    near_after = ((high * width / 1000.0 - offset_px) * 1000.0 / final_width
                  if geometry is not None else high - shift_permille)
    status = "set_with_note" if uncertain or limited else "set"
    return AutoNearFraming(offset_px, shift_permille, width, near_after, status)


def framed_edges_permille(
    *,
    low_edge_permille: float | None,
    high_edge_permille: float | None,
    offset_x_px: int,
    base_width_px: int | None,
) -> tuple[float | None, float | None]:
    """Return raw far/near disparity edges after a horizontal x framing shift."""

    if low_edge_permille is None or high_edge_permille is None or base_width_px is None or base_width_px <= 0:
        return None, None
    shift = 1000.0 * float(offset_x_px) / float(base_width_px)
    return float(low_edge_permille) - shift, float(high_edge_permille) - shift
