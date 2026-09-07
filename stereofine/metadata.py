from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .resources import tool_path


@dataclass(frozen=True)
class MetadataCopyResult:
    attempted: bool
    success: bool
    message: str = ""


def find_exiftool_path() -> Path | None:
    # Windows portable builds ship exiftool.exe; macOS/Linux portable builds
    # use the native executable name.  Source runs may also use ExifTool from PATH.
    for name in ("exiftool.exe", "exiftool"):
        bundled = tool_path(name)
        if bundled.is_file():
            return bundled
    found = shutil.which("exiftool") or shutil.which("exiftool.exe")
    return Path(found) if found else None


def copy_metadata_without_preview_or_orientation(src_path: Path | None, dst_path: Path) -> MetadataCopyResult:
    """Copy useful metadata while excluding preview, Orientation and MPO/MPF container data."""
    if src_path is None or not src_path.is_file():
        return MetadataCopyResult(False, False, "Keine gültige Metadatenquelle.")
    if not dst_path.is_file():
        # The caller has already written the image when metadata copy is
        # requested. A missing destination is therefore a real copy failure.
        return MetadataCopyResult(True, False, "Zieldatei existiert nicht.")
    exiftool_path = find_exiftool_path()
    if exiftool_path is None:
        # Metadata was requested from a valid source; image export may still
        # succeed, but the caller should surface this non-fatal warning.
        return MetadataCopyResult(True, False, "ExifTool nicht gefunden.")

    try:
        completed = subprocess.run(
            [
                str(exiftool_path),
                "-overwrite_original",
                "-TagsFromFile",
                str(src_path),
                "--Preview:all",
                "--Orientation",
                "--MPF:all",
                str(dst_path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as exc:
        return MetadataCopyResult(True, False, str(exc))

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "ExifTool meldete einen Fehler.").strip()
        return MetadataCopyResult(True, False, detail)
    return MetadataCopyResult(True, True, (completed.stdout or "").strip())
