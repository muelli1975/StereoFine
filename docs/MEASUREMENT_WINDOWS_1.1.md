# Measurement windows and output geometry

Status: 21 October 2026. Pixel widths below refer to one eye, not the combined
side-by-side image. The working images are reduced copies; originals remain the
source of exported pixels. Smaller sources are not upscaled to the width limit.

## What a measurement window means

A single pixel rarely identifies a scene point reliably. A local patch includes
the brightness pattern around a proposed correspondence so it can be compared
with the other eye. A radius of eight pixels gives `8 + 1 + 8 = 17` pixels per
side. A radius of twenty gives `20 + 1 + 20 = 41`. Odd sizes put the source pixel
at the exact centre. These radii are implementation choices, not universal
optima established for all photographs.

The windows do not divide the image into independently corrected tiles. They
are not export crops. Correspondence measurements subsequently inform a smooth
geometric model; local patch comparison itself does not deform the output.

## Existing stages

| Stage | Working image | Local window | Purpose |
| --- | --- | --- | --- |
| AKAZE/SIFT feature extraction | Up to 3000 px per eye | Detector-specific support | Find feature correspondences; not a tiling into 17px blocks |
| Additional photometric checks during alignment refinement | Geometry-analysis grayscale pair | 17x17 | Check brightness patterns at candidate correspondences before model refinement |
| SGBM disparity candidate generation | Corrected pair, up to 1500 px per eye | Configured block size 5 | Local matching cost combined by semi-global aggregation |
| Additional near-point confirmation and far-end confidence audit | Raw-luma disparity-analysis pair | 17x17 | Global horizontal strip search, limited vertical tolerance, uniqueness, reciprocal match and nearby support |
| Native near-point recovery and conditional two-ended range confirmation | Corrected pair at original spatial resolution | 41x41 | Additional native confirmation for initially unconfirmed measurements |

The 17px local verifier permits up to two analysis pixels of vertical mismatch.
The native verifier permits up to six original pixels. They reject low local
contrast, low correlation, ambiguous matches and failed reciprocal checks.
Neither searches for a preferred zero-depth disparity: horizontal position is
measured across the strip. Nearby points must corroborate extreme values.

Native recovery does **not** run for every production near measurement: an
already-confirmed near estimate follows the existing path. In contrast, the
two-ended research pilot deliberately checks both observed endpoints natively.
The production far confidence audit currently uses the analysis-scale patch
verifier. Do not describe every production far estimate as native-confirmed.

## Why scale matters

For a 4500px-wide original reduced to 1500px, the 17px analysis window covers
approximately 51x51 original pixels.
A fixed 41px native window therefore uses a smaller scene neighbourhood. The
actual resize ratio and rounded per-axis dimensions determine the mapping.

More context can distinguish repeated structures. However, a larger window can
also cross a depth boundary and mix foreground and background. Increasing the
window is therefore not automatically a more accurate measurement of its centre.

## Research status

The `range-evidence-4` pilot preserves the original native 41px result and, only
after a failed forward photometric check, tries a larger native window sized to
the analysis patch's footprint, capped at 129px per side. Contrast, correlation,
uniqueness, reciprocal and same-source-location agreement requirements remain.
Missing local texture and reciprocal failures do not trigger this fallback.

This larger-window fallback is **not enabled in regular processing**. Its
evaluation is separate from the production 3000/1500 width choice and from the
output's affine, projective and vertical-polish geometry.

## Current application integration

The fixed 41x41 verifier also checks both observed endpoints during conditional
range recovery. This runs only for eligible uncertain far estimates and requires
agreement at the primary width and a second width (normally 1500/1000 pixels).
A smaller observed range retains an uncertainty flag. The larger-footprint pilot
is still research-only. See [the admission rule and validation](OBSERVED_RANGE_1.1.md).
