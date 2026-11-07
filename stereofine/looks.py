"""Display-referred RGB LUTs, shared by stereo preview and export.

Tables are data: no ICC transform is applied to Hald images. Cube outputs may
extend beyond 0..1; clip only after interpolation and strength blending.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import json
from pathlib import Path

import numpy as np

from .resources import asset_path


@dataclass(frozen=True)
class ColorLUT:
    table: np.ndarray  # [blue, green, red, output RGB]
    domain_min: tuple[float, float, float] = (0., 0., 0.)
    domain_max: tuple[float, float, float] = (1., 1., 1.)
    _display_filters: dict = field(default_factory=dict, compare=False, repr=False)

    def apply(self, image: np.ndarray, strength: float = 1.) -> np.ndarray:
        strength = float(strength)
        if not np.isfinite(strength):
            raise ValueError('LUT strength must be finite.')
        strength = float(np.clip(strength, 0., 1.))
        if strength == 0:
            return image
        arr = np.asarray(image)
        if arr.ndim != 3 or arr.shape[2] != 3:
            raise ValueError('A LUT requires an RGB image.')
        if arr.dtype not in (np.uint8, np.uint16) and not np.issubdtype(arr.dtype, np.floating):
            raise ValueError('Unsupported LUT image depth.')
        if (arr.dtype == np.uint8 and self.table.shape[0] <= 65
                and self.domain_min == (0., 0., 0.) and self.domain_max == (1., 1., 1.)
                and np.min(self.table) >= -1 and np.max(self.table) <= 2):
            # Pillow's native trilinear filter handles the 8-bit display path.
            # Blend the TABLE with identity before filtering, so negative LUT
            # outputs are not clipped prematurely at partial strength.
            from PIL import Image, ImageFilter
            filter_ = self._display_filters.get(strength)
            if filter_ is None:
                n = self.table.shape[0]
                table = self.table * strength
                identity = np.linspace(0., 1.-strength, n, dtype=np.float32)
                table[..., 0] += identity[None, None, :]
                table[..., 1] += identity[None, :, None]
                table[..., 2] += identity[:, None, None]
                filter_ = ImageFilter.Color3DLUT(n, table.ravel().tolist(), channels=3)
                self._display_filters.clear()
                self._display_filters[strength] = filter_
            return np.asarray(Image.fromarray(arr).filter(filter_))
        maximum = float(np.iinfo(arr.dtype).max) if np.issubdtype(arr.dtype, np.integer) else 1.
        out = np.empty_like(arr)
        size = self.table.shape[0]
        lower = np.asarray(self.domain_min, np.float32)
        span = np.asarray(self.domain_max, np.float32) - lower
        # Bound working memory for large native images and 16-bit TIFF exports.
        rows = max(1, min(128, 500_000 // max(1, arr.shape[1])))
        for y in range(0, arr.shape[0], rows):
            original = arr[y:y+rows].astype(np.float32) / maximum
            pos = np.clip((original - lower) / span, 0., 1.) * (size - 1)
            lo = np.minimum(pos.astype(np.int32), size - 2)
            frac = pos - lo
            result = np.zeros_like(original)
            for bz in (0, 1):
                for gy in (0, 1):
                    for rx in (0, 1):
                        weight = ((frac[..., 0] if rx else 1-frac[..., 0]) *
                                  (frac[..., 1] if gy else 1-frac[..., 1]) *
                                  (frac[..., 2] if bz else 1-frac[..., 2]))
                        result += self.table[lo[..., 2]+bz, lo[..., 1]+gy,
                                             lo[..., 0]+rx] * weight[..., None]
            result = np.clip(original + strength * (result - original), 0., 1.)
            if np.issubdtype(arr.dtype, np.integer):
                result = np.rint(result * maximum)
            out[y:y+rows] = result.astype(arr.dtype)
        return out


def read_cube(path: Path) -> ColorLUT:
    if path.stat().st_size > 128 * 1024 * 1024:
        raise ValueError('LUT file is too large.')
    raw = path.read_bytes()
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = raw.decode('cp1252')
    size = None
    lower, upper = (0., 0., 0.), (1., 1., 1.)
    values = []
    for number, line in enumerate(text.splitlines(), 1):
        fields = line.partition('#')[0].strip().split()
        if not fields:
            continue
        key = fields[0]
        if key == 'TITLE':
            continue
        if key == 'LUT_3D_SIZE':
            if size is not None or len(fields) != 2:
                raise ValueError('Invalid LUT_3D_SIZE.')
            size = int(fields[1])
            if not 2 <= size <= 129:
                raise ValueError('Supported 3D LUT sizes: 2 through 129.')
            continue
        if key in ('DOMAIN_MIN', 'DOMAIN_MAX'):
            if len(fields) != 4:
                raise ValueError('Invalid LUT domain.')
            vector = tuple(map(float, fields[1:]))
            if key == 'DOMAIN_MIN': lower = vector
            else: upper = vector
            continue
        if key == 'LUT_1D_SIZE':
            raise ValueError('This file contains a 1D LUT; a 3D LUT is required.')
        if len(fields) != 3:
            raise ValueError(f'Invalid LUT data on line {number}.')
        try:
            values.append(tuple(map(float, fields)))
        except ValueError as exc:
            raise ValueError(f'Invalid LUT data on line {number}.') from exc
        if len(values) > 129 ** 3:
            raise ValueError('Too many LUT entries.')
    if size is None or len(values) != size ** 3:
        raise ValueError('LUT entry count does not match LUT_3D_SIZE.')
    table = np.asarray(values, dtype=np.float32)
    if not np.isfinite(table).all() or not np.isfinite([lower, upper]).all():
        raise ValueError('LUT contains non-finite values.')
    if not np.all(np.asarray(upper) > lower):
        raise ValueError('LUT domain maximum must exceed minimum.')
    table = table.reshape(size, size, size, 3)
    table.setflags(write=False)
    return ColorLUT(table, lower, upper)


def read_hald(path: Path) -> ColorLUT:
    import cv2
    # imdecode also supports Unicode paths on Windows, unlike some imread builds.
    data = np.frombuffer(path.read_bytes(), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
    if image is None or image.ndim != 3 or image.shape[2] not in (3, 4):
        raise ValueError('PNG must contain an RGB HaldCLUT.')
    h, w = image.shape[:2]
    level = round(w ** (1/3))
    if h != w or level < 2 or level ** 3 != w or level > 11:
        raise ValueError('Invalid square HaldCLUT dimensions.')
    if image.dtype not in (np.uint8, np.uint16):
        raise ValueError('HaldCLUT must be an 8-bit or 16-bit PNG.')
    maximum = np.iinfo(image.dtype).max
    if image.shape[2] == 4 and np.any(image[..., 3] != maximum):
        raise ValueError('HaldCLUT must be opaque.')
    size = level ** 2
    table = np.ascontiguousarray(image[..., :3][..., ::-1], dtype=np.float32) / maximum
    table = table.reshape(size, size, size, 3)
    table.setflags(write=False)
    return ColorLUT(table)


@lru_cache(maxsize=4)
def _cached_lut(path: str, mtime_ns: int, size: int) -> ColorLUT:
    p = Path(path)
    if p.suffix.lower() == '.cube': return read_cube(p)
    if p.suffix.lower() == '.png': return read_hald(p)
    raise ValueError('Supported LUT formats: .cube and .png HaldCLUT.')


def load_lut(path: str | Path) -> ColorLUT:
    p = Path(path).expanduser().resolve()
    stat = p.stat()
    return _cached_lut(str(p), stat.st_mtime_ns, stat.st_size)


def builtin_looks() -> list[dict]:
    path = asset_path('luts/manifest.json')
    return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else []


def look_label(entry, language='de'):
    return entry.get('name_en', entry['name']) if language == 'en' else entry['name']


def look_path(look) -> Path:
    if look.path:
        return Path(look.path)
    for entry in builtin_looks():
        if entry['id'] == look.preset_id:
            return asset_path('luts/' + entry['file'])
    raise ValueError(f'Unknown LUT preset: {look.preset_id}')


def apply_look(image: np.ndarray, look) -> np.ndarray:
    if look is None or not look.enabled or look.strength <= 0:
        return image
    return load_lut(look_path(look)).apply(image, look.strength)


def apply_pair_look(left, right, look):
    return apply_look(left, look), apply_look(right, look)


def look_signature(look):
    if look is None or not look.enabled or look.strength <= 0:
        return None
    path = look_path(look).resolve()
    stat = path.stat()
    return str(path), stat.st_mtime_ns, stat.st_size, float(look.strength)
