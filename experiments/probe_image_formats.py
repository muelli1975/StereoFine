"""Read-only feasibility probe, not registration of new production formats."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import tempfile

import cv2
import numpy as np
from PIL import Image, __version__ as PILLOW_VERSION

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from stereofine.config import SUPPORTED_IMAGE_EXTENSIONS
from stereofine.inputs import (_apply_exif_orientation_array, _decode_cv_image,
    _read_exif_orientation, _to_rgb_keep_depth)


def decode(path):
    return _apply_exif_orientation_array(_to_rgb_keep_depth(_decode_cv_image(path)),
                                         _read_exif_orientation(path))


def probe():
    y, x = np.indices((48, 96))
    image = np.stack([(x*7+y)%256, (x+y*9)%256, (x*3+y*5)%256], axis=-1).astype(np.uint8)
    records = []
    with tempfile.TemporaryDirectory(prefix='stereofine-format-probe-') as td:
        folder = Path(td)
        for format, suffix in [('JPEG', '.jps'), ('PNG', '.pns'), ('BMP', '.bmp'), ('WEBP', '.webp')]:
            path = folder/('probe'+suffix)
            options = dict(lossless=True, exact=True) if format == 'WEBP' else {}
            Image.fromarray(image).save(path, format=format, **options)
            decoded = decode(path)
            with Image.open(path) as im:
                reference = np.asarray(im.convert('RGB'))
            assert np.array_equal(decoded, reference), suffix
            if format != 'JPEG':
                assert np.array_equal(decoded, image), suffix
            records.append(dict(extension=suffix, encoded_format=format,
                production_registered=suffix in SUPPORTED_IMAGE_EXTENSIONS,
                decoder_passed=True, dtype=str(decoded.dtype), shape=list(decoded.shape),
                pixels_equal_pillow=True, lossless_pixels_equal_source=format != 'JPEG'))
        master16 = image.astype(np.uint16)*257
        path = folder/'sixteen.pns'
        ok, data = cv2.imencode('.png', cv2.cvtColor(master16, cv2.COLOR_RGB2BGR))
        assert ok
        path.write_bytes(data.tobytes())
        decoded = decode(path)
        assert decoded.dtype == np.uint16 and np.array_equal(decoded, master16)
        records.append(dict(extension='.pns', encoded_format='PNG16', decoder_passed=True,
                            dtype=str(decoded.dtype), lossless_pixels_equal_source=True))
        path = folder/'animated.webp'
        Image.fromarray(image).save(path, format='WEBP', save_all=True,
            append_images=[Image.fromarray(255-image)], lossless=True, duration=100, loop=0)
        with Image.open(path) as im:
            frames = im.n_frames
        records.append(dict(extension='.webp', case='animation', detected_frames=frames,
            scope='must reject animation or require explicit frame selection; not a stereo pair'))
    return dict(scope='Linux local pinned decoder feasibility only; no input registration or platform build test',
                opencv=cv2.__version__, pillow=PILLOW_VERSION, checks=records)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = probe()
    args.output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))
