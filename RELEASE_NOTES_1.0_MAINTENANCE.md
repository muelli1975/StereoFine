# StereoFine 1.0 – Quality update, 20 October 2026

This maintenance update replaces the existing StereoFine 1.0 downloads. The
application version, program name and archive names remain 1.0. The separate
1.1 RC3 packages are unchanged.

- “Original” preserves the aspect ratio of the oriented input images during
  alignment and export, instead of using the already reduced common crop.
- Inputs that would share an output or sidecar name are detected before
  processing and reported clearly.
- TIFF orientation is no longer applied twice. All eight EXIF orientations
  are covered for 8/16-bit input and different channel layouts/compressions.
  Outdated automatic analyses are invalidated; applicable manual edits and
  favorites are retained for unchanged source files.
- Integer color transfer and the largest common valid rectangle calculation
  are faster while retaining identical results.
- SIFT uses a memory-bounded exact distance calculation for quantized OpenCV
  descriptors, retaining the same ratio test and matches. Other descriptor
  formats continue to use the previous matcher.
- Windows instructions use the actual archive name,
  `StereoFine_1.0_Windows_x64.zip`. The program folder is `StereoFine` and the
  executable is `StereoFine.exe`, without version or architecture suffixes.
- Every platform package contains a source snapshot taken before the build
  and verified against raw Git blobs, including on Windows EOL checkouts.

The alignment models, model selection and near-point calculations remain those
of 1.0. The additional alignment/near-point changes in the 1.1 prerelease and
experimental subpixel, LightGlue and RoMa methods are not included. Known limits
in difficult border regions and near-point measurements are not generally
resolved by this update. Controls, sliders, original assets and CPU operation
are retained; no additional models or GPU are required.

## Validation

The maintenance build passed 101 automated tests, German and English GUI smoke
tests under Linux, and Windows, Linux and both macOS builds. Source files and
original assets were verified byte-for-byte in all four native packages before
publication. Practical Windows validation with the original photographs is still
pending; macOS/Linux remain unvalidated on real desktops.

## Windows download

Download [StereoFine_1.0_Windows_x64.zip](https://github.com/muelli1975/StereoFine/releases/download/v1.0/StereoFine_1.0_Windows_x64.zip),
extract the complete archive, open the `StereoFine` folder and start
`StereoFine.exe`. `Source/SOURCE_COMMIT.txt` identifies the exact source
revision included in the build.

Previous release source revision: `83e7fb4526df841aaddfc952f27e5b178bd184a9`.
This maintenance update does not guarantee flawless automatic alignment of
every possible subject.
