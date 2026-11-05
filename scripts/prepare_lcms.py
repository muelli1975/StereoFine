"""Build the pinned, MIT-licensed LittleCMS library for the current platform."""
from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
VERSION = '2.19.1'
SHA256 = 'bfc54f7bab59fbc921012014a8032e4cba4abd46db47d46b76416a8c0b2815c8'
URL = f'https://github.com/mm2/Little-CMS/releases/download/lcms{VERSION}/lcms2-{VERSION}.tar.gz'


def main():
    build = ROOT / 'build/lcms'
    build.mkdir(parents=True, exist_ok=True)
    archive = build / 'source.tar.gz'
    if not archive.exists():
        with urlopen(URL, timeout=90) as response:
            archive.write_bytes(response.read())
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise RuntimeError('LittleCMS source SHA-256 mismatch.')
    source = build / f'lcms2-{VERSION}'
    if not source.exists():
        with tarfile.open(archive) as data:
            data.extractall(build, filter='data')
    cmake = build / 'CMakeLists.txt'
    cmake.write_text('''cmake_minimum_required(VERSION 3.16)
project(StereoFineLCMS C)
file(GLOB LCMS_SOURCES "lcms2-2.19.1/src/cms*.c")
add_library(lcms2 SHARED ${LCMS_SOURCES})
target_include_directories(lcms2 PRIVATE "lcms2-2.19.1/include")
target_compile_definitions(lcms2 PRIVATE CMS_DLL_BUILD)
if(UNIX)
  target_link_libraries(lcms2 PRIVATE m)
endif()
''', encoding='utf-8')
    subprocess.run(['cmake', '-S', str(build), '-B', str(build/'out'),
                    '-DCMAKE_BUILD_TYPE=Release'], check=True)
    subprocess.run(['cmake', '--build', str(build/'out'), '--config', 'Release', '-j', '2'], check=True)
    name = ('lcms2.dll' if sys.platform == 'win32' else
            'liblcms2.dylib' if sys.platform == 'darwin' else 'liblcms2.so')
    matches = list((build/'out').rglob(name))
    if len(matches) != 1:
        raise RuntimeError(f'Expected one native LittleCMS library, found {matches}')
    target = ROOT/'tools/lcms'
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(matches[0], target/name)
    # Verify the committed notice without rewriting a Windows CRLF checkout.
    # A raw LF copy makes Git report a dirty tree even when normalized text is
    # identical; release source snapshots deliberately reject dirty sources.
    if (source/'LICENSE').read_text(encoding='utf-8') != (ROOT/'licenses/LittleCMS.txt').read_text(encoding='utf-8'):
        raise RuntimeError('The bundled LittleCMS license does not match the pinned source.')
    print(f'Prepared LittleCMS {VERSION}: {target/name}')


if __name__ == '__main__':
    main()
