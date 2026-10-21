# Quadratic and cubic vertical residual models

Implementation review, 21 October 2026. This describes the current development
code; it does not introduce a new alignment method or change published packages.

## Shared purpose

After the affine alignment and optional symmetric vergence/trapezoid correction,
the two images can still have a vertical mismatch that varies with image position.
Y-polish estimates a smooth residual field from measured correspondences. The
renderer applies it symmetrically to the two eyes. This field changes only Y;
horizontal scene disparity is not fitted toward zero. It is a constrained image
deformation, not a calibrated lens profile or an unconstrained local warp.

The complete geometry is composed into one inverse sampling map per eye, with one
image remapping operation. Selecting cubic does not add another resampling pass.

## Model families

Let x and y be centered image coordinates divided by image width and height.
Ignoring basis centering, which does not change the family of possible fields:

| Model | Terms | Coefficients | Typical additional flexibility |
| --- | --- | ---: | --- |
| yQuad | 1, x, y, xy, x², y² | 6 | Broad curvature and saddle-shaped residuals |
| yCubic | All quadratic terms, x³, x²y, xy², y³ | 10 | Asymmetric curvature and changes of curvature |

A cubic polynomial can express every quadratic polynomial by setting its four
extra coefficients to zero. That does **not** make an independently estimated
cubic field automatically more accurate. The extra coefficients can amplify
measurement noise and unsupported extrapolation. A simpler model is useful when
the measurements do not justify additional freedom.

The estimators are not interchangeable implementations of a single solver.
Quadratic fitting currently uses a left-coordinate design with squared terms
centered on the correspondence distribution. Cubic fitting uses a symmetric
design from both eyes and two destination-coordinate relinearizations. Both are
evaluated using the actual symmetric application convention. Their coefficients
must not be copied between payloads without accounting for these differences.

## Selection in the current pipeline

The initial model comparison includes affine, affine plus vergence, and their
quadratic variants. Common held-out point identities and global/regional checks
govern selection; a quadratic fit is not unconditionally applied.

After point recovery and the initial model selection, one cubic candidate is
tested against the complete preceding result. Its own coefficient fit excludes
whole 32-analysis-pixel blocks used for checking. Requirements include:

- Patch correlation at least 0.90, bounded preceding residuals, at least 120
  training points and 48 spatially thinned checks.
- Training support in at least five regions, with at least ten points each,
  plus numerical rank and conditioning checks.
- A whole-image 33×33 field check: displacement within the existing limit
  (24 analysis pixels or 1.8% of the smaller image dimension, whichever is lower)
  and sampled gradient at most 0.10.
- Improvement and regional safeguards against the complete preceding correction,
  including sufficiently supported outer 20% corners. These guards include
  explicit small-error allowances; they do not prohibit every numerical increase.

The cubic held-out blocks are excluded from that cubic coefficient fit. They are
not independent of every upstream fitting and selection stage. Sparse corner
support cannot establish accuracy there, even if numerical field checks pass.

If accepted, yCubic **replaces** `y_residual_apply`; it is not stacked on yQuad.
Otherwise the preceding result is retained. A selected cubic model is therefore
a measured additional opportunity, not a universally superior quality mode.

## Architecture judgement

Retain both complexity levels for now. Their mathematical overlap does not prove
that either selection option is redundant. Conversely, the existing comparisons
do not establish that two separate estimator implementations are indispensable.

Potential maintenance work is to share more measurement, scoring and diagnostic
code while retaining the tested model families, payload conventions and guard
policies. Replacing both with a single degree-adaptive or regularized solver
requires an ablation against the current complete pipeline. The earlier symmetric
quadratic refit did not establish an admissible general gain; see
[applied-model scoring](APPLIED_MODEL_SCORING_1.1.md).

No additional polynomial degree or free local warp is proposed. Better supported
measurements and reproducible validation take priority over another model family.
