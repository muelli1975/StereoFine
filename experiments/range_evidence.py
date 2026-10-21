"""Research adapter to the shared production observed-range verifier."""
from stereofine.range_evidence import PROTOCOL, supported
from stereofine.range_evidence import measure_range_evidence as _measure
from experiments.native_footprint import check_native_footprint


def measure_range_evidence(left, right, max_width=1500, dense=None, *, include_dense_tail=True, native_footprint=False):
    checker = None
    if native_footprint:
        def checker(a, b, shape, points):
            return check_native_footprint(a, b, shape, points, enabled=True)
    result = _measure(left, right, max_width, dense, include_dense_tail=include_dense_tail, _native_checker=checker)
    if native_footprint:
        result['protocol'].update(version='range-evidence-4', native_footprint_radius_cap=64,
            native_fallback='only failed forward photometric checks; original accepted checks retained')
    return result
