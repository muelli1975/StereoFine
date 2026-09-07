from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable


def _unix_sound_command(
    path: Path,
    *,
    platform: str | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> list[str] | None:
    """Return a native asynchronous WAV playback command for macOS/Linux.

    StereoFine deliberately keeps the completion sound lightweight and uses the
    platform's existing desktop audio tools instead of adding a second multimedia
    runtime solely for one short WAV notification.
    """
    platform = platform or sys.platform
    if platform == "darwin":
        afplay = which("afplay") or ("/usr/bin/afplay" if Path("/usr/bin/afplay").is_file() else None)
        return [afplay, str(path)] if afplay else None

    if platform.startswith("linux"):
        for player in ("paplay", "pw-play", "aplay"):
            executable = which(player)
            if executable:
                return [executable, str(path)]
    return None


def play_ready_sound(path: Path) -> bool:
    """Play StereoFine's completion WAV once and asynchronously when possible."""
    path = Path(path)
    if not path.is_file():
        return False

    if sys.platform.startswith("win"):
        try:
            import winsound

            winsound.PlaySound(
                str(path),
                winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
            )
            return True
        except Exception:
            return False

    command = _unix_sound_command(path)
    if command is None:
        return False
    try:
        subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            close_fds=True,
        )
        return True
    except Exception:
        return False
