# PyInstaller onedir specification for StereoFine 1.0.
# Build from a clean Windows x64 Python 3.12.10 environment.

from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

datas = collect_data_files("customtkinter")
datas += [("assets", "assets")]

a = Analysis(
    ["StereoFine.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name="StereoFine_1.0",
)
