"""Render the visible inspection region with the full-frame filter support."""
from functools import lru_cache
from math import ceil, floor

import numpy as np
from PIL import Image

from .anaglyph import DEFAULT_BLOCK_ROWS, make_anaglyph
from .geometry import _apply_black_mask, apply_floating_window_masks

LANCZOS = Image.Resampling.LANCZOS


@lru_cache(maxsize=8)
def _tilted_border(width, height, side, direction, pixels):
    # Pillow draws the polygon with float32 scan-line intersections. Evaluate
    # those at the original coordinates, and rasterize only the border strip.
    strip_width = min(width, pixels + 6)
    origin = 0 if side == 'left' else width - strip_width
    sw, sh, amount = width * 4, height * 4, pixels * 4
    y = np.arange(sh, dtype=np.float32)
    slope = np.float32(amount) / np.float32(sh)
    if direction == 'bottom':
        y -= sh
    if (side, direction) in (('left', 'top'), ('right', 'bottom')):
        slope = -slope
    boundary = y * slope + np.float32(amount if side == 'left' else sw - amount)
    x = np.arange(origin * 4, (origin + strip_width) * 4, dtype=np.int32)
    if side == 'left':
        filled = x[None, :] <= np.ceil(boundary - np.float32(.5)).astype(np.int32)[:, None]
    else:
        filled = x[None, :] >= np.floor(boundary + np.float32(.5)).astype(np.int32)[:, None]
    return origin, Image.fromarray(filled.astype(np.uint8) * 255).resize((strip_width, height), LANCZOS)


def _mask_region(image, size, side, direction, pixels, box):
    x, y, x1, y1 = box
    width, height = size
    if (side == 'left' and x >= pixels + 6) or (side == 'right' and x1 <= width - pixels - 6):
        return image
    origin, strip = _tilted_border(width, height, side, direction, pixels)
    start, stop = max(x, origin), min(x1, origin + strip.width)
    mask = Image.new('L', (x1 - x, y1 - y), 0)
    mask.paste(strip.crop((start - origin, y, stop - origin, y1)), (start - x, 0))
    return _apply_black_mask(image, mask)


def render_viewport(left, right, window, mode, viewport, adjust):
    raw_box, display = viewport
    height, width = left.shape[:2]
    # Pillow converts the resize box to float32. Rebase those coordinates
    # after adding the complete Lanczos support around the visible region.
    x, y, x1, y1 = map(float, np.float32(raw_box))
    margin_x = ceil(3 * max(1., (x1 - x) / display[0])) + 2
    margin_y = ceil(3 * max(1., (y1 - y) / display[1])) + 2
    ox, oy = max(0, floor(x) - margin_x), max(0, floor(y) - margin_y)
    ex, ey = min(width, ceil(x1) + margin_x), min(height, ceil(y1) + margin_y)
    region = (ox, oy, ex, ey)
    a, b = adjust(left[oy:ey, ox:ex], right[oy:ey, ox:ex])
    tilted = window.top_permille or window.bottom_permille
    if tilted:
        pixels = round(width * tilted / 1000)
        if pixels:
            direction = 'top' if window.top_permille else 'bottom'
            a = _mask_region(a, (width, height), 'left', direction, pixels, region)
            b = _mask_region(b, (width, height), 'right', direction, pixels, region)
    else:
        a, b = apply_floating_window_masks(a, b, window.left_permille, window.right_permille,
                                           reference_size=(width, height), origin=(ox, oy))
    box = x - ox, y - oy, x1 - ox, y1 - oy
    if mode == 'Kreuzblick':
        image = Image.new('RGB', (display[0] * 2, display[1]))
        for i, eye in enumerate((b, a)):
            image.paste(Image.fromarray(eye).resize(display, LANCZOS, box=box), (i * display[0], 0))
        return image
    if mode == 'Graustufen':
        # Preserve the original full-width dot-product block shapes and
        # alignment, including rounding of ties on different BLAS backends.
        start = oy // DEFAULT_BLOCK_ROWS * DEFAULT_BLOCK_ROWS
        stop = min(height, ceil(ey / DEFAULT_BLOCK_ROWS) * DEFAULT_BLOCK_ROWS)
        padded = []
        for eye in (a, b):
            buffer = np.zeros((stop - start, width, 3), dtype=np.uint8)
            buffer[oy - start:ey - start, ox:ex] = eye
            padded.append(buffer)
        rendered = make_anaglyph(*padded, gray=True)[oy - start:ey - start, ox:ex]
    else:
        rendered = make_anaglyph(a, b)
    return Image.fromarray(rendered).resize(display, LANCZOS, box=box)
