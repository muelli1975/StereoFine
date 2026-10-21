"""Verify the four final-candidate archives and write their SHA-256 manifest."""
from __future__ import annotations

import hashlib
from pathlib import Path
import sys

ARCHIVES = (
    'StereoFine_1.1_Windows_x64.zip',
    'StereoFine_1.1_Linux_x64.tar.gz',
    'StereoFine_1.1_macOS_AppleSilicon.zip',
    'StereoFine_1.1_macOS_Intel.zip',
)


def write_manifest(directory: Path):
    rows = []
    for name in ARCHIVES:
        archive = directory/name
        with archive.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        row = f'{digest}  {name}\n'
        if archive.with_name(name+'.sha256').read_text('utf-8') != row:
            raise RuntimeError(f'Checksum mismatch: {name}')
        rows.append(row)
    target = directory/'SHA256SUMS.txt'
    target.write_text(''.join(rows), 'utf-8')
    return target


if __name__ == '__main__':
    print(write_manifest(Path(sys.argv[1])))
