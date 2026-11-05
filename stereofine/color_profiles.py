"""RGB ICC transforms at the master's actual precision (LittleCMS, MIT).

The packaged application ships the native library. Source runs can use the
system library. No profile conversion silently falls back to an 8-bit path.
"""
from __future__ import annotations

import ctypes as C
import ctypes.util
from functools import lru_cache
import sys

import numpy as np

from .resources import tool_path


@lru_cache(maxsize=1)
def _library():
    name = ('lcms2.dll' if sys.platform == 'win32' else
            'liblcms2.dylib' if sys.platform == 'darwin' else 'liblcms2.so')
    bundled = tool_path('lcms/' + name)
    path = str(bundled) if bundled.is_file() else ctypes.util.find_library('lcms2')
    if not path:
        raise RuntimeError('LittleCMS fehlt; Farbprofile können nicht sicher verarbeitet werden.')
    lib = C.CDLL(path)
    signatures = {
        'cmsOpenProfileFromMem': ([C.c_void_p, C.c_uint32], C.c_void_p),
        'cmsCreate_sRGBProfile': ([], C.c_void_p),
        'cmsCloseProfile': ([C.c_void_p], C.c_int),
        'cmsCreateTransform': ([C.c_void_p, C.c_uint32, C.c_void_p, C.c_uint32,
                                C.c_uint32, C.c_uint32], C.c_void_p),
        'cmsDoTransform': ([C.c_void_p, C.c_void_p, C.c_void_p, C.c_uint32], None),
        'cmsDeleteTransform': ([C.c_void_p], None),
        'cmsGetColorSpace': ([C.c_void_p], C.c_uint32),
    }
    for name, (args, result) in signatures.items():
        function = getattr(lib, name)
        function.argtypes, function.restype = args, result
    return lib


def transform_rgb(image: np.ndarray, source: bytes | None,
                  destination: bytes | None = None) -> np.ndarray:
    """None denotes sRGB. Equal profiles leave samples exactly unchanged."""
    if source == destination:
        return image
    if image.dtype not in (np.uint8, np.uint16) or image.ndim != 3 or image.shape[2] != 3:
        raise ValueError('ICC transforms require RGB uint8 or uint16 master data.')
    lib = _library()
    buffers = []
    profiles = []
    transform = None
    try:
        for data in (source, destination):
            if data:
                buffer = C.create_string_buffer(data)
                buffers.append(buffer)
                profile = lib.cmsOpenProfileFromMem(buffer, len(data))
            else:
                profile = lib.cmsCreate_sRGBProfile()
            if not profile:
                raise ValueError('Ungültiges ICC-Farbprofil.')
            profiles.append(profile)
            if lib.cmsGetColorSpace(profile) != 0x52474220:  # cmsSigRgbData
                raise ValueError('Das eingebettete ICC-Farbprofil ist kein RGB-Profil.')
        # PT_RGB, three channels, native-endian integer samples. Perceptual
        # rendering agrees with the existing Pillow sRGB import contract.
        pixel_type = (4 << 16) | (3 << 3) | image.dtype.itemsize
        transform = lib.cmsCreateTransform(profiles[0], pixel_type, profiles[1], pixel_type, 0, 0)
        if not transform:
            raise ValueError('ICC-Farbprofile konnten nicht ineinander umgerechnet werden.')
        src = np.ascontiguousarray(image)
        result = np.empty_like(src)
        # Bound each C call and avoid the uint32 pixel-count limit.
        for y in range(0, src.shape[0], 128):
            a, b = src[y:y+128], result[y:y+128]
            lib.cmsDoTransform(transform, a.ctypes.data, b.ctypes.data, a.shape[0] * a.shape[1])
        return result
    finally:
        if transform:
            lib.cmsDeleteTransform(transform)
        for profile in profiles:
            lib.cmsCloseProfile(profile)


def promote_pair(left: np.ndarray, right: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    if left.dtype != right.dtype:
        if {left.dtype, right.dtype} != {np.dtype('uint8'), np.dtype('uint16')}:
            raise ValueError('Unsupported mixed master depths.')
        left = left.astype(np.uint16) * 257 if left.dtype == np.uint8 else left
        right = right.astype(np.uint16) * 257 if right.dtype == np.uint8 else right
    return left, right
