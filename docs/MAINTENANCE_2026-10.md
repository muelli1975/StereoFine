# October 2026 maintenance validation

Base: `2868324026b479f2f65a5a150c8c7d40fde73a9a` (the corrected Windows download links are retained).

## Scope

- `Original` export framing uses the oriented/common source aspect before alignment and overlap cropping, matching preview and disparity analysis. Other aspect modes retain their behavior.
- Duplicate source stems and duplicate batch result/sidecar names are rejected before processing the conflicting sources. Ambiguous L/R eyes are no longer silently discarded or selected by extension order. Existing source names, output names and `.sfin` format remain unchanged. A sidecar with a different source-path identity is not overwritten; edits to the same source remain supported.
- Integer color-curve application uses transient lookup tables. The fit, interpolation arithmetic, rounding and stored parameters are unchanged. Small images and floating-point inputs retain direct evaluation.
- The valid-rectangle histogram processes equal-height runs. It retains the original first-maximum choice and two-pixel safety margin, with no extra dependency.

The deviation search range/uncertainty logic, geometry fitting/model selection, analysis widths, P1/P99, anaglyph matrices, GUI styling and supplied assets are outside this change.

## Compatibility checks

Run `python -m unittest discover -s tests -p 'test_*.py'`.

The 92 tests include the existing 77 checks and new maintenance regressions:

- Full-resolution preview/export pixel equality across all aspect modes, both source orientations, crop zoom/pan and manual offsets; `Original` also agrees with disparity framing.
- Every uint8/uint16 input value at strengths 0, 0.2, 0.35, 0.7 and 1, including duplicate curve knots and non-contiguous arrays, compared with frozen released color arithmetic. Float/small-image fallbacks are checked separately.
- Every 4×4 binary mask, scaled masks containing tied rectangles, 2,000 random masks, and complete composed warps in uint8/uint16 compared with the frozen released rectangle function.
- Colliding Full-SBS filenames, ambiguous pair eyes, L/R-directory aliases, cross-folder batch result names, sidecar ownership, normal names and localized GUI error handling.
- The full-size bundled reference still selects `Affine`, with AKAZE mean vertical residual about 0.10198 px and total deviation about 19.833‰. This test never writes a reference-image sidecar.

Additional local reference check: SIFT selects `Affine`, with mean vertical residual 0.0784477 px and deviation 19.833333‰. For AKAZE and SIFT, full-resolution rendered half-images are pixel-identical to the released rectangle/color calculation, both with and without color matching.

The full German/English GUI smoke tests run under Xvfb before platform packaging. Automated checks do not substitute for visual verification on a physical Windows desktop.

## Timing sample

Local Linux, Python 3.12, pinned NumPy 2.4.6 / OpenCV 4.13.0, four OpenCV threads; median of three runs. These measure individual stages, not end-to-end application speed.

| Stage | Input per eye | Released | Optimized |
| --- | --- | ---: | ---: |
| Complete geometric warp and valid crop | 1500×1000 uint8 | 0.632 s | 0.166 s |
| Complete geometric warp and valid crop | 3240×2160 uint8 | 3.215 s | 0.658 s |
| Apply color curves to both eyes, including table creation | 1620×1080 uint8 | 0.276 s | 0.035 s |
| Apply color curves to both eyes, including table creation | 1620×1080 uint16 | 0.273 s | 0.042 s |

The runtime paths retain the existing pipeline versions: the rendering optimization is exact, and disparity already used the correct `Original` source aspect before this export fix. A changed export crop naturally invalidates its fitted color basis through the existing shape/basis comparison.
