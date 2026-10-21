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

## Validation

198 application and 48 research tests passed on each of Windows, Linux and macOS. All four native archives passed source/asset/architecture verification and repeated input/session/export checks after extraction. German/English GUI smoke passed on Linux; extracted executable startup was checked on every target.

[Build validation](https://github.com/muelli1975/StereoFine/actions/runs/39594205017). Detailed results are attached as `BUILD_CHECKS.json`.

## SHA-256

```text
883be049175061c57f6dec2cfec1133fd0edbb54a511f2a9e293aa33c7792b4e  StereoFine_1.1_Windows_x64.zip
8ab0819449eaebeacf8ac29b5a07672d88930aa6f3eb6bde89ec38cb0619477e  StereoFine_1.1_Linux_x64.tar.gz
b20a0e90be718405ace10bf04ea5f5d9309e55102ddb547329cc7e6c6783d3b7  StereoFine_1.1_macOS_AppleSilicon.zip
f740edbb93fdc469132ad3cfb6807549b18fb04a8c5c2df980250a653eff2da6  StereoFine_1.1_macOS_Intel.zip
```
