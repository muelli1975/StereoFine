from __future__ import annotations

import math
import numpy as np
from PIL import Image

from .alignment import _warp_pair_symmetric_simple
from .geometry import center_crop_to_common_size, crop_pair_to_aspect_and_framing, crop_shifted_pair_to_overlap

def _rgb_to_luma_uint8(rgb: np.ndarray) -> np.ndarray:
    """Return uint8 luma image from an RGB array."""
    arr = np.asarray(rgb)
    if arr.ndim == 2:
        gray = arr
    elif arr.ndim == 3 and arr.shape[2] >= 3:
        gray = (0.299 * arr[..., 0] + 0.587 * arr[..., 1] + 0.114 * arr[..., 2])
    else:
        gray = np.zeros(arr.shape[:2], dtype=np.float32)
    return np.clip(gray, 0, 255).astype(np.uint8)

def _resize_pair_for_disparity(left: np.ndarray, right: np.ndarray, max_width: int) -> tuple[np.ndarray, np.ndarray, float]:
    """Resize a corrected pair for dense/semi-dense disparity analysis.

    The returned scale maps full-resolution half-image pixels to analysis pixels.
    """
    if left is None or right is None:
        return left, right, 1.0
    h = min(left.shape[0], right.shape[0])
    w = min(left.shape[1], right.shape[1])
    left = left[:h, :w]
    right = right[:h, :w]
    if w <= 0 or max_width <= 0 or w <= max_width:
        return left, right, 1.0
    scale = float(max_width) / float(w)
    new_size = (max(1, round(w * scale)), max(1, round(h * scale)))
    l_img = Image.fromarray(left, "RGB").resize(new_size, Image.Resampling.LANCZOS)
    r_img = Image.fromarray(right, "RGB").resize(new_size, Image.Resampling.LANCZOS)
    return np.asarray(l_img, dtype=np.uint8), np.asarray(r_img, dtype=np.uint8), scale

def _robust_percentiles(values: np.ndarray, percentiles: list[float]) -> dict[str, float | None]:
    values = np.asarray(values, dtype=np.float32)
    values = values[np.isfinite(values)]
    if values.size == 0:
        return {str(p).replace('.', '_'): None for p in percentiles}
    out = {}
    for p in percentiles:
        out[str(p).replace('.', '_')] = float(np.percentile(values, p))
    return out

def _largest_components_for_mask(mask: np.ndarray, values: np.ndarray, prefer_high: bool, min_area: int) -> list[dict]:
    """Return connected-component summaries for an extreme disparity mask."""
    try:
        import cv2
    except Exception:
        return []
    mask_u8 = (np.asarray(mask, dtype=bool).astype(np.uint8) * 255)
    n, labels, stats, _centroids = cv2.connectedComponentsWithStats(mask_u8, connectivity=8)
    comps = []
    for idx in range(1, int(n)):
        area = int(stats[idx, cv2.CC_STAT_AREA])
        if area < int(min_area):
            continue
        ys, xs = np.where(labels == idx)
        if ys.size == 0:
            continue
        vals = np.asarray(values[ys, xs], dtype=np.float32)
        vals = vals[np.isfinite(vals)]
        if vals.size == 0:
            continue
        robust_value = float(np.percentile(vals, 98 if prefer_high else 2))
        comps.append({
            "area_px": area,
            "bbox": [
                int(stats[idx, cv2.CC_STAT_LEFT]),
                int(stats[idx, cv2.CC_STAT_TOP]),
                int(stats[idx, cv2.CC_STAT_LEFT] + stats[idx, cv2.CC_STAT_WIDTH]),
                int(stats[idx, cv2.CC_STAT_TOP] + stats[idx, cv2.CC_STAT_HEIGHT]),
            ],
            "mean_permille": float(np.mean(vals)),
            "median_permille": float(np.median(vals)),
            "robust_edge_permille": robust_value,
        })
    comps.sort(key=lambda c: (abs(float(c.get("robust_edge_permille", 0.0))), int(c.get("area_px", 0))), reverse=True)
    return comps[:8]

def analyze_horizontal_disparity(
    left_rgb: np.ndarray,
    right_rgb: np.ndarray,
    max_width: int = 2000,
) -> dict:
    """Dense/semi-dense horizontal disparity probe for corrected stereo pairs.

    This is deliberately independent of AKAZE/SIFT matches.  It runs on the
    geometrically corrected pair and estimates horizontal parallax only.
    """
    try:
        import cv2
    except Exception as exc:
        return {
            "ready": False,
            "status": "error",
            "message": f"OpenCV nicht verfügbar: {exc}",
        }

    left_small, right_small, scale = _resize_pair_for_disparity(left_rgb, right_rgb, int(max_width))
    if left_small is None or right_small is None:
        return {"ready": False, "status": "error", "message": "Kein vollständiges Bildpaar."}

    h, w = left_small.shape[:2]
    if h < 40 or w < 80:
        return {"ready": False, "status": "error", "message": "Analysebild zu klein."}

    gray_l = _rgb_to_luma_uint8(left_small)
    gray_r = _rgb_to_luma_uint8(right_small)

    # Moderate local contrast normalization; useful for real stereo pairs with
    # slight camera/color differences, but still conservative.
    try:
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        gray_l_eq = clahe.apply(gray_l)
        gray_r_eq = clahe.apply(gray_r)
    except Exception:
        gray_l_eq, gray_r_eq = gray_l, gray_r

    # Cover a practical stereo range.  Values are in analysis pixels.
    # v1c returns to the wider original probe range.  The no-data side guard
    # bands are expected with SGBM and are shown as diagnostics; the near/far
    # decision no longer uses the most extreme tiny clusters, so the range itself
    # should not create false red Deviation values.
    search_half_range_permille = 80.0
    max_disp = int(max(32, min(192, round(w * (search_half_range_permille / 1000.0)))))
    min_disp = -max_disp
    num_disp = int(math.ceil((2 * max_disp + 1) / 16.0) * 16)
    if num_disp < 16:
        num_disp = 16

    block_size = 5
    channels = 1
    p1 = 8 * channels * block_size * block_size
    p2 = 32 * channels * block_size * block_size

    matcher = cv2.StereoSGBM_create(
        minDisparity=min_disp,
        numDisparities=num_disp,
        blockSize=block_size,
        P1=p1,
        P2=p2,
        disp12MaxDiff=2,
        uniquenessRatio=8,
        speckleWindowSize=80,
        speckleRange=2,
        preFilterCap=31,
        mode=cv2.STEREO_SGBM_MODE_SGBM_3WAY,
    )

    disp_l_raw = matcher.compute(gray_l_eq, gray_r_eq).astype(np.float32) / 16.0
    disp_r_raw = matcher.compute(gray_r_eq, gray_l_eq).astype(np.float32) / 16.0

    invalid_low = float(min_disp - 1)
    valid_l = np.isfinite(disp_l_raw) & (disp_l_raw > invalid_low + 0.5) & (disp_l_raw < min_disp + num_disp - 1)
    valid_r = np.isfinite(disp_r_raw) & (disp_r_raw > invalid_low + 0.5) & (disp_r_raw < min_disp + num_disp - 1)

    # Texture/confidence mask: disparity from flat areas is often unstable.
    sobel_x = cv2.Sobel(gray_l_eq, cv2.CV_32F, 1, 0, ksize=3)
    sobel_y = cv2.Sobel(gray_l_eq, cv2.CV_32F, 0, 1, ksize=3)
    grad = cv2.magnitude(sobel_x, sobel_y)
    texture_thresh = max(5.0, float(np.percentile(grad, 55)) * 0.35)
    texture_mask = grad >= texture_thresh

    # Left/right consistency.  For a left disparity d = x_left - x_right, the
    # corresponding right pixel is x_right = x_left - d.  Swapped SGBM returns
    # approximately -d at that location.
    yy, xx = np.indices((h, w), dtype=np.float32)
    x_right = xx - disp_l_raw
    y_right = yy
    disp_r_at = cv2.remap(
        disp_r_raw,
        x_right.astype(np.float32),
        y_right.astype(np.float32),
        interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=np.nan,
    )
    valid_r_at = cv2.remap(
        valid_r.astype(np.uint8),
        x_right.astype(np.float32),
        y_right.astype(np.float32),
        interpolation=cv2.INTER_NEAREST,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    ).astype(bool)
    lr_error = np.abs(disp_l_raw + disp_r_at)
    lr_consistent = np.isfinite(lr_error) & (lr_error <= 1.5)

    border = max(8, block_size * 2)
    border_mask = np.zeros((h, w), dtype=bool)
    border_mask[border:h-border if h > 2*border else h, border:w-border if w > 2*border else w] = True

    confidence_mask = valid_l & valid_r_at & lr_consistent & texture_mask & border_mask
    valid_count = int(np.count_nonzero(confidence_mask))
    total = int(h * w)
    valid_ratio = 100.0 * valid_count / max(1, total)

    disp_permille = (disp_l_raw.astype(np.float32) / max(1.0, float(w))) * 1000.0
    valid_values = disp_permille[confidence_mask]
    if valid_values.size == 0:
        return {
            "ready": False,
            "status": "uncertain",
            "message": "Zu wenig belastbare Disparitätsdaten.",
            "analysis_width": int(w),
            "analysis_height": int(h),
            "scale": float(scale),
            "valid_pixels": 0,
            "valid_percent": 0.0,
        }

    pct = _robust_percentiles(valid_values, [0, 0.5, 1, 2, 5, 50, 95, 98, 99, 99.5, 100])

    # Near/far must not be selected from the absolute most extreme component.
    # In the first probe that caused tiny SGBM artefact islands to dominate the
    # Deviation although the robust percentiles already matched Cosima closely.
    # v1c therefore uses robust global percentile edges for the numeric value
    # and keeps connected components as visual/support diagnostics only.
    low_05 = float(np.percentile(valid_values, 0.5))
    high_995 = float(np.percentile(valid_values, 99.5))
    low_1 = float(np.percentile(valid_values, 1))
    high_99 = float(np.percentile(valid_values, 99))
    low_2 = float(np.percentile(valid_values, 2))
    high_98 = float(np.percentile(valid_values, 98))

    # 1/99 is the conservative default estimate.  0.5/99.5 is recorded as a
    # slightly more extreme cross-check; 0/100 remains diagnostic only.
    low_edge = low_1
    high_edge = high_99
    deviation_permille = abs(high_edge - low_edge)
    deviation_permille_0_5_99_5 = abs(high_995 - low_05)
    deviation_permille_2_98 = abs(high_98 - low_2)

    min_area = max(80, int(total * 0.00005))
    low_mask = confidence_mask & (disp_permille <= low_2)
    high_mask = confidence_mask & (disp_permille >= high_98)
    low_components = _largest_components_for_mask(low_mask, disp_permille, prefer_high=False, min_area=min_area)
    high_components = _largest_components_for_mask(high_mask, disp_permille, prefer_high=True, min_area=min_area)

    # Conservative certainty rules.  These do not claim a perfect depth map; they
    # decide whether the automatic Deviation/Near/Far estimate is safe enough.
    uncertain_reasons = []
    if valid_ratio < 2.0:
        uncertain_reasons.append("low_valid_area")
    if not low_components:
        uncertain_reasons.append("low_edge_cluster_missing")
    if not high_components:
        uncertain_reasons.append("high_edge_cluster_missing")
    if deviation_permille < 0.5:
        uncertain_reasons.append("disparity_range_unreliable")

    warning_reasons = []
    if deviation_permille_0_5_99_5 - deviation_permille > max(5.0, deviation_permille * 0.25):
        warning_reasons.append("outer_range_wider")
    if deviation_permille - deviation_permille_2_98 > max(5.0, deviation_permille * 0.25):
        warning_reasons.append("inner_range_narrower")
    if valid_ratio < 10.0:
        warning_reasons.append("low_valid_area_warning")

    if uncertain_reasons:
        traffic = "gray"
        status = "uncertain"
    elif deviation_permille <= 33.0:
        traffic = "green"
        status = "ok"
    elif deviation_permille <= 40.0:
        traffic = "orange"
        status = "warning"
    else:
        traffic = "red"
        status = "bad"

    return {
        "ready": True,
        "status": status,
        "traffic": traffic,
        "analysis_width": int(w),
        "analysis_height": int(h),
        "requested_max_width": int(max_width),
        "scale": float(scale),
        "min_disparity_px": int(min_disp),
        "num_disparities_px": int(num_disp),
        "search_half_range_permille": float(search_half_range_permille),
        "expected_side_no_data_px": int(max_disp),
        "expected_side_no_data_permille": float(1000.0 * max_disp / max(1.0, float(w))),
        "valid_pixels": valid_count,
        "valid_percent": float(valid_ratio),
        "texture_threshold": float(texture_thresh),
        "lr_consistency_threshold_px": 1.5,
        "disparity_percentiles_permille": pct,
        "low_edge_permille": float(low_edge),
        "high_edge_permille": float(high_edge),
        "deviation_permille": float(deviation_permille),
        "deviation_method": "percentile_1_99",
        "deviation_permille_0_5_99_5": float(deviation_permille_0_5_99_5),
        "deviation_permille_2_98": float(deviation_permille_2_98),
        "uncertain_reasons": uncertain_reasons,
        "warning_reasons": warning_reasons,
        "low_components": low_components,
        "high_components": high_components,
        # Compact arrays for visualization only; not written to JSON directly.
        "_left_preview": left_small,
        "_disp_permille": disp_permille,
        "_confidence_mask": confidence_mask,
        "_low_mask": low_mask,
        "_high_mask": high_mask,
    }

def json_safe_disparity_summary(result: dict) -> dict:
    """Strip preview arrays from a disparity result before persistence/reporting."""
    return {k: v for k, v in result.items() if not str(k).startswith("_")}


# Backward-compatible internal alias for the earlier disparity-analysis code path.
def _json_safe_disparity_summary(result: dict) -> dict:
    return json_safe_disparity_summary(result)

def render_pair_for_disparity_analysis_from_arrays(
    left: np.ndarray | None,
    right: np.ndarray | None,
    correction: dict | None,
    manual_offset_x: int = 0,
    manual_offset_y: int = 0,
    output_aspect: str = "maximum",
    crop_zoom: float = 1.0,
    crop_pan_x_permille: int = 0,
    crop_pan_y_permille: int = 0,
    input_aspect_ratio: float | None = None,
) -> tuple[np.ndarray | None, np.ndarray | None]:
    """Render the corrected pair for dense Nah/Fern analysis.

    This mirrors the GUI single-image disparity path, but is deliberately
    standalone so batch workers can compute JSON-only Nah/Fern results without
    touching Tk widgets.  Floating-window masks are not applied here because
    near/far analysis must inspect the corrected image content before masking.
    """
    if left is None or right is None:
        return None, None

    if correction is not None:
        left, right = _warp_pair_symmetric_simple(left, right, correction)
    else:
        left, right, _changed = center_crop_to_common_size(left, right)

    left, right, _changed = crop_shifted_pair_to_overlap(
        left,
        right,
        int(manual_offset_x),
        int(manual_offset_y),
    )

    if input_aspect_ratio is None:
        h, w = left.shape[:2]
        input_aspect_ratio = w / max(1, h)

    left, right, _changed = crop_pair_to_aspect_and_framing(
        left,
        right,
        output_aspect,
        float(crop_zoom),
        int(crop_pan_x_permille),
        int(crop_pan_y_permille),
        float(input_aspect_ratio),
    )
    return left, right

