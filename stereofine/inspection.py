"""View-only geometry. It never changes image framing or sidecar crop values."""
from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass
class InspectionView:
    scale: float | None = None  # physical display pixels / final image pixel
    center: tuple[float, float] | None = None

    @property
    def active(self):
        return self.scale is not None

    def reset(self):
        self.scale = None
        self.center = None

    @staticmethod
    def fit_scale(image_size, viewport):
        return min(viewport[0] / image_size[0], viewport[1] / image_size[1])

    def layout(self, image_size, viewport):
        w, h = image_size
        s = self.scale or self.fit_scale(image_size, viewport)
        cw, ch = min(w, viewport[0]/s), min(h, viewport[1]/s)
        cx, cy = self.center or (w/2, h/2)
        cx, cy = max(cw/2, min(w-cw/2, cx)), max(ch/2, min(h-ch/2, cy))
        self.center = cx, cy
        box = (cx-cw/2, cy-ch/2, cx+cw/2, cy+ch/2)
        size = max(1, round(cw*s)), max(1, round(ch*s))
        return box, size

    def zoom(self, factor, image_size, viewport, anchor=(.5, .5)):
        fit = self.fit_scale(image_size, viewport)
        old_box, old_size = self.layout(image_size, viewport)
        old_scale = self.scale or fit
        new_scale = max(fit, min(max(8., fit), old_scale*factor))
        if new_scale <= fit * (1 + 1e-6):
            self.reset()
            return
        ax, ay = anchor
        px = old_box[0] + ax*(old_box[2]-old_box[0])
        py = old_box[1] + ay*(old_box[3]-old_box[1])
        new_w, new_h = min(image_size[0], viewport[0]/new_scale), min(image_size[1], viewport[1]/new_scale)
        self.scale = new_scale
        self.center = px + (.5-ax)*old_size[0]/new_scale, py + (.5-ay)*old_size[1]/new_scale
        self.layout(image_size, viewport)

    def pan(self, dx, dy, image_size, viewport):
        if not self.active:
            return
        self.layout(image_size, viewport)
        self.center = self.center[0]-dx/self.scale, self.center[1]-dy/self.scale
        self.layout(image_size, viewport)


def image_point(display_point, display_size, source_box):
    """Map display coordinates to native final-crop coordinates."""
    x, y = display_point
    dw, dh = display_size
    if not (0 <= x < dw and 0 <= y < dh):
        return None
    a, b, c, d = source_box
    return a+x/dw*(c-a), b+y/dh*(d-b)


def measured_deviation(start, end, image_width):
    if image_width <= 0 or not all(math.isfinite(v) for p in (start, end) for v in p):
        raise ValueError('Invalid measurement geometry.')
    return 1000. * (end[0]-start[0]) / image_width
