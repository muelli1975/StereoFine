# StereoFine 1.4

- **Faster browsing.** StereoFine prepares the previous and next previews in the background so you can move through a folder more quickly in either direction.
- **Faster batch processing.** StereoFine can analyse several stereo pairs in parallel. In a Linux benchmark with fresh analysis and JPEG export, median batch time fell from 19.9 to 15.1 seconds (24% less time), with identical measurements and JPEGs.
- **Exposure correction.** Adjust both eyes together from −2 to +2 EV. Apply the adjustment to one stereo pair or to a whole folder. The source files are preserved.
- **Horizon and vertical perspective.** Press **H** to straighten the horizon or correct converging verticals in the stereo preview. The on-screen hint shows how to apply with **Enter** or discard with **Esc** or **H**. Applying the correction realigns the pair and retains your inspection zoom. Outside H mode, **Ctrl+R** removes a saved correction and realigns the pair.
- **Preview and LUT controls.** Switch directly between cross-view and your last anaglyph view, and browse LUTs or adjust their strength from the keyboard.
- **Measurement cross.** Scale ticks and labels now clip correctly at the preview edge, including in a zoomed view.

## Maintenance update

- **Near and far markers.** StereoFine shows a marker only when it can verify the position in both views. When the measured endpoint is refined, the marker follows the verified position.
- **Batch folders.** StereoFine rescans the selected folder when a batch starts, including after a cancellation.
