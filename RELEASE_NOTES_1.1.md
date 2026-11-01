# StereoFine 1.1

- Improve automatic alignment, vertical edge correction and near/far measurements.
- Mark uncertain depth measurements more clearly and add a measurement cross for manual checking.
- Add JPS/PNS, static WebP/BMP and supported SDR HEIC/HEIF inputs, including stereo images and Spatial Photos.
- Recalculate outdated analyses while preserving saved fine adjustments during Save and batch processing.
- Make the measurement-cross preview smoother.
- Fix the dark Windows titlebar after leaving fullscreen.
- Restore arrow-key editing after a held-key release is missed while switching windows or opening a dialog.
- Add the optional **Deviation in filename** checkbox: for example, `_057_sbs.jpg` and `_057_anaglyph.jpg` for 57 permille, with `_uncertain` after uncertain estimates. The option is off by default.

## Installation

Extract the complete package for your system into a writable folder. Start `StereoFine.exe` on Windows, `StereoFine` on Linux or `StereoFine.app` on macOS. Keep the supplied tools and application files together. No separate Python installation is required. Linux/macOS metadata transfer requires Perl.

Keep `settings.json` and saved image adjustments when updating. Outdated automatic measurements are recalculated. Automatic alignment and depth measurements can remain uncertain for difficult subjects.

See [supported input formats](https://github.com/muelli1975/StereoFine/blob/main/docs/IMAGE_FORMATS_1.1.md) and [measurement limitations](https://github.com/muelli1975/StereoFine/blob/main/docs/OBSERVED_RANGE_1.1.md).
