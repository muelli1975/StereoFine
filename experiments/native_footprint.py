"""Research fallback for an analysis patch's larger native-pixel footprint."""
from __future__ import annotations

import math

from stereofine.near_point_recovery import native_patch_checks


def check_native_footprint(left, right, analysis_shape, points, *, enabled=False):
    audit = []
    checked = native_patch_checks(left, right, analysis_shape, points, audit=audit)
    if not enabled:
        return checked, audit
    h, w = left.shape[:2]
    ah, aw = analysis_shape
    radius = min(64, max(20, math.ceil((17*max(h/ah, w/aw)-1)/2)))
    if radius == 20:
        return checked, audit
    # Retain all accepted native checks. A source without local texture or a
    # failed reciprocal match cannot be rescued by including different scenery.
    retry_xy = {(r['x'], r['y']) for r in audit
                if r['reason'] in {'forward_correlation', 'forward_uniqueness'}}
    retry = [p for p in points if
             (round((p['x']+.5)*w/aw-.5), round((p['y']+.5)*h/ah-.5)) in retry_xy]
    extra_audit = []
    extra = native_patch_checks(left, right, analysis_shape, retry,
                                patch_radius=radius, audit=extra_audit) if retry else []
    checked.extend(extra)
    audit.extend(extra_audit)
    return checked, audit
