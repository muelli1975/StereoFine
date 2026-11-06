"""Protect job inputs and distinct job outputs; existing exports remain replaceable."""
from pathlib import Path


def _key(path: Path) -> str:
    return str(path.resolve()).casefold()


def _inode(path: Path):
    try:
        info = path.stat()
        return (info.st_dev, info.st_ino) if info.st_ino else None
    except FileNotFoundError:
        return None


class OutputPathGuard:
    def __init__(self, input_paths=()):
        paths = [Path(path) for path in input_paths]
        self._inputs = {_key(path) for path in paths}
        self._input_inodes = {value for path in paths if (value := _inode(path)) is not None}
        self._outputs = {}

    def claim(self, paths, owner):
        """Validate the complete per-source plan before writing its first file."""
        planned = [(Path(path), _key(Path(path))) for path in paths if path is not None]
        for path, key in planned:
            if key in self._inputs or _inode(path) in self._input_inodes:
                raise ValueError(f"Die Ausgabe würde eine Eingabedatei ersetzen. Bitte einen getrennten Ausgabeordner wählen: {path}")
            if key in self._outputs and self._outputs[key] != owner:
                raise ValueError(f"Verschiedene Bilder würden dieselbe Ausgabedatei erzeugen. Bitte Dateinamen oder Ausgabeziel ändern: {path}")
        for _path, key in planned:
            self._outputs[key] = owner
