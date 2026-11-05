from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .config import ASPECT_RATIOS, normalize_aspect_code
from .resources import settings_path
from .output_naming import validate_sbs_suffix

SETTINGS_SCHEMA_VERSION = 1


@dataclass
class AppSettings:
    schema_version: int = SETTINGS_SCHEMA_VERSION
    language: str = "de"
    last_input_location: str = ""
    use_input_output_subfolder: bool = True
    custom_output_folder: str = ""
    default_aspect: str = "original"
    analysis_method: str = "AKAZE"
    color_match_enabled: bool = True
    append_deviation_to_filename: bool = False
    gray_anaglyph: bool = False
    save_cross: bool = False
    tiff_sbs: bool = False
    save_anaglyph: bool = True
    use_custom_sbs_suffix: bool = False
    sbs_suffix: str = "_sbs"

    def normalize(self) -> "AppSettings":
        if self.language not in {"de", "en"}:
            self.language = "de"
        self.default_aspect = normalize_aspect_code(self.default_aspect)
        if self.default_aspect not in ASPECT_RATIOS:
            self.default_aspect = "original"
        self.analysis_method = str(self.analysis_method or "AKAZE").upper()
        if self.analysis_method not in {"AKAZE", "SIFT"}:
            self.analysis_method = "AKAZE"
        self.use_input_output_subfolder = bool(self.use_input_output_subfolder)
        self.color_match_enabled = bool(self.color_match_enabled)
        self.append_deviation_to_filename = bool(self.append_deviation_to_filename)
        self.gray_anaglyph = bool(self.gray_anaglyph)
        self.save_cross = bool(self.save_cross)
        self.tiff_sbs = bool(self.tiff_sbs)
        self.save_anaglyph = bool(self.save_anaglyph)
        self.use_custom_sbs_suffix = bool(self.use_custom_sbs_suffix)
        try:
            self.sbs_suffix = validate_sbs_suffix(self.sbs_suffix)
        except ValueError:
            self.sbs_suffix = "_sbs"
        return self

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppSettings":
        values = {
            field: data.get(field, getattr(cls(), field))
            for field in cls.__dataclass_fields__
        }
        # Preserve the export choice of old settings without restoring a preview.
        if "gray_anaglyph" not in data:
            values["gray_anaglyph"] = data.get("preview_mode") == "Graustufen"
        return cls(**values).normalize()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self.normalize())


def load_settings(path: Path | None = None) -> AppSettings:
    path = path or settings_path()
    if not path.exists():
        return AppSettings()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("settings root must be an object")
        return AppSettings.from_dict(data)
    except Exception:
        # A corrupt preference file must never prevent StereoFine from starting.
        return AppSettings()


def save_settings(settings: AppSettings, path: Path | None = None) -> Path:
    path = path or settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(settings.to_dict(), ensure_ascii=False, indent=2) + "\n"
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
    return path

