from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal

from .inputs import (
    LoadedStereoPair,
    InputError,
    build_lr_dir_pair_sequence,
    build_suffix_pair_sequence,
    is_image_file,
    is_stereo_single_file,
    list_stereo_single_files,
    validate_unique_image_stems,
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
    pairs = lr_pairs or build_suffix_pair_sequence(folder)
    sources = [source_from_pair(left, right, folder) for left, right in pairs]
    validate_source_names(sources)
    return sources


def discover_stereo_file_sources(folder: Path) -> list[StereoSource]:
    paths = list_stereo_single_files(folder)
    validate_unique_image_stems(paths)
    return [source_from_stereo_file(path, folder) for path in paths]


def validate_source_names(sources: Iterable[StereoSource], *, check_outputs: bool = True) -> None:
    """Keep existing filenames, but reject collisions across a complete job."""
    sidecars: dict[str, StereoSource] = {}
    outputs: dict[str, StereoSource] = {}
    for source in sources:
        keys = [(sidecars, str(source.sidecar_path.resolve()).casefold())]
        if check_outputs:
            keys.append((outputs, source.base_name.casefold()))
        for seen, key in keys:
            previous = seen.get(key)
            if previous is not None and previous != source:
                raise InputError(
                    "Mehrere Quellen verwenden denselben Ergebnisnamen. Bitte Quelldateien eindeutig umbenennen: "
                    + f"{previous.left_path}, {source.left_path}"
                )
            seen[key] = source


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
    # Also cover single-file/API entry points and files added after discovery.
    for path in dict.fromkeys((source.left_path, source.right_path)):
        is_supported = is_image_file if source.kind == "pair" else is_stereo_single_file
        if path.parent.is_dir():
            validate_unique_image_stems([
                item for item in path.parent.iterdir()
                if item.stem.casefold() == path.stem.casefold() and is_supported(item)
            ])
    if source.kind == "pair":
        return load_pair(source.left_path, source.right_path)
    if source.kind == "mpo":
        return load_mpo(source.left_path)
    if source.kind == "full_sbs":
        return load_full_sbs(source.left_path)
    raise ValueError(f"Unbekannte Stereoquelle: {source.kind}")
