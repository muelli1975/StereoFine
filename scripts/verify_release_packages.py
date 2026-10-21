"""Verify native release archives against raw committed source and asset bytes."""
from __future__ import annotations

import hashlib
import json
import struct
import sys
import tarfile
import zipfile
from pathlib import Path

if __package__:
    from .package_source import ROOT, committed_sources
else:
    from package_source import ROOT, committed_sources

PACKAGES = {
    'StereoFine_1.1_Windows_x64.zip': 'windows',
    'StereoFine_1.1_Linux_x64.tar.gz': 'linux',
    'StereoFine_1.1_macOS_AppleSilicon.zip': 'arm64',
    'StereoFine_1.1_macOS_Intel.zip': 'intel',
}
ASSETS = {'stereofine.jpg', 'stereofine.ico', 'stereofine.icns', 'ready.wav'}


def verify_archive(path: Path, platform: str, expected: dict[str, bytes]) -> dict:
    sources = {}
    assets = set()
    binary = None
    helper = False
    tool = exif_version = notes = False

    def inspect(name: str, read) -> None:
        nonlocal binary, helper, tool, exif_version, notes
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
            binary = read()[:4096]
        if name.endswith(('/tools/heif/StereoFine-HEIF', '/tools/heif/StereoFine-HEIF.exe')):
            helper = True
        if name.endswith(('/tools/exiftool', '/tools/exiftool.exe')):
            tool = True
        if '/tools/' in name and name.endswith('/Image/ExifTool.pm'):
            body = read()
            exif_version = b"$VERSION = '13.59'" in body or b'$VERSION = "13.59"' in body
        if name == 'StereoFine/RELEASE_NOTES_1.1.md':
            # Windows checkout text uses CRLF; canonical Source stays byte-exact.
            notes = read().replace(b'\r\n', b'\n') == expected['RELEASE_NOTES_1.1.md'].replace(b'\r\n', b'\n')

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
    if not binary or assets != ASSETS or not all([helper, tool, exif_version, notes]):
        raise RuntimeError(f'{path.name}: binary={bool(binary)}, assets={sorted(assets)}, '
                           f'tool={tool}, exif_version={exif_version}, notes={notes}')
    if platform == 'windows':
        offset = struct.unpack_from('<I', binary, 0x3c)[0] if binary[:2] == b'MZ' else len(binary)
        valid = (binary[offset:offset+4] == b'PE\x00\x00'
                 and struct.unpack_from('<H', binary, offset+4)[0] == 0x8664)
    elif platform == 'linux':
        valid = (binary[:4] == b'\x7fELF' and binary[4] == 2
                 and struct.unpack_from('<H', binary, 18)[0] == 62)
    else:
        valid = (binary[:4] == b'\xcf\xfa\xed\xfe'
                 and struct.unpack('<I', binary[4:8])[0] == {'arm64': 0x100000c, 'intel': 0x1000007}[platform])
    if not valid:
        raise RuntimeError(f'{path.name}: unexpected executable format or architecture')
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'archive': path.name, 'sha256': digest, 'source_files': len(sources), 'passed': True}


def main(folder: Path) -> None:
    if not set(PACKAGES).issubset({p.name for p in folder.iterdir()}):
        raise RuntimeError('Expected all four native 1.1 packages')
    commit, expected = committed_sources()
    expected['SOURCE_COMMIT.txt'] = (commit + '\n').encode()
    for name, platform in PACKAGES.items():
        print(json.dumps(verify_archive(folder / name, platform, expected)), flush=True)


if __name__ == '__main__':
    main(Path(sys.argv[1]))
