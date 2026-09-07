# StereoFine 1.0 – release checklist

## Automated source checks

- [ ] `APP_VERSION` is exactly `1.0`.
- [ ] `python -m unittest discover -s tests -p "test_*.py"` passes.
- [ ] `compileall` passes.
- [ ] all `stereofine` modules import successfully.
- [ ] no runtime `TODO`, `FIXME`, debug prints or development version labels remain.
- [ ] new `.sfin` sidecars contain no obsolete window-position fields or localized GUI prose.

## Validated StereoFine baselines

- [ ] geometry analysis remains max. 3000 px.
- [ ] disparity analysis remains max. 1500 px with robust P1/P99 as the primary range.
- [ ] automatic near-point framing remains 3‰ behind the stereo window when the analysis is reliable.
- [ ] Floating Window remains mask-only and does not affect deviation.
- [ ] the nominal 20‰ SplatTricia reference remains about 19.8‰ and stays on the simple Affine model.

## Windows build

- [ ] build was created with `build_windows.ps1` on Windows x64 / Python 3.12.10.
- [ ] `StereoFine.exe` starts from the extracted portable folder.
- [ ] icon is correct in Explorer/title bar/taskbar.
- [ ] German and English GUI are readable without clipping.
- [ ] the two subtle separators around the scroll area are visible.
- [ ] one real pair or Full-SBS aligns and saves correctly.
- [ ] the single primary button becomes `Abbrechen` / `Cancel` while work is running and returns to the correct start action after success, cancellation or error.
- [ ] cancelling a source load does not leave source index/collection and visible preview out of sync.
- [ ] start-button rest/hover/disabled states match the SplatTricia family styling.
- [ ] activity spinner shows a closed base ring without a visible seam; the moving segment has even thickness and no endpoint bumps.
- [ ] the complete `G` keyboard cycle stays synchronized with Off/White/Black and the grid-spacing menu; the spacing menu remains usable after the cycle returns to Off.
- [ ] `L/R/T/B` + arrows change the Floating Window visibly and immediately; `S` changes only coupling; a 30‰ curtain remains fully visible inside the image while the pure-black `3% + 2 px` border stays outside it.
- [ ] the current projective Vergence stage is shown as `Vergenz (Trapezkorrektur)` / `Vergence (trapezoid correction)` with the actual applied correction magnitude; legacy V/H values appear only for genuine legacy sidecars, and live/reloaded `.sfin` status remains consistent.
- [ ] batch status advances through every source (`n/N` and filename) independently of whether a lightweight preview frame is available.
- [ ] successful save, analysis-only batch and image-output batch each produce exactly one completion notification; no extra native Windows info-dialog tone is emitted.
- [ ] `stereofine_analysis.txt` is the compact aligned quality table (Ampel, Deviation, Nahpunkt, Fernpunkt, Höhenfehler, Vergenz, Rotation, optional uncertainty note) with no technical match/inlier/model ballast.
- [ ] F1 help is a clean, aligned two-column key/function table and fits without scrolling.
- [ ] `ready.wav` works after success and not after cancel/error; Windows uses `winsound`, macOS `afplay`, Linux `paplay`/`pw-play`/`aplay` when available.
- [ ] bundled ExifTool copies metadata without a warning.
- [ ] `Source/` is present in the portable folder.
- [ ] `LICENSE.txt`, third-party notices and runtime license files are present.

## GitHub release

- [ ] repository contains the exact 1.0 source.
- [ ] tag/release is named `1.0` (or `v1.0` if that is the repository convention).
- [ ] upload `StereoFine_1.0.zip` from `release/`.
- [ ] copy SHA-256 from `release/SHA256SUMS.txt` into the release notes.
- [ ] use `RELEASE_NOTES_1.0.md` as the starting release text.
