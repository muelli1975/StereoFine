# JPS/PNS input for StereoFine 1.1

Status: implemented on the 1.1 image-format development branch, not included in
the published RC3 packages. No new release was created for this change.

## Supported paths

- `.jps` is accepted through the existing JPEG reader.
- `.pns` is accepted through the existing PNG reader, including 16-bit RGB data.
- Packed Full-SBS sources use the existing Full-SBS/MPO entry point.
- Separate eye images use the existing `_l`/`_r` or `l`/`r` discovery paths.
- Both German and English file dialogs derive their filters from the supported
  extension sets, so registration and file selection remain consistent.

The extension does not choose an eye order, infer a packed layout, unpack
Over/Under or decode JPS-specific stereo-layout metadata. The explicitly chosen
Full-SBS workflow retains its existing left-half/right-half interpretation.
Inspect eye assignment and use Swap L/R when appropriate. These are additional
file extensions for the established input paths, not automatic recognition of
every possible stereo arrangement stored in JPEG or PNG.

## Preserved behavior

Existing JPEG/PNG/TIFF decoding, EXIF orientation, master bit depth, source
fingerprints, collision protection and `.sfin` source contracts are retained.
No changes to alignment, model selection, near-point measurement, framing,
color processing, export formats, sliders or interaction layout.

Since existing image pixels and source interpretation are unchanged, this
extension does not require invalidating analyses of existing JPEG/PNG/TIFF/MPO
sources. New JPS/PNS sources use the established source fingerprints and sidecar
schema; no new transformation model is stored.

## Validation

146 production tests passed. Seven added tests cover:

- identical JPEG pixels and explicit eye order through the actual JPS source loader;
- all eight JPEG EXIF orientations under the JPS extension;
- exact native 16-bit samples in packed PNS input;
- discovery and eye assignment of separate PNS suffix pairs;
- filename/sidecar collision protection across PNG/PNS aliases;
- real PNS sidecar save/load preserving eye swap, manual edits and favorites;
- complete extension coverage in both localized input-dialog filters.

Compilation and English README parity were checked. These are automated Linux
checks, not a new packaged Windows/macOS validation. Release titles, notes and
the public changelog remain English; localized README files stay separate.
