**Superseded by [RC3](https://github.com/muelli1975/StereoFine/releases/tag/v1.1-rc3).** RC3 fixes source packaging, including Windows line endings; image processing is unchanged.

# StereoFine 1.1 – Release candidate 1

This is a prerelease for testing the revised alignment pipeline. The regular
1.0 release remains available separately.

- Improved automatic model selection with robust, spatially distributed checks
  comparing complete correction chains.
- Recovery of photometrically confirmed correspondences for residual distortion.
  Entire image blocks validate each refit without training it.
- An additional bounded cubic vertical correction for smooth residual errors
  near image borders. It requires confirmed correspondences and improvement on
  withheld image blocks, with separate corner protections. This is not a full
  lens calibration.
- Near-point checks account for small genuine foreground areas and previous
  measurement gaps near image borders. Extreme candidates are checked through
  unambiguous mutual image comparisons and neighboring correspondences.
- Faster exact SIFT matching retains the same correspondence pairs without
  approximate nearest-neighbor search.
- Corrected TIFF orientation for 8/16-bit input. Outdated automatic calculations
  are invalidated while applicable manual edits and favorites are retained.
- Includes the earlier original-aspect-ratio and filename-collision fixes,
  plus result-preserving color and valid-crop accelerations.

Controls and traffic-light thresholds are unchanged. More complete foreground
detection can produce larger near-point and total-disparity values than 1.0.
Uncertain measurements remain explicitly marked as uncertain.

Validated on eleven real pairs (seven Canon S110, four Canon IXUS 100 IS) using
AKAZE and SIFT, together with automated regressions and platform builds. For
the four supplied IXUS pairs, set the left input rotation to 180 degrees: their
pixels are stored upside down despite normal EXIF orientation. Near-point
measurement for IXUS/bild008 remains uncertain with both methods. Local residual
errors remain possible; this prerelease still requires practical validation
on Christoph's Windows computer.

Archives include the exact source revision under `Source/`. Start the application
locally from a fully extracted folder and keep the existing 1.0 installation
separate.
