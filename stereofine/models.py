from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

InputKind = Literal["pair", "full_sbs", "mpo"]
OutputMode = Literal["both", "sbs", "anaglyph"]


@dataclass(frozen=True)
class FileStamp:
    path: str
    size_bytes: int
    mtime_ns: int
    width: int
    height: int
    frame: int | None = None

    @classmethod
    def from_path(
        cls,
        path: Path,
        *,
        relative_to: Path | None = None,
        width: int,
        height: int,
        frame: int | None = None,
    ) -> "FileStamp":
        stat = path.stat()
        try:
            saved_path = str(path.resolve().relative_to(relative_to.resolve())) if relative_to else str(path.resolve())
        except ValueError:
            saved_path = str(path.resolve())
        return cls(
            path=saved_path,
            size_bytes=int(stat.st_size),
            mtime_ns=int(stat.st_mtime_ns),
            width=int(width),
            height=int(height),
            frame=frame,
        )


@dataclass(frozen=True)
class SourceStamp:
    kind: InputKind
    left: FileStamp
    right: FileStamp


@dataclass
class DisparitySummary:
    near_permille: float | None = None
    far_permille: float | None = None
    total_permille: float | None = None
    valid_fraction: float | None = None
    uncertain: bool = False
    uncertain_reasons: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass
class AnalysisRecord:
    source_name: str
    model: str | None
    matches: int | None
    inliers: int | None
    vertical_error_mean_px: float | None
    near_permille: float | None
    far_permille: float | None
    total_permille: float | None
    traffic: str
    favorite: bool
    status: str
    notes: str = ""
    rotation_deg: float | None = None
    vergence_applied_px: float | None = None
    vergence_v_px: float | None = None
    vergence_h_px: float | None = None
    uncertain: bool = False
