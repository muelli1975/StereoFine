from __future__ import annotations

import sys
from pathlib import Path


def source_root() -> Path:
    return Path(__file__).resolve().parent.parent


def bundle_root() -> Path:
    """Read-only resource root for source runs and PyInstaller builds."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return source_root()


def writable_app_root() -> Path:
    """Portable writable root: next to the executable, or project root in source runs."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return source_root()


def asset_path(name: str) -> Path:
    return bundle_root() / "assets" / name


def tool_path(name: str) -> Path:
    # In onedir builds tools are intentionally visible next to the executable.
    frozen_visible = writable_app_root() / "tools" / name
    if frozen_visible.exists():
        return frozen_visible
    return bundle_root() / "tools" / name


def settings_path() -> Path:
    return writable_app_root() / "settings.json"
