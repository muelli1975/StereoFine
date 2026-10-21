# StereoFine 1.1

StereoFine 1.1 improves alignment and measurement reliability and adds supported
SDR HEIC/HEIF and additional raster input formats. Existing 1.0 and RC3 downloads
remain available separately.

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

## Updated 1.1 packages — 21 October 2026

- Recover a supported far endpoint even when the additional near control cannot
  confirm its own endpoint. Keep unresolved near evidence and incomplete scene
  coverage explicitly uncertain.
- Show the uncertainty warning in bold gold with a warning triangle and a fixed
  two-line layout in German and English. Hold M to check with the measurement cross.
- Reuse the scaled preview background while moving that cross. Keyboard steps,
  hold delay, speed and acceleration are unchanged.
- Restore the dark Windows titlebar when leaving fullscreen through the button,
  F11 or Escape.

The version remains **1.1**, including archive names. Replace the extracted
application with the complete updated package. Outdated automatic disparity
measurements are recalculated while valid alignment, saved manual adjustments
and favorites remain reusable. Near-point recognition and all measurement
thresholds are unchanged by this final GUI update.

## Downloads

| Platform | Filename |
| --- | --- |
| Windows x64 | `StereoFine_1.1_Windows_x64.zip` |
| Linux x64 | `StereoFine_1.1_Linux_x64.tar.gz` |
| macOS Apple Silicon | `StereoFine_1.1_macOS_AppleSilicon.zip` |
| macOS Intel | `StereoFine_1.1_macOS_Intel.zip` |

All archives include the exact corresponding source under `Source/`. Extract
the complete archive before starting the application. SHA-256 values are supplied
in `SHA256SUMS.txt` alongside the downloads.

The release build repeats application and synthetic research regressions on
Windows, Linux and macOS, German/English GUI smoke on Linux, source/asset byte
verification and actual packaged input/session/export checks on all four targets.
The accompanying `BUILD_CHECKS.json` identifies the exact source commit and
validation run for these updated archives. Its checks include reticle pixel
identity and native Windows titlebar restoration. Use the accompanying
`SHA256SUMS.txt` for this package update; earlier 1.1 checksums do not apply.
