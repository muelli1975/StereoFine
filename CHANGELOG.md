# Changelog

## 1.1 — 2026-10-21

- Improve automatic alignment, vertical edge correction and near/far measurements.
- Mark uncertain depth measurements more clearly and add a measurement cross for manual checking.
- Add JPS/PNS, static WebP/BMP and supported SDR HEIC/HEIF inputs, including stereo images and Spatial Photos.
- Recalculate outdated analyses while preserving saved fine adjustments during Save and batch processing.
- Make the measurement-cross preview smoother.
- Fix the dark Windows titlebar after leaving fullscreen.

## 1.1-rc3 – 2026-10-20 (prerelease)

- Read canonical source blobs directly; git archive also applies Windows autocrlf conversion.
- Verify source byte identity independently of checkout line endings; image processing unchanged.

## 1.1-rc2 – 2026-10-20 (prerelease)

- Snapshot clean source inputs before PyInstaller can replace generated build files.
- Preserve exact repository sources in every platform archive; image processing unchanged from RC1.

## 1.1-rc1 – 2026-10-20 (prerelease)

- Robust spatial model selection and independently checked nonlinear inlier recovery.
- Bounded cubic vertical edge correction with blocked validation and explicit corner checks.
- Confirmed foreground near points and improved physical-rim coverage.
- Exact batched SIFT matching, TIFF orientation/cache migration and the four maintenance corrections.
- See RELEASE_NOTES_1.1-rc1.md and docs/VALIDATION_1.1_RC1.md for scope and validation.

## 1.0 – Quality update, 2026-10-20

- Correct TIFF orientation for 8/16-bit input, original aspect ratio and input/output name collisions.
- Accelerate integer color transfer, valid-rectangle calculation and exact SIFT distances while retaining identical results.
- Preserve canonical source bytes before building and document the actual Windows filenames.
- Keep version and archive names at 1.0; retain existing alignment and near-point procedures.

## 1.0 – 2026-09-07

Initial public release.

Highlights:

- automatic stereo alignment with conservative Affine / Vergence / Y-Polish model selection;
- separate robust near/far/deviation analysis;
- automatic 3‰ near-point framing;
- manual fine alignment, crop and Floating Window masks;
- optional symmetric color matching;
- Full-SBS, MPO and separate Left/Right input workflows;
- reusable `.sfin` sidecars;
- analysis-only batch reports and favorites-only export;
- color and grayscale anaglyph output;
- German and English GUI;
- portable Windows onedir release with bundled ExifTool;
- MIT-licensed StereoFine source with separate third-party license material.
- final Windows-facing GUI regression fixes: structurally unobstructed activity ring, v41-style immediate Floating Window preview, and save completion using only `ready.wav` without an additional native info-dialog tone;
- post-handoff GUI cleanup: grid spacing remains editable after the keyboard cycle returns to Off; status values update in place to prevent footer/status flicker; F1 help uses a larger desktop-friendly window; preview sizing now reserves the documented dynamic 3% + 2 px black border outside the image so the full 30‰ Floating Window remains visible;
- spinner moving segment uses an even-width arc without oversized endpoint caps;
- Vergence status no longer exposes compatibility `V 0.000 / H 0.000` placeholders; the current projective Vergence stage reports the magnitude of the correction actually applied and preserves it across `.sfin` reloads;
- F1 keyboard help is rendered as a real typographic key/function table.
- sidebar mouse-wheel scrolling uses CustomTkinter's native single scroll path again; the redundant competing global StereoFine wheel forwarder was removed.

- batch progress status now follows every processed source even when a lightweight preview frame is unavailable;
- successful save/batch/analysis completion produces one `ready.wav` notification and no additional native Windows information-dialog chime;
- analysis-only report reduced to a readable aligned quality table: traffic light, deviation, near/far point, vertical error, Vergence, rotation and uncertainty note.
