# LoMa and FlexGlue CPU pilot

6 November 2026. Isolated research branch based on the released StereoFine 1.2
commit `29d41ad2c29c2704a1e8ddd6d1bdb646ab35a95f`. No product changes.

## Scope agreed before measurement

Compare the existing AKAZE and SIFT paths with official LoMa-B, FlexGlue and
FlexGlue with the official RoMa v2 refinement. The old 29 private camera-rig
pairs are unavailable in this environment. This pilot therefore uses public
Middlebury 2014 Adirondack, Pipes and Playroom pairs with ground truth.

For each scene, evaluate an already aligned control and a challenge combining
the dataset's alternate right-eye lighting with known right-eye rotation
(0.24 degrees), scale (1.003) and translation (1.7, 3.6 pixels). Images are
resized to a 1600-pixel long side. Geometry and thresholds are unchanged.

The dense GT control points are never supplied to a matcher or fit. They are
selected deterministically, checked for left/right disparity agreement and
excluded near depth boundaries. The known affine is applied to the GT as well
as the image. Record global, 5x5-cell and corner vertical errors of the actual
StereoFine correction map; also exercise raster rendering. Evaluate raw match
quality separately without using GT to remove matches before fitting.

The neural paths replace only point extraction/matching. They use StereoFine's
unchanged y-RANSAC, model selection, refinement and residual-field stages.
LoMa uses its standard 2048 keypoints. FlexGlue uses sampled sparse-to-dense
matching with 4096 samples at its official 512x512 descriptor/refinement sizes,
float32 transformers on CPU. Pixel-corner model coordinates are converted to
OpenCV pixel-centre coordinates before fitting. Different point budgets and
separate runner machines mean this is not a controlled speed ranking.

## Sources and reproducibility

- Middlebury data: https://vision.middlebury.edu/stereo/data/scenes2014/
- LoMa: https://github.com/davnords/LoMa at
  `415caedde23a9ed479172ed174fe4ff7b4514d4b`.
- FlexGlue: https://github.com/cvg/FlexGlue at
  `c6cbc7a933bb70ab58608e8835d99b6cc4adca1a`.
- Original public weights, their sizes/hashes, input hashes, actual dependency
  versions, hardware, initialization/download times and per-case RSS are logged.
- Workflow: `.github/workflows/research-neural-20261106.yml`.

## Interpretation limits

A candidate earns a useful quality signal only if it improves the challenge
cases without damaging the aligned controls or hiding worse regions behind
global scores. Initialization failures and missing measurements are explicit;
they are not quality failures. No thresholds are relaxed after seeing results.
This small controlled indoor-photo pilot cannot establish superiority on real
camera-rig lens errors, outdoor/night images, other hardware, or the current
private photo collection. It does not evaluate full export/deviation behaviour
or authorize runtime integration. Public benchmarks may overlap model training
or development data; no claim of unseen training content is made.

All inference runs on isolated GitHub-hosted CPU runners. There is no GPU
measurement and no extrapolation to Christoph's RTX 3060.
