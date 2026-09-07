# StereoFine 1.0

StereoFine 1.0 is the first stable public release of the stereoscopic image alignment and inspection tool.

The release focuses on a compact practical workflow rather than a large toolbox: automatic alignment, robust deviation/near/far analysis, automatic near-point framing, optional manual refinement, Floating Window masks, symmetric color matching and reproducible `.sfin` sidecars for later batch output.

For image quality, the selected affine, Vergence/Trapezoid and Y-Polish geometry is composed into one mapping and each half-image is resampled only once with high-quality Lanczos interpolation.

## Portable Windows release

Download `StereoFine_1.0.zip`, extract the complete folder and start `StereoFine.exe`. No separate Python installation is required.

## Deliberate scope

StereoFine 1.0 supports JPEG, PNG, TIFF, MPO and Full-SBS workflows. HEIC/HEIF and RAW are intentionally not included. Output is always an SBS JPEG plus one anaglyph JPEG; the anaglyph can be color or grayscale.

## License

StereoFine source and original documentation: MIT License. Third-party components remain under their own licenses; see the included notices.

## Additional platform builds

GitHub Actions also produces macOS Apple Silicon, macOS Intel and Linux x64 packages from the exact same 1.0 source. Windows is the reference-tested release platform. The macOS/Linux packages are automatically built but should be regarded as unverified on real desktops until platform smoke tests have been completed. They include the official ExifTool Perl distribution locally; metadata handling on macOS/Linux therefore expects a working Perl interpreter on the target system.
