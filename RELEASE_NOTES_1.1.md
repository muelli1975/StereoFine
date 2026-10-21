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
Final build evidence and checksums accompany the release.
