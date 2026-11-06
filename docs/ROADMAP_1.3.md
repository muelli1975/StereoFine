# StereoFine 1.3 ideas

Recorded on 6 November 2026. These are proposals, not implemented features or
final interaction decisions. Release the maintenance update to 1.2 first.

## First topic: near and far overlays

- A toggle shows **N** at the near-point candidate and **F** at the far-point
  candidate, including uncertain estimates. Choose the shortcut together.
- Keep the image easy to inspect: small outlined labels, readable on bright
  and dark subjects. Distinguish uncertain candidates with a hollow or dashed
  marker, while retaining the status warning.
- Check which verified image coordinates support each endpoint. A statistical
  endpoint or safety margin must not be presented as an exact located pixel.
  If a usable location is unavailable, say so instead of inventing a marker.
- Optionally add a horizontal deviation bracket with short vertical end caps.
  Decide whether it belongs beside a matched feature or in a small screen
  overlay. A bracket of arbitrary length must not imply a measured disparity.
- Use the final-crop coordinate system in fitted and native views. Keep overlays
  out of image exports by default.

## Mouse interaction

- Mouse wheel for zoom, with an explicit decision between inspection zoom and
  output-crop zoom. Avoid silently changing the exported crop.
- Hold right or middle mouse to pan the view; define separately whether an
  optional modifier moves the output crop.
- Left mouse may position the measurement cross, turn the cursor into the
  cross, or measure disparity with two clicks on corresponding features.
- Retain keyboard controls and avoid conflicts with sliders and scrolling.

## Local stereo retouching

Consider an SPM-style copy tool that transfers a selected region from one eye
to the other to remove local disturbances. Define source eye, destination eye,
correspondence/offset and feathering explicitly. Discuss undo, a before/after
view, reproducible saved edits, and how edited regions affect measurement and
colour matching. Original source images must remain unchanged.

## Defaults, LUTs and viewing modes

- Add a Restore defaults button analogous to SplatTricia. First agree which
  settings it resets and how it differs from the existing Ctrl+R image reset.
- Optional user-loaded LUTs, especially for low-contrast Fuji W3 images. Discuss
  `.cube` support, neutral default, shared application to both eyes, processing
  order relative to colour matching, and consistent preview/export behaviour.
- Full-colour stereo previews provide the clearest view of a LUT's appearance.
  Decide whether anaglyph previews show the same graded pair before the
  anaglyph conversion, and explain their limits for judging colour.
- Consider adding parallel-view preview, with **II** and **X** as compact menu
  choices. Decide how they integrate with the existing preview cycle.

No research-mode disparity changes or relaxed uncertainty thresholds are part
of the 1.2 maintenance update.
