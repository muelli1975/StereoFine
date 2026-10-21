# Correspondence coverage audit

21 October 2026. Research only; no production geometry, `.sfin` schema, published
package or guard threshold changes. The current Windows development build has
received positive practical feedback; this audit addresses remaining evidence
limits rather than retracting that improvement.

## Reproduction and scope

The existing 29 private pairs were recovered and checked against previously
recorded source SHA-256 values. All 58 original files match, including the
explicitly named S110 `bild023R.tif`. Both methods give 58 method/pair cases;
the 116 method/eye checksum comparisons all match. IXUS left inputs retain the
previous explicit 180-degree orientation; other inputs use source orientation.
Original files remain outside the repository and are not modified.

The baseline is a fresh fit using current core revision
`8088bd403bef948e3a99ac1279c4a526fae456a6`, not an exact replay of historical
private RC3 states. OpenCV 4.13.0, NumPy 2.4.6, four OpenCV threads, seed 1337,
analysis width 3000. Per-input, experiment and dependency hashes are recorded in
[the numeric results](CORRESPONDENCE_COVERAGE_1.1_RESULTS.json).

Run against a private JSON manifest with `name`, `left`, `right`, and optional
`left_orientation`/`right_orientation` fields. Names end in `_AKAZE` or `_SIFT`.
Both method rows for a pair must refer to the same sources and orientation:

```sh
python experiments/audit_correspondence_coverage.py private_manifest.json --output private_coverage
python -m unittest discover -s experiments/tests -p 'test_*.py'
```

The audit reuses the existing source LK/NCC controls, native-LK confirmation,
and 128-analysis-pixel reserved blocks with 16-pixel training halos in both eyes.
It does not lower correlation thresholds or select a candidate. Counts are
anchored in left source coordinates. Per-case private outputs include 5x5 grids;
the public numeric report retains whole-image and corner summaries with hashes
of the complete private results. Control counts are shared across both methods
and must be counted once per pair when aggregating.

## Results

| Current complete fit | Cases |
| --- | ---: |
| Affine + yQuad | 39 |
| Affine + yCubic | 19 |

The S110 subset selects yQuad in nine of fourteen runs and yCubic in five.
This documents use of both complexity levels, not an ablation establishing that
two separate estimator implementations are necessary. See
[the implementation review](Y_POLISH_MODELS_1.1.md).

The blocked diagnostic retains a median **59.08%** of the original seed inliers
(range 51.67–69.68%) before its own RANSAC/refinement. Its model label differs
from the complete fit in 12/58 cases. Removing training data can change model
selection in either direction; it does not prove every blocked fit is worse.

Native control support is uneven:

| Left-source region | Pairs with at least 6 native controls before reserving blocks | Pairs with at least 6 reserved native controls |
| --- | ---: | ---: |
| Top-left 20% corner | 7 / 29 | 1 / 29 |
| Top-right 20% corner | 12 / 29 | 4 / 29 |
| Bottom-left 20% corner | 13 / 29 | 6 / 29 |
| Bottom-right 20% corner | 19 / 29 | 10 / 29 |
| Bottom-right 10% corner | 7 / 29 | 2 / 29 |

Six is the existing minimum for assessing a supported corner, not a guarantee
of accuracy or of support in both later confirmation folds. Eleven pairs have
no native-confirmed control in BR10 even before reserving blocks. This diagnoses
the **additional control measurement**, not the absence of all production matches.
For example NX1000 001/AKAZE has 140 native-accepted original seed inliers in
BR10 while the source-LK control detector supplies no native control there.

### S110 bild090

The fresh ordinary fit retains yQuad for AKAZE (`field_limit`) and accepts
yCubic for SIFT. The original cubic limit is still enforced.

| BR10 evidence | AKAZE | SIFT |
| --- | ---: | ---: |
| Raw feature matches | 34 | 48 |
| Original seed inliers | 29 | 40 |
| Seed inliers with analysis patch NCC at least 0.90 | 25 | 28 |
| Seed inliers accepted by native refinement | 10 | 12 |
| Original seed inliers retained by experimental blocked training | 0 | 3 |
| Native-confirmed source controls before block reservation | 4 | 4 |
| Reserved native source controls | 2 | 2 |

The larger BR20 region has 60 native-confirmed source controls, eight reserved.
That cannot establish performance in the smaller BR10 corner. These control
counts differ from the historical rendered-image detector's sample and must
not be presented as the same measurements.

Original seed-inlier counts precede production point recovery and cubic
refinement, which can use additional measured correspondences. A zero seed
count is not necessarily zero final support. Likewise, the zero retained
AKAZE BR10 count belongs to the experimental 128-pixel blocking protocol, not
to the production cubic stage's separate 32-pixel holdout.

## Decisions and next experiment

- Keep yQuad and bounded yCubic. Add no polynomial degree or free local warp.
- Do not weaken field limits, photometric checks or the existing admission veto.
- Do not infer a new quality gain from these counts or descriptive residuals:
  controls may overlap the complete fit's training, and no ground truth exists.
- Prioritize better control-seed coverage at native resolution. A separate pilot
  should freeze seeds before fitting, use the unchanged reciprocal/photometric
  confirmation, retain genuinely excluded control areas, and report unsupported
  regions explicitly. More accepted training points alone cannot validate them.
- Assess common fitting/scoring infrastructure as maintenance work, with a
  before/after ablation. Also expand ordinary and already-good image controls;
  this predominantly difficult corpus is insufficient for a universal claim.

All **42 existing research tests** pass, including known-displacement precision,
depth-disparity preservation, failed-seed retention and blocked-training checks.
The new count helper was additionally checked at exact half-open corner/grid
boundaries, and its module compiles. No new test package was requested or built.
