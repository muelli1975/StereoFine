# StereoFine 1.3 implementation scope

The active development build adds the agreed N/F preview checkbox and D shortcut, view-only mouse zoom, an anaglyph two-click meter, LUT import and 50 looks in six groups, and Restore defaults below the preview options. The input guide is called Controls (Bedienhilfe in German).

The parallel-view preview, LoMa research and another ORB trial are outside this round. A stereo copy/retouching tool remains a separate future design topic. A double-click fits a magnified view.

The existing geometry correction stays in 1.3. The [vergence pilot](VERGENCE_SEED_PILOT_1.3.md) retained it in all 56 runs on the available original pairs.

Custom output folder and the selected folder mode survive Restore defaults. Sidecars preserve LUT enablement, identity/path and strength; view zoom is transient and does not alter framing. Existing image adjustments remain compatible.

The individual LUT sources and terms are documented in the catalog. Windows native controls, image-coordinate measurements, both master depths and previous processing behaviour are validated before packaging. macOS/Linux desktop checks remain separate from the local Windows tests.
