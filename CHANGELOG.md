# Changelog

## 1.4

- Straighten the horizon and correct vertical perspective with **H** in the current stereo preview. Use the arrow keys to adjust, **Enter** to realign the pair, and **Esc** to discard the draft. **Ctrl+R** resets a saved correction and realigns the pair.
- Retain inspection zoom when realigning the current pair.
- Prepare neighbouring previews in both directions while browsing.
- Analyse several pairs in parallel in batch mode when resources allow.
- Adjust exposure from **−2 to +2 EV** per pair or apply the current exposure to a folder.
- Press **X** to switch between cross-view and the last anaglyph preview. Hold **C** with **Left/Right** to browse LUTs in a loop or with **Up/Down** to adjust strength in five-percentage-point steps.
- Hold **Shift** to adjust exposure and LUT strength with the mouse wheel.

## 1.3 – 2026-11-07

- Add independent mouse/keyboard view zoom and middle-button panning.
- Add optional near/far point overlays and an anaglyph-only two-click disparity meter.
- Add 50 built-in Cube looks in six groups, custom Cube/HaldCLUT import, and 0-100% strength, retained per image.
- Preview a LUT on hover and optionally apply aspect, LUT and colour matching to a folder.
- Toggle LUTs with C and switch looks with C held and the Left or Right arrow. Show the selected name in the preview and clear stored LUT choices when applying a disabled LUT to a folder.
- Filter browsing by favorites and save folder orientation in `orientation.json`.
- Add Restore defaults while retaining the output destination and language.
- Fit a magnified view by double-clicking. Clarify fit, Escape and right-click actions in the bilingual Controls guide.
- Rotate local diagnostic logs and match displayed near/far values to the status display.

## 1.2 – 2026-11-05 (updated 2026-11-06)

- Base the automatic 3-permille stereo-window reserve on the final half-image width after overlap and the selected aspect/crop zoom, using the smallest sufficient whole-pixel shift. Retain independent displayed measurements and existing saved framing.

- Add optional lossless TIFF SBS output with automatic 8/16-bit depth and working ICC profiles.
- Add momentary native 100% inspection with Z, fine arrow-key taps and smooth acceleration when held.
- Use final-crop colour matching consistently in preview and output; sample the entire image.
- Retain edits after sidecar write failures and block transitions that would read old settings.
- Save cross-view JPEGs at quality 90 with 4:4:4 sampling.
- Keep the master crop stable when toggling colour matching and recover pending previews after interrupted work.
- Keep the preview steady when saving directly after a fresh alignment.
- Keep status rows in place during aspect changes and deviation calculations.
- Show native inspection on the first Z press after fullscreen or window-size changes.
- Retain prepared colour matching throughout crop and manual-offset edits while the new crop fit is calculated.
- Prevent held arrows from changing alignment after releasing the measurement or floating-window key.
- Preserve fixed black/white curve endpoints, including when reusing existing saved curves.
- Default new settings to Original aspect ratio and enabled symmetric colour matching, retaining saved choices.
- Add remembered anaglyph saving and an editable Full-SBS suffix list with program-specific presets.
- Keep loaded-settings status concise without exposing internal calculation-version differences.
- Protect source files and distinct batch outputs from filename collisions while retaining replacement of existing exports.
- Commit single-image analysis only after its preview is ready; reject saving an externally changed source until it is reopened.
- Share the master crop geometry with interactive previews and retain completed colour updates after saving.
- Reuse native pixels on viewport changes and reduce colour-fit allocations without changing the fitted curves.
- Make the status panel more compact with aligned values, fixed warning space.
- Measure deviation and confidence on the final selected crop after automatic stereo-window framing; refresh older pre-framing measurements without replacing saved edits.
- Show per-image batch measurements and clear the previous image's values while the next image is being analyzed.


## 1.1 — 2026-10-21 (updated 2026-11-01)

- Clear transient held-key modes when the main window loses focus or is hidden, restoring manual arrow-key editing after a missed key release.
- Add an optional, persistent total-deviation suffix in whole permille, such as `_057_sbs.jpg` and `_057_anaglyph.jpg`; use only the number for both confirmed and uncertain estimates and preserve existing filenames by default.

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

