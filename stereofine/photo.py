"""Shared, pair-wide photographic adjustments before creative LUTs."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import math

import numpy as np

from .color_transfer import linear_to_srgb, srgb_to_linear


@dataclass(frozen=True)
class PhotoAdjustments:
    exposure: float = 0.0
    highlights: int = 0
    shadows: int = 0
    temperature: int = 0
    tint: int = 0

    @classmethod
    def from_values(cls, values):
        normalized = {}
        for name in cls.__dataclass_fields__:
            limit = 2 if name == 'exposure' else 100
            try:
                value = float(values.get(name, 0))
            except (TypeError, ValueError):
                value = 0
            value = max(-limit, min(limit, value)) if math.isfinite(value) else 0
            normalized[name] = round(value, 2) if name == 'exposure' else round(value)
        return cls(**normalized)


NEUTRAL_PHOTO = PhotoAdjustments()
RGB_XYZ = np.array(((.4124564, .3575761, .1804375),
                    (.2126729, .7151522, .0721750),
                    (.0193339, .1191920, .9503041)))
BRADFORD = np.array(((.8951, .2664, -.1614), (-.7502, 1.7135, .0367), (.0389, -.0685, 1.0296)))
RGB_LMS = BRADFORD @ RGB_XYZ
LMS_RGB = np.linalg.inv(RGB_LMS)
LUMA = RGB_XYZ[1].astype(np.float32)


@lru_cache(maxsize=64)
def _white_balance(temperature, tint):
    white = RGB_XYZ.sum(axis=1)
    denominator = white[0] + 15 * white[1] + 3 * white[2]
    u = 4 * white[0] / denominator + .00022 * temperature + .00009 * tint
    v = 9 * white[1] / denominator + .00023 * temperature - .00020 * tint
    target = np.array((9 * u / (4 * v), 1., (12 - 3 * u - 20 * v) / (4 * v)))
    gains = (BRADFORD @ target) / (BRADFORD @ white)
    return (LMS_RGB @ (gains[:, None] * RGB_LMS)).T.astype(np.float32)


@lru_cache(maxsize=32)
def _tone_curve(highlights, shadows):
    x = np.linspace(0., 3., 12289, dtype=np.float32)
    shadow = np.clip(2 * x, 0, 1)
    light = np.clip(2 * x - 1, 0, 1)
    shifted = (x + .0012 * shadows * 16 * (shadow * (1 - shadow)) ** 2
               + .0014 * highlights * light ** 2 * (3 - 2 * light))
    return x, shifted ** 2


@lru_cache(maxsize=32)
def _linear_input(peak, exposure):
    return srgb_to_linear(np.arange(peak + 1, dtype=np.float32) / peak) * np.float32(2 ** exposure)


def apply_photo(image, adjustments):
    if adjustments == NEUTRAL_PHOTO:
        return image
    peak = np.iinfo(image.dtype).max
    decode = _linear_input(peak, adjustments.exposure)
    matrix = (_white_balance(adjustments.temperature, adjustments.tint)
              if adjustments.temperature or adjustments.tint else None)
    curve = (_tone_curve(adjustments.highlights, adjustments.shadows)
             if adjustments.highlights or adjustments.shadows else None)
    output = np.empty_like(image)
    for row in range(0, image.shape[0], 128):
        rgb = decode[image[row:row + 128]]
        if matrix is not None:
            rgb = rgb @ matrix
        if curve is not None:
            luminance = np.maximum(rgb @ LUMA, 0.)
            target = np.interp(np.sqrt(luminance), *curve).astype(np.float32)
            ratio = np.divide(target, luminance, out=np.ones_like(luminance), where=luminance > 0)
            rgb *= ratio[..., None]
        # Bring out-of-gamut colors toward the neutral axis at constant hue.
        if matrix is not None or curve is not None:
            gray = np.clip(rgb @ LUMA, 0., 1.)
            delta = rgb - gray[..., None]
            upper = np.maximum(delta.max(axis=2), 1.e-7)
            lower = np.maximum(-delta.min(axis=2), 1.e-7)
            scale = np.minimum(1., np.minimum((1 - gray) / upper, gray / lower))
            rgb = gray[..., None] + scale[..., None] * delta
        output[row:row + 128] = np.rint(linear_to_srgb(rgb) * peak).astype(image.dtype)
    return output


def apply_photo_look(left, right, adjustments, look):
    from .looks import apply_pair_look

    return apply_pair_look(apply_photo(left, adjustments), apply_photo(right, adjustments), look)
