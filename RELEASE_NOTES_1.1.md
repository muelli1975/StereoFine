# StereoFine 1.1 — release notes draft

Unreleased. This document describes the current source changes; final platform
archives and their checksums must be verified before publication. Existing
1.0 and RC3 downloads do not contain all changes described here.

StereoFine 1.1 improves automatic alignment and the evidence behind near/far
measurements while keeping the compact workflow and automatic 3-permille
near-point framing.

- Score geometric candidates against the correction actually applied to both
  eyes, with bounded vertical edge correction and explicit corner checks.
- Confirm additional near and far correspondences on original-resolution
  pixels. Ambiguous far estimates receive a second analysis-width check;
  smaller observed spans retain an uncertainty indication. Textureless,
  occluded and unsampled surfaces remain a limitation.
- Recompute outdated automatic analyses while preserving saved fine adjustments
  during Save and batch processing. Explicit Start recalculates alignment and
  framing, clears manual X/Y nudges and retains crop/aspect/position.
- Add JPS/PNS, static WebP/BMP and SDR HEIC/HEIF inputs, including supported
  tagged stereo and Spatial Photo containers. HEIF uses a separate replaceable
  reader. Unsupported HDR/color descriptions are rejected explicitly.
- Include corresponding sources, licenses and portable metadata tools. Build
  checks exercise actual packaged imports, session reload and rendering.

Geometry and disparity analysis remain limited to 3000 and 1500 pixels per eye,
respectively. Color matching and Floating Window masks remain outside these
measurements. Every save produces both an SBS JPEG and an anaglyph JPEG.

See [measurement evidence and limitations](docs/OBSERVED_RANGE_1.1.md) and
[input-format scope](docs/IMAGE_FORMATS_1.1.md).

## Planned downloads

| Platform | Filename |
| --- | --- |
| Windows x64 | `StereoFine_1.1_Windows_x64.zip` |
| Linux x64 | `StereoFine_1.1_Linux_x64.tar.gz` |
| macOS Apple Silicon | `StereoFine_1.1_macOS_AppleSilicon.zip` |
| macOS Intel | `StereoFine_1.1_macOS_Intel.zip` |

The candidate workflow prepares these archives without publishing a release.
Add verified SHA-256 values and actual platform validation results here before
publishing; do not reuse checksums or download links from RC3.
