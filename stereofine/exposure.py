"""Apply the same exposure correction to both eyes before the creative look."""
from __future__ import annotations

from functools import lru_cache
import math

import numpy as np

from .color_transfer import linear_to_srgb, srgb_to_linear


def normalize_exposure(value) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0.0
    return round(max(-2.0, min(2.0, value)), 2) if math.isfinite(value) else 0.0


@lru_cache(maxsize=32)
def _exposure_table(dtype: np.dtype, exposure: float) -> np.ndarray:
    peak = np.iinfo(dtype).max
    samples = np.arange(peak + 1, dtype=np.float32) / peak
    linear = srgb_to_linear(samples) * np.float32(2 ** exposure)
    return np.rint(linear_to_srgb(linear) * peak).astype(dtype)


def apply_exposure(image: np.ndarray, exposure: float) -> np.ndarray:
    if not exposure:
        return image
    return _exposure_table(image.dtype, exposure)[image]


def apply_exposure_and_look(left, right, exposure, look):
    from .looks import apply_pair_look

    return apply_pair_look(apply_exposure(left, exposure), apply_exposure(right, exposure), look)
