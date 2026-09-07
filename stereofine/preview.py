from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from .config import GRID_DIVISIONS_BY_SPACING

MEASURE_CROSS_STEPS_PERMILLE = (10, 20, 30, 40, 50)
MEASURE_CROSS_MINOR_STEPS_PERMILLE = (5, 15, 25, 35, 45)
MEASURE_CROSS_SHADOW_RGBA = (0, 0, 0, 105)

def grid_divisions_for_spacing(spacing: int | str) -> int | None:
    """Return the fixed field count for the visible grid spacing choice."""
    if spacing in GRID_DIVISIONS_BY_SPACING:
        return int(GRID_DIVISIONS_BY_SPACING[spacing])

    if isinstance(spacing, str):
        normalized = spacing.strip()
        if normalized in GRID_DIVISIONS_BY_SPACING:
            return int(GRID_DIVISIONS_BY_SPACING[normalized])
        if normalized.endswith("‰"):
            try:
                value = int(normalized[:-1].strip())
                return int(GRID_DIVISIONS_BY_SPACING.get(value))
            except Exception:
                return None

    return None

def draw_grid_overlay(img: Image.Image, spacing_permille: int | str, color_name: str) -> Image.Image:
    w, h = img.size
    color = (255, 255, 255, 120) if color_name == "Weiß" else (0, 0, 0, 120)

    divisions = grid_divisions_for_spacing(spacing_permille)
    if divisions is None or divisions <= 1:
        return img

    out = img.convert("RGBA")
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    def draw_vertical_if_inner(x_value: int | float):
        x_line = int(round(x_value))
        # Feldbasiert: Die Bildränder bilden die äußeren Rastergrenzen.
        # Gezeichnet werden nur innere Linien; dadurch entstehen immer genau
        # 40x40, 20x20, 10x10 bzw. beim Drittel-Raster 3x3 Felder.
        if 0 < x_line < w - 1:
            draw.line((x_line, 0, x_line, h), fill=color, width=1)

    def draw_horizontal_if_inner(y_value: int | float):
        y_line = int(round(y_value))
        if 0 < y_line < h - 1:
            draw.line((0, y_line, w, y_line), fill=color, width=1)

    for index in range(1, divisions):
        draw_vertical_if_inner(w * index / float(divisions))
        draw_horizontal_if_inner(h * index / float(divisions))

    return Image.alpha_composite(out, overlay).convert("RGB")

def draw_measure_cross_overlay(
    img: Image.Image,
    center_x: int | float,
    center_y: int | float,
    steps_permille: tuple[int, ...] = MEASURE_CROSS_STEPS_PERMILLE,
    minor_steps_permille: tuple[int, ...] = MEASURE_CROSS_MINOR_STEPS_PERMILLE,
) -> Image.Image:
    """Draw a fast antialiased deviation measurement overlay on a preview image.

    Distances are measured in permille of the displayed preview width.  This is
    intentionally a pure preview overlay; it does not touch the stereo images,
    analysis values, export output or .sfin data.
    """
    if img is None:
        return img

    width, height = img.size
    if width <= 1 or height <= 1:
        return img

    x = int(round(float(center_x)))
    y = int(round(float(center_y)))
    x = max(0, min(width - 1, x))
    y = max(0, min(height - 1, y))

    try:
        import cv2
    except Exception:
        # StereoFine requires OpenCV for its core workflow.  If it is missing,
        # keep the preview usable instead of carrying a second rendering path.
        return img

    major_radii = [max(1, int(round(width * float(step) / 1000.0))) for step in steps_permille]
    minor_radii = [max(1, int(round(width * float(step) / 1000.0))) for step in minor_steps_permille]
    if not major_radii:
        return img
    outer = max(major_radii)

    base = np.asarray(img.convert("RGB"), dtype=np.uint8).copy()
    overlay = np.zeros((height, width, 4), dtype=np.uint8)

    # Transparent, antialiased two-pass drawing: soft black shadow first, then a
    # thin light measurement scale.  This mimics the global grid's transparency
    # idea, but stays a little less intrusive around the actual measuring point.
    shadow = MEASURE_CROSS_SHADOW_RGBA
    major_shadow = MEASURE_CROSS_SHADOW_RGBA
    minor_shadow = MEASURE_CROSS_SHADOW_RGBA
    main = (245, 245, 245, 132)
    main_soft = (245, 245, 245, 96)
    minor_soft = main

    def clamp_point(px: int | float, py: int | float) -> tuple[int, int]:
        return (
            int(max(0, min(width - 1, round(float(px))))),
            int(max(0, min(height - 1, round(float(py))))),
        )

    def line_layer(pt1, pt2, color, thickness: int):
        cv2.line(
            overlay,
            clamp_point(pt1[0], pt1[1]),
            clamp_point(pt2[0], pt2[1]),
            color,
            thickness=thickness,
            lineType=cv2.LINE_AA,
        )

    def text_layer(label: str, org, color, scale: float = 0.42, thickness: int = 1):
        ox, oy = clamp_point(org[0], org[1])
        cv2.putText(
            overlay,
            str(label),
            (ox, oy),
            cv2.FONT_HERSHEY_SIMPLEX,
            scale,
            color,
            thickness,
            cv2.LINE_AA,
        )

    x0, y0 = clamp_point(x - outer, y)
    x1, y1 = clamp_point(x + outer, y)
    vx0, vy0 = clamp_point(x, y - outer)
    vx1, vy1 = clamp_point(x, y + outer)

    # Shadow pass.  The axes intentionally stop at the last 50‰ mark.
    line_layer((x0, y0), (x1, y1), shadow, 3)
    line_layer((vx0, vy0), (vx1, vy1), shadow, 3)

    for radius in minor_radii:
        for sign in (-1, 1):
            xx = x + sign * radius
            line_layer((xx, y - 3), (xx, y + 3), minor_shadow, 1)
        yy_top = y - radius
        yy_bottom = y + radius
        line_layer((x - 3, yy_top), (x + 3, yy_top), minor_shadow, 1)
        line_layer((x - 3, yy_bottom), (x + 3, yy_bottom), minor_shadow, 1)

    for radius in major_radii:
        for sign in (-1, 1):
            xx = x + sign * radius
            line_layer((xx, y - 6), (xx, y + 6), major_shadow, 2)
        yy_top = y - radius
        yy_bottom = y + radius
        line_layer((x - 6, yy_top), (x + 6, yy_top), major_shadow, 2)
        line_layer((x - 6, yy_bottom), (x + 6, yy_bottom), major_shadow, 2)

    # Main pass.
    line_layer((x0, y0), (x1, y1), main, 1)
    line_layer((vx0, vy0), (vx1, vy1), main, 1)

    for radius in minor_radii:
        for sign in (-1, 1):
            xx = x + sign * radius
            line_layer((xx, y - 3), (xx, y + 3), minor_soft, 1)
        yy_top = y - radius
        yy_bottom = y + radius
        line_layer((x - 3, yy_top), (x + 3, yy_top), minor_soft, 1)
        line_layer((x - 3, yy_bottom), (x + 3, yy_bottom), minor_soft, 1)

    for radius in major_radii:
        for sign in (-1, 1):
            xx = x + sign * radius
            line_layer((xx, y - 6), (xx, y + 6), main, 1)
        yy_top = y - radius
        yy_bottom = y + radius
        line_layer((x - 6, yy_top), (x + 6, yy_top), main, 1)
        line_layer((x - 6, yy_bottom), (x + 6, yy_bottom), main, 1)

    # Only the two outer numbers.  They sit on the x-axis instead of floating
    # above the reticle, keeping the tool quiet and compact.
    outer_label = str(int(steps_permille[-1]))
    left_text = f"-{outer_label}"
    right_text = outer_label
    left_org = (x - outer - 36, y + 5)
    right_org = (x + outer + 8, y + 5)
    text_layer(left_text, (left_org[0] + 1, left_org[1] + 1), shadow, 0.42, 2)
    text_layer(right_text, (right_org[0] + 1, right_org[1] + 1), shadow, 0.42, 2)
    text_layer(left_text, left_org, main, 0.42, 1)
    text_layer(right_text, right_org, main, 0.42, 1)

    alpha = overlay[:, :, 3:4].astype(np.float32) / 255.0
    color = overlay[:, :, :3].astype(np.float32)
    out = color * alpha + base.astype(np.float32) * (1.0 - alpha)
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGB")

