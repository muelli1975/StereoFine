"""Photometrically confirm small, genuinely near regions independently of SGBM."""
from __future__ import annotations

import numpy as np


def verify_patch(left: np.ndarray, right: np.ndarray, x: int, y: int) -> dict | None:
    import cv2
    radius, vertical = 8, 2
    h, w = left.shape
    if not (radius + 1 <= x < w - radius - 1 and radius + vertical <= y < h - radius - vertical):
        return None
    patch = left[y-radius:y+radius+1, x-radius:x+radius+1]
    if float(patch.std()) < 6:
        return None
    scores = cv2.matchTemplate(right[y-radius-vertical:y+radius+vertical+1], patch, cv2.TM_CCOEFF_NORMED)
    _, peak, _, position = cv2.minMaxLoc(scores)
    if peak < .85:
        return None
    px, py = position
    other = scores.copy()
    other[max(0, py-1):py+2, max(0, px-3):px+4] = -1
    uniqueness = peak - float(other.max())
    if uniqueness < .05:
        return None
    subpixel = 0.0
    if 0 < px < scores.shape[1] - 1:
        lo, mid, hi = map(float, scores[py, px-1:px+2])
        curvature = lo - 2 * mid + hi
        if curvature < -1e-6:
            subpixel = float(np.clip(.5 * (lo - hi) / curvature, -.5, .5))
    rx, ry = px + radius, y - vertical + py
    if not (radius + vertical <= ry < h - radius - vertical):
        return None
    inverse = right[ry-radius:ry+radius+1, rx-radius:rx+radius+1]
    reverse = cv2.matchTemplate(left[ry-radius-vertical:ry+radius+vertical+1], inverse, cv2.TM_CCOEFF_NORMED)
    _, reverse_peak, _, back = cv2.minMaxLoc(reverse)
    if reverse_peak < .85 or np.hypot(back[0] + radius - x, ry - vertical + back[1] - y) > 1.0:
        return None
    return {"x": int(x), "y": int(y), "disparity_px": float(x - rx - subpixel),
            "vertical_px": int(y - ry), "correlation": float(peak), "uniqueness": float(uniqueness)}


def supported_near_edge(points: list[dict], baseline_px: float, width: int) -> dict:
    """Require spatial corroboration of extreme values, rather than a maximum."""
    supported = []
    for index, point in enumerate(points):
        for other in points[:index] + points[index+1:]:
            distance = np.hypot(point["x"] - other["x"], point["y"] - other["y"])
            if 6 <= distance <= 64 and abs(point["disparity_px"] - other["disparity_px"]) <= 3:
                supported.append(point)
                break
    maximum = max((p["disparity_px"] for p in supported), default=None)
    edge = float(baseline_px)
    # Do not change a uniform/known-good plane for subpixel NCC/SGBM noise.
    # A confirmed, more extreme region receives half an analysis pixel of
    # measurement margin before the existing three-permille framing is applied.
    if maximum is not None and maximum > edge + .5:
        edge = maximum + .5
    return {"edge_permille": edge * 1000 / width, "supported_points": len(supported),
            "maximum_supported_px": maximum, "verified_points": points,
            "confirmed": maximum is not None and maximum >= baseline_px - 1.5,
            "unsupported_extreme": any(p["disparity_px"] > edge + .5 for p in points if p not in supported),
            "method": "percentile_99_plus_reciprocal_patch_support"}


def confirm_near_edge(left_gray: np.ndarray, right_gray: np.ndarray, disparity_px: np.ndarray,
                      confidence: np.ndarray, baseline_permille: float) -> dict:
    import cv2
    h, w = left_gray.shape
    values = disparity_px[confidence]
    threshold = float(np.percentile(values, 98))
    mask = (confidence & (disparity_px >= threshold)).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    regions = []
    for label in range(1, count):
        if stats[label, cv2.CC_STAT_AREA] < max(32, int(h * w * .00002)):
            continue
        ys, xs = np.where(labels == label)
        regions.append((float(np.percentile(disparity_px[ys, xs], 98)), ys, xs))
    regions.sort(key=lambda row: row[0], reverse=True)
    seeds = []

    def add_seed(x, y):
        if any((x-a)**2 + (y-b)**2 < 64 for a, b in seeds):
            return False
        seeds.append((int(x), int(y)))
        return True

    for _, ys, xs in regions[:12]:
        order = np.argsort(-disparity_px[ys, xs], kind="stable")
        added = 0
        for index in order:
            if add_seed(int(xs[index]), int(ys[index])):
                added += 1
                if added == 8:
                    break
    corners = cv2.goodFeaturesToTrack(left_gray, maxCorners=600, qualityLevel=.01, minDistance=8, blockSize=5)
    if corners is not None:
        corners = np.rint(corners[:, 0]).astype(int)
        for row in range(3):
            for col in range(3):
                cell = corners[(corners[:, 0] * 3 // w == col) & (corners[:, 1] * 3 // h == row)]
                # Cover holes/rims independently as well as the dense near tail.
                priority = sorted(cell.tolist(), key=lambda p: (bool(confidence[p[1], p[0]]),
                                                               -float(disparity_px[p[1], p[0]])))
                added = 0
                for x, y in priority:
                    if add_seed(x, y):
                        added += 1
                        if added == 8:
                            break
    verified = []
    for x, y in seeds:
        point = verify_patch(left_gray, right_gray, x, y)
        if point is not None:
            verified.append(point)
    # The very nearest surface may have only one good initial seed. Seek
    # corroboration around the strongest verified candidates and along the
    # physical rim instead of silently discarding that surface as an island.
    extremes = sorted(verified, key=lambda p: p["disparity_px"], reverse=True)[:6]
    for point in extremes:
        for dx, dy in ((-8, 0), (8, 0), (0, -8), (0, 8), (-8, 8), (8, 8), (-16, 0), (16, 0)):
            x, y = point["x"] + dx, point["y"] + dy
            if add_seed(x, y):
                corroboration = verify_patch(left_gray, right_gray, x, y)
                if corroboration is not None:
                    verified.append(corroboration)
    result = supported_near_edge(verified, baseline_permille * w / 1000, w)
    result.update(probed_points=len(seeds), baseline_percentile_permille=float(baseline_permille))
    return result
