from __future__ import annotations

APP_NAME = "StereoFine"
APP_VERSION = "1.0"
SIDECAR_SCHEMA_VERSION = 3

# Pipeline versions are intentionally separate from the app version so a later
# GUI-only release does not invalidate valid analysis results.
ALIGNMENT_PIPELINE_VERSION = "sf-align-2"
DISPARITY_PIPELINE_VERSION = "sf-disparity-1"
COLOR_PIPELINE_VERSION = "sf-color-1"
ANAGLYPH_PIPELINE_VERSION = "sf-anaglyph-1"

# Validated project baselines from the previous StereoFine test rounds.
ALIGNMENT_ANALYSIS_MAX_WIDTH = 3000
DISPARITY_ANALYSIS_MAX_WIDTH = 1500
PREVIEW_MAX_WIDTH = 1600
AUTO_NEAR_WINDOW_BACK_PERMILLE = 3.0

# Existing practical traffic-light convention. This is a user-facing guidance
# scale, not a claim of a hard physiological boundary.
DEVIATION_GREEN_MAX_PERMILLE = 33.0
DEVIATION_ORANGE_MAX_PERMILLE = 40.0

SBS_JPEG_QUALITY = 95
ANAGLYPH_JPEG_QUALITY = 90
ANAGLYPH_TARGET_HEIGHT = 2160

SUPPORTED_IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".tif", ".tiff"})
SUPPORTED_MPO_EXTENSIONS = frozenset({".mpo"})
SUPPORTED_STEREO_SINGLE_EXTENSIONS = SUPPORTED_IMAGE_EXTENSIONS | SUPPORTED_MPO_EXTENSIONS


ASPECT_RATIOS: dict[str, float | str | None] = {
    "maximum": None,
    "original": "original",
    "3:2": 3 / 2,
    "4:3": 4 / 3,
    "16:9": 16 / 9,
    "1:1": 1.0,
}

ORIENTATION_CODES = ("0", "180", "90_cw", "90_ccw")

def normalize_aspect_code(value: str | None) -> str:
    value = str(value or "maximum")
    return {"Maximal": "maximum", "Maximum": "maximum", "Original": "original"}.get(value, value)

def normalize_orientation_code(value: str | None) -> str:
    value = str(value or "0")
    return {
        "0°": "0",
        "180°": "180",
        "90° rechts": "90_cw",
        "90° links": "90_ccw",
        "90° right": "90_cw",
        "90° left": "90_ccw",
    }.get(value, value)

GRID_SPACING_OPTIONS = ("25 Promille", "50 Promille", "100 Promille", "Drittel-Raster")
GRID_DIVISIONS_BY_SPACING = {
    "25 Promille": 40,
    "50 Promille": 20,
    "100 Promille": 10,
    "Drittel-Raster": 3,
}

CROP_ZOOM_LEVELS = (1.00, 1.05, 1.10, 1.15, 1.25, 1.40, 1.60, 1.80, 2.00)

ANALYSIS_REPORT_FILENAME = "stereofine_analysis.txt"
