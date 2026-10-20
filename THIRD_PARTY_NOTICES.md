# StereoFine – Third-party notices

StereoFine's own source code and original documentation are licensed under the MIT License (`LICENSE.txt`). Third-party software remains under its own licenses.

## Runtime components

| Component | Release | Purpose | License material |
| --- | --- | --- | --- |
| Python | 3.12.10 | Runtime bundled into the portable Windows build | `licenses/Python-3.12.10-LICENSE.txt` in the final Windows package |
| Tcl/Tk | 8.6 series supplied with Python 3.12.10 | Tk GUI runtime | `licenses/Tcl-8.6-LICENSE.txt` and `licenses/Tk-8.6-LICENSE.txt` in the final Windows package |
| CustomTkinter | 5.2.2 | GUI | `licenses/CustomTkinter-5.2.2-LICENSE.txt` |
| darkdetect | 0.8.0 | CustomTkinter dependency | `licenses/darkdetect-0.8.0-LICENSE.txt` |
| NumPy | 2.4.6 | Numerical processing | `licenses/NumPy-2.4.6-LICENSE.txt` |
| OpenCV-Python | 4.13.0.92 | Feature matching, geometry, disparity and image I/O | `licenses/OpenCV-Python-4.13.0.92-LICENSE.txt` and `licenses/OpenCV-Python-4.13.0.92-THIRD-PARTY.txt` |
| Pillow | 12.2.0 | MPO/JPEG handling and GUI image support | `licenses/Pillow-12.2.0-LICENSE.txt` |
| ExifTool | 13.59 | Metadata copy | The official platform-appropriate distribution and its license/readme material are retained under `tools/` in binary packages |

The source tree includes the official Tcl and Tk 8.6 license terms from the upstream `core-8-6-branch`. The Windows build always copies the exact Python license from the Python 3.12.10 installation used for the build. If that Python installation also includes standalone Tcl/Tk `license.terms` files, the build uses those copies; some standard Windows Python installations omit them, in which case the bundled official Tcl/Tk 8.6 license references remain in the portable package.

ExifTool is kept visibly separate in `tools/`. The Windows portable package uses ExifTool's official Windows distribution, including its launcher and bundled Perl runtime. The macOS/Linux packages use the official Unix/macOS ExifTool distribution (`exiftool` plus its support files). StereoFine does not relicense or merge ExifTool into the MIT-licensed application source; the original distribution material is kept intact.

## Build-time component

StereoFine is built with **PyInstaller 6.22.2**. PyInstaller is a build-time tool and is not part of StereoFine's MIT-licensed source. PyInstaller's license exception permits distributing generated executable bundles under the application's own license while respecting dependency licenses; its license file does not need to be included with the generated application.

See the individual license files and the upstream projects for the complete terms.

## Separate HEIF reader

SDR HEIC/HEIF is decoded by the separate replaceable `tools/heif/StereoFine-HEIF` process. The main application never imports pillow-heif. The reader is adapted from TransCora commit `c8f7a00b8ea0494912454e668740c2071a5c2766` (MIT; original notice in `native/heif/UPSTREAM_LICENSE.txt`).

The pinned pillow-heif 1.8.1 wheel includes the BSD-3-Clause wrapper, libheif 1.23.6 and libde265 1.1.3 (LGPLv3), and x265 4.3 (GPLv2 or later). The combined helper is distributed under GPL-3.0-or-later, separately from the MIT application. The package retains component notices, complete pinned corresponding source archives, reader/packaging sources and `BUILD_SOURCES.json` / `BUILD_READER.json` under `tools/heif`. Its native libraries remain replaceable in `_internal`. See `native/heif/LICENSE.md` and `scripts/heif-sources.json`. No FFmpeg binary or converter is added.

The tiny synthetic stereo fixtures come unchanged from pillow-heif v1.8.1 and retain their BSD notice under `tests/fixtures/heif`.
