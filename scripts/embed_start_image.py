"""Prepare the original start JPEG as an importable PyInstaller module."""
from pathlib import Path


def embed_start_image(root: Path, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    image = (root / 'assets' / 'stereofine.jpg').read_bytes()
    module = directory / '_stereofine_start_image.py'
    module.write_text(f'JPEG_DATA = {image!r}\n', encoding='ascii')
    return directory.resolve()
