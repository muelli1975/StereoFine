from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

try:
    from PIL import MpoImagePlugin as _PIL_MPO_PLUGIN  # noqa: F401
except Exception:  # pragma: no cover - defensive for unusual Pillow builds
    _PIL_MPO_PLUGIN = None

from .config import (
    SUPPORTED_IMAGE_EXTENSIONS,
    SUPPORTED_MPO_EXTENSIONS,
    SUPPORTED_STEREO_SINGLE_EXTENSIONS,
)


class InputError(RuntimeError):
    pass


@dataclass(frozen=True)
class LoadedStereoPair:
    left: np.ndarray
    right: np.ndarray
    left_path: Path
    right_path: Path
    kind: str
    source_width: int
    source_height: int
    left_source_width: int
    left_source_height: int
    right_source_width: int
    right_source_height: int


def is_image_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS


def is_mpo_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in SUPPORTED_MPO_EXTENSIONS


def is_stereo_single_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in SUPPORTED_STEREO_SINGLE_EXTENSIONS


def list_image_files(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted((p for p in folder.iterdir() if is_image_file(p)), key=lambda p: p.name.lower())


def list_stereo_single_files(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted((p for p in folder.iterdir() if is_stereo_single_file(p)), key=lambda p: p.name.lower())


def _read_exif_orientation(path: Path) -> int:
    try:
        with Image.open(path) as image:
            return int(image.getexif().get(274, 1) or 1)
    except Exception:
        return 1


def _apply_exif_orientation_array(array: np.ndarray, orientation: int) -> np.ndarray:
    # Equivalent to Pillow ImageOps.exif_transpose, but keeps uint16 master data.
    if orientation == 1:
        return array
    if orientation == 2:
        return np.fliplr(array)
    if orientation == 3:
        return np.rot90(array, 2)
    if orientation == 4:
        return np.flipud(array)
    if orientation == 5:
        return np.transpose(array, (1, 0, 2)) if array.ndim == 3 else array.T
    if orientation == 6:
        return np.rot90(array, 3)
    if orientation == 7:
        transposed = np.transpose(array, (1, 0, 2)) if array.ndim == 3 else array.T
        return np.flipud(np.fliplr(transposed))
    if orientation == 8:
        return np.rot90(array, 1)
    return array


def _decode_cv_image(path: Path) -> np.ndarray:
    try:
        encoded = np.fromfile(path, dtype=np.uint8)
    except OSError as exc:
        raise InputError(f"Bild konnte nicht gelesen werden: {path}") from exc
    flags = cv2.IMREAD_UNCHANGED
    if hasattr(cv2, "IMREAD_IGNORE_ORIENTATION"):
        flags |= cv2.IMREAD_IGNORE_ORIENTATION
    decoded = cv2.imdecode(encoded, flags)
    if decoded is None:
        raise InputError(f"Nicht unterstützte oder beschädigte Bilddatei: {path}")
    return decoded


def _to_rgb_keep_depth(decoded: np.ndarray) -> np.ndarray:
    if decoded.ndim == 2:
        return np.repeat(decoded[:, :, None], 3, axis=2)
    if decoded.ndim != 3:
        raise InputError(f"Unerwartete Bildform: {decoded.shape}")
    channels = decoded.shape[2]
    if channels == 3:
        return cv2.cvtColor(decoded, cv2.COLOR_BGR2RGB)
    if channels == 4:
        # StereoFine does not use alpha as image content. Drop it deliberately,
        # preserving the underlying RGB bit depth instead of converting to 8 bit.
        return cv2.cvtColor(decoded, cv2.COLOR_BGRA2RGB)
    if channels == 1:
        return np.repeat(decoded, 3, axis=2)
    raise InputError(f"Unerwartete Kanalzahl: {channels}")


def load_master_image(path: Path) -> np.ndarray:
    """Load JPEG/PNG/TIFF as RGB while retaining uint8/uint16 precision."""
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_IMAGE_EXTENSIONS:
        raise InputError(f"Nicht unterstütztes Bildformat: {suffix or path.name}")
    decoded = _decode_cv_image(path)
    rgb = _to_rgb_keep_depth(decoded)
    orientation = _read_exif_orientation(path)
    rgb = _apply_exif_orientation_array(rgb, orientation)
    if rgb.dtype not in (np.uint8, np.uint16):
        raise InputError(f"Nicht unterstützte Bittiefe: {rgb.dtype}")
    return np.ascontiguousarray(rgb)


def master_to_uint8(image: np.ndarray) -> np.ndarray:
    """Create the explicit 8-bit proxy used by preview/feature/disparity code."""
    if image.dtype == np.uint8:
        return image
    if image.dtype == np.uint16:
        # Standard full-range uint16 -> uint8 conversion with rounding.
        return ((image.astype(np.uint32) + 128) // 257).astype(np.uint8)
    raise InputError(f"Nicht unterstützte Bittiefe: {image.dtype}")


def center_crop_to_common_size(left: np.ndarray, right: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    h = min(left.shape[0], right.shape[0])
    w = min(left.shape[1], right.shape[1])
    if h < 1 or w < 1:
        raise InputError("Die Halbbilder besitzen keinen gemeinsamen gültigen Bildbereich.")

    def crop(image: np.ndarray) -> np.ndarray:
        y0 = max(0, (image.shape[0] - h) // 2)
        x0 = max(0, (image.shape[1] - w) // 2)
        return np.ascontiguousarray(image[y0:y0 + h, x0:x0 + w])

    return crop(left), crop(right)


def load_pair(left_path: Path, right_path: Path) -> LoadedStereoPair:
    # Transactional load: do not publish either half until both are valid.
    left = load_master_image(left_path)
    right = load_master_image(right_path)
    left_size = (left.shape[1], left.shape[0])
    right_size = (right.shape[1], right.shape[0])
    left, right = center_crop_to_common_size(left, right)
    return LoadedStereoPair(
        left=left,
        right=right,
        left_path=left_path,
        right_path=right_path,
        kind="pair",
        source_width=left.shape[1],
        source_height=left.shape[0],
        left_source_width=left_size[0],
        left_source_height=left_size[1],
        right_source_width=right_size[0],
        right_source_height=right_size[1],
    )


def load_full_sbs(path: Path) -> LoadedStereoPair:
    image = load_master_image(path)
    h, w = image.shape[:2]
    if w < 2:
        raise InputError("Full-SBS-Datei ist zu schmal.")
    half = w // 2
    if half < 1:
        raise InputError("Full-SBS-Datei enthält keine zwei gültigen Halbbilder.")
    # If the source width is odd, discard the single center remainder pixel.
    left = np.ascontiguousarray(image[:, :half])
    right = np.ascontiguousarray(image[:, w - half:])
    left_size = (left.shape[1], left.shape[0])
    right_size = (right.shape[1], right.shape[0])
    left, right = center_crop_to_common_size(left, right)
    return LoadedStereoPair(
        left, right, path, path, "full_sbs", left.shape[1], left.shape[0],
        left_size[0], left_size[1], right_size[0], right_size[1]
    )


def _pil_frame_to_rgb_array(image: Image.Image) -> np.ndarray:
    return np.asarray(image.convert("RGB"), dtype=np.uint8).copy()


def load_mpo(path: Path) -> LoadedStereoPair:
    try:
        with Image.open(path) as image:
            image.seek(0)
            left = _pil_frame_to_rgb_array(image.copy())
            left_size = (left.shape[1], left.shape[0])
            try:
                image.seek(1)
            except EOFError as exc:
                raise InputError("MPO-Datei enthält kein zweites Halbbild.") from exc
            right = _pil_frame_to_rgb_array(image.copy())
            right_size = (right.shape[1], right.shape[0])
    except InputError:
        raise
    except Exception as exc:
        raise InputError(f"MPO-Datei konnte nicht geladen werden: {path}") from exc
    left, right = center_crop_to_common_size(left, right)
    return LoadedStereoPair(
        left, right, path, path, "mpo", left.shape[1], left.shape[0],
        left_size[0], left_size[1], right_size[0], right_size[1]
    )


def load_stereo_single_file(path: Path) -> LoadedStereoPair:
    if is_mpo_file(path):
        return load_mpo(path)
    return load_full_sbs(path)


def detect_underscore_side(path: Path) -> tuple[str, str] | None:
    stem = path.stem
    lower = stem.lower()
    if lower.endswith("_l"):
        return stem[:-2], "left"
    if lower.endswith("_r"):
        return stem[:-2], "right"
    return None


def find_file_case_insensitive(folder: Path, name: str) -> Path | None:
    if not folder.is_dir():
        return None
    target = name.casefold()
    for item in folder.iterdir():
        if item.is_file() and item.name.casefold() == target:
            return item
    return None


def find_child_dir_case_insensitive(folder: Path, name: str) -> Path | None:
    if not folder.is_dir():
        return None
    target = name.casefold()
    for item in folder.iterdir():
        if item.is_dir() and item.name.casefold() == target:
            return item
    return None


def find_file_by_stem_case_insensitive(folder: Path, stem: str) -> Path | None:
    if not folder.is_dir():
        return None
    target = stem.casefold()
    candidates = [p for p in folder.iterdir() if is_image_file(p) and p.stem.casefold() == target]
    return sorted(candidates, key=lambda p: p.name.lower())[0] if candidates else None


def find_pair_for_image(path: Path) -> tuple[Path, Path] | None:
    """Resolve either sibling _l/_r pairs or l/r directory pairs."""
    side = detect_underscore_side(path)
    if side:
        base, which = side
        other_stem = base + ("_r" if which == "left" else "_l")
        other = find_file_by_stem_case_insensitive(path.parent, other_stem)
        if other:
            return (path, other) if which == "left" else (other, path)

    parent = path.parent
    parent_name = parent.name.casefold()
    if parent_name in {"l", "r"}:
        sibling_name = "r" if parent_name == "l" else "l"
        sibling_dir = find_child_dir_case_insensitive(parent.parent, sibling_name)
        if sibling_dir:
            other = find_file_case_insensitive(sibling_dir, path.name)
            if other is None:
                other = find_file_by_stem_case_insensitive(sibling_dir, path.stem)
            if other:
                return (path, other) if parent_name == "l" else (other, path)
    return None


def build_suffix_pair_sequence(folder: Path) -> list[tuple[Path, Path]]:
    files = list_image_files(folder)
    by_key: dict[str, dict[str, Path]] = {}
    for path in files:
        side = detect_underscore_side(path)
        if side is None:
            continue
        base, which = side
        by_key.setdefault(base.casefold(), {})[which] = path
    pairs = []
    for key in sorted(by_key):
        entry = by_key[key]
        if "left" in entry and "right" in entry:
            pairs.append((entry["left"], entry["right"]))
    return pairs


def build_lr_dir_pair_sequence(root: Path) -> list[tuple[Path, Path]]:
    left_dir = find_child_dir_case_insensitive(root, "l")
    right_dir = find_child_dir_case_insensitive(root, "r")
    if left_dir is None or right_dir is None:
        return []
    pairs: list[tuple[Path, Path]] = []
    for left in list_image_files(left_dir):
        right = find_file_case_insensitive(right_dir, left.name)
        if right is None:
            right = find_file_by_stem_case_insensitive(right_dir, left.stem)
        if right is not None:
            pairs.append((left, right))
    return pairs
