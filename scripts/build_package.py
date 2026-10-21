"""Build checked development or final-candidate packages without publishing."""
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


def archive_spec(candidate, commit, system, machine):
    if not candidate:
        return f'StereoFine_1.1-dev_{commit[:8]}_{system}_{machine}', 'zip'
    if system == 'Windows' and machine.lower() in {'amd64', 'x86_64'}:
        return 'StereoFine_1.1_Windows_x64', 'zip'
    if system == 'Linux' and machine.lower() in {'amd64', 'x86_64'}:
        return 'StereoFine_1.1_Linux_x64', 'gztar'
    if system == 'macOS' and machine.lower() in {'arm64', 'aarch64', 'x86_64'}:
        architecture = 'Intel' if machine.lower() == 'x86_64' else 'AppleSilicon'
        return f'StereoFine_1.1_macOS_{architecture}', 'zip'
    raise ValueError(f'Unsupported release target: {system}/{machine}')


def require_candidate_version(root):
    # Check both displayed versions before downloading or building anything.
    import ast
    values = {}
    for statement in ast.parse((root/'stereofine/config.py').read_text('utf-8')).body:
        if isinstance(statement, ast.Assign):
            for target in statement.targets:
                if isinstance(target, ast.Name) and target.id == 'APP_VERSION':
                    values[target.id] = ast.literal_eval(statement.value)
    info = (root/'version_info.txt').read_text('utf-8')
    if (values.get('APP_VERSION') != '1.1'
            or "StringStruct('FileVersion', '1.1')" not in info
            or "StringStruct('ProductVersion', '1.1')" not in info
            or 'flags=0x0,' not in info):
        raise RuntimeError('Final candidates require APP_VERSION and Windows metadata set to 1.1 without prerelease flags.')


def run(*arguments):
    subprocess.run([str(a) for a in arguments], cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skip-helper-build', action='store_true')
    parser.add_argument('--candidate', action='store_true', help='Require final 1.1 metadata; build without publishing')
    parser.add_argument('--fixtures', type=Path, default=ROOT/'tests/fixtures/heif')
    args = parser.parse_args()
    if args.candidate:
        require_candidate_version(ROOT)
    build_kind = 'candidate' if args.candidate else 'development'
    if not args.skip_helper_build:
        run(sys.executable, 'scripts/prepare_heif.py')
    # Snapshot before PyInstaller touches generated files. Canonical tracked blobs.
    snapshot = ROOT/f'build/{build_kind}-source'
    if snapshot.exists(): shutil.rmtree(snapshot)
    run(sys.executable, 'scripts/package_source.py', snapshot)
    arguments = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir',
                 '--windowed', '--name', 'StereoFine', '--collect-data', 'customtkinter',
                 '--exclude-module', 'pillow_heif', '--add-data', str(ROOT/'assets')+':assets',
                 '--specpath', f'build/{build_kind}-spec']
    if sys.platform == 'win32': arguments += ['--icon', str(ROOT/'assets/stereofine.ico'), '--version-file', str(ROOT/'version_info.txt')]
    if sys.platform == 'darwin': arguments += ['--icon', str(ROOT/'assets/stereofine.icns')]
    run(*arguments, 'StereoFine.py')
    package = ROOT/f'build/{build_kind}-package/StereoFine'
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
    for name in ('README_DE.md', 'README_EN.md', 'LICENSE.txt', 'THIRD_PARTY_NOTICES.md', 'RELEASE_NOTES_1.1.md'):
        shutil.copy2(ROOT/name, package/name)
    shutil.copytree(ROOT/'licenses', package/'licenses')
    shutil.copytree(snapshot, package/'Source')
    run(sys.executable, 'scripts/package_source.py', '--verify', package/'Source')
    executable = executable_root/('StereoFine.exe' if sys.platform == 'win32' else 'StereoFine')
    report = ROOT/f'build/{build_kind}-input-check.json'
    run(executable, '--check-inputs', report, args.fixtures.resolve())
    checked = json.loads(report.read_text('utf-8'))
    if not checked['ok']: raise RuntimeError('Packaged inputs failed')
    if not all(row.get('metadata_success', True) for row in checked['checks']):
        raise RuntimeError('Packaged metadata export failed')
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    marker = 'RELEASE_CANDIDATE.txt' if args.candidate else 'DEVELOPMENT_BUILD.txt'
    (package/marker).write_text(
        f'StereoFine 1.1 {build_kind}\nCommit: {commit}\n'
        'Unpublished build; platform verification is required before release.\n', 'utf-8')
    label = {'win32': 'Windows', 'darwin': 'macOS'}.get(sys.platform, 'Linux')
    name, archive_format = archive_spec(args.candidate, commit, label, platform.machine())
    output = ROOT/'release'; output.mkdir(exist_ok=True)
    if args.candidate and sys.platform == 'darwin':
        archive = output/(name+'.zip')
        run('ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', package, archive)
    else:
        archive = Path(shutil.make_archive(str(output/name), archive_format, package.parent, 'StereoFine'))
    archive.with_name(archive.name+'.sha256').write_text(hashlib.sha256(archive.read_bytes()).hexdigest()+'  '+archive.name+'\n', 'utf-8')
    print(f'{build_kind.capitalize()} artifact:', archive)


if __name__ == '__main__': main()
