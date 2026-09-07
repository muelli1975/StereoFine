from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from .config import ASPECT_RATIOS, normalize_orientation_code

def _apply_black_mask(img: np.ndarray, mask: Image.Image) -> np.ndarray:
    """Apply a soft black alpha mask to an RGB image."""
    if img is None or mask is None:
        return img
    mask_arr = np.asarray(mask, dtype=np.float32) / 255.0
    if mask_arr.ndim != 2 or mask_arr.shape[:2] != img.shape[:2]:
        return img
    dtype = img.dtype
    if dtype == np.uint8:
        max_value = 255.0
    elif dtype == np.uint16:
        max_value = 65535.0
    else:
        max_value = float(np.nanmax(img)) if img.size else 1.0
    out = img.astype(np.float32, copy=True)
    out *= (1.0 - mask_arr[..., None])
    return np.clip(out, 0.0, max_value).astype(dtype)

def _make_triangle_mask(width: int, height: int, side: str, direction: str, max_px: int, scale: int = 4) -> Image.Image:
    """Create an antialiased triangular floating-window mask.

    side: "left" or "right" image border.
    direction: "top" means maximum mask width at the top edge,
               "bottom" means maximum mask width at the bottom edge.
    max_px is intentionally the full requested per-side value, not half of it.
    """
    width = max(1, int(width))
    height = max(1, int(height))
    max_px = max(0, int(max_px))
    if max_px <= 0:
        return Image.new("L", (width, height), 0)

    scale = max(1, int(scale))
    sw = width * scale
    sh = height * scale
    mx = min(sw, max_px * scale)

    mask_hi = Image.new("L", (sw, sh), 0)
    draw = ImageDraw.Draw(mask_hi)

    if side == "left" and direction == "bottom":
        points = [(0, 0), (0, sh), (mx, sh)]
    elif side == "right" and direction == "bottom":
        points = [(sw, 0), (sw, sh), (sw - mx, sh)]
    elif side == "left" and direction == "top":
        points = [(0, 0), (mx, 0), (0, sh)]
    elif side == "right" and direction == "top":
        points = [(sw, 0), (sw - mx, 0), (sw, sh)]
    else:
        raise ValueError(f"Invalid floating-window side/direction: {side}/{direction}")

    draw.polygon(points, fill=255)
    return mask_hi.resize((width, height), Image.Resampling.LANCZOS)

def apply_floating_window_masks(
    left: np.ndarray,
    right: np.ndarray,
    left_permille: float = 0.0,
    right_permille: float = 0.0,
    top_permille: float = 0.0,
    bottom_permille: float = 0.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Apply StereoFine floating-window masks to the final stereo pair.

    Left/right values create black vertical bars on the corresponding side.
    Top/bottom values create antialiased triangular masks.  Unlike the old
    Sharp2Stereo test code, top/bottom values are not split in half: 10‰ means
    a 10‰ maximum mask width on each affected half-image side.
    """
    if left is None or right is None:
        return left, right

    h = min(left.shape[0], right.shape[0])
    w = min(left.shape[1], right.shape[1])
    if h <= 0 or w <= 0:
        return left, right

    left_out = left[:h, :w]
    right_out = right[:h, :w]

    left_permille = max(0.0, float(left_permille or 0.0))
    right_permille = max(0.0, float(right_permille or 0.0))
    top_permille = max(0.0, float(top_permille or 0.0))
    bottom_permille = max(0.0, float(bottom_permille or 0.0))

    # Vertical tilted windows are exclusive and take precedence.  The GUI also
    # enforces this, but the function stays defensive for loaded sidecars.
    if top_permille > 0.0 and bottom_permille > 0.0:
        if top_permille >= bottom_permille:
            bottom_permille = 0.0
        else:
            top_permille = 0.0

    if top_permille > 0.0 or bottom_permille > 0.0:
        value = top_permille if top_permille > 0.0 else bottom_permille
        direction = "top" if top_permille > 0.0 else "bottom"
        max_px = int(round(w * value / 1000.0))
        if max_px > 0:
            left_mask = _make_triangle_mask(w, h, "left", direction, max_px)
            right_mask = _make_triangle_mask(w, h, "right", direction, max_px)
            left_out = _apply_black_mask(left_out, left_mask)
            right_out = _apply_black_mask(right_out, right_mask)
        return left_out, right_out

    left_px = int(round(w * left_permille / 1000.0))
    right_px = int(round(w * right_permille / 1000.0))

    if left_px > 0:
        left_out = left_out.copy()
        left_out[:, :min(w, left_px), :] = 0

    if right_px > 0:
        right_out = right_out.copy()
        right_out[:, max(0, w - right_px):, :] = 0

    return left_out, right_out

def apply_orientation(arr: np.ndarray, mode: str, mirror: bool = False) -> np.ndarray:
    out = arr

    mode = normalize_orientation_code(mode)
    if mode == "180":
        out = np.rot90(out, 2)
    elif mode == "90_cw":
        out = np.rot90(out, 3)
    elif mode == "90_ccw":
        out = np.rot90(out, 1)

    if mirror:
        out = np.fliplr(out)

    return out

def center_crop_to_common_size(left: np.ndarray, right: np.ndarray) -> tuple[np.ndarray, np.ndarray, bool]:
    lh, lw = left.shape[:2]
    rh, rw = right.shape[:2]

    common_w = min(lw, rw)
    common_h = min(lh, rh)

    changed = (lw != common_w or rw != common_w or lh != common_h or rh != common_h)

    def crop(img: np.ndarray) -> np.ndarray:
        h, w = img.shape[:2]
        x0 = max(0, (w - common_w) // 2)
        y0 = max(0, (h - common_h) // 2)
        return img[y0:y0 + common_h, x0:x0 + common_w]

    return crop(left), crop(right), changed

def clamp_pair_offset(
    left: np.ndarray,
    right: np.ndarray,
    offset_x: int,
    offset_y: int,
    *,
    min_overlap_px: int = 2,
) -> tuple[int, int]:
    """Clamp a requested right-eye shift to a geometrically valid overlap.

    The old GUI silently fell back to an unshifted crop after an extreme manual
    value while retaining the impossible value in state. 1.0 keeps state and
    rendered geometry identical instead.
    """
    canvas_w = min(left.shape[1], right.shape[1])
    canvas_h = min(left.shape[0], right.shape[0])
    min_overlap_px = max(2, int(min_overlap_px))
    max_abs_x = max(0, canvas_w - min_overlap_px)
    max_abs_y = max(0, canvas_h - min_overlap_px)
    return (
        int(np.clip(int(offset_x), -max_abs_x, max_abs_x)),
        int(np.clip(int(offset_y), -max_abs_y, max_abs_y)),
    )


def crop_shifted_pair_to_overlap(
    left: np.ndarray,
    right: np.ndarray,
    offset_x: int,
    offset_y: int,
) -> tuple[np.ndarray, np.ndarray, bool]:
    """Crop left/right to the valid shared area after shifting the right image.

    Positive offset_x means the right image is shifted to the right.
    Positive offset_y means the right image is shifted down. Requested offsets
    are clamped to the actual image geometry rather than silently ignored.
    """
    lh, lw = left.shape[:2]
    rh, rw = right.shape[:2]

    canvas_w = min(lw, rw)
    canvas_h = min(lh, rh)
    offset_x, offset_y = clamp_pair_offset(left, right, offset_x, offset_y)

    left_x0 = max(0, offset_x)
    right_x0 = max(0, -offset_x)
    overlap_w = canvas_w - abs(offset_x)

    left_y0 = max(0, offset_y)
    right_y0 = max(0, -offset_y)
    overlap_h = canvas_h - abs(offset_y)

    left_crop = left[left_y0:left_y0 + overlap_h, left_x0:left_x0 + overlap_w]
    right_crop = right[right_y0:right_y0 + overlap_h, right_x0:right_x0 + overlap_w]

    changed = (
        lw != overlap_w or rw != overlap_w or
        lh != overlap_h or rh != overlap_h or
        offset_x != 0 or offset_y != 0
    )
    return left_crop, right_crop, changed

def framing_crop_geometry(
    width: int,
    height: int,
    aspect_name: str,
    zoom_level: float,
    original_aspect: float | None = None,
) -> tuple[int, int, float, float]:
    """Return crop size and available half-shift range for the current framing."""
    w = max(2, int(width))
    h = max(2, int(height))

    target_aspect = ASPECT_RATIOS.get(aspect_name)
    if target_aspect == "original":
        target_aspect = original_aspect if original_aspect and original_aspect > 0 else w / max(1, h)
    elif target_aspect is None:
        target_aspect = w / max(1, h)

    current_aspect = w / max(1, h)
    if current_aspect > target_aspect:
        base_h = h
        base_w = int(round(base_h * target_aspect))
    else:
        base_w = w
        base_h = int(round(base_w / target_aspect))

    zoom = max(1.0, float(zoom_level))
    crop_w = max(2, min(w, int(round(base_w / zoom))))
    crop_h = max(2, min(h, int(round(base_h / zoom))))

    if crop_w / max(1, crop_h) > target_aspect:
        crop_w = max(2, int(round(crop_h * target_aspect)))
    else:
        crop_h = max(2, int(round(crop_w / target_aspect)))

    max_shift_x = max(0.0, (w - crop_w) / 2.0)
    max_shift_y = max(0.0, (h - crop_h) / 2.0)
    return crop_w, crop_h, max_shift_x, max_shift_y

def crop_pair_to_aspect_and_framing(
    left: np.ndarray,
    right: np.ndarray,
    aspect_name: str,
    zoom_level: float,
    pan_x_permille: int,
    pan_y_permille: int,
    original_aspect: float | None = None,
) -> tuple[np.ndarray, np.ndarray, bool]:
    """Crop both halves identically to the selected output framing.

    Pan values are normalized to the available movement range. This keeps the
    framing independent of preview/full-resolution scaling and prevents invalid
    black borders.
    """
    h, w = left.shape[:2]
    if h <= 2 or w <= 2:
        return left, right, False

    crop_w, crop_h, max_shift_x, max_shift_y = framing_crop_geometry(
        w,
        h,
        aspect_name,
        zoom_level,
        original_aspect,
    )
    pan_x = float(np.clip(pan_x_permille, -1000, 1000)) / 1000.0
    pan_y = float(np.clip(pan_y_permille, -1000, 1000)) / 1000.0

    cx = (w / 2.0) + pan_x * max_shift_x
    cy = (h / 2.0) + pan_y * max_shift_y

    x0 = int(round(cx - crop_w / 2.0))
    y0 = int(round(cy - crop_h / 2.0))
    x0 = max(0, min(w - crop_w, x0))
    y0 = max(0, min(h - crop_h, y0))
    x1 = x0 + crop_w
    y1 = y0 + crop_h

    changed = (crop_w != w or crop_h != h)
    return left[y0:y1, x0:x1], right[y0:y1, x0:x1], changed

