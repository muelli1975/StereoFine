"""Shared measurement presentation; persisted values remain numeric."""


def format_number(value, suffix='', decimals=2, *, language='en', significant=None):
    if value is None:
        return '-'
    if isinstance(value, int):
        result = str(value)
    elif significant is not None:
        result = f'{float(value):.{significant}g}'
    else:
        result = f'{float(value):.{decimals}f}'
    return (result.replace('.', ',') if language == 'de' else result) + suffix


def endpoint_values(state, language='en'):
    near, far = state.current_scene_positions_permille()
    available = state.disparity.valid and not state.disparity.stale
    return {name: format_number(value if available else None, '‰', language=language)
            for name, value in (('near', near), ('far', far))}
