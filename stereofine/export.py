from __future__ import annotations

from dataclasses import dataclass, field
import math
import os
from pathlib import Path
import tempfile

import numpy as np
from PIL import Image

from .anaglyph import make_anaglyph
from .color_profiles import promote_pair, transform_rgb
from .config import ANAGLYPH_JPEG_QUALITY, ANAGLYPH_TARGET_HEIGHT, CROSS_JPEG_QUALITY, SBS_JPEG_QUALITY
from .metadata import MetadataCopyResult, copy_metadata_without_preview_or_orientation
from .models import OutputMode


@dataclass
class ExportResult:
    sbs_path: Path | None = None
    anaglyph_path: Path | None = None
    cross_path: Path | None = None
    metadata_results: list[MetadataCopyResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def to_uint8_output(image: np.ndarray) -> np.ndarray:
    """Perform the intentional final conversion to 8-bit for JPEG output."""
    arr = np.asarray(image)
    if arr.dtype == np.uint8:
        return np.ascontiguousarray(arr)
    if arr.dtype == np.uint16:
        return ((arr.astype(np.uint32) + 128) // 257).astype(np.uint8)
    if np.issubdtype(arr.dtype, np.floating):
        # Color modules may work in normalized float. Keep this conversion explicit.
        if arr.size and float(np.nanmax(arr)) <= 1.00001:
            arr = arr * 255.0
        return np.clip(np.rint(arr), 0, 255).astype(np.uint8)
    raise TypeError(f"Nicht unterstützte Ausgabebittiefe: {arr.dtype}")


def resize_array_to_height(image: np.ndarray, target_height: int) -> np.ndarray:
    if target_height <= 0 or image.shape[0] <= target_height:
        return image
    ratio = target_height / image.shape[0]
    target_width = max(1, round(image.shape[1] * ratio))
    pil = Image.fromarray(image, "RGB")
    return np.asarray(pil.resize((target_width, target_height), Image.Resampling.LANCZOS), dtype=np.uint8)


def _save_rgb_jpeg(image: np.ndarray, path: Path, *, quality: int) -> None:
    """Write a complete JPEG before atomically replacing an existing output."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            Image.fromarray(image, "RGB").save(
                handle,
                format="JPEG",
                quality=int(quality),
                subsampling=0,
                optimize=True,
            )
            handle.flush()
            os.fsync(handle.fileno())
        if not temp_path.is_file() or temp_path.stat().st_size <= 0:
            raise RuntimeError(f"Ausgabedatei wurde nicht korrekt geschrieben: {path}")
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)


def _save_rgb_tiff(image: np.ndarray, path: Path, icc_profile: bytes | None) -> None:
    import tifffile
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    temp = Path(name)
    try:
        os.close(fd)
        with temp.open('w+b') as handle:
            tifffile.imwrite(handle, image, photometric='rgb', compression='deflate',
                             metadata=None, iccprofile=icc_profile)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def deviation_filename_suffix(value: float | None) -> str:
    """Round measured total deviation to whole permille, at least three digits."""
    if value is None or not math.isfinite(value) or value < 0:
        return ""
    return f"_{math.floor(value + 0.5):03d}"


def save_pair_outputs(
    left: np.ndarray,
    right: np.ndarray,
    folder: Path,
    base_name: str,
    *,
    output_mode: OutputMode = "both",
    gray_anaglyph: bool = False,
    save_cross: bool = False,
    tiff_sbs: bool = False,
    icc_profile: bytes | None = None,
    metadata_source: Path | None = None,
    filename_deviation_permille: float | None = None,
) -> ExportResult:
    if left.shape != right.shape:
        raise ValueError(f"Halbbilder haben unterschiedliche Größen: {left.shape} != {right.shape}")
    if output_mode not in {"both", "sbs", "anaglyph"}:
        raise ValueError(f"Unbekannter Ausgabemodus: {output_mode}")

    left, right = promote_pair(left, right)
    left8 = to_uint8_output(transform_rgb(left, icc_profile))
    right8 = to_uint8_output(transform_rgb(right, icc_profile))
    result = ExportResult()
    output_stem = base_name + deviation_filename_suffix(filename_deviation_permille)

    if output_mode in {"both", "sbs"}:
        extension = 'tif' if tiff_sbs else 'jpg'
        result.sbs_path = folder / "sbs" / f"{output_stem}_sbs.{extension}"
        if tiff_sbs:
            _save_rgb_tiff(np.concatenate([left, right], axis=1), result.sbs_path, icc_profile)
        else:
            _save_rgb_jpeg(np.concatenate([left8, right8], axis=1), result.sbs_path, quality=SBS_JPEG_QUALITY)
        meta = copy_metadata_without_preview_or_orientation(
            metadata_source, result.sbs_path, preserve_output_profile=True,
            output_srgb=not (tiff_sbs and icc_profile))
        result.metadata_results.append(meta)
        if meta.attempted and not meta.success:
            result.warnings.append(f"Metadaten SBS: {meta.message}")

    if save_cross:
        result.cross_path = folder / "cross" / f"{output_stem}_cross.jpg"
        _save_rgb_jpeg(np.concatenate([right8, left8], axis=1), result.cross_path, quality=CROSS_JPEG_QUALITY)
        meta = copy_metadata_without_preview_or_orientation(metadata_source, result.cross_path,
                                                               preserve_output_profile=True, output_srgb=True)
        result.metadata_results.append(meta)
        if meta.attempted and not meta.success:
            result.warnings.append(f"Metadaten Kreuzblick: {meta.message}")

    if output_mode in {"both", "anaglyph"}:
        anaglyph = make_anaglyph(left8, right8, gray=gray_anaglyph)
        anaglyph = resize_array_to_height(anaglyph, ANAGLYPH_TARGET_HEIGHT)
        result.anaglyph_path = folder / "anaglyph" / f"{output_stem}_anaglyph.jpg"
        _save_rgb_jpeg(anaglyph, result.anaglyph_path, quality=ANAGLYPH_JPEG_QUALITY)
        meta = copy_metadata_without_preview_or_orientation(metadata_source, result.anaglyph_path,
                                                               preserve_output_profile=True, output_srgb=True)
        result.metadata_results.append(meta)
        if meta.attempted and not meta.success:
            result.warnings.append(f"Metadaten Anaglyphe: {meta.message}")

    return result

