from __future__ import annotations

# Shared Stereo-Tool design standard, August 2026.
APP_BG = "#111111"
SECONDARY_BG = "#181818"
PANEL_BG = "#202020"
HOVER_BG = "#282828"
BORDER = "#333333"
TEXT_PRIMARY = "#f2f2f2"
TEXT_SECONDARY = "#b8b8b8"
TEXT_DISABLED = "#727272"
GOLD_DARK = "#9c7c38"
GOLD_LIGHT = "#c6a95e"
PREVIEW_BG = "#000000"

DANGER = "#7f3939"
DANGER_HOVER = "#944545"

PANEL_RADIUS = 12
CONTROL_RADIUS = 8

SPACE_1 = 4
SPACE_2 = 8
SPACE_3 = 12
SPACE_4 = 16
SPACE_5 = 20
SPACE_6 = 24

FONT_FAMILY = "Segoe UI"


def preview_border_px(displayed_image_width: int) -> int:
    """Shared preview-border rule from the Stereo-Tool design standard."""
    width = max(0, int(displayed_image_width))
    return max(16, round(width * 0.030) + 2)

TRAFFIC_GREEN = "#3fa34d"
TRAFFIC_ORANGE = "#d89000"
TRAFFIC_RED = "#d24a43"
TRAFFIC_GRAY = "#727272"
