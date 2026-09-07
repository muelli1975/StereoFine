from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .inputs import (
    LoadedStereoPair,
    build_lr_dir_pair_sequence,
    build_suffix_pair_sequence,
    list_stereo_single_files,
    load_mpo,
    load_full_sbs,
    load_pair,
)
from .models import FileStamp, SourceStamp

SourceMode = Literal["pair", "full_sbs", "mpo"]


@dataclass(frozen=True)
class StereoSource:
    kind: SourceMode
    left_path: Path
    right_path: Path
    input_root: Path
    base_name: str

    @property
    def display_name(self) -> str:
        if self.left_path == self.right_path:
            return self.left_path.name
        return self.base_name

    @property
    def sidecar_path(self) -> Path:
        return self.input_root / "_stereofine" / f"{self.base_name}.sfin"

    @property
    def metadata_source(self) -> Path:
        return self.left_path


def _suffix_base(path: Path) -> str:
    lower = path.stem.lower()
    if lower.endswith("_l") or lower.endswith("_r"):
        return path.stem[:-2]
    return path.stem


def source_from_pair(left: Path, right: Path, input_root: Path) -> StereoSource:
    return StereoSource("pair", left, right, input_root, _suffix_base(left))


def source_from_stereo_file(path: Path, input_root: Path) -> StereoSource:
    kind: SourceMode = "mpo" if path.suffix.lower() == ".mpo" else "full_sbs"
    return StereoSource(kind, path, path, input_root, path.stem)


def discover_pair_sources(folder: Path) -> list[StereoSource]:
    """Discover the established pair layouts without guessing between them per file."""
    lr_pairs = build_lr_dir_pair_sequence(folder)
    if lr_pairs:
        return [source_from_pair(left, right, folder) for left, right in lr_pairs]
    suffix_pairs = build_suffix_pair_sequence(folder)
    return [source_from_pair(left, right, folder) for left, right in suffix_pairs]


def discover_stereo_file_sources(folder: Path) -> list[StereoSource]:
    return [source_from_stereo_file(path, folder) for path in list_stereo_single_files(folder)]


def build_source_stamp(source: StereoSource, loaded: LoadedStereoPair) -> SourceStamp:
    if source.kind == "pair":
        left_frame = None
        right_frame = None
    else:
        left_frame = 0
        right_frame = 1
    return SourceStamp(
        kind=source.kind,
        left=FileStamp.from_path(
            source.left_path,
            relative_to=source.input_root,
            width=loaded.left_source_width,
            height=loaded.left_source_height,
            frame=left_frame,
        ),
        right=FileStamp.from_path(
            source.right_path,
            relative_to=source.input_root,
            width=loaded.right_source_width,
            height=loaded.right_source_height,
            frame=right_frame,
        ),
    )


def load_source(source: StereoSource) -> LoadedStereoPair:
    """Load a discovered StereoSource transactionally into master arrays."""
    if source.kind == "pair":
        return load_pair(source.left_path, source.right_path)
    if source.kind == "mpo":
        return load_mpo(source.left_path)
    if source.kind == "full_sbs":
        return load_full_sbs(source.left_path)
    raise ValueError(f"Unbekannte Stereoquelle: {source.kind}")
