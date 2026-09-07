# StereoFine 1.0

**[Deutsch](README_DE.md)**

StereoFine is a local desktop tool for automatically aligning, checking, framing and exporting stereoscopic image pairs. It is designed to do as much reliable work automatically as possible without taking manual control away from the user. The interface therefore stays deliberately compact and keyboard-friendly.

StereoFine works completely locally: no account, no cloud, no tracking and no automatic downloads during use.

## Portable Windows release

The published Windows version is portable:

1. Extract the complete `StereoFine_1.0.zip` into a normal writable folder.
2. Start `StereoFine.exe`.
3. Keep the application folder together; `tools`, `_internal` and the other supplied files belong to the application.

The portable version does not require a separate Python installation. Global settings are stored as `settings.json` next to `StereoFine.exe`.

## macOS and Linux builds

The same source can also be packaged for macOS (Apple Silicon and Intel) and Linux x64. GitHub Actions builds these variants from the tagged source. The Windows build is the reference-tested 1.0 platform; macOS/Linux binaries should be treated as platform builds pending a real desktop smoke test on those systems. No stereo, geometry or color-processing code differs between platforms. The platform packages include ExifTool for metadata handling; on macOS/Linux the official ExifTool distribution is Perl-based and therefore expects a working Perl interpreter on the target system. If metadata copying is unavailable, StereoFine keeps the successfully written image and reports a non-fatal warning.

## Quick start

1. Use **Left/Right** to select one image from a stereo pair, or **Full-SBS/MPO** to open a stereo file.
2. Choose **Start alignment**. StereoFine analyzes the geometry, determines near point, far point and total deviation, and frames the detected near point slightly behind the stereo window by default.
3. Check the result in the anaglyph preview and fine-tune it with the keyboard if required.
4. Choose **Save**. StereoFine always writes an SBS JPEG and one anaglyph. The preview choice only determines whether the anaglyph is color or grayscale.

While processing is active, the same primary button becomes **Cancel**; after success, cancellation or error it automatically returns to the appropriate start action.

The same processing core is available for complete folders through batch processing.

## Supported input

Officially supported:

- JPEG/JPG
- PNG
- TIFF/TIF
- MPO
- Full-SBS in JPEG, PNG or TIFF
- separate Left/Right pairs using `*_l` / `*_r`
- separate pairs in `l` and `r` subfolders

HEIC/HEIF and RAW are deliberately outside the scope of StereoFine 1.0 and should be converted first.

16-bit PNG and 16-bit TIFF are not reduced to 8 bit immediately when loaded. StereoFine creates separate 8-bit proxies for feature/disparity analysis and preview. Final JPEG output is deliberately 8 bit.

## Automatic alignment

StereoFine uses a conservative model hierarchy:

- **AKAZE** is the fast default feature method.
- **SIFT** is available as a slower manual alternative.
- A symmetric affine correction handles vertical shift, rotation and relative scale differences.
- A controlled **Vergence/Trapezoid correction** is accepted only when it actually performs better than the simpler model on independent validation points.
- **Y-Polish** can correct remaining vertical residuals, but is likewise used only when it provides a measurable additional benefit.

Geometry analysis uses a maximum width of 3000 px. All selected geometric corrections — affine alignment, Vergence/Trapezoid correction and Y-Polish — are composed into a single mapping. Each half-image is then resampled only once with high-quality Lanczos interpolation, avoiding cumulative interpolation loss from a chain of successive warps.

## Deviation, near point and far point

After geometric correction, StereoFine runs a separate semi-dense horizontal disparity analysis at up to 1500 px width. The main values use robust P1/P99 limits; additional robust ranges are used to assess uncertainty.

The traffic light is practical guidance:

- **green:** up to 33‰ total deviation
- **orange:** above 33‰ up to 40‰
- **red:** above 40‰
- **gray:** measurement unavailable or considered uncertain

These colors are a working aid, not a hard physiological boundary.

### Automatic near-point framing

When the analysis is reliable, StereoFine shifts the pair horizontally so that the detected near point lies at least **3‰ behind the stereo window** by default. Pixel rounding may place it slightly farther back.

`Ctrl+R` restores exactly this automatic state: automatic alignment including the 3‰ near-point framing. Later manual adjustments are discarded.

## Floating Window

Floating Window masks provide a convenient way to correct stereo-window violations without changing the depth or parallax of the scene itself. Adjustable side masks and tilted masks at the top or bottom can bring the perceived stereo-window edge forward where needed — especially when foreground objects intersect an image border. StereoFine lets these masks be adjusted directly in the preview and applies them consistently to the final stereo output.

Left, right, top and bottom values are stored per image in the `.sfin` sidecar.

## Symmetric color matching

Color matching is optional. It does not force one eye to match the other. Instead, robust percentile curves move both half-images toward a shared target state. It remains completely outside geometry and deviation analysis.

Pairs that already match well should remain practically unchanged. The function can be enabled or disabled at any time.

## `.sfin` sidecars

StereoFine stores the reproducible state of an image pair in a small `.sfin` file inside the `_stereofine` subfolder of the input folder. It contains only technically useful state and parameters, including:

- source and validity fingerprint
- automatic correction and analysis basis
- deviation, near point and far point
- automatic near-point framing
- manual X/Y adjustment
- crop and aspect ratio
- Floating Window
- color matching
- favorite state

Technical analysis and uncertainty diagnostics remain available in the sidecar, while the normal analysis report is deliberately limited to the values needed for stereoscopic quality control. Development diagnostics and localized GUI prose are not stored as sidecar ballast. A valid sidecar can be reused in later batch runs. Changed source files or relevant pipeline versions invalidate only the calculations that need to be recomputed.

## Batch processing

StereoFine can automatically process separate pairs or folders containing Full-SBS/MPO files. Single-image and batch work use the same core.

### Analysis only · Text report

StereoFine analyzes the complete folder, creates or updates sidecars and writes `stereofine_analysis.txt`. No SBS or anaglyph images are exported.

The report is a compact aligned text table containing only file, traffic light, total deviation, near point, far point, mean vertical error, vergence and rotation. The note “Estimate uncertain – please check!” is added only when the disparity estimate is genuinely uncertain.

### Export favorites only

A practical review workflow is:

1. Browse a folder in StereoFine.
2. Fine-tune individual pairs when necessary and mark favorites.
3. Later run the complete folder with **Export favorites only** enabled.

Saved `.sfin` states are reused. Non-favorites may still be analyzed, but produce no image output.

## Output and folders

Every image export produces both:

- an SBS JPEG, quality 95
- one color or grayscale anaglyph JPEG, quality 90

Anaglyphs are reduced to a maximum height of 2160 px when needed. Color anaglyph output uses the shared StereoFine/SplatTricia reference pipeline with proper sRGB linearization.

By default StereoFine creates an `output` folder inside the input folder. Alternatively, a persistent custom output folder can be selected. Finished JPEGs and analysis reports are first written completely to temporary files and only then atomically replaced at their final paths.

Existing image outputs with the same name are deliberately replaced.

## Metadata

Where possible, StereoFine copies metadata using the bundled ExifTool. Preview, Orientation and MPF/MPO container metadata are not copied into ordinary SBS/anaglyph JPEG files. If only metadata copying fails, a successfully written image remains valid and StereoFine shows a warning.

## Keyboard

### Navigation

- `Page Up` / `Page Down` – previous / next image
- `Space` – start alignment or batch
- `Enter` – save current image

### Manual alignment

- Arrow keys – shift horizontally/vertically by 1 px
- `Shift` + Arrow – 5 px
- `Ctrl` + Arrow – 10 px
- `Ctrl+R` – restore automatic alignment including 3‰ framing

### Crop

- `Alt` + Arrow – move crop
- `Ctrl+Shift+↑/↓` – zoom

### Floating Window

- `S` – link/separate Left/Right
- hold `L`, `R`, `T` or `B` + `←/→` – change the selected edge by 1‰

### Preview

- `A` – toggle color/grayscale anaglyph
- `G` – cycle grid
- `Shift+G` – grid off
- hold `M` – show measurement cross
- `M` + Arrow keys – move measurement cross
- `F11` – fullscreen
- `F1` – keyboard help
- `Esc` – close fullscreen/help

## Settings and language

Global preferences are stored in `settings.json` next to the portable application. Image-specific state belongs exclusively in `.sfin`.

**Analysis only** and **Export favorites only** are job modes and are not stored as persistent preferences.

The GUI can be switched between German and English. StereoFine terms such as Affine, Vergence, Y-Polish and Deviation remain technically consistent.

## Source and build

The published portable folder contains the exact source used to build `StereoFine.exe` under `Source/`. The same source is intended for the public GitHub repository.

Build instructions are in [BUILD_WINDOWS.md](BUILD_WINDOWS.md). Historical validated analysis baselines are documented in [docs/VALIDATION.md](docs/VALIDATION.md).

## License

StereoFine source code and original documentation created by Christoph are released under the **MIT License**. Third-party components remain explicitly under their respective licenses.

See `LICENSE.txt`, `THIRD_PARTY_NOTICES.md` and `licenses/`.
