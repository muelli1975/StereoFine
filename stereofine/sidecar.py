from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from .config import (
    ALIGNMENT_PIPELINE_VERSION,
    COLOR_PIPELINE_VERSION,
    DISPARITY_PIPELINE_VERSION,
    INPUT_PIPELINE_VERSION,
    SIDECAR_SCHEMA_VERSION,
)
from .exposure import normalize_exposure
from .models import FileStamp, SourceStamp


class SidecarStatus(str, Enum):
    MISSING = "missing"
    VALID = "valid"
    STALE = "stale"
    INVALID = "invalid"


@dataclass
class SidecarDocument:
    schema_version: int = SIDECAR_SCHEMA_VERSION
    source: dict[str, Any] = field(default_factory=dict)
    pipeline: dict[str, str] = field(
        default_factory=lambda: {
            "input": INPUT_PIPELINE_VERSION,
            "alignment": ALIGNMENT_PIPELINE_VERSION,
            "disparity": DISPARITY_PIPELINE_VERSION,
            "color": COLOR_PIPELINE_VERSION,
        }
    )
    favorite: bool = False
    input_state: dict[str, Any] = field(default_factory=dict)
    alignment: dict[str, Any] = field(default_factory=dict)
    manual: dict[str, Any] = field(default_factory=dict)
    framing: dict[str, Any] = field(default_factory=dict)
    floating_window: dict[str, Any] = field(default_factory=dict)
    disparity: dict[str, Any] = field(default_factory=dict)
    color: dict[str, Any] = field(default_factory=dict)
    look: dict[str, Any] = field(default_factory=dict)
    exposure: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        exposure = data.pop("exposure")
        if exposure:
            data["photo"] = {"exposure": exposure}
        data["schema_version"] = SIDECAR_SCHEMA_VERSION
        return {key: value for key, value in data.items() if value}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SidecarDocument":
        return cls(
            schema_version=int(data.get("schema_version", SIDECAR_SCHEMA_VERSION)),
            source=dict(data.get("source") or {}),
            pipeline=dict(data.get("pipeline") or {}),
            favorite=bool(data.get("favorite", False)),
            # Test builds also wrote preview orientations. Only the stored
            # image value, if any, survives a read or rewrite.
            input_state={} if data.get("input_override") is False else dict(data.get("input_state") or {}),
            alignment=dict(data.get("alignment") or {}),
            manual=dict(data.get("manual") or {}),
            framing=dict(data.get("framing") or {}),
            floating_window=dict(data.get("floating_window") or {}),
            disparity=dict(data.get("disparity") or {}),
            color=dict(data.get("color") or {}),
            look=dict(data.get("look") or {}),
            exposure=normalize_exposure(dict(data.get("photo") or {}).get("exposure", 0.0)),
        )


@dataclass(frozen=True)
class SidecarLoadResult:
    status: SidecarStatus
    document: SidecarDocument | None = None
    message: str = ""
    pipeline_mismatches: tuple[str, ...] = ()

    @property
    def alignment_cache_valid(self) -> bool:
        return self.status == SidecarStatus.VALID and not {"input", "alignment"}.intersection(self.pipeline_mismatches)

    @property
    def disparity_cache_valid(self) -> bool:
        return self.status == SidecarStatus.VALID and not {"input", "alignment", "disparity"}.intersection(self.pipeline_mismatches)

    @property
    def color_cache_valid(self) -> bool:
        # Fitted color curves are based on the rendered/aligned pair. A change
        # in alignment/render geometry therefore invalidates color parameters
        # even when the color algorithm itself is unchanged.
        return (
            self.status == SidecarStatus.VALID
            and "input" not in self.pipeline_mismatches
            and "alignment" not in self.pipeline_mismatches
            and "color" not in self.pipeline_mismatches
        )


def source_stamp_to_dict(stamp: SourceStamp) -> dict[str, Any]:
    return {
        "kind": stamp.kind,
        "left": {key: value for key, value in asdict(stamp.left).items() if value is not None},
        "right": {key: value for key, value in asdict(stamp.right).items() if value is not None},
    }


def _file_stamp_matches(saved: dict[str, Any], expected: FileStamp, *, allow_transposed_dimensions: bool = False,
                        header_only: bool = False) -> bool:
    try:
        saved_dimensions = (int(saved.get("width", -1)), int(saved.get("height", -1)))
        dimensions_match = header_only or saved_dimensions == (expected.width, expected.height)
        if allow_transposed_dimensions:
            dimensions_match |= saved_dimensions == (expected.height, expected.width)
        return (
            str(saved.get("path", "")) == expected.path
            and int(saved.get("size_bytes", -1)) == expected.size_bytes
            and int(saved.get("mtime_ns", -1)) == expected.mtime_ns
            and dimensions_match
            and (header_only or saved.get("frame") == expected.frame)
            and (header_only or saved.get("entity") == expected.entity)
        )
    except (TypeError, ValueError):
        return False


def source_matches(saved: dict[str, Any], expected: SourceStamp, *, allow_transposed_dimensions: bool = False,
                   header_only: bool = False) -> bool:
    if not saved or saved.get("kind") != expected.kind:
        return False
    return _file_stamp_matches(dict(saved.get("left") or {}), expected.left,
        allow_transposed_dimensions=allow_transposed_dimensions, header_only=header_only) and _file_stamp_matches(
        dict(saved.get("right") or {}), expected.right,
        allow_transposed_dimensions=allow_transposed_dimensions, header_only=header_only
    )


def pipeline_mismatches(saved: dict[str, Any]) -> tuple[str, ...]:
    expected = {
        "input": INPUT_PIPELINE_VERSION,
        "alignment": ALIGNMENT_PIPELINE_VERSION,
        "disparity": DISPARITY_PIPELINE_VERSION,
        "color": COLOR_PIPELINE_VERSION,
    }
    return tuple(key for key, value in expected.items() if saved.get(key) != value)


def load_sidecar(path: Path, expected_source: SourceStamp | None = None) -> SidecarLoadResult:
    if not path.exists():
        return SidecarLoadResult(SidecarStatus.MISSING)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("root is not an object")
    except Exception as exc:
        return SidecarLoadResult(SidecarStatus.INVALID, message=str(exc))

    if raw.get("schema_version") != SIDECAR_SCHEMA_VERSION:
        return SidecarLoadResult(SidecarStatus.INVALID, message="Unbekanntes Sidecar-Schema.")

    try:
        doc = SidecarDocument.from_dict(raw)
        eyes = (doc.source.get("left"), doc.source.get("right"))
        header_only = all(isinstance(eye, dict) and not eye.get("width") and not eye.get("height")
                          for eye in eyes)
        # Before the TIFF decoder fix, an unchanged source could have
        # transposed dimensions. Preserve its edits and invalidate its caches.
        if expected_source is not None and not source_matches(
            doc.source, expected_source, allow_transposed_dimensions="input" not in doc.pipeline,
            header_only=header_only,
        ):
            return SidecarLoadResult(SidecarStatus.STALE, doc, "Quelldatei stimmt nicht mit Sidecar überein.")
    except (TypeError, ValueError) as exc:
        return SidecarLoadResult(SidecarStatus.INVALID, message=str(exc))

    if header_only:
        # Folder settings written without decoding the image have no caches.
        doc.pipeline = {}
        doc.alignment = {}
        doc.disparity = {}
        doc.color.pop("parameters", None)
        doc.color.pop("valid", None)
    mismatches = pipeline_mismatches(doc.pipeline)
    if not doc.input_state and "input" not in mismatches:
        # Reusable geometry must be tied to a saved orientation.
        mismatches = ("input", *mismatches)
    message = "Neu berechnen: " + ", ".join(mismatches) if mismatches and not header_only else ""
    return SidecarLoadResult(SidecarStatus.VALID, doc, message, mismatches)


def _source_path_identity(source: dict[str, Any]) -> tuple[str, str, str] | None:
    try:
        kind = str(source["kind"])
        left = str(source["left"]["path"]).replace("\\", "/").casefold()
        right = str(source["right"]["path"]).replace("\\", "/").casefold()
        return (kind, left, right) if left and right else None
    except (KeyError, TypeError):
        return None


def save_sidecar(path: Path, document: SidecarDocument) -> Path:
    # Changed pixels/mtime may invalidate analysis, but another source must not
    # silently take ownership of an existing pair's edits and favorite flag.
    if path.is_file():
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = None
        if isinstance(saved, dict):
            previous = _source_path_identity(saved.get("source") or {})
            current = _source_path_identity(document.source)
            if previous is not None and current is not None and previous != current:
                raise ValueError(
                    "Die Einstellungsdatei gehört zu anderen Quelldateien. Bitte Quelldateien eindeutig umbenennen: "
                    + str(path)
                )
    return write_json_atomic(path, document.to_dict())


def write_json_atomic(path: Path, data: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
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
