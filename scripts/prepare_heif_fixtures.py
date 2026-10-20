"""Download pinned public fixtures at test/build time only; no runtime downloads."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import urllib.request

FIXTURES = {
    'stereo_pair.heic': ('heif_other', '628d02b8111e9ee8bb9e30935d3b54c32c1dab7c6a852067fcbe315412715b20'),
    'entity_groups.heic': ('heif_special', '463966c69196ee4bc204581fe97c6092bd386d8f8282010ffd622275be0e5c16'),
    'spatial_photo.heic': ('heif_other', 'ef941d328072a2df034adb3c3b46f41117606bfc8fcc100dff975d31f55ec028'),
    'arrow.heic': ('heif_other', '73f604d7353df4848505a1f45a5517f736857fe047372f95c2f3d671df92c22c'),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    args = parser.parse_args()
    args.folder.mkdir(parents=True, exist_ok=True)
    for name, (directory, digest) in FIXTURES.items():
        path = args.folder/name
        if not path.exists():
            url = f'https://raw.githubusercontent.com/bigcat88/pillow_heif/v1.8.1/tests/images/{directory}/{name}'
            with urllib.request.urlopen(url, timeout=60) as response:
                path.write_bytes(response.read())
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('HEIF test fixture checksum mismatch: '+name)
        print('Verified public fixture:', name)


if __name__ == '__main__': main()
