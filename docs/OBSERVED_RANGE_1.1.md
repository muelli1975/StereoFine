# Observed-range recovery for StereoFine 1.1

Date: 21 October 2026. Implemented locally; application version remains `1.1-dev`.
Cross-platform packages for this change have not yet been built or verified.

## Result and limits

A confirmed dense result is unchanged. An uncertain far endpoint can receive an
additional measurement from native image correspondences at two analysis
widths. In the motivating S110 bild098 case, the application now reports
30.430 permille with AKAZE and 29.655 permille with SIFT, rather than 67.458 and
73.484. Both retain the gray uncertainty indication: confirming visible
endpoints does not prove that every surface in the scene was measurable.

Neither Cosima nor manual point selection is treated as calibrated whole-scene
ground truth. The evidence supports about 30 permille in this example; it does
not establish the reported 23 permille as the complete scene range.

## Admission rule

The application keeps its 3000-pixel geometry analysis and 1500-pixel disparity
baseline. It adds no geometric deformation and makes no change to the dense
matcher, native 41x41 window or 17x17 analysis-window match gates.

1. Only attempt recovery when the existing near endpoint has support, there is
   no unresolved nearer extreme, and the far endpoint is unconfirmed or lies
   outside the estimate. Require native images at least 1.5 times the analysis
   dimensions. Confirmed baseline results bypass recovery entirely.
2. Use the shared bounded [endpoint verifier](RANGE_EVIDENCE_1.1.md) at the
   primary width. Both endpoints need native same-location agreement and
   spatial support, with no unresolved more extreme evidence.
3. Repeat at two thirds of the primary width (normally 1000 pixels). Both
   endpoint values and their span must agree within 1.5 permille. This is a
   consistency gate, not a guaranteed measurement error.
4. Reject a candidate that would drop a previously supported farther surface
   by more than one primary analysis pixel. Failed or conflicting checks retain
   the original values and uncertainty.
5. Use the farther of the two admitted far measurements, with a half-analysis-
   pixel reserve. Retain the existing near estimate unless the native evidence
   establishes a nearer point beyond that reserve; then extend it with the same
   reserve. Keep the established additional 3-permille automatic window offset.
6. If this replaces a wider unconfirmed far tail with a smaller observed span,
   retain `range_completeness_unconfirmed` and a gray traffic light. Extending
   the range can clear the far-end warning if all other checks pass.

A newly confirmed near point can change horizontal framing and the resulting
output width. That is a translation and overlap crop; alignment coefficients
are unchanged. No mask or color adjustment feeds back into the measurement.

## Regression evidence

[Machine-readable results](OBSERVED_RANGE_1.1_RESULTS.json) cover 30 original
pairs, each with AKAZE and SIFT: 60 cases. The comparison replays frozen,
previously recorded geometric corrections and reproduces the old dense scalar
values, status and uncertainty exactly before comparing the new path.

| Check | Result |
| --- | ---: |
| Previously confirmed cases, unchanged | 24 of 24 |
| Cases admitting additional endpoint evidence | 15 of 60 |
| Admitted range extensions | 13 |
| Smaller observed spans, explicitly still uncertain | 2 |
| Cases retaining baseline values | 45 |
| Remaining uncertain cases | 23 |
| Dense arrays identical | 60 of 60 |
| Original file SHA-256 unchanged | 60 of 60 |

The 13 extensions are approximately 0.85–1.47 permille. Only bild098/AKAZE
changes the near endpoint, by 3.153 permille. This is not a claim that all 60
results now have known absolute accuracy. In particular, the remaining
uncertain cases are not silently assigned a more favorable range.

Synthetic regressions cover known displacements, sky, a small surface,
exposure, occlusion, swapped eyes, repeated patterns and constant images. The
application integration additionally tests an injected false dense far tail
against real synthetic pixels, inconsistent control measurements, preservation
of an existing farther supported surface, and old-sidecar recomputation with
manual edits retained. The dense outlier is injected in the test; native matches
and the separate control measurement use the actual image pixels.

The calculation version is `sf-disparity-5`. Older disparity caches recompute
without invalidating alignment or deleting manual adjustments and favorites.
Sidecars retain compact method, scope, uncertainty and scalar values, rather
than the full per-point research audit.

A fresh run of the bundled nominal 20-permille Full-SBS reference returns
19.625 permille with the simple Affine model, exactly matching the prior dense
path. The rendered pixels and reloaded-session pixels are identical. A fresh
bild098/AKAZE run also reproduces 30.430 permille, retains uncertainty and
reloads with identical rendered pixels. Its auto offset is 173 native pixels;
only the newly supported near point changes framing, not the geometric fit.

Local checks pass: 195 application tests, 48 research tests, compilation of all
Python sources, import of every runtime module, original asset hashes and
byte-identical default/English READMEs. The local environment is Python 3.12.14,
OpenCV 4.13.0, NumPy 2.4.6 and Pillow 12.2.0. Candidate filename, metadata guard
and checksum tests are included in those application tests. The final-candidate
command correctly rejects the current development metadata before building.

The local host has no Xvfb/display for a fresh GUI smoke run. The prepared CI
workflow still needs to exercise the exact new commit on its pinned Python
3.12.10 platforms, including GUI smoke and the actual frozen packages. No new
application archive or published release is claimed by these source checks.

## Reproduction

Keep photographs and full native-location diagnostics outside the repository.
Given the private manifest and the previous `range-evidence-3` saved corrections:

```sh
python experiments/validate_observed_range.py cases.json --baseline previous-v3 --output production-v5
python -m unittest discover -s tests -p 'test_*.py'
python -m unittest discover -s experiments/tests -p 'test_*.py'
```

The production verifier lives in `stereofine/range_evidence.py`. The research
adapter reuses it; the larger native-footprint fallback remains research-only.
