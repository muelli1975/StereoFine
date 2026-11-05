# StereoFine 1.2

- **Lossless TIFF SBS:** An optional checkbox under Image and output saves a losslessly compressed TIFF with automatic 8- or 16-bit depth per channel. Mixed-depth pairs use 16 bits. The choice is remembered for single-image and batch exports.
- **Native 100% inspection:** Hold **Z** to inspect corrected image pixels at their actual screen size. Use the arrow keys to pan both eyes together in fixed steps. Release **Z** to return to the fitted preview. The view remembers its position for the current image without changing alignment or crop.
- **Consistent colour:** Preview and export share colour matching based on the final crop. Sampling covers the entire image. Working ICC profiles are retained in TIFF; previews and JPEG outputs use sRGB.
- **Reliable saved adjustments:** Failed sidecar writes keep edits in memory, show an error and prevent export or navigation from silently using older settings.
- **Cross-view JPEG quality:** Cross-view exports use quality **90**, with **4:4:4** sampling. Anaglyphs remain JPEG quality 90 and ordinary SBS JPEGs remain quality 95.

The compact keyboard workflow and existing stereo alignment and deviation methods are retained. See the English or German README for controls and platform requirements.
