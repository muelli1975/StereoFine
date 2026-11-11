# PyInstaller onedir specification for StereoFine 1.4.
# Build from a clean Windows x64 Python 3.12.10 environment.

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files
from scripts.embed_start_image import embed_start_image

block_cipher = None

root = Path(SPECPATH)
embedded = embed_start_image(root, root / 'build' / 'embedded-start-image')
datas = collect_data_files("customtkinter")
datas += [("assets", "assets")]

a = Analysis(
    ["StereoFine.py"],
    pathex=[str(embedded)],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pillow_heif"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="StereoFine",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon="assets/stereofine.ico",
    version="version_info.txt",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="StereoFine",
)

