# Integrated input formats and quality components for 1.1

Unreleased development source, not the published RC3 packages or stable 1.0.

## Processing admitted to production

The robust complete-chain model selection, photometrically checked inlier
recovery and bounded cubic vertical correction from RC1/RC3 remain active.
Renderer-consistent quadratic scoring (`sf-align-5`) and native-confirmed
near-point recovery and conditional observed-range confirmation (`sf-disparity-5`)
are active, as documented in
[applied scoring](APPLIED_MODEL_SCORING_1.1.md) and
[near-point recovery](NATIVE_NEAR_RECOVERY_1.1.md) and
[observed-range validation](OBSERVED_RANGE_1.1.md).

The current format integration does not change their coefficients, thresholds,
guards, horizontal disparity, framing controls or resampling. Native LK alignment
refinement, the alternative symmetric quadratic fitter, bounded-field projection,
neural matching and full uncalibrated rectification remain research code. None
has passed the existing independent admission checks as a general improvement.
S110 bild090's extreme lower-right residual remains open; three method/image
near-point cases retain uncertainty for insufficient evidence.

## Input contract

| Container | Import |
| --- | --- |
| JPEG/JPS, PNG/PNS, TIFF, MPO | Existing paths retained, including native 16-bit PNG/PNS/TIFF |
| Static WebP/BMP | Pillow decoding, EXIF transpose once, ICC to sRGB, 8-bit RGB |
| SDR HEIC/HEIF | Separate local reader, libheif orientation, ICC to sRGB, 8-bit RGB |
| Tagged stereo/Spatial HEIF | Select the applicable `ster` group and preserve its eye/entity order |
| Untagged HEIF | Use only the primary image; explicit Full-SBS entry or a separate L/R eye |

New extensions participate in both file dialogs, folder discovery, duplicate-name
protection, sessions and export. Layout/eye guessing, Over/Under reconstruction,
RAW development, HDR/gainmap tone mapping and new export containers are outside
this change. Alpha is discarded, preserving stored RGB as in the existing PNG
path; no matte is invented. Animated WebP is rejected.

HEIF uses TransCora's reader from commit
`c8f7a00b8ea0494912454e668740c2071a5c2766`, with its established stereo-group
selection, auxiliary-item resolution, orientation and SDR checks. Unlike
TransCora, StereoFine does **not** ship FFmpeg: SDR without an ICC profile must
be sRGB/unspecified primaries and transfer as supported by that reader. Other
NCLX colour conversions are rejected with a request for an sRGB TIFF/PNG export.
This is a deliberate supported subset, not universal HEIF support. Multiple
applicable groups, broken stereo references, non-square pixels, unequal eye
dimensions and PQ/HLG are rejected. Depth images and gainmaps are not stereo eyes.

ICC conversion uses Pillow/LittleCMS, the same established mechanism used in
TransCora. BMP V4/V5 colour metadata is checked separately because Pillow 12.2.0 does not expose it. Embedded V5 ICC profiles are passed to LittleCMS; linked profiles and calibrated endpoints are rejected instead of being ignored. Offsets follow the [Microsoft BITMAPV5HEADER definition](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/ns-wingdi-bitmapv5header). Pixel decoding remains Pillow’s job.

New normalized imports must not regain their source ICC/AdobeRGB tags
when ExifTool copies metadata: exports exclude that profile and mark EXIF sRGB.
Existing JPEG/PNG/TIFF/MPO import and metadata behavior is unchanged.

## Session/source identity

Schema 3 accepts the additional `heif` source kind and optional `entity` field
in each file stamp. HEIF entity IDs are distinct from MPO frame indices. File
path, size, mtime, decoded dimensions and the selected eye IDs must all match.
Missing `entity` means `None` for existing sources, so their caches and user
edits remain compatible. Existing input pixels have not changed, so the shared
input version remains `sf-input-2`; alignment/disparity remain at 5/3. Saving
and reopening preserves explicit eye swap, manual shifts and favorite state.

## Validation and packaging

Local validation passed 178 application tests and 42 research tests.
Twelve added regressions cover real WebP/BMP pixels, all WebP EXIF orientations,
ICC/alpha, animation/corrupt profile rejection, collisions, group ambiguity,
HDR/pixel-aspect/size guards, real tagged eyes, native `.sfin` render identity,
entity mismatch, untagged HEIF packed/separate inputs, BMP V5 profile handling and codec isolation. The previous test that deliberately
rejected every HEIC was replaced by rejection of a damaged HEIC.

The frozen reader was built locally from pinned dependencies. Actual public
Spatial Photo and camera-orientation files also load through the production
reader: 2560×2560 per eye with entity IDs 26/52, and 3024×4032 portrait pixels,
respectively. Their original files remain outside the repository. A fresh check of all eight previously unconfirmed method/image cases and S110 bild090/SIFT reproduced the pre-format near-point confirmation objects and uncertainty reasons exactly (five recovered, three still uncertain, one confirmed control). These are
decoder/identity checks, not stereo accuracy ground truth.

The development workflow runs source regressions on Windows/Linux/macOS and
builds four separate development artifacts (Windows, Linux, macOS ARM/Intel).
It downloads all four public fixtures with pinned SHA-256 checks and tests each actual frozen application and reader via `--check-inputs`, including
tagged eye order, real session/render replay, WebP/BMP pixel identity and metadata
export, Spatial Photo entities/dimensions and native portrait orientation. The DE/EN GUI smoke also opens HEIF/WebP/BMP through the actual asynchronous load worker and preview. The main binary excludes pillow-heif; the helper carries its replaceable
native libraries, sources and notices. The workflow has only `contents: read`
and no release/tag publication step. Builds identify as `1.1-dev`, with commit
and platform in the artifact name; published RC3 and stable 1.0 are untouched.

The earlier input-format commit `e00b168fc54d65750bcf7a7210326cc181cdbefb` passed all seven jobs in [run 39489282334](https://github.com/muelli1975/StereoFine/actions/runs/39489282334): 178 application and 42 research tests on each of Windows, Linux and macOS, DE/EN GUI smoke, and actual frozen packages on Windows, Linux, macOS ARM and macOS Intel. The package checks include all four checksum-pinned public HEIF fixtures. A locally built Linux ZIP was additionally extracted into a fresh temporary directory and its frozen application/reader passed all six input/session/export checks. [Structured evidence](IMAGE_FORMATS_1.1_RESULTS.json). Those platform results precede the current observed-range changes and do not validate the new commit. See [current local checks and remaining platform gates](OBSERVED_RANGE_1.1.md). Automated
package checks do not replace desktop operation with the user's original images.

Reproduction:

```sh
python -m pip install -r requirements-build.txt
python -m unittest discover -s tests -p 'test_*.py'
python -m unittest discover -s experiments/tests -p 'test_*.py'
python scripts/prepare_heif_fixtures.py build/heif-fixtures
python StereoFine.py --check-inputs input-check.json build/heif-fixtures
# Clean committed tree and the official platform ExifTool tree under tools/:
python scripts/build_development.py --fixtures build/heif-fixtures
```

Public HEIF fixtures, unchanged from pillow-heif v1.8.1:

| File | Upstream tests/images directory | SHA-256 |
| --- | --- | --- |
| stereo_pair.heic | heif_other | 628d02b8111e9ee8bb9e30935d3b54c32c1dab7c6a852067fcbe315412715b20 |
| entity_groups.heic | heif_special | 463966c69196ee4bc204581fe97c6092bd386d8f8282010ffd622275be0e5c16 |
| spatial_photo.heic | heif_other | ef941d328072a2df034adb3c3b46f41117606bfc8fcc100dff975d31f55ec028 |
| arrow.heic | heif_other | 73f604d7353df4848505a1f45a5517f736857fe047372f95c2f3d671df92c22c |

Only the first two tiny synthetic fixtures are committed; their upstream BSD
notice is retained. The larger images are development probes only.
