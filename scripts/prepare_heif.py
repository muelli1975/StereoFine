"""Freeze the separate reader and retain exact native sources and notices."""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import urllib.request


def main():
    root = Path(__file__).resolve().parents[1]
    pins = json.loads((root/'scripts/heif-sources.json').read_text('utf-8'))
    if importlib.metadata.version('pillow-heif') != pins['reader_version']:
        raise ValueError('Build requires the pinned pillow-heif reader version')
    output = root/'tools/heif'
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--console',
                    '--onedir', '--name', 'StereoFine-HEIF', '--collect-all=pillow_heif',
                    '--distpath', str(root/'build/heif-dist'), '--workpath', str(root/'build/heif-work'),
                    '--specpath', str(root/'build/heif-spec'), str(root/'native/heif/read_heif.py')],
                   cwd=root, check=True)
    shutil.copytree(root/'build/heif-dist/StereoFine-HEIF', output, dirs_exist_ok=True)
    sources = output/'source'; sources.mkdir(exist_ok=True)
    notices = output/'licenses'; notices.mkdir(exist_ok=True)
    for entry in pins['sources']:
        archive = sources/entry['file']
        if not archive.exists():
            with urllib.request.urlopen(entry['url'], timeout=60) as response:
                archive.write_bytes(response.read())
        if archive.stat().st_size != entry['size'] or hashlib.sha256(archive.read_bytes()).hexdigest() != entry['sha256']:
            raise ValueError('HEIF corresponding source checksum mismatch: '+entry['file'])
        # Read notices without unpacking paths or duplicating source trees.
        with tarfile.open(archive, 'r:gz') as package:
            for member in package.getmembers():
                if member.isfile() and Path(member.name).name.lower() in {'copying', 'copying.txt', 'license', 'license.txt', 'licenses_bundled.txt'}:
                    data = package.extractfile(member)
                    if data is not None:
                        (notices/(archive.stem+'-'+member.name.replace('/', '_'))).write_bytes(data.read())
    for name in ('pillow-heif', 'Pillow'):
        distribution = importlib.metadata.distribution(name)
        for entry in distribution.files or []:
            if ('license' in str(entry).lower()) and Path(distribution.locate_file(entry)).is_file():
                shutil.copy2(distribution.locate_file(entry), notices/(name+'-'+Path(entry).name))
    shutil.copy2(root/'native/heif/read_heif.py', sources/'read_heif.py')
    shutil.copy2(root/'native/heif/LICENSE.md', output/'LICENSE.md')
    shutil.copy2(root/'native/heif/UPSTREAM_LICENSE.txt', notices/'TransCora-MIT.txt')
    shutil.copy2(root/'licenses/GPL-3.0.txt', notices/'GPL-3.0.txt')
    shutil.copy2(root/'scripts/prepare_heif.py', sources/'prepare_heif.py')
    shutil.copy2(root/'requirements-build.txt', sources/'requirements-build.txt')
    shutil.copy2(root/'requirements-heif.txt', sources/'requirements-heif.txt')
    shutil.copy2(root/'requirements-lock.txt', sources/'requirements-lock.txt')
    shutil.copy2(root/'scripts/heif-sources.json', output/'BUILD_SOURCES.json')
    binary = output/('StereoFine-HEIF.exe' if sys.platform == 'win32' else 'StereoFine-HEIF')
    result = subprocess.run([str(binary), '--version'], capture_output=True, text=True, check=True, timeout=30)
    (output/'BUILD_READER.json').write_text(result.stdout, 'utf-8')
    print('Separate HEIF reader prepared:', binary)


if __name__ == '__main__':
    main()
