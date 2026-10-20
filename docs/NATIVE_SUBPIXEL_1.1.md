# Native-resolution measurement and bounded-field review for StereoFine 1.1

Status: 20 October 2026. Research checkpoint after
[the earlier subpixel selection review](SUBPIXEL_SELECTION_1.1.md).

## Decision

Keep the existing application alignment unchanged at this checkpoint. Native
subpixel measurement is promising, but this experiment does not establish a safe
automatic replacement for the actual full-data RC3 results. The bounded cubic
proposal also fails the additional strict regional confirmation.

The new implementation lives entirely under `experiments/`. It is not imported
by the application. This checkpoint changes no applied geometry, `.sfin` schema,
pipeline version, near-point logic, GUI, stable 1.0 package or RC3 package.

## Implemented and tested

- Native-resolution sparse Lucas–Kanade measurement initialized from observed
  AKAZE/SIFT correspondences; a 21×21 window, one pyramid level, 40 iterations
  and 0.001 termination epsilon. This measures points, without applying a new
  image deformation or minimizing horizontal scene disparity.
- Before/after normalized patch-correlation checks, native forward/backward
  consistency within 0.25 pixels, movement within 1.5 pixels, and finite/in-bounds
  checks. Unconfirmed measurements retain their original seed coordinates.
- Pixel-center conversion using the actual width **and** rounded height of each
  analysis image. Original images and source point arrays are not modified.
- A reproducible comparison with the complete saved RC3 correction, plus separate
  spatially withheld fitting, selection, confirmation and pooled regional vetoes.
- A counterfactual that scales an excessive cubic field into the existing cap
  before reapplying all original photometric, conditioning, gradient, holdout and
  corner checks. It neither increases the cap nor adds model terms.
- Native geometry rendering and real temporary `.sfin` save/load checks for the
  three promising full-fit diagnostics and the one changed bounded candidate.

The measurement uses OpenCV's established
[sparse pyramidal LK implementation](https://docs.opencv.org/4.13.0/dc/d6b/group__video__track.html).
No neural package, model download or GPU is required.

## Comparison protocol and limits

The private corpus contains 29 pairs from Canon S110, Canon IXUS, Canon S95 and
Samsung NX1000, each evaluated with AKAZE and SIFT: **58 method/pair cases**.
All 58 saved full-data RC3 correction payloads were reproduced exactly before
comparison. Input hashes and the numeric results are retained in the
[public numeric audit](NATIVE_SUBPIXEL_1.1_RESULTS.json); images, point coordinates,
source paths and user sidecars are not published.

Source controls are detected with the existing distributed LK/NCC procedure and
confirmed on native pixels **before** candidate fitting. The same frozen controls
evaluate every variant. No candidate residual is used to remove difficult checks.
Reserved 128-analysis-pixel blocks, including a 16-pixel training margin in both
eyes, supply two disjoint control stages. Both stages and their union must pass
the unchanged strict gain and 3×3/5×5 regional criteria.

The full-data candidate is a diagnostic: its training was not spatially withheld
from these controls. The independent candidate uses the withheld training subset
and must improve both its equivalently fitted baseline and the actual saved
full-data RC3 result. This last comparison is deliberately conservative. Removing
training regions can weaken coverage and change model selection. A rejection
does **not** prove that native subpixel measurement cannot help; it means the
current protocol has not established production admission. These are photometric
measurements, not manually verified ground truth. Some cases retain as few as
four reserved native controls; sparse regions remain unverified.

## Results

| Check | Cases |
| --- | ---: |
| Complete saved RC3 correction exactly reproduced | 58 / 58 |
| Lower global P95 for the full-data diagnostic | 44 / 58 |
| Withheld candidate passes independent baseline comparison | 7 / 58 |
| Withheld candidate additionally improves actual full-data RC3 | 0 / 58 |
| Full-data diagnostic passes the control gates, without spatial training independence | 3 / 58 |
| Bounded cubic proposal changes the applied correction | 1 / 58 |
| Bounded proposal passes additional native regional confirmation | 0 / 58 |

The **44/58** figure is not a count of verified production improvements. The three
full-fit diagnostics that pass the control gates are S110 090/AKAZE, S95 038/AKAZE
and S110 023/SIFT. Their native fixed-source-control P95 values are:

| Case | Actual RC3 | Full-data native candidate |
| --- | ---: | ---: |
| S110 090 / AKAZE | 1.116 px | 0.686 px |
| S95 038 / AKAZE | 1.051 px | 0.488 px |
| S110 023 / SIFT | 0.671 px | 0.404 px |

The corresponding independently fitted candidates do not establish the same gain
over actual RC3. A direct integration based only on this shortlist would confuse
an encouraging diagnostic with independent validation.

### S110 090 bounded cubic field

The unconstrained peak is 24.068682 analysis pixels against the existing 24-pixel
cap. Uniform coefficient scaling by 0.997146396 fits within that same cap. All
existing production guards then pass, and no other case changes its applied
geometry in this experiment.

On 162 additional native controls reserved from cubic coefficient training, mean
absolute error falls from 0.458 to 0.224 native pixels; P95 falls from 1.002 to
0.620. However, the central 3×3 region's pooled P90 rises from 0.184 to 0.339
pixels. Its confirmation-fold mean also rises from 0.081 to 0.227 pixels. The
strict regional confirmation rejects the proposal. These additional controls are
excluded from the cubic fit; the preceding common affine/trapezoid fit is shared
and is not independent of those regions.

The outermost lower-right 10% has only **one** reserved native control here.
It cannot establish that the original troublesome corner is solved. The cap is
therefore a demonstrated rejection trigger, while releasing that rejection is
not yet a demonstrated safe fix.

## Render and persistence checks

All four candidates were rendered at original resolution through the unchanged
production geometry renderer. Each candidate's supported correction payload was
saved to a real temporary `.sfin`, loaded with the real source stamp, restored
through `PairState.from_sidecar`, and rendered again. **All four produced identical
native pixels after roundtrip**; favorite, manual shift and input orientation
were preserved. The temporary sidecars were removed; original files were untouched.

Independent output-raster detection gives the following supplementary global P95
measurements, expressed in native pixels:

| Case / proposal | RC3 raster | Candidate raster |
| --- | ---: | ---: |
| S110 090 / native AKAZE | 1.140 | 0.846 |
| S95 038 / native AKAZE | 1.957 | 0.792 |
| S110 023 / native SIFT | 0.750 | 0.623 |
| S110 090 / bounded cubic | 1.140 | 0.829 |

Output features are redetected per raster at a 1500-pixel measurement width;
their counts and locations differ. These are **not** paired source-control tests
or fully native-resolution output measurements. They confirm useful rendered
changes but cannot override the admission veto. The native S110 090 candidate's
BR20 raster P95, for example, increases from 1.775 to 1.904 pixels despite a better
global result. The output BR10 samples contain only six points per variant.

These checks cover geometry and persistence. They do not validate a newly
computed near point, final window framing, a future `process_source` integration
or Windows operation with the user's originals. The IXUS 008 near-point
uncertainty remains unresolved.

## Next integration criterion

Continue within the agreed affine/controlled-vergence/Y-Polish pipeline. The next
experiment must address measurement coverage and the stability of model selection
when validation regions are withheld. Native subpixel measurement remains a
candidate rather than an automatic default. Do not tune thresholds to these three
images or weaken guards to produce an acceptance count.

Any eventual applied change requires independent control evidence, native raster
checks, suitable pipeline cache invalidation and `.sfin` integration checks before
a new build. No new deformation model or file-format change is needed merely for
this research checkpoint.

## Reproduction

Runtime: Python 3.12.14, OpenCV 4.13.0, NumPy 2.4.6, Pillow 12.2.0.
The exact saved-reference check intentionally excludes a run when the correction
payload differs. Changing the BLAS thread environment caused tiny numerical
differences in trial runs; those excluded records were rerun under the original
environment and are not counted as algorithm failures. Final counts include only
exactly reproduced references. The scripts set OpenCV thread counts explicitly.

Provide a private manifest of `{name, left, right, state}` rows, using a full
PairState diagnostic JSON for `state`; optional `points` identifies an original
raw-match NPZ containing `left`, `right`, `mask` and `shape`. Names end in `_AKAZE`
or `_SIFT`. The experiment can also generate missing correspondence caches.

```sh
python -m unittest discover -s tests -p 'test_*.py'
python -m unittest discover -s experiments/tests -p 'test_*.py'
python experiments/compare_native_subpixel.py private_manifest.json --output private_native
python experiments/compare_bounded_field.py private_manifest.json \
  --output private_bounded --caches private_native
python experiments/check_native_candidates.py private_manifest.json \
  --results private_native --kind native \
  --names s110_bild090_AKAZE s95_bild038_AKAZE s110_bild023_SIFT
python experiments/check_native_candidates.py private_manifest.json \
  --results private_bounded --kind bounded --names s110_bild090_AKAZE
python -m experiments.summarize_native_subpixel private_manifest.json \
  --native private_native --bounded private_bounded --output native_summary.json
```

**146 application tests and 38 research tests pass.** Seven new measurement tests
cover known subpixel precision, retained horizontal disparity, actual-dimension
pixel-center mapping, flat images, invalid coordinates, invalid input layouts,
tracker failure and empty input.
