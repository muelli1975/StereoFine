from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


# Robust display-referred percentile knots. 0/100 are deliberately kept as
# fixed endpoints while the actual fit ignores the most fragile extreme pixels.
DEFAULT_COLOR_PERCENTILES = (0.5, 2.0, 10.0, 25.0, 50.0, 75.0, 90.0, 98.0, 99.5)
COLOR_METHOD = "symmetric_percentile_curve_v1"


def srgb_to_linear(values: np.ndarray) -> np.ndarray:
    """Convert normalized sRGB values [0, 1] to linear-light RGB."""
    values = np.asarray(values, dtype=np.float32)
    return np.where(
        values <= np.float32(0.04045),
        values / np.float32(12.92),
        np.power((values + np.float32(0.055)) / np.float32(1.055), np.float32(2.4)),
    ).astype(np.float32, copy=False)


def linear_to_srgb(values: np.ndarray) -> np.ndarray:
    """Convert linear-light RGB to normalized sRGB values [0, 1]."""
    values = np.asarray(values, dtype=np.float32)
    values = np.clip(values, 0.0, 1.0)
    return np.where(
        values <= np.float32(0.0031308),
        values * np.float32(12.92),
        np.float32(1.055) * np.power(values, np.float32(1.0 / 2.4)) - np.float32(0.055),
    ).astype(np.float32, copy=False)


def _dtype_peak(image: np.ndarray) -> float:
    if image.dtype == np.uint8:
        return 255.0
    if image.dtype == np.uint16:
        return 65535.0
    if np.issubdtype(image.dtype, np.floating):
        return 1.0
    raise TypeError(f"Nicht unterstützte Bittiefe für Farbangleich: {image.dtype}")


def _validate_rgb_pair(left: np.ndarray, right: np.ndarray) -> None:
    if left.shape != right.shape:
        raise ValueError(f"Halbbilder haben unterschiedliche Größen: {left.shape} != {right.shape}")
    if left.ndim != 3 or left.shape[2] != 3:
        raise ValueError(f"RGB-Bild HxWx3 erwartet, erhalten: {left.shape}")
    if left.dtype != right.dtype:
        raise TypeError(f"Halbbilder haben unterschiedliche Datentypen: {left.dtype} != {right.dtype}")
    _dtype_peak(left)


def _normalized_float(image: np.ndarray) -> np.ndarray:
    peak = _dtype_peak(image)
    arr = np.asarray(image, dtype=np.float32)
    if peak != 1.0:
        arr = arr / np.float32(peak)
    return np.clip(arr, 0.0, 1.0)


def _sample_rgb(image: np.ndarray, max_samples: int) -> np.ndarray:
    flat = image.reshape(-1, 3)
    count = flat.shape[0]
    if count <= max_samples:
        return flat
    # Deterministic stride sampling. No random state, no hidden non-reproducibility.
    step = max(1, count // max_samples)
    sampled = flat[::step]
    return sampled[:max_samples]


def _strict_interp_knots(source: np.ndarray, target: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Collapse duplicate source knots while keeping a monotonic deterministic curve."""
    source = np.asarray(source, dtype=np.float32)
    target = np.asarray(target, dtype=np.float32)
    unique, inverse = np.unique(source, return_inverse=True)
    if len(unique) == len(source):
        return source, target
    sums = np.zeros(len(unique), dtype=np.float64)
    counts = np.zeros(len(unique), dtype=np.int32)
    for idx, group in enumerate(inverse):
        sums[group] += float(target[idx])
        counts[group] += 1
    collapsed = (sums / np.maximum(1, counts)).astype(np.float32)
    return unique.astype(np.float32), collapsed


@dataclass(frozen=True)
class SymmetricColorTransfer:
    method: str
    percentiles: tuple[float, ...]
    left_source: tuple[tuple[float, ...], tuple[float, ...], tuple[float, ...]]
    right_source: tuple[tuple[float, ...], tuple[float, ...], tuple[float, ...]]
    target: tuple[tuple[float, ...], tuple[float, ...], tuple[float, ...]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "percentiles": list(self.percentiles),
            "left_source": [list(v) for v in self.left_source],
            "right_source": [list(v) for v in self.right_source],
            "target": [list(v) for v in self.target],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SymmetricColorTransfer":
        def triples(key: str):
            values = data.get(key)
            if not isinstance(values, list) or len(values) != 3:
                raise ValueError(f"Ungültige Farbangleich-Parameter: {key}")
            return tuple(tuple(float(x) for x in channel) for channel in values)

        return cls(
            method=str(data.get("method", "")),
            percentiles=tuple(float(x) for x in data.get("percentiles", [])),
            left_source=triples("left_source"),
            right_source=triples("right_source"),
            target=triples("target"),
        )


def fit_symmetric_color_transfer(
    left: np.ndarray,
    right: np.ndarray,
    *,
    percentiles: tuple[float, ...] = DEFAULT_COLOR_PERCENTILES,
    max_samples: int = 500_000,
) -> SymmetricColorTransfer:
    """Fit a conservative symmetric per-channel percentile curve.

    Neither eye is the reference. Each channel of both images is mapped towards
    the midpoint of the two robust percentile curves. Endpoints 0 and 1 are fixed,
    so the mapping does not create an artificial black/white clipping boundary.
    """
    _validate_rgb_pair(left, right)
    if max_samples < 1:
        raise ValueError("max_samples muss mindestens 1 sein.")
    if not percentiles:
        raise ValueError("Mindestens ein Perzentil wird benötigt.")
    p = np.asarray(percentiles, dtype=np.float32)
    if np.any(p <= 0.0) or np.any(p >= 100.0) or np.any(np.diff(p) <= 0.0):
        raise ValueError("Perzentile müssen strikt steigend zwischen 0 und 100 liegen.")

    left_sample = _sample_rgb(_normalized_float(left), max_samples)
    right_sample = _sample_rgb(_normalized_float(right), max_samples)

    left_curves: list[tuple[float, ...]] = []
    right_curves: list[tuple[float, ...]] = []
    target_curves: list[tuple[float, ...]] = []
    for channel in range(3):
        lq = np.percentile(left_sample[:, channel], p).astype(np.float32)
        rq = np.percentile(right_sample[:, channel], p).astype(np.float32)
        target = (lq + rq) * np.float32(0.5)
        # Explicit full-range anchors keep the transfer bounded and predictable.
        lq = np.concatenate(([0.0], lq, [1.0])).astype(np.float32)
        rq = np.concatenate(([0.0], rq, [1.0])).astype(np.float32)
        target = np.concatenate(([0.0], target, [1.0])).astype(np.float32)
        target = np.maximum.accumulate(target)
        left_curves.append(tuple(float(x) for x in lq))
        right_curves.append(tuple(float(x) for x in rq))
        target_curves.append(tuple(float(x) for x in target))

    return SymmetricColorTransfer(
        method=COLOR_METHOD,
        percentiles=tuple(float(x) for x in percentiles),
        left_source=tuple(left_curves),  # type: ignore[arg-type]
        right_source=tuple(right_curves),  # type: ignore[arg-type]
        target=tuple(target_curves),  # type: ignore[arg-type]
    )


def _apply_curve(image: np.ndarray, source_curves, target_curves, strength: float) -> np.ndarray:
    src = _normalized_float(image)
    out = np.empty_like(src, dtype=np.float32)
    for channel in range(3):
        xp, fp = _strict_interp_knots(
            np.asarray(source_curves[channel], dtype=np.float32),
            np.asarray(target_curves[channel], dtype=np.float32),
        )
        mapped = np.interp(src[..., channel], xp, fp).astype(np.float32)
        if strength < 1.0:
            mapped = src[..., channel] + np.float32(strength) * (mapped - src[..., channel])
        out[..., channel] = mapped
    out = np.clip(out, 0.0, 1.0)

    if image.dtype == np.uint8:
        return np.rint(out * np.float32(255.0)).astype(np.uint8)
    if image.dtype == np.uint16:
        return np.rint(out * np.float32(65535.0)).astype(np.uint16)
    return out.astype(image.dtype, copy=False)


def apply_symmetric_color_transfer(
    left: np.ndarray,
    right: np.ndarray,
    transfer: SymmetricColorTransfer,
    *,
    strength: float = 1.0,
) -> tuple[np.ndarray, np.ndarray]:
    _validate_rgb_pair(left, right)
    strength = float(strength)
    if not 0.0 <= strength <= 1.0:
        raise ValueError("Farbangleich-Stärke muss zwischen 0 und 1 liegen.")
    if transfer.method != COLOR_METHOD:
        raise ValueError(f"Unbekannte Farbangleich-Methode: {transfer.method}")
    if strength == 0.0:
        return left.copy(), right.copy()
    return (
        _apply_curve(left, transfer.left_source, transfer.target, strength),
        _apply_curve(right, transfer.right_source, transfer.target, strength),
    )


def symmetric_color_match(
    left: np.ndarray,
    right: np.ndarray,
    *,
    strength: float = 1.0,
    percentiles: tuple[float, ...] = DEFAULT_COLOR_PERCENTILES,
    max_samples: int = 500_000,
) -> tuple[np.ndarray, np.ndarray, SymmetricColorTransfer]:
    transfer = fit_symmetric_color_transfer(
        left,
        right,
        percentiles=percentiles,
        max_samples=max_samples,
    )
    left_out, right_out = apply_symmetric_color_transfer(left, right, transfer, strength=strength)
    return left_out, right_out, transfer
