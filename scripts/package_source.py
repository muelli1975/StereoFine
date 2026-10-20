"""Include the exact tracked application sources, without local user state."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIRECTORIES = {"stereofine", "assets", "tests", "docs", "licenses", "scripts", ".github"}
FILES = {".gitignore", "AGENTS.md", "DESIGN_STANDARD_STEREOTOOLS.txt", "StereoFine.py", "StereoFine.spec",
         "version_info.txt", "build_windows.ps1", "requirements-lock.txt", "requirements-build.txt",
         "README.md", "README_DE.md", "README_EN.md", "LICENSE.txt", "THIRD_PARTY_NOTICES.md",
         "BUILD_WINDOWS.md", "RELEASE_CHECKLIST.md", "CHANGELOG.md", "RELEASE_NOTES_1.1-rc1.md"}


def main(destination: Path) -> None:
    try:
        tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
        if "StereoFine.py" not in tracked:
            raise subprocess.CalledProcessError(1, "git ls-files")
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        tracked = [str(p.relative_to(ROOT)) for p in ROOT.rglob("*") if p.is_file()]
        source_commit = ROOT / "SOURCE_COMMIT.txt"
        commit = source_commit.read_text().strip() if source_commit.exists() else "source snapshot"
    destination.mkdir(parents=True, exist_ok=True)
    for name in tracked:
        if not name:
            continue
        path = Path(name)
        if name not in FILES and path.parts[0] not in DIRECTORIES:
            continue
        if "__pycache__" in path.parts or path.suffix in {".pyc", ".sfin", ".log"} or path.name == "settings.json":
            continue
        target = destination / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / path, target)
    (destination / "SOURCE_COMMIT.txt").write_text(commit + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
