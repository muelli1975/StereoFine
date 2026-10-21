from __future__ import annotations

import sys

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


def restore_dark_titlebar(window) -> bool:
    """Restore Tk's native Windows frame theme without changing window state."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        ancestor = user32.GetAncestor
        ancestor.argtypes = (wintypes.HWND, wintypes.UINT)
        ancestor.restype = wintypes.HWND
        hwnd = ancestor(window.winfo_id(), 2)  # GA_ROOT: Tk's outer native frame.
        if not hwnd:
            return False
        set_attribute = ctypes.WinDLL("dwmapi").DwmSetWindowAttribute
        set_attribute.argtypes = (wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD)
        set_attribute.restype = ctypes.c_long
        dark = ctypes.c_int(1)
        # Attribute 19 is the older Windows 10 equivalent used by CustomTkinter.
        for attribute in (20, 19):
            if set_attribute(hwnd, attribute, ctypes.byref(dark), ctypes.sizeof(dark)) == 0:
                return True
    except (AttributeError, OSError):
        pass
    return False

