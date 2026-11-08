"""Explicit per-image preferences, including intentionally partial sidecars."""
from dataclasses import asdict, replace
import json

from .sidecar import write_json_atomic
from .state import InputTransformState, LookState

PREFERENCE_NAMES = ('aspect', 'color', 'look')


def series_input_path(source):
    return source.sidecar_path.with_name('orientation.json')


def save_series_input(source, transform):
    return write_json_atomic(series_input_path(source), {'version': 1, 'input_state': asdict(transform)})


def with_series_input(defaults, source):
    path = series_input_path(source)
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return defaults
    except ValueError as exc:
        raise ValueError(f'Ungültige Ordnerausrichtung: {path}') from exc
    transform = data.get('input_state') if isinstance(data, dict) and data.get('version') == 1 else None
    if (not isinstance(transform, dict) or transform.keys() != InputTransformState.__dataclass_fields__.keys()
            or any(transform[name] not in ('0', '180', '90_cw', '90_ccw')
                   for name in ('left_orientation', 'right_orientation'))
            or any(type(transform[name]) is not bool for name in ('left_mirror', 'right_mirror', 'swap_eyes'))):
        raise ValueError(f'Ungültige Ordnerausrichtung: {path}')
    return replace(defaults, **transform)


def document_preferences(document):
    return {name for name, present in (
        ('aspect', 'aspect' in document.framing), ('color', 'enabled' in document.color),
        ('look', bool(document.look))) if present}


def inherit_missing_preferences(state, defaults, document):
    transform = replace(state.input_transform, **{
        name: getattr(defaults, name)
        for name in InputTransformState.__dataclass_fields__
        if name not in document.input_state
    })
    if transform != state.input_transform:
        state.input_transform = transform
        state.invalidate_for_input_transform(keep_manual=True)

    owned = document_preferences(document)
    if 'aspect' not in owned:
        state.framing.aspect = defaults.aspect
    if 'color' not in owned:
        state.color.enabled = defaults.color_enabled
        state.color.valid = False
    look = document.look if 'look' in owned else {}
    state.look = LookState(look.get('enabled', defaults.look_enabled),
        look.get('preset_id', defaults.look_preset_id), look.get('path', defaults.look_path),
        look.get('strength', defaults.look_strength)).normalize()
    state.preference_fields = None if owned == set(PREFERENCE_NAMES) else sorted(owned)


def mark_preference(state, name):
    if state.preference_fields is not None:
        state.preference_fields = sorted(set(state.preference_fields) | {name})
