"""SDR colour normalization for newly supported image containers only."""
from __future__ import annotations

import io

import numpy as np
from PIL import Image, ImageCms


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
