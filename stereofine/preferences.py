"""Explicit per-image preferences, including intentionally partial sidecars."""
from .state import LookState

PREFERENCE_NAMES = ('aspect', 'color', 'look')


def document_preferences(document):
    if document.preference_fields is not None:
        return set(document.preference_fields).intersection(PREFERENCE_NAMES)
    return {name for name, present in (
        ('aspect', 'aspect' in document.framing), ('color', 'enabled' in document.color),
        ('look', bool(document.look))) if present}


def inherit_missing_preferences(state, defaults, document):
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
