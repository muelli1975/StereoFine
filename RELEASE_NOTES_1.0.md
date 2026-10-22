# StereoFine 1.0

Automatically align, check and export stereoscopic image pairs, with manual fine adjustments, cropping and floating-window masks.

## Fixes and improvements

- Preserve the input aspect ratio when using Original size.
- Detect conflicting output and sidecar filenames before processing.
- Correct TIFF orientation handling.
- Speed up colour matching, common-crop calculation and feature matching.

## Installation

Extract the complete package for your system into a writable folder. Start `StereoFine.exe` on Windows, `StereoFine` on Linux or `StereoFine.app` on macOS. Keep the supplied tools and application files together. No separate Python installation is required. Linux/macOS metadata transfer requires Perl.

Keep `settings.json` and saved image adjustments when updating. Automatic alignment and near-point measurements can remain uncertain for difficult subjects.
