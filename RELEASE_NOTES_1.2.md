# StereoFine 1.2

- **Compact status panel:** Aligned values, stable row positions and a fixed warning area keep the status readable at normal and enlarged display scales. Long input names have a full-filename tooltip.
- **Final-crop deviation:** After automatic stereo-window framing, deviation and confidence are measured on the finished selected crop. Earlier pre-framing measurements are refreshed while saved framing and manual edits are retained. Batch status now shows the measurements belonging to the current progress image.
- **Safer processing:** Source files and distinct batch outputs are protected from filename collisions. A source changed since loading must be reopened before saving; cancelled or failed analysis does not replace saved adjustments.
- **Smoother preview updates:** Preview and output share the same master crop. Completed colour updates survive saving, native pixels are reused after viewport changes, and colour fitting uses less temporary memory.

- **Lossless TIFF SBS:** An optional checkbox under Image and output saves a losslessly compressed TIFF with automatic 8- or 16-bit depth per channel. Mixed-depth pairs use 16 bits. The choice is remembered for single-image and batch exports.
- **Native 100% inspection:** Hold **Z** to inspect corrected image pixels at their actual screen size. Use the arrow keys to pan both eyes together, with fine taps and smooth acceleration when held. Release **Z** to return to the fitted preview. The view remembers its position for the current image without changing alignment or crop.
- **Consistent colour:** Preview and export share colour matching based on the final crop. Sampling covers the entire image. Working ICC profiles are retained in TIFF; previews and JPEG outputs use sRGB.
- **Reliable saved adjustments:** Failed sidecar writes keep edits in memory, show an error and prevent export or navigation from silently using older settings.
- **Cross-view JPEG quality:** Cross-view exports use quality **90**, with **4:4:4** sampling. Anaglyphs remain JPEG quality 90 and ordinary SBS JPEGs remain quality 95.

- **Stable preview controls:** Colour matching toggles retain the same master crop. Held arrows remain protected after releasing M or a floating-window key; interrupted work resumes the latest preview. Fixed black/white curve anchors also apply to existing saved curves.
- **Steady view after saving:** Saving directly after a fresh alignment retains the displayed preview without a temporary zoom change.
- **Stable status layout:** Status rows retain their positions when switching aspect ratios or recalculating near and far points, including at enlarged display scales.
- **Responsive inspection and editing:** Z opens the native view immediately after fullscreen changes. Existing colour matching remains visible during crop and manual-offset edits while the updated crop is calculated.
- **Initial defaults:** Original aspect ratio and enabled symmetric colour matching for new settings. Existing preferences and saved image adjustments keep their chosen values.

- **Output preferences:** Anaglyph saving can be switched off independently of the preview; its indented grayscale choice is retained. An editable SBS suffix list includes m.objects, COSIMA and Bino naming conventions. The standard `_sbs` suffix applies when the custom-suffix checkbox is off. Both preferences are remembered for single-image and batch exports.

The compact keyboard workflow and existing stereo alignment and deviation methods are retained. See the English or German README for controls and platform requirements.
