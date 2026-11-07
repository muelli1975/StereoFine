# Vergence seed recovery pilot

The production geometry is unchanged. The initial affine-plane RANSAC filter
can reject real matches with nonlinear vertical displacement before the
existing projective stage is evaluated. This pilot tests whether a separate
seed hypothesis can recover them while leaving the existing warp and its
model-selection rules intact.

The experimental filter adds one normalized `x*y` term to the vertical
displacement hypothesis. Horizontal disparity does not enter its score.
Only matches with patch correlation of at least 0.85 can be newly admitted.
The tested coefficient bound corresponds to a corner contribution of at most
2.5% of the analysis height. The seed is not an image warp. The resulting mask
is passed to the ordinary affine, projective and residual-model pipeline.

## Evidence

Seven pinhole stereo scenes with fixed camera geometry and known visible
world points were evaluated with both AKAZE and SIFT. The evaluation inverts
the actual native renderer maps and uses the same control identities for both
fits within their common valid region. It also records 3×3 regions, the outer
15%, retained area and centered horizontal disparity error against the
parallel-camera reference.

The full-data hypothesis makes the 4° convergence case much better, but
the 8° AKAZE stress case worse. On common retained points that case changes
from 50.01 to 89.16 pixels at the 95th percentile. SIFT does not yield a
usable alternative there. Photometric similarity and a bounded hypothesis
alone are therefore insufficient admission criteria.

The screened variant reserves 128-pixel blocks before candidate fitting,
with a 16-pixel training margin in both eyes. It compares the trial with
the complete production fit using photometrically checked matches in
reserved blocks. The trial must recover at least 25% additional seed
support (at least 30 points) and remove at most 5% of the original seed.
The existing projective stage must pass its own guards, the baseline P95
must exceed 3 analysis pixels and the existing spatial holdout comparison
must pass. Known world points are used only for the external evaluation.
The production fit has access to the complete data, including the regions
reserved from the candidate.

Three of 14 cases pass the pilot screen. The following results measure
the actual maps on the independent known points, in input pixels.

| Case | Baseline P95 | Screened candidate P95 | Outer P95 before → after |
| --- | ---: | ---: | ---: |
| 4° convergence / AKAZE | 27.565 | 0.016 | 37.311 → 0.021 |
| 4° convergence / SIFT | 15.753 | 0.120 | 20.893 → 0.135 |
| 2° divergence / SIFT | 3.220 | 0.085 | 4.428 → 0.093 |

The other cases keep the production fit under this rule. The two 4° trials
retain roughly 96% of input area versus roughly 98% for the original fit.
Both improve the agreement with the known horizontal disparity field.

The bundled SBS sample was also compared with the same spatial blocks
withheld from both fits. The seed masks match exactly for each detector.
On 639 fixed LK/NCC control points the native-renderer P95 remains about
0.310 px for AKAZE and 0.311 px for SIFT.

## Archived photographs

Five recovered archives supplied 56 of the 58 expected originals, verified by
SHA-256, and 28 of the 29 reference pairs. The available pairs completed all
56 AKAZE and SIFT runs. The existing fit was selected in every run. In 55 runs
the candidate did not recover enough additional seed matches. The remaining
candidate failed the existing projective-model checks.

On independent native controls the median of the per-run vertical P95 errors
was 0.592 px for AKAZE and 0.684 px for SIFT. The synthetic improvements support
further research on strong convergence. StereoFine 1.3 retains the existing
production correction.

## Reproduction

```sh
python experiments/synthetic_vergence.py --output build/synthetic-vergence-13
python experiments/compare_vergence_seeds.py build/synthetic-vergence-13 --output build/vergence-seed-comparison.json
python experiments/compare_vergence_seeds.py build/synthetic-vergence-13 --screen --output build/vergence-seed-screened.json
python experiments/compare_vergence_seeds.py build/synthetic-vergence-13 --real-sbs assets/stereofine.jpg --output build/vergence-seed-real.json
python experiments/compare_vergence_corpus.py PRIVATE_UPLOADS --output build/private-geometry-13/corpus.json
```

The corpus runner accepts the original ZIPs or loose image files. It matches
images to the 29-pair reference by SHA-256, reports missing eyes/pairs and
preserves the historical IXUS orientation. Use `--inventory-only` for a
checksum-only check. Two disjoint sets of reserved blocks serve selection and
confirmation. Native-confirmed LK controls in the second set are measured on
both renderer maps. The pilot vetoes regression in supported regions and
excessive additional crop loss. Horizontal disparity changes are reported for
review because the private photographs do not have measured scene depth.

Before production admission, broaden the comparison with additional good and
difficult captures, including real pairs with strong convergence. Check
supported corners, native raster results, retained image area and depth consistency.
An automatic switch must reject ambiguous matches and preserve the existing
result when there is insufficient independent evidence.
