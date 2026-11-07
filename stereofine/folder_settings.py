"""Apply independently selected preferences without decoding or processing images."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile

from .config import APP_NAME, APP_VERSION
from .diagnostics import log_event, log_failure
from .models import FileStamp
from .preferences import document_preferences
from .sidecar import SidecarDocument, SIDECAR_SCHEMA_VERSION
from .sources import validate_source_names
from .state import LookState


@dataclass(frozen=True)
class FolderChoices:
    aspect: str | None = None
    look: LookState | None = None
    color_enabled: bool | None = None

    @property
    def selected(self):
        return {name for name, value in (('aspect', self.aspect), ('look', self.look),
                                         ('color', self.color_enabled)) if value is not None}


@dataclass
class FolderApplyResult:
    total: int
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    cancelled: bool = False


@dataclass(frozen=True)
class FolderProgress:
    index: int
    total: int
    source_name: str


def _source_header(source):
    frame = source.kind not in {'pair', 'heif'}
    return dict(kind=source.kind, **{eye: asdict(FileStamp.from_path(path,
        relative_to=source.input_root, width=0, height=0, frame=i if frame else None))
        for i, (eye, path) in enumerate((('left', source.left_path), ('right', source.right_path)))})


def _verify_source(saved, header):
    if saved.get('kind') != header['kind']:
        raise ValueError('Settings belong to another source type.')
    for eye in ('left', 'right'):
        actual, old = header[eye], saved.get(eye) or {}
        if any(old.get(key) != actual[key] for key in ('path', 'size_bytes', 'mtime_ns')):
            raise ValueError('Source changed or settings belong to other files; open and save this image first.')


def _patch_preferences(raw, choices):
    result = deepcopy(raw)
    owned = document_preferences(SidecarDocument.from_dict(raw)) | choices.selected
    if owned != {'aspect', 'color', 'look'} or 'preference_fields' in result:
        result['preference_fields'] = sorted(owned)
    if choices.aspect is not None:
        framing = result.setdefault('framing', {})
        if framing.get('aspect') != choices.aspect:
            framing['aspect'] = choices.aspect
            disparity = result.get('disparity')
            if disparity:
                disparity.update(valid=False, stale=True, status='stale')
            if result.get('color'):
                result['color']['valid'] = False
    if choices.color_enabled is not None:
        result.setdefault('color', {})['enabled'] = bool(choices.color_enabled)
    if choices.look is not None:
        result['look'] = asdict(deepcopy(choices.look).normalize())
    return result


def _atomic_write(path, data, previous):
    path.parent.mkdir(parents=True, exist_ok=True)
    current = path.read_bytes() if path.exists() else None
    if current != previous:
        raise OSError('Settings changed while the folder operation was running.')
    fd, name = tempfile.mkstemp(prefix=path.name+'.', suffix='.tmp', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as file:
            json.dump(data, file, ensure_ascii=False, indent=2, allow_nan=False)
            file.write('\n'); file.flush(); os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def apply_folder_preferences(sources, choices, *, cancellation=None, progress=None):
    sources = list(sources)
    validate_source_names(sources, check_outputs=False)
    if not choices.selected:
        raise ValueError('Select at least one setting.')
    if choices.look is not None and choices.look.enabled and choices.look.strength > 0:
        from .looks import load_lut, look_path
        load_lut(look_path(choices.look))
    result = FolderApplyResult(len(sources))
    for index, source in enumerate(sources, 1):
        if cancellation is not None and cancellation.cancelled:
            break
        name, path = source.display_name, source.sidecar_path
        try:
            header = _source_header(source)
            previous = path.read_bytes() if path.exists() else None
            if previous is None:
                raw = dict(schema_version=SIDECAR_SCHEMA_VERSION,
                    app=dict(name=APP_NAME, version=APP_VERSION),
                    source=header, pipeline=SidecarDocument().pipeline,
                    settings_only=True, preference_fields=[])
            else:
                raw = json.loads(previous.decode('utf-8'))
                if not isinstance(raw, dict) or raw.get('schema_version') != SIDECAR_SCHEMA_VERSION:
                    raise ValueError('Unsupported or damaged settings; open and save this image first.')
                # Parse before writing. Unknown non-preference keys remain byte-value equivalent.
                SidecarDocument.from_dict(raw)
                _verify_source(raw.get('source') or {}, header)
            updated = _patch_preferences(raw, choices)
            if updated == raw and previous is not None:
                result.unchanged.append(name)
            else:
                _verify_source(header, _source_header(source))
                _atomic_write(path, updated, previous)
                result.updated.append(name)
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            result.failed.append((name, str(exc)))
            log_failure('Apply folder settings', exc, source=source.left_path)
        if progress is not None:
            progress(FolderProgress(index, result.total, name))
    result.cancelled = bool(cancellation is not None and cancellation.cancelled)
    log_event(f'Folder settings: total={result.total}, updated={len(result.updated)}, '
              f'unchanged={len(result.unchanged)}, failed={len(result.failed)}, cancelled={result.cancelled}')
    return result
