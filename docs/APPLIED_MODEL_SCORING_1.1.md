# Renderer-consistent quadratic model scoring for StereoFine 1.1

Status: 20 October 2026, following the
[native subpixel investigation](NATIVE_SUBPIXEL_1.1.md).

## Integrated correctness fix

Quadratic complete-chain scoring now predicts the same symmetric destination
field that the renderer applies. The former score evaluated a clipped field at
the left source coordinates and subtracted it from the vertical difference.
Actual output applies half of the field to each eye, at that eye's destination
coordinates. These operations differ with nonzero horizontal scene disparity
and with a vertically varying field.

The corrected score reuses `corrected_point_residuals`, already used by the
photometric recovery and cubic refinement checks. It retains the fitted
normalization, actual per-eye clipping and the existing four inverse fixed-point
steps. Inputs already passed through the affine/trapezoid stages, so scoring
applies only the residual field in those coordinates. No horizontal zero-depth
target, new deformation model or higher correction allowance is introduced.

Coefficient fitting, available model chains and all acceptance thresholds remain
unchanged. The renderer itself is unchanged. This is a correction to the
prediction used for complete-chain selection and its reported residuals, rather
than a claim of improved image alignment across the current corpus.

### Analytic counterexample

For an 800-pixel-wide image, take a field `40*x`, where `x` is the normalized
horizontal position about the image center. A correspondence with 80 pixels of
horizontal disparity receives an average field two pixels different from the
left-only approximation. This difference is a consequence of the existing
symmetric application, not evidence that the scene disparity should be removed.

Seven new application tests check both-eye evaluation, an independent closed-form
destination-coordinate solution, separate clipping per eye, frozen normalization,
analysis/full-resolution units, identity/empty inputs and actual native renderer
maps. The last test captures the unchanged renderer's master-coordinate maps for
a 16-bit pair and verifies aligned destination scanlines with nonzero horizontal
depth differences. The four-step solver is tested within its numerical precision;
it is not represented as an exact closed-form inverse for arbitrary fields.

## Original-image regression

The same 29 private pairs, each with AKAZE and SIFT, were evaluated: **58 cases**.
The frozen RC3 approximation reproduces the saved full-data correction payload
exactly in all 58 cases before the counterfactual is measured. Coefficient fits,
matching, inlier masks, photometric recovery, cubic refinement and acceptance
thresholds are held fixed.

For the scoring fix, **all 58 applied correction payloads remain identical** to
the saved RC3 reference. The frozen native source controls likewise report
identical errors. This is a regression result, not a measured accuracy gain.
Candidate prediction differences can still be substantial: the largest recorded
single-candidate discrepancy is 8.463 native-equivalent pixels at S110 026/SIFT.
That is an internal candidate prediction discrepancy, not an output improvement
or a claim that every correspondence is correct.

Five cases additionally pass native geometry raster checks: S110 090/AKAZE,
S110 023/SIFT, IXUS 008/AKAZE, S95 038/AKAZE and NX1000 033/SIFT. Rendered pixel
hashes are identical to their RC3 references. Each candidate was also saved to a
real temporary `.sfin`, loaded with its source stamp, restored through
`PairState.from_sidecar` and rendered again: **all five roundtrips are pixel
identical**, with favorite, manual shift and input transforms retained.

These are geometry checks. They do not claim that the original corner problem or
IXUS near-point uncertainty is resolved, or constitute Windows testing with the
user's original files.

## Separate coefficient-fitting experiment: not integrated

A second experiment fits the same six-term quadratic to the average field at
both eye positions, then uses two relinearizations, following the approach
already present in the cubic refinement. It retains the existing support,
conditioning, clipping and admission rules. It is confined to `experiments/`.

Known synthetic stereo fields with varying horizontal disparity expose the
old fit's model mismatch. The new fit reconstructs their withheld geometry within
0.00001 pixels, and deliberately corrupted held-out vertical measurements cannot
change its fitted coefficients. These tests isolate mathematical consistency;
they are not a substitute for original-image validation.

| Original-image check | Scoring fix | Symmetric coefficient refit |
| --- | ---: | ---: |
| Exact saved RC3 reference reproduced | 58 / 58 | 58 / 58 |
| Applied correction changes | 0 / 58 | 48 / 58 |
| Full-data diagnostic has lower global P95 | 0 / 58 | 25 / 58 |
| Full-data diagnostic has higher global P95 | 0 / 58 | 23 / 58 |
| Withheld candidate beats its equivalently fitted baseline | 0 / 58 | 1 / 58 |
| Withheld candidate also passes actual full-data RC3 veto | 0 / 58 | 0 / 58 |

Ten refit cases retain the same full-data residuals. None of the refit's full-data
diagnostics passes the full two-stage/pooled gate either. The one independent
baseline comparison that passes is S110 023/AKAZE, but it does not improve the
actual full-data RC3 reference sufficiently. These results do not support a
default coefficient-fitting change, despite success on the known synthetic data.

The conservative reference veto and the training-coverage limits described in
the native subpixel report still apply. Frozen controls are photometric
measurements rather than manual ground truth. No acceptance threshold was tuned
to force an improvement count. The current result directs further work toward
measurement reliability and coverage before changing the fit automatically.

## Persistence and validation

Alignment calculation version advances from `sf-align-4` to **`sf-align-5`**.
The `.sfin` schema remains 3: the supported correction parameters and renderer
contract have not changed. Old automatic alignment, dependent disparity/near
framing and fitted color caches are invalidated through the existing mechanism.
The processing integration test uses an actual `sf-align-4` sidecar, verifies
reanalysis, retains favorite/manual/floating-window edits, replaces a deliberately
stale automatic near offset, writes the current pipeline version, and confirms
cache reuse on the next pass.

Local validation: **153 application tests and 42 research tests pass**; all
application modules import, sources compile, and original asset hashes match.
The separate `validate-development.yml` workflow runs both suites on Windows,
Linux and macOS and the existing German/English GUI smoke tests on Linux. It has
read-only repository permissions and no package or release publication step.

Remote validation completed successfully in
[GitHub Actions run 39468269894](https://github.com/muelli1975/StereoFine/actions/runs/39468269894)
for code commit `d8b434fd7ca076cc47efd5ec014940fb5063b8db`:

| Runner | Application tests | Research tests | Additional checks |
| --- | ---: | ---: | --- |
| Windows 2022 | 153 passed | 42 passed | Compilation and original asset hashes passed |
| Ubuntu 22.04 | 153 passed | 42 passed | Compilation, original asset hashes and German/English GUI smoke passed |
| macOS 14 | 153 passed | 42 passed | Compilation and original asset hashes passed |

CI uses Python 3.12.10 and the pinned runtime dependencies. Private original-image
comparisons ran locally; these platform jobs use the public regression fixtures.
No private originals were uploaded to GitHub Actions.

Published stable 1.0 and RC3 packages are not changed. The development branch's
app version label remains the existing RC3 baseline until a separately validated
new package is prepared; this fix is an unreleased development change.

## Reproduction and evidence

[Compact numeric audit](APPLIED_MODEL_SCORING_1.1_RESULTS.json), including input
hashes, exact-reference checks, frozen native-control comparisons and raster
digests. No private image, correspondence coordinates, source paths or user
sidecar is included in the repository. Runtime: Python 3.12.14, OpenCV 4.13.0,
NumPy 2.4.6, Pillow 12.2.0.

First reproduce the frozen native-control dataset from the preceding report.
Then run the two variants into **different** private directories:

```sh
python -m unittest discover -s tests -p 'test_*.py'
python -m unittest discover -s experiments/tests -p 'test_*.py'
python experiments/compare_applied_model_scoring.py private_manifest.json \
  --native private_native --output private_scoring
python experiments/compare_applied_model_scoring.py private_manifest.json \
  --native private_native --output private_symmetric --refit
python experiments/check_native_candidates.py private_manifest.json \
  --results private_scoring --kind applied \
  --names s110_bild090_AKAZE s110_bild023_SIFT ixus_bild008_AKAZE \
          s95_bild038_AKAZE nx1000_bild033_SIFT
python -m experiments.summarize_applied_model_scoring private_manifest.json \
  --scoring private_scoring --refit private_symmetric --output scoring_summary.json
```

The baseline evaluator is frozen explicitly in `experiments/applied_model_scoring.py`.
Both drivers refuse to count a saved-reference mismatch as a measured result.
As with the preceding investigation, changing the numerical runtime can prevent
exact payload reproduction; such a run is excluded, not counted as a regression.
