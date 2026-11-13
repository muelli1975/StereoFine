"""Update only documentation and its checksums in verified release archives."""
import argparse
import copy
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def blob(path):
    return subprocess.check_output(['git', 'show', f'HEAD:{path}'], cwd=ROOT)


def prepare_files(plan, config):
    if plan['repository'].endswith('/StereoFine'):
        from build_package import portable_readme
        from package_source import committed_sources
        commit, sources = committed_sources()
        readmes = {name: portable_readme(sources[name].decode('utf-8')).encode()
                   for name in ('README_DE.md', 'README_EN.md')}
        name = 'RELEASE_NOTES_1.4.md'
        return 'StereoFine', readmes | {name: sources[name]} | {
            f'Source/{name}': data for name, data in sources.items()
        } | {'Source/SOURCE_COMMIT.txt': (commit + '\n').encode()}

    docs = {name: blob(name) for name in (
        'README.md', 'README_DE.md', 'docs/RELEASE_NOTES_1.1.md',
    )}
    source_files = docs | {path: blob(path) for path in (
        config, '.github/workflows/refresh-release-documentation.yml',
        'scripts/refresh_release_docs.py', 'scripts/publish_color_update.py',
    )}
    return 'TransCora', docs | {f'source/{name}': data for name, data in source_files.items()}


def archive_members(path, output, replacements, manifest):
    remaining = dict(replacements)

    def file_data(name, stream, old_size):
        if name == manifest:
            hashes = json.load(stream)
            hashes.update({key.removeprefix(name.split('/')[0] + '/'): hashlib.sha256(value).hexdigest()
                           for key, value in replacements.items()})
            data = json.dumps(dict(sorted(hashes.items())), indent=2).encode()
        elif name in remaining:
            data = remaining.pop(name)
        else:
            return stream, old_size
        return io.BytesIO(data), len(data)

    if path.suffix == '.zip':
        with zipfile.ZipFile(path) as source, zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as target:
            target.comment = source.comment
            for item in source.infolist():
                with source.open(item) as original:
                    data, _ = file_data(item.filename, original, item.file_size)
                    with target.open(copy.copy(item), 'w') as member:
                        shutil.copyfileobj(data, member)
            for name, data in remaining.items():
                target.writestr(name, data)
        with zipfile.ZipFile(output) as target:
            assert target.testzip() is None
            for name, data in replacements.items():
                assert target.read(name) == data
    else:
        with tarfile.open(path, 'r:gz') as source, tarfile.open(output, 'w:gz', compresslevel=3) as target:
            for item in source:
                if not item.isfile():
                    target.addfile(item)
                    continue
                with source.extractfile(item) as original:
                    data, size = file_data(item.name, original, item.size)
                    if size != item.size:
                        item = copy.copy(item)
                        item.size = size
                        item.pax_headers = {key: value for key, value in item.pax_headers.items() if key != 'size'}
                    target.addfile(item, data)
            for name, data in remaining.items():
                item = tarfile.TarInfo(name)
                item.size = len(data)
                target.addfile(item, io.BytesIO(data))
        with tarfile.open(output, 'r:gz') as target:
            for item in target:
                if item.name in replacements:
                    with target.extractfile(item) as stream:
                        assert stream.read() == replacements[item.name]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--originals', type=Path, default=Path('originals'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    plan = json.loads((ROOT / args.config).read_text(encoding='utf-8'))
    app, files = prepare_files(plan, args.config)
    args.originals.mkdir(parents=True, exist_ok=True)
    args.output.mkdir(parents=True, exist_ok=True)
    replacements = {f'{app}/{name}': data for name, data in files.items()}
    manifest = 'TransCora/BUILD_HASHES.json' if app == 'TransCora' else None
    checksums = {}
    for name, expected in plan['assets'].items():
        if not name.endswith(('.zip', '.tar.gz')):
            continue
        archive = args.originals / name
        if not archive.is_file():
            url = f"https://github.com/{plan['repository']}/releases/download/{plan['tag']}/{name}"
            temporary = archive.with_suffix('.download')
            with urllib.request.urlopen(url, timeout=120) as source, temporary.open('wb') as target:
                shutil.copyfileobj(source, target)
            temporary.replace(archive)
        assert 'sha256:' + sha256(archive) == expected, f'Release asset changed: {name}'
        output = args.output / name
        archive_members(archive, output, replacements, manifest)
        checksums[name] = f'{sha256(output)}  {name}\n'
        print(f'Checked {name}', flush=True)
    for name in plan['assets']:
        if name == 'SHA256SUMS.txt':
            (args.output / name).write_text(''.join(checksums.values()), encoding='utf-8')
        elif name.endswith('.sha256'):
            (args.output / name).write_text(checksums[name.removesuffix('.sha256')], encoding='utf-8')


if __name__ == '__main__':
    main()
