# Building StereoFine 1.0 on Windows

StereoFine is published as a **portable Windows x64 onedir application**. The public executable must be built on Windows; PyInstaller is not used to cross-compile it from Linux.

## Required build environment

- Windows x64
- Python **3.12.10**, 64 bit, installed with the standard Python installer
- Internet access for the one-time installation of the pinned Python build dependencies
- the complete StereoFine 1.0 source directory, including `assets/` and `tools/`

Runtime dependencies are pinned in `requirements-lock.txt`. The build tool is pinned in `requirements-build.txt`:

- PyInstaller 6.22.2

## Build

Open PowerShell in the exact StereoFine 1.0 source directory and run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\build_windows.ps1
```

The script deliberately creates a clean `.venv-build`, verifies Python 3.12.10, installs the pinned dependencies, runs the automated core test suite and compile/import checks, builds the onedir application and assembles the release package.
It does not require the Windows Python installer to contain separate Tcl/Tk `license.terms` files; official Tcl/Tk 8.6 license references are already included in the source package and are replaced by installation-specific copies when those are available.

Expected final artifacts:

```text
release/
    StereoFine_1.0.zip
    SHA256SUMS.txt

dist/
    StereoFine_1.0/
        StereoFine.exe
        _internal/
        tools/
            exiftool.exe
            exiftool_files/
        licenses/
        Source/
        README_DE.md
        README_EN.md
        LICENSE.txt
        THIRD_PARTY_NOTICES.md
        BUILD_INFO.txt
```

`Source/` contains the exact application source, assets, tests, documentation and build files used for the executable. The third-party ExifTool package remains visible once at `tools/` beside the executable and is not duplicated inside `Source/`.

StereoFine stores `settings.json` beside `StereoFine.exe` at runtime. This is deliberate portable behavior, so the application should be kept in a normal writable folder rather than a protected system directory.

## Required manual Windows smoke check

After the script finishes, extract `release/StereoFine_1.0.zip` into a fresh folder and check at least:

1. `StereoFine.exe` starts without an external Python installation being used.
2. The application icon is correct in Explorer, the title bar and taskbar.
3. German and English GUI fit without clipping at the normal display scaling used on the machine.
4. The two subtle separator lines around the scroll area are visible.
5. One normal stereo pair or Full-SBS can be loaded and aligned.
6. Saving always produces both an SBS JPEG and an anaglyph JPEG; the preview mode only selects color or grayscale anaglyph output.
7. A normal successful save plays `ready.wav` without an additional Windows notification tone; cancel/error do not play `ready.wav`.
8. ExifTool is found from the portable `tools/` folder and metadata copying does not show a warning.
9. During loading, alignment, saving or batch work, the primary button becomes `Cancel`; cancelling returns the same button and the GUI to the correct idle state without changing the visible source unexpectedly.
10. The primary start button is dark/gold at rest and visibly fills light gold on hover; normal secondary buttons retain the SplatTricia dark/gray style.
11. The activity ring has a visibly closed base ring with no seam or gap, and the moving segment has no thick endpoint bumps.
12. The full `G` grid cycle keeps the visible Off/White/Black controls and spacing menu synchronized; after returning to Off, the spacing menu remains usable instead of getting stuck/disabled.
13. `L/R/T/B` + arrow keys update Floating Window masks immediately in the preview, and `S` changes only left/right coupling. At 30‰ the curtain must remain fully visible inside the image edge, with the documented pure-black `3% + 2 px` preview border still outside the image.
14. When the projective Vergence stage is active, the status shows `Vergenz (Trapezkorrektur)` / `Vergence (trapezoid correction)` with the actually applied correction magnitude; genuine legacy V/H values are used only for legacy V/H sidecars, and reloading `.sfin` does not change the status.
15. F1 help is cleanly aligned as a two-column key/function table and fits without scrolling.
16. The application closes cleanly.

A genuine camera MPO and additional real camera color-mismatch material are useful extra checks when available, but they are not required to rebuild the already validated 1.0 core.

## Releasing

The public release archive is simply:

```text
StereoFine_1.0.zip
```

Upload it manually to the GitHub release for version `1.0`. The SHA-256 produced in `release/SHA256SUMS.txt` can be copied into the release notes.
