"""Build reviewable 1.1 development artifacts; never publish or update releases."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def run(*arguments):
    subprocess.run([str(a) for a in arguments], cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skip-helper-build', action='store_true')
    args = parser.parse_args()
    if not args.skip_helper_build:
        run(sys.executable, 'scripts/prepare_heif.py')
    # Snapshot before PyInstaller touches generated files. Canonical tracked blobs.
    snapshot = ROOT/'build/development-source'
    if snapshot.exists(): shutil.rmtree(snapshot)
    run(sys.executable, 'scripts/package_source.py', snapshot)
    arguments = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir',
                 '--windowed', '--name', 'StereoFine', '--collect-data', 'customtkinter',
                 '--exclude-module', 'pillow_heif', '--add-data', str(ROOT/'assets')+':assets',
                 '--specpath', 'build/development-spec']
    if sys.platform == 'win32': arguments += ['--icon', str(ROOT/'assets/stereofine.ico'), '--version-file', str(ROOT/'version_info.txt')]
    if sys.platform == 'darwin': arguments += ['--icon', str(ROOT/'assets/stereofine.icns')]
    run(*arguments, 'StereoFine.py')
    package = ROOT/'build/development-package/StereoFine'
    if package.exists(): shutil.rmtree(package)
    package.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform == 'darwin':
        shutil.copytree(ROOT/'dist/StereoFine.app', package/'StereoFine.app')
        executable_root = package/'StereoFine.app/Contents/MacOS'
    else:
        shutil.copytree(ROOT/'dist/StereoFine', package)
        executable_root = package
    shutil.copytree(ROOT/'tools/heif', executable_root/'tools/heif')
    # Build CI supplies the official ExifTool tree before calling this script.
    for path in (ROOT/'tools').iterdir():
        if path.name == 'heif': continue
        target = executable_root/'tools'/path.name
        if path.is_dir(): shutil.copytree(path, target)
        else: shutil.copy2(path, target)
    for name in ('README_DE.md', 'README_EN.md', 'LICENSE.txt', 'THIRD_PARTY_NOTICES.md'):
        shutil.copy2(ROOT/name, package/name)
    shutil.copytree(ROOT/'licenses', package/'licenses')
    shutil.copytree(snapshot, package/'Source')
    run(sys.executable, 'scripts/package_source.py', '--verify', package/'Source')
    executable = executable_root/('StereoFine.exe' if sys.platform == 'win32' else 'StereoFine')
    report = ROOT/'build/development-input-check.json'
    run(executable, '--check-inputs', report, ROOT/'tests/fixtures/heif')
    checked = json.loads(report.read_text('utf-8'))
    if not checked['ok']: raise RuntimeError('Packaged inputs failed')
    if not all(row.get('metadata_success', True) for row in checked['checks']):
        raise RuntimeError('Packaged metadata export failed')
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    (package/'DEVELOPMENT_BUILD.txt').write_text(
        f'StereoFine 1.1 development\nCommit: {commit}\n'
        'Unreleased development artifact; includes changes after RC3.\n', 'utf-8')
    label = {'win32': 'Windows', 'darwin': 'macOS'}.get(sys.platform, 'Linux')
    name = f'StereoFine_1.1-dev_{commit[:8]}_{label}_{platform.machine()}'
    output = ROOT/'release'; output.mkdir(exist_ok=True)
    archive = Path(shutil.make_archive(str(output/name), 'zip', package.parent, 'StereoFine'))
    archive.with_suffix('.zip.sha256').write_text(hashlib.sha256(archive.read_bytes()).hexdigest()+'  '+archive.name+'\n', 'utf-8')
    print('Development artifact:', archive)


if __name__ == '__main__': main()
