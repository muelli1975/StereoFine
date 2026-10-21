# StereoFine 1.1 release checklist

The source identifies itself as `1.1`. A completed source test is
not evidence that a Windows/macOS/Linux package has passed. Record results for
the exact final source commit and archive hashes.

## Source validation

- [x] Run application regressions and research safety/synthetic geometry tests.
- [x] Run `compileall`, import all runtime modules, and verify `assets/ASSET_HASHES.txt`.
- [x] Confirm README.md and README_EN.md agree; update README_DE.md consistently.
- [x] Confirm no runtime TODO/FIXME, obsolete cache assumptions or duplicated measurement implementations remain.
- [x] Reproduce the original-image comparison in `docs/OBSERVED_RANGE_1.1.md`; retain uncertainty where completeness is unproven.
- [x] Recheck the nominal 20-permille reference: 19.625 permille in the current baseline, simple Affine, unchanged render and session reload.
- [x] Verify migration from older disparity caches retains manual adjustments and favorites.

## Preserved behavior

- [x] Geometry/disparity primary widths remain 3000/1500 pixels per eye.
- [x] Additional 1000-pixel evidence is conditional; it does not replace the primary baseline for confirmed cases.
- [x] Near framing keeps its measurement reserve and additional 3-permille window allowance.
- [x] Floating Window masks and color adjustments do not affect disparity analysis.
- [x] Existing GUI keyboard, cancellation, batch progress, DE/EN layout and single completion-sound regressions pass.
- [x] Saving produces both SBS and anaglyph JPEGs; original assets and photographs remain byte-identical.

## Final metadata and candidate build

- [x] After source validation, set APP_VERSION, Windows FileVersion and ProductVersion to `1.1`; clear Windows prerelease flags.
- [ ] Commit the exact reviewed sources. Packaging rejects dirty source snapshots and inconsistent final metadata.
- [ ] Run `prepare-release.yml` on that commit. It reuses source/platform validation and never creates tags or releases.
- [ ] All three source-test platforms and all four package targets pass.
- [ ] Actual packaged `--check-inputs` passes for raster/HEIF/Spatial Photo/orientation, metadata export, session reuse and rendering.
- [ ] No HEIF codec is linked into the main executable; separate helper, sources, ExifTool and licenses are present.
- [ ] Canonical `Source/` matches the exact commit, including Windows line-ending-independent bytes.
- [ ] Extract each archive and check application startup, icon, DE/EN interface and one save on the corresponding system.
- [ ] Candidate archive set matches `scripts/release_checksums.py`; its verified four-file SHA256SUMS.txt is available.

## Publication

- [ ] Replace draft status in `RELEASE_NOTES_1.1.md` with actual validation results and SHA-256 values.
- [ ] Update English/default and German README download links to the actual 1.1 archives.
- [ ] Verify release/tag naming against the repository's existing convention (`v1.1-rc3` for RC3).
- [ ] Publish only the verified final commit and archives; preserve historical RC3 and 1.0 downloads.

The archived `build-release.yml` remains disabled. `build_windows.ps1` is an
alternative Windows build, not the four-platform final-candidate route.
