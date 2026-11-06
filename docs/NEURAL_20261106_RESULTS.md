# LoMa and FlexGlue: public stereo CPU pilot

Measured on 6 November 2026 against released StereoFine 1.2.

[Protocol](NEURAL_20261106_PROTOCOL.md) | [Complete results](NEURAL_20261106_RESULTS.json) | [Execution evidence](https://github.com/muelli1975/StereoFine/actions/runs/42215447087)

Three public Middlebury 2014 scenes, each as an aligned control and as an alternate-lighting challenge with a known right-eye affine transform. The six images pairs use a 1600-pixel long side. Between 26,916 and 34,264 independent GT points are used per case; none is passed into a matcher or fit.

## Vertical error after the unchanged StereoFine correction

P95 is the absolute vertical error below which 95% of the independent control points lie. All values are pixels at the stated input resolution; lower is better.

| Case | AKAZE | SIFT | LoMa-B | FlexGlue | FlexGlue + refinement |
|---|---:|---:|---:|---:|---:|
| Adirondack_aligned | 0.1748 | 0.0461 | 0.0900 | 0.1212 | not measured |
| Adirondack_light_affine | 0.3072 | 0.2918 | 0.2003 | 0.7778 | not measured |
| Pipes_aligned | 0.0945 | 0.0764 | 0.0584 | 0.1616 | not measured |
| Pipes_light_affine | 1.2315 | 0.8151 | 0.1856 | 0.3504 | not measured |
| Playroom_aligned | 0.1304 | 0.0930 | 0.1964 | 0.1361 | not measured |
| Playroom_light_affine | 0.9737 | 0.2678 | 0.3720 | 0.3514 | not measured |

The optional official FlexGlue refinement job reached its 75-minute CPU job limit without completing a case. It is recorded as not measured; this supplies no accuracy comparison for refinement. [Job log](https://github.com/muelli1975/StereoFine/actions/runs/42215447087/job/127884182410).

## Regional differences versus SIFT

These are exact signed differences in P95, not an admission rule. Positive values mean more vertical error than SIFT. Only regions with at least 20 GT points in both methods are compared.

| Case | Candidate | Global delta | Largest 5x5-cell increase | Largest corner increase |
|---|---|---:|---:|---:|
| Adirondack_aligned | flexglue | +0.0751 | +0.1347 | +0.1347 |
| Adirondack_light_affine | flexglue | +0.4860 | +0.8431 | +0.7818 |
| Pipes_aligned | flexglue | +0.0852 | +0.1342 | +0.1342 |
| Pipes_light_affine | flexglue | -0.4647 | +0.1204 | +0.1204 |
| Playroom_aligned | flexglue | +0.0431 | +0.0712 | +0.0712 |
| Playroom_light_affine | flexglue | +0.0836 | +0.0959 | +0.0959 |
| Adirondack_aligned | loma_b | +0.0438 | +0.0698 | +0.0698 |
| Adirondack_light_affine | loma_b | -0.0915 | +0.0288 | -0.0087 |
| Pipes_aligned | loma_b | -0.0180 | +0.0284 | +0.0144 |
| Pipes_light_affine | loma_b | -0.6294 | +0.0075 | -0.0022 |
| Playroom_aligned | loma_b | +0.1034 | +0.1328 | +0.1328 |
| Playroom_light_affine | loma_b | +0.1042 | +0.1425 | +0.1425 |

## Observed resources

Wall times include point matching and StereoFine fitting. They exclude initial model loading and downloads. Different GitHub VMs and method-specific point budgets prevent a controlled speed ranking. The first inference includes warmup. RSS includes the complete Python process.

| Method | Completed cases | Median time (s) | Range (s) | Peak process RSS (GiB) |
|---|---:|---:|---:|---:|
| AKAZE | 6 | 0.49 | 0.29–0.63 | 0.571 |
| SIFT | 6 | 0.85 | 0.62–1.24 | 0.571 |
| loma_b | 6 | 31.73 | 31.35–31.84 | 3.857 |
| flexglue | 6 | 18.03 | 18.01–18.13 | 1.469 |
| flexglue_refined | 0 | - | - | - |

## Limits

- The earlier 29 private StereoFine camera-rig pairs were unavailable and were not used.
- These controlled indoor scenes do not establish accuracy on real lens errors, outdoor/night scenes, or new cameras.
- Public scenes may have been used during model training or development; no unseen-data claim is made.
- Raw match precision is diagnostic and can be affected by sampling near depth boundaries. GT never filters fitted matches.
- The score evaluates the actual correction point map; raster rendering was exercised, but full export/deviation/session behaviour was not tested.
- No automatic candidate selection or product integration occurred. Different budgets: LoMa-B 2048 keypoints; FlexGlue 4096 samples.
- Official model code and weights were used. FlexGlue uses fp32 transformers on CPU; refinement retains its official implementation.
- Input/model hashes, source commit, exact configuration, versions and machine metadata are in the complete results.
- Source images and weight files are not redistributed in this repository.
