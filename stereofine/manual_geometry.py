"""A common horizon and vertical-perspective correction for a stereo pair."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from math import cos, radians, sin

import numpy as np


ROLL_LIMIT_TENTHS = 50
PERSPECTIVE_LIMIT = 20


def _bounded_integer(value, limit):
    try:
        return max(-limit, min(limit, int(value)))
    except (TypeError, ValueError, OverflowError):
        return 0


@dataclass(frozen=True)
class GeometryAdjustment:
    roll_tenths: int = 0
    perspective: int = 0

    @property
    def active(self):
        return bool(self.roll_tenths or self.perspective)

    def to_dict(self):
        return asdict(self) if self.active else {}

    @classmethod
    def from_dict(cls, values):
        return cls(_bounded_integer(values.get('roll_tenths'), ROLL_LIMIT_TENTHS),
                   _bounded_integer(values.get('perspective'), PERSPECTIVE_LIMIT))

    def step(self, roll=0, perspective=0):
        return GeometryAdjustment(
            _bounded_integer(self.roll_tenths + roll, ROLL_LIMIT_TENTHS),
            _bounded_integer(self.perspective + perspective, PERSPECTIVE_LIMIT),
        )


def geometry_matrix(shape, adjustment: GeometryAdjustment):
    """Map source to corrected pixels, rotating clockwise before the lens shift."""
    h, w = shape[:2]
    cx, cy = (w - 1) / 2, (h - 1) / 2
    angle = radians(adjustment.roll_tenths / 10)
    c, s = cos(angle), sin(angle)
    # At +20, the horizontal magnification at the top is 1.20 times
    # the magnification at the bottom. Negative values exchange those edges.
    shift = adjustment.perspective / (200 + abs(adjustment.perspective)) / max(cy, 1.)
    to_center = np.array([[1., 0., -cx], [0., 1., -cy], [0., 0., 1.]])
    rotate = np.array([[c, -s, 0.], [s, c, 0.], [0., 0., 1.]])
    project = np.array([[1., 0., 0.], [0., 1., 0.], [0., shift, 1.]])
    from_center = np.array([[1., 0., cx], [0., 1., cy], [0., 0., 1.]])
    return from_center @ project @ rotate @ to_center


def prepare_geometry_analysis(left, right, adjustment):
    """Warp only the resized grayscale inputs and exclude generated borders."""
    import cv2

    h, w = left.shape
    matrix = geometry_matrix(left.shape, adjustment)
    valid = cv2.warpPerspective(np.full((h, w), 255, dtype=np.uint8),
                                matrix, (w, h), flags=cv2.INTER_NEAREST)
    valid = cv2.erode(valid, np.ones((5, 5), dtype=np.uint8))
    return (cv2.warpPerspective(left, matrix, (w, h), flags=cv2.INTER_LINEAR),
            cv2.warpPerspective(right, matrix, (w, h), flags=cv2.INTER_LINEAR),
            valid)
