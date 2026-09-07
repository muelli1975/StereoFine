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
    ANAGLYPH_PIPELINE_VERSION,
    APP_NAME,
    APP_VERSION,
    COLOR_PIPELINE_VERSION,
    DISPARITY_PIPELINE_VERSION,
    SIDECAR_SCHEMA_VERSION,
    normalize_aspect_code,
    normalize_orientation_code,
)
from .models import FileStamp, SourceStamp


class SidecarStatus(str, Enum):
    MISSING = "missing"
    VALID = "valid"
    MIGRATED = "migrated"
    STALE = "stale"
    INVALID = "invalid"


@dataclass
class SidecarDocument:
    schema_version: int = SIDECAR_SCHEMA_VERSION
    app: dict[str, Any] = field(default_factory=lambda: {"name": APP_NAME, "version": APP_VERSION})
    source: dict[str, Any] = field(default_factory=dict)
    pipeline: dict[str, str] = field(
        default_factory=lambda: {
            "alignment": ALIGNMENT_PIPELINE_VERSION,
            "disparity": DISPARITY_PIPELINE_VERSION,
            "color": COLOR_PIPELINE_VERSION,
            "anaglyph": ANAGLYPH_PIPELINE_VERSION,
        }
    )
    favorite: bool = False
    input_state: dict[str, Any] = field(default_factory=dict)
    alignment: dict[str, Any] = field(default_factory=dict)
    manual: dict[str, Any] = field(default_factory=lambda: {"delta_x_px": 0, "delta_y_px": 0})
    framing: dict[str, Any] = field(default_factory=dict)
    floating_window: dict[str, Any] = field(
        default_factory=lambda: {"left_permille": 0, "right_permille": 0, "top_permille": 0, "bottom_permille": 0}
    )
    disparity: dict[str, Any] = field(default_factory=dict)
    color: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["schema_version"] = SIDECAR_SCHEMA_VERSION
        data["app"] = {"name": APP_NAME, "version": APP_VERSION}
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SidecarDocument":
        return cls(
            schema_version=int(data.get("schema_version", SIDECAR_SCHEMA_VERSION)),
            app=dict(data.get("app") or {}),
            source=dict(data.get("source") or {}),
            pipeline=dict(data.get("pipeline") or {}),
            favorite=bool(data.get("favorite", False)),
            input_state=dict(data.get("input_state") or {}),
            alignment=dict(data.get("alignment") or {}),
            manual=dict(data.get("manual") or {}),
            framing=dict(data.get("framing") or {}),
            floating_window=dict(data.get("floating_window") or {}),
            disparity=dict(data.get("disparity") or {}),
            color=dict(data.get("color") or {}),
        )


@dataclass(frozen=True)
class SidecarLoadResult:
    status: SidecarStatus
    document: SidecarDocument | None = None
    message: str = ""
    pipeline_mismatches: tuple[str, ...] = ()

    @property
    def alignment_cache_valid(self) -> bool:
        return self.status == SidecarStatus.VALID and "alignment" not in self.pipeline_mismatches

    @property
    def disparity_cache_valid(self) -> bool:
        return self.status == SidecarStatus.VALID and "disparity" not in self.pipeline_mismatches

    @property
    def color_cache_valid(self) -> bool:
        # Fitted color curves are based on the rendered/aligned pair. A change
        # in alignment/render geometry therefore invalidates color parameters
        # even when the color algorithm itself is unchanged.
        return (
            self.status == SidecarStatus.VALID
            and "alignment" not in self.pipeline_mismatches
            and "color" not in self.pipeline_mismatches
        )

    @property
    def anaglyph_cache_valid(self) -> bool:
        return self.status == SidecarStatus.VALID and "anaglyph" not in self.pipeline_mismatches


def source_stamp_to_dict(stamp: SourceStamp) -> dict[str, Any]:
    return {
        "kind": stamp.kind,
        "left": asdict(stamp.left),
        "right": asdict(stamp.right),
    }


def _file_stamp_matches(saved: dict[str, Any], expected: FileStamp) -> bool:
    try:
        return (
            str(saved.get("path", "")) == expected.path
            and int(saved.get("size_bytes", -1)) == expected.size_bytes
            and int(saved.get("mtime_ns", -1)) == expected.mtime_ns
            and int(saved.get("width", -1)) == expected.width
            and int(saved.get("height", -1)) == expected.height
            and saved.get("frame") == expected.frame
        )
    except (TypeError, ValueError):
        return False


def source_matches(saved: dict[str, Any], expected: SourceStamp) -> bool:
    if not saved or saved.get("kind") != expected.kind:
        return False
    return _file_stamp_matches(dict(saved.get("left") or {}), expected.left) and _file_stamp_matches(
        dict(saved.get("right") or {}), expected.right
    )


def pipeline_mismatches(saved: dict[str, Any]) -> tuple[str, ...]:
    expected = {
        "alignment": ALIGNMENT_PIPELINE_VERSION,
        "disparity": DISPARITY_PIPELINE_VERSION,
        "color": COLOR_PIPELINE_VERSION,
        "anaglyph": ANAGLYPH_PIPELINE_VERSION,
    }
    return tuple(key for key, value in expected.items() if saved.get(key) != value)


def pipeline_matches(saved: dict[str, Any]) -> bool:
    return not pipeline_mismatches(saved)


def _migrate_v2(data: dict[str, Any]) -> SidecarDocument:
    """Import only geometry-independent user intent from legacy v2 sidecars.

    The v41-era sidecar mixed automatic geometry, near-point framing and manual
    deltas in representations that are not safe to replay blindly in the 1.0
    pipeline.  Reusing those values can make an otherwise correct pair look
    badly shifted.  Orientation/eye order, favorite and floating-window masks
    are independent user intent and are safe to retain; alignment, disparity,
    manual offsets and crop framing are deliberately reset and recalculated.
    """
    input_state = {
        "left_orientation": normalize_orientation_code(data.get("left_orientation")),
        "right_orientation": normalize_orientation_code(data.get("right_orientation")),
        "left_mirror": bool(data.get("left_mirror", False)),
        "right_mirror": bool(data.get("right_mirror", False)),
        "swap_eyes": bool(data.get("swap_eyes", False)),
    }
    floating = {
        "left_permille": int(data.get("floating_left_permille", 0) or 0),
        "right_permille": int(data.get("floating_right_permille", 0) or 0),
        "top_permille": int(data.get("floating_top_permille", 0) or 0),
        "bottom_permille": int(data.get("floating_bottom_permille", 0) or 0),
    }
    return SidecarDocument(
        favorite=bool(data.get("favorite", False)),
        input_state=input_state,
        manual={"delta_x_px": 0, "delta_y_px": 0},
        framing={"aspect": "maximum", "crop_zoom_index": 0, "pan_x_permille": 0, "pan_y_permille": 0},
        floating_window=floating,
        alignment={},
        disparity={},
        color={},
    )


def load_sidecar(path: Path, expected_source: SourceStamp | None = None) -> SidecarLoadResult:
    if not path.exists():
        return SidecarLoadResult(SidecarStatus.MISSING)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("root is not an object")
    except Exception as exc:
        return SidecarLoadResult(SidecarStatus.INVALID, message=str(exc))

    if raw.get("schema_version") == SIDECAR_SCHEMA_VERSION:
        try:
            doc = SidecarDocument.from_dict(raw)
        except Exception as exc:
            return SidecarLoadResult(SidecarStatus.INVALID, message=str(exc))
        if expected_source is not None and not source_matches(doc.source, expected_source):
            return SidecarLoadResult(SidecarStatus.STALE, doc, "Quelldatei stimmt nicht mit Sidecar überein.")
        mismatches = pipeline_mismatches(doc.pipeline)
        message = ""
        if mismatches:
            message = "Neu berechnen: " + ", ".join(mismatches)
        # Pipeline changes invalidate only the affected cached calculations, not
        # manual framing, floating-window values or the favorite flag.
        return SidecarLoadResult(SidecarStatus.VALID, doc, message, mismatches)

    if raw.get("version") == 2:
        doc = _migrate_v2(raw)
        # Legacy v2 had no robust source stamp. It may be imported for manual
        # review, but is never silently treated as fully validated cache data.
        return SidecarLoadResult(
            SidecarStatus.MIGRATED,
            doc,
            "Legacy-Sidecar v2: Ausrichtung/Favorit/Floating Window übernommen; Geometrie wird neu berechnet.",
        )

    return SidecarLoadResult(SidecarStatus.INVALID, message="Unbekanntes Sidecar-Schema.")


def save_sidecar(path: Path, document: SidecarDocument) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(document.to_dict(), ensure_ascii=False, indent=2) + "\n"
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
