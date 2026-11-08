# StereoFine 1.3

- View zoom with Ctrl+wheel or Ctrl+Plus/Minus and middle-button panning. The fitted-view label stays visible briefly when the wheel reaches the fit limit. Ctrl+0 fits the view. Double-click also fits a zoomed view outside measurement mode. Esc closes an open menu, help or the measurement tool. Otherwise it fits a zoomed view or leaves fullscreen when already fitted.
- Optional near/far point labels under Preview, also toggled with D. Labels show the status values, including decimal commas in German and decimal points in English. Crosses mark the image evidence and question marks identify uncertain locations.
- An anaglyph-only two-click disparity meter in the right-click menu. Points are stored in image coordinates while measuring, so view zoom does not change the measured distance.
- The release includes 50 built-in Cube looks in six groups, plus import of 3D .cube and square HaldCLUT .png files. A 0-100% strength slider applies the same look to both eyes before floating-window masks and anaglyph conversion. LUT selection, strength and custom path are retained in .sfin.
- Hover over a LUT to preview it and click to apply it. Press C to toggle the LUT, or hold C and press Left or Right to switch looks. The selected name appears briefly in the preview.
- Apply to folder independently saves aspect ratio, LUT and strength, and symmetric colour matching across the recognised stereo images. Applying with the LUT switched off clears the per-image LUT entries so images can follow the current default. The dialog shows progress and keeps completed changes when cancelled.
- Save as folder orientation under Alignment to share rotation, mirroring and eye order in `orientation.json`. Individual image orientations take precedence. Save an existing folder orientation again to use the new filename.
- Use **Show favorites only** beside the Controls link to browse marked images. The batch export filter is a separate control.
- Restore defaults retains the selected output destination and dialog locations. The button is below the preview options. Manual image corrections remain controlled by Ctrl+R.
- The bilingual Controls guide uses up to three columns and adapts to the available screen space.
- Portable diagnostic logs rotate at 2 MiB with two backups and 30-day retention.

Alignment, disparity confidence thresholds, output formats and existing JPEG quality settings are retained. Original input images are never overwritten. Supplied LUT sources and terms are listed in assets/luts/CREDITS.md and THIRD_PARTY_NOTICES.md.
