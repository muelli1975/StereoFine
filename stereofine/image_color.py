"""SDR colour normalization for newly supported image containers only."""
from __future__ import annotations

import io
from pathlib import Path

import numpy as np
from PIL import Image, ImageCms


def bmp_profile(path: Path) -> bytes | None:
    """Read only V4/V5 colour metadata that Pillow's BMP decoder omits.

    Pixel decoding remains Pillow's job. Offsets follow Microsoft's
    BITMAPV5HEADER; linked profiles and calibrated endpoints are unsupported.
    """
    with path.open('rb') as source:
        header = source.read(138)
        if header[:2] != b'BM' or len(header) < 18:
            return None
        size = int.from_bytes(header[14:18], 'little')
        if size not in (108, 124):
            return None
        if len(header) < 14+size:
            raise ValueError('Truncated BMP colour header.')
        color_space = int.from_bytes(header[70:74], 'little')
        if color_space in (0x73524742, 0x57696E20):  # sRGB / Windows default sRGB
            return None
        if color_space != 0x4D424544 or size != 124:  # PROFILE_EMBEDDED
            raise ValueError('BMP linked/calibrated colour profiles are unsupported; export an sRGB PNG or TIFF.')
        offset = int.from_bytes(header[126:130], 'little')
        length = int.from_bytes(header[130:134], 'little')
        if offset < size or not 0 < length <= 16*1024*1024 or 14+offset+length > path.stat().st_size:
            raise ValueError('Invalid embedded BMP profile range.')
        source.seek(14+offset)
        return source.read(length)


def sdr_rgb(image: Image.Image) -> np.ndarray:
    # Match the existing PNG import contract: use stored RGB, discard alpha.
    # No new matte, geometry or analysis content is invented for transparent pixels.
    rgb = image.convert('RGB')
    profile = image.info.get('icc_profile')
    if profile:
        rgb = ImageCms.profileToProfile(
            rgb, ImageCms.ImageCmsProfile(io.BytesIO(profile)),
            ImageCms.createProfile('sRGB'), outputMode='RGB')
    return np.asarray(rgb, dtype=np.uint8).copy()
