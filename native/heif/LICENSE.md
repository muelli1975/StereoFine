# Separate HEIF reader

This helper's Python source is covered by TransCora's MIT license. It runs as a
separate program; the main application must not import pillow-heif.

Adapted for StereoFine from TransCora commit
`c8f7a00b8ea0494912454e668740c2071a5c2766`. StereoFine keeps the decoder,
stereo-group selection and orientation handling, and makes FFmpeg optional:
the supported import path uses sRGB/unspecified SDR or an embedded ICC profile.
Other NCLX SDR colour conversions are rejected without a converter. The
unchanged upstream MIT notice is in `UPSTREAM_LICENSE.txt`.

The investigated pillow-heif 1.8.1 binary wheel includes GPLv2 x265, LGPLv3
libheif and LGPLv3 libde265. The wrapper is BSD-3-Clause. A frozen helper built
with that wheel must be distributed under the applicable combined GPL terms,
with the exact corresponding source, build scripts and dependency notices.
The main application license does not replace these terms.

The combined reader executable is distributed under GPL-3.0-or-later. x265's
source permits GPL version 2 or any later version; version 3 accommodates the
LGPLv3 components. Original component notices are retained under `licenses/`.
Complete pinned native source archives, the wrapper source (including upstream
wheel build scripts), the reader source and packaging recipe are under `source/`.
`BUILD_SOURCES.json` records their download origins, versions and checksums.
The replaceable native libraries remain beside the executable in `_internal/`.

Development builds require tests of the actual frozen reader on every supported
platform before release. Decoder-only LGPL builds remain an alternative.

Primary sources:

- https://github.com/bigcat88/pillow_heif/tree/v1.8.1
- https://github.com/bigcat88/pillow_heif/blob/v1.8.1/LICENSES_bundled.txt
- https://github.com/strukturag/libheif
- https://github.com/strukturag/libde265
- https://x265.org/legal-notices/
