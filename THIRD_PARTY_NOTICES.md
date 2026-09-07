# StereoFine 1.0 – Third-party notices

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
| ExifTool | 13.53 | Metadata copy | The official platform-appropriate distribution and its license/readme material are retained under `tools/` in binary packages |

The source tree includes the official Tcl and Tk 8.6 license terms from the upstream `core-8-6-branch`. The Windows build always copies the exact Python license from the Python 3.12.10 installation used for the build. If that Python installation also includes standalone Tcl/Tk `license.terms` files, the build uses those copies; some standard Windows Python installations omit them, in which case the bundled official Tcl/Tk 8.6 license references remain in the portable package.

ExifTool is kept visibly separate in `tools/`. The Windows portable package uses ExifTool's official Windows distribution, including its launcher and bundled Perl runtime. The macOS/Linux packages use the official Unix/macOS ExifTool distribution (`exiftool` plus its support files). StereoFine does not relicense or merge ExifTool into the MIT-licensed application source; the original distribution material is kept intact.

## Build-time component

StereoFine 1.0 is built with **PyInstaller 6.22.2**. PyInstaller is a build-time tool and is not part of StereoFine's MIT-licensed source. PyInstaller's license exception permits distributing generated executable bundles under the application's own license while respecting dependency licenses; its license file does not need to be included with the generated application.

See the individual license files and the upstream projects for the complete terms.
