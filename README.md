# StereoFine

StereoFine is a local desktop tool for automatically aligning, checking, framing and exporting stereoscopic image pairs. It is designed to do as much reliable work automatically as possible without taking manual control away from the user. The interface therefore stays deliberately compact and keyboard-friendly.

## Portable Windows release

The published Windows version is portable:

1. download and extract the complete `StereoFine_1.0` folder;
2. start `StereoFine.exe`;
3. keep the bundled `tools`, `assets`, `licenses` and `Source` folders beside the executable.

The portable version does not require a separate Python installation. Global settings are stored as `settings.json` next to `StereoFine.exe`.

## macOS and Linux builds

The same source can also be packaged for macOS (Apple Silicon and Intel) and Linux x64. GitHub Actions builds these variants from the tagged source. The Windows build is the reference-tested 1.0 platform; macOS/Linux binaries should be treated as platform builds pending a real desktop smoke test on those systems. No stereo, geometry or color-processing code differs between platforms.

## Stereo workflow

StereoFine 1.0 supports JPEG, PNG, TIFF, MPO and Full-SBS input workflows. HEIC/HEIF and RAW are intentionally outside the 1.0 scope.

The automatic processing chain is deliberately conservative:

- robust feature matching and affine alignment;
- controlled projective Vergence/trapezoid correction when supported;
- Y-Polish as a restrained residual vertical-error correction;
- deviation and near/far analysis at a fixed 1500 px analysis width;
- automatic near-point framing with a fixed 3‰ offset behind the stereo window;
- optional symmetric color matching;
- manual crop, framing and Floating Window refinement;
- deterministic SBS and anaglyph JPEG export.

Floating Window masks remain a separate manual stereo-window function. They do not alter the automatic near-point framing model. The preview keeps a pure-black border sized to the displayed image (`max(16 px, round(width × 0.030) + 2 px)`) so masks up to 30‰ remain fully visible while editing.

## Keyboard-centered editing

Important shortcuts include:

- `Space` – automatic analysis/alignment;
- `Enter` – save current result;
- `G` / `Shift+G` – cycle grid / grid off;
- `A` – switch color/grayscale anaglyph preview;
- `L`, `R`, `T`, `B` + arrow keys – adjust Floating Window edges;
- `S` – couple/decouple left and right Floating Window edges;
- `M` + arrow keys – move the measurement cross;
- `Ctrl+R` – reset manual editing to the automatic state;
- `F1` – keyboard help;
- `F11` – fullscreen.

## Output

StereoFine always writes both:

- an SBS JPEG;
- one anaglyph JPEG (color or grayscale according to the preview/output selection).

Image-specific editing and analysis state is stored in `.sfin` sidecars so a result can be reopened or used later for batch output without rerunning successful analysis unnecessarily.

Where possible, StereoFine copies metadata using the bundled ExifTool. Preview, Orientation and MPF/MPO container metadata are not copied into ordinary SBS/anaglyph JPEG files. If only metadata copying fails, a successfully written image remains valid and StereoFine shows a warning.

The included `assets/ready.wav` is used as the single completion notification after successful save, analysis or batch completion; cancel/error paths do not play it.

## License

StereoFine source and original documentation are released under the MIT License. Third-party components remain under their respective licenses. See `THIRD_PARTY_NOTICES.md` and the files under `licenses/`.

## Source and build

The published portable Windows folder contains the exact source used to build `StereoFine.exe` under `Source/`. The same source is intended for this public repository.

Windows build instructions are in `BUILD_WINDOWS.md`. Historical validated analysis baselines and release validation are documented in `docs/VALIDATION.md`.
