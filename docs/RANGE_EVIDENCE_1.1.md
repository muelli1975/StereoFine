# Two-ended disparity evidence pilot

Date: 21 October 2026. Historical research comparison; no application package from this pilot.

The shared verifier now also supports conditional application recovery under a
stricter admission rule. See [current integration and validation](OBSERVED_RANGE_1.1.md).
The pilot counts and recommendations below describe the earlier experiment,
not the current application behavior.

## Outcome

The bounded interior-tail search improves endpoint coverage, but is **not
approved to replace the application's range estimate or automatic framing**.
On 30 original pairs with AKAZE and SIFT, 29 of 60 cases have native-confirmed
observed endpoints and agree at both analysis widths. The other 31 retain
missing evidence, unresolved extremes, or scale disagreement. These are not 31
proven incorrect application results: this pilot applies an additional native
confirmation requirement to both ends of an observed span.

Agreement between resolutions is supporting evidence from the same photographs,
not independent depth ground truth. Finding two endpoints cannot prove that
every textureless, occluded or unsampled surface has been measured.

## Shared measurement, bounded search

The pilot reuses the application's existing 17x17 patch verifier, spatial
support rule and 41x41 native strip verifier. It introduces no learned model,
new geometric correction or weaker correlation/uniqueness/reciprocity gates.

1. Detect up to four corners in each cell of an 8x6 image grid. Detection is
   local to each cell so strong foreground texture cannot consume every seed.
2. For each dense 2% tail, select one representative near the centre of each
   occupied 16-pixel cell. Spend up to 32 seeds on extreme values and up to 32
   on spatially distributed cells. Percentiles select search locations, not the
   final measured range. Include the existing production endpoint candidates.
3. Apply the existing photometric and reciprocal patch checks. Search the same
   bounded neighbourhood around the six strongest candidates at each end.
4. Recheck up to 24 candidates per end on native pixels, using a global
   horizontal search and the existing vertical tolerance. Match native results
   back to the same pixel-centre-mapped source locations; require agreement
   within one analysis pixel and the existing spatial support.
5. Retain a veto for an isolated more extreme native point, or an analysis-
   supported surface beyond the native-supported envelope. Report observed
   endpoints separately from a claim about scene completeness.
6. Compare 1500- and 1000-pixel analysis widths. Both endpoints **and** their
   difference must agree within 1.5 permille, and both endpoint checks must pass
   at each width. This is a diagnostic stability gate, not an accuracy bound.

Endpoint values do not include the near-framing measurement reserve or the
three-permille window allowance. They must not be used directly as a replacement
for the application's established conservative framing offset.

## Known-geometry checks

The initial pilot missed a real small far surface in a synthetic scene with
sky at 720-pixel analysis width. Uniform spatial sampling had selected other
background cells from the same percentile tail. The split value/spatial seed
budget addresses that specific search failure without changing match gates.

The final tests cover 18 two-endpoint configurations with exactly known
displacements: ordinary texture, constant sky, a small near object, exposure
differences, occlusion, four additional random seeds, both disparity signs and
swapped eyes. The known span is 50 permille; endpoint errors must be within
1 permille and span errors within 1.5 permille. A separate single-plane check
must remain within 0.5 permille of zero span. Constant and repeated-pattern
images must not return a confirmed span. All these checks pass.

## Original-image comparison

The 29 existing pairs plus bild098 were freshly processed with both detectors.
All measurements read original files only; before/after SHA-256 checks match.
Subsequent search comparisons replay exactly those saved corrections and
require identical application near, far, total and uncertainty values at both
widths before comparing the research evidence. No sidecar is written.

| Outcome versus the initial bounded sampler | Cases |
| --- | ---: |
| Retains native-confirmed, scale-stable endpoints | 23 |
| Newly meets the endpoint and stability checks | 6 |
| Newly exposes an unresolved extreme | 2 |
| Remains unresolved or unstable | 29 |

The six newly qualifying cases are IXUS 008/AKAZE and SIFT, NX1000 001/SIFT,
S110 087/AKAZE, S110 098/AKAZE and S95 012/AKAZE. IXUS 027/SIFT exposes an
isolated more extreme far point; NX1000 008/AKAZE exposes an unresolved more
extreme analysis surface. These new candidates must not be silently discarded
to retain the previous certainty label.

| bild098 | Application estimate | Observed span at 1500 px | Observed span at 1000 px |
| --- | ---: | ---: | ---: |
| AKAZE | 67.458 permille | 29.763 permille | 29.529 permille |
| SIFT | 73.484 permille | 28.812 permille | 29.047 permille |

Both detector results pass the pilot gates. They support a measured span around
29-30 permille rather than treating the roughly 23-permille central percentile
span as the complete range. There is still no calibrated full-scene reference.

The extra pilot measurement took a median 1.65 seconds per analysis width on
this host (maximum 3.81 seconds). Runs overlapped, so this is a development
timing, not a platform benchmark. The production application test suite passes
184 tests; the research suite passes 46 tests, including four new test methods
with the known-geometry subcases above. No Windows/macOS rerun or package build
was performed for this research change.

## Reproduction

Use a private manifest of `name`, `left`, `right`, `left_orientation` rows, with
names ending in `_AKAZE` or `_SIFT`. Keep original images outside the repository.

```sh
python experiments/compare_range_evidence.py cases.json --output initial --initial-sampler
python experiments/compare_range_evidence.py cases.json --output revised --replay-dir initial
python experiments/summarize_range_evidence.py revised --reference initial --output summary.json
python -m unittest discover -s tests
python -m unittest discover -s experiments/tests
```

Use a separate output directory per protocol. Private full measurements retain
native point locations and input fingerprints; the accompanying checked-in
summary omits photographs and private filesystem paths.

## Next decision

Keep the existing production near/framing path and the newly added far
uncertainty audit. Do not replace unconfirmed dense extrema with the smaller
observed span automatically. Before integrating a range replacement, resolve
the native-support gaps and contradictory extremes, and test a defensible
admission rule against known geometry and the full image set. Additional manual
testing by the user is not required for this next investigation.
