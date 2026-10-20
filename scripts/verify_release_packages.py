"""Verify native release archives against raw committed source and asset bytes."""
from __future__ import annotations

import hashlib
import json
import struct
import sys
import tarfile
import zipfile
from pathlib import Path

from package_source import ROOT, committed_sources

PACKAGES = {
    'StereoFine_1.0_Windows_x64.zip': 'windows',
    'StereoFine_1.0_Linux_x64.tar.gz': 'linux',
    'StereoFine_1.0_macOS_AppleSilicon.zip': 'arm64',
    'StereoFine_1.0_macOS_Intel.zip': 'intel',
}
ASSETS = {'stereofine.jpg', 'stereofine.ico', 'stereofine.icns', 'ready.wav'}


def verify_archive(path: Path, platform: str, expected: dict[str, bytes]) -> dict:
    sources = {}
    assets = set()
    binary = None
    tool = exif_version = notes = False

    def inspect(name: str, read) -> None:
        nonlocal binary, tool, exif_version, notes
        if name.startswith('__MACOSX/'):
            return
        if '/Source/' in name:
            sources[name.split('/Source/', 1)[1]] = read()
            return
        leaf = name.rsplit('/', 1)[-1]
        if '/assets/' in name and leaf in ASSETS:
            if read() != (ROOT / 'assets' / leaf).read_bytes():
                raise RuntimeError(f'Changed original asset: {name}')
            assets.add(leaf)
        if name in {'StereoFine/StereoFine.exe', 'StereoFine/StereoFine',
                    'StereoFine/StereoFine.app/Contents/MacOS/StereoFine'}:
            binary = read()[:32]
        if name.endswith(('/tools/exiftool', '/tools/exiftool.exe')):
            tool = True
        if '/tools/' in name and name.endswith('/Image/ExifTool.pm'):
            body = read()
            exif_version = b"$VERSION = '13.59'" in body or b'$VERSION = "13.59"' in body
        if name == 'StereoFine/RELEASE_NOTES_1.0_MAINTENANCE.md':
            # Windows checkout text uses CRLF; canonical Source stays byte-exact.
            notes = read().replace(b'\r\n', b'\n') == expected['RELEASE_NOTES_1.0_MAINTENANCE.md'].replace(b'\r\n', b'\n')

    if path.name.endswith('.tar.gz'):
        with tarfile.open(path, 'r|gz') as archive:
            for member in archive:
                if member.isfile():
                    inspect(member.name, lambda m=member: archive.extractfile(m).read())
    else:
        with zipfile.ZipFile(path) as archive:
            for member in archive.infolist():
                if not member.is_dir():
                    inspect(member.filename, lambda m=member: archive.read(m))
    if sources != expected:
        changed = sorted(k for k in sources.keys() | expected.keys() if sources.get(k) != expected.get(k))
        raise RuntimeError(f'{path.name}: source mismatch: {changed}')
    if not binary or assets != ASSETS or not all([tool, exif_version, notes]):
        raise RuntimeError(f'{path.name}: binary={bool(binary)}, assets={sorted(assets)}, '
                           f'tool={tool}, exif_version={exif_version}, notes={notes}')
    if platform == 'windows':
        valid = binary[:2] == b'MZ'
    elif platform == 'linux':
        valid = binary[:4] == b'\x7fELF' and binary[4] == 2
    else:
        valid = (binary[:4] == b'\xcf\xfa\xed\xfe'
                 and struct.unpack('<I', binary[4:8])[0] == {'arm64': 0x100000c, 'intel': 0x1000007}[platform])
    if not valid:
        raise RuntimeError(f'{path.name}: unexpected executable format or architecture')
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'archive': path.name, 'sha256': digest, 'source_files': len(sources), 'passed': True}


def main(folder: Path) -> None:
    if {p.name for p in folder.iterdir()} != set(PACKAGES):
        raise RuntimeError('Expected exactly the four native 1.0 packages')
    commit, expected = committed_sources()
    expected['SOURCE_COMMIT.txt'] = (commit + '\n').encode()
    for name, platform in PACKAGES.items():
        print(json.dumps(verify_archive(folder / name, platform, expected)), flush=True)


if __name__ == '__main__':
    main(Path(sys.argv[1]))
