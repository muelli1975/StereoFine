# StereoFine 1.0 – validated historical baselines

This note preserves numerical conclusions from the earlier StereoFine test rounds so
1.0 does not repeat settled experiments without a concrete regression reason.

## Geometry analysis width

Direct 150-image comparison, 2000 px vs 3000 px:

| Method | Width | Mean vertical residual | Mean per-image p95 |
| --- | ---: | ---: | ---: |
| SIFT | 3000 px | 0.435 px | 1.364 px |
| SIFT | 2000 px | 0.510 px | 1.694 px |
| AKAZE | 3000 px | 0.464 px | 1.603 px |
| AKAZE | 2000 px | 0.587 px | 2.156 px |

3000 px was better on the mean for AKAZE on 150/150 images and SIFT on 145/150;
it was better on p95 for both methods on 148/150 images. Therefore 3000 px remains
the fixed high-quality geometry-analysis width. AKAZE remains the default because of
its speed/quality balance; SIFT remains the manual alternative.

## Deviation / near / far analysis width

150-image comparison against the existing Cosima reference values:

| Method | Mean absolute difference vs Cosima | Median | Correlation | within ±3‰ | within ±5‰ |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1500 px P1/P99 | 2.10‰ | 1.45‰ | 0.91 | 112/150 | 139/150 |
| 2000 px P1/P99 | 2.02‰ | 1.42‰ | 0.91 | 113/150 | 139/150 |

1500 px was effectively equivalent to 2000 px for the intended robust P1/P99
measurement while being faster. It therefore remains the fixed disparity-analysis
width for StereoFine 1.0.

The comparison is a practical reference, not proof that Cosima is ground truth.
Several larger differences were manually checked and StereoFine's robust measurement
was found more plausible.

## Manual discrepancy validation

Known manually inspected cases included Bild126, Bild164, Bild077 and Bild122.
For Bild126 the far point was the tip of a tower on a bridge. A manually positioned
floating measurement/window of about 18‰ matched the visible half-image separation
at that point and supported StereoFine's P1/P99 result of about 17.8‰ rather than the
approximately 40‰ Cosima value. The other named discrepancy cases were likewise
visually checked and did not provide evidence that StereoFine's P1/P99 result should
be replaced by the Cosima value.

## Current regression reference

`assets/stereofine.jpg` is a SplatTricia-generated Full-SBS reference with a nominal
20‰ total deviation. The current modular StereoFine core measures about 19.8‰ on this
image. Since the source is already geometrically clean, the model selector should not
promote unnecessary projective/yQuad corrections merely because they are available.

## Consequence for 1.0

- Geometry analysis width: 3000 px.
- Disparity/near/far analysis width: 1500 px.
- Main disparity estimate: robust P1/P99.
- Do not re-open these choices without a concrete regression or a better controlled
  benchmark.
- Cosima remains a useful comparison/reference tool, not an unquestioned ground truth.

## Final 1.0 release regression

Numerical core regression repeated on 2026-09-07 using the 6314×2160 `assets/stereofine.jpg` master:

| Method | Selected model | Mean vertical residual | Total deviation | Auto-framed near point |
| --- | --- | ---: | ---: | ---: |
| AKAZE | Affine | 0.10198 px | 19.833‰ | about -3.17‰ |
| SIFT | Affine | 0.07845 px | 19.833‰ | about -3.17‰ |

Both methods therefore retain the expected simple model and independently reproduce the nominal 20‰ SplatTricia reference very closely.

The current post-handoff source-level regression on 2026-09-07 passes 76 automated unit/integration/release-hygiene tests plus full AST/compile checks and the complete StereoFine module import sweep in the clean build environment. The protected alignment, disparity, geometry, framing, rendering, color-transfer, processing, anaglyph, export, sidecar, session and state modules remain byte-identical to the handoff checkpoint. The critical rendered Windows regression was exercised interactively on the release-candidate lineage; the user confirmed that Floating Window curtains are again visibly adjustable in the preview after the preview-bound fix. The final locally built Windows ZIP should still receive the short smoke checklist after extraction before it is mirrored to additional download locations.

The Floating Window audit no longer accepts reconstructed or additional preview mechanisms. The current candidate keeps the established v41 data flow: the authoritative preview pair itself contains the Floating-Window masks and StereoFine's normal current anaglyph mixer is then built from that pair. The actual regression was in the modular preview geometry: only 40 px total were reserved before a dynamic black border of 3% + 2 px per side was applied, which could clip the complete outer 30‰ Floating-Window area on screen. The preview bounds now reserve the documented dynamic border outside the image before scaling. No extra black-overlay layer, alternate preview mixer or separate unmasked Floating-Window hotpath remains.

The post-handoff GUI fixes are limited to verified user-visible regressions and agreed wording: the grid-spacing menu remains usable when the grid is Off, status widgets are updated in place instead of being destroyed/recreated during key repeats and sidecar saves, F1 help uses a larger desktop-friendly window, and the status label is `Vergenz (Trapezkorrektur)` / `Vergence (trapezoid correction)` while the compact report retains `Vergenz` / `Vergence`.

The short final Windows smoke checklist remains the release-packaging check for the self-built executable: complete G cycle, all four `L/R/T/B` Floating-Window edges with real key events and visible preview response, absence of status/footer flicker, F1 layout, spinner rendering, start/cancel state, batch progress and exactly one completion sound.

The final integration regression also covers the real batch-state failures found during Windows testing: progress identity (`n/N` and filename) advances on every worker progress event even when no lightweight preview frame is present; successful save/batch/analysis completion produces exactly one `ready.wav` notification with no native success-dialog chime; and the analysis-only report is a compact aligned user table containing only traffic light, deviation, near/far point, mean vertical error, Vergence, rotation and the uncertainty note when needed.
