"""Package and verify canonical release sources without local user state."""
from __future__ import annotations

import io
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIRECTORIES = {"stereofine", "assets", "tests", "docs", "licenses", "scripts", ".github"}
FILES = {".gitignore", "AGENTS.md", "DESIGN_STANDARD_STEREOTOOLS.txt", "StereoFine.py", "StereoFine.spec",
         "version_info.txt", "build_windows.ps1", "requirements-lock.txt", "requirements-build.txt",
         "README.md", "README_DE.md", "README_EN.md", "LICENSE.txt", "THIRD_PARTY_NOTICES.md",
         "BUILD_WINDOWS.md", "RELEASE_CHECKLIST.md", "CHANGELOG.md", "RELEASE_NOTES_1.1-rc1.md",
         "RELEASE_NOTES_1.1-rc2.md"}


def included(name: str) -> bool:
    path = Path(name)
    return (bool(path.parts) and (name in FILES or path.parts[0] in DIRECTORIES)
            and "__pycache__" not in path.parts
            and path.suffix not in {".pyc", ".sfin", ".log"} and path.name != "settings.json")


def committed_sources() -> tuple[str, dict[str, bytes]]:
    repository_root = subprocess.check_output(
        ["git", "rev-parse", "--show-toplevel"], cwd=ROOT, text=True).strip()
    if Path(repository_root).resolve() != ROOT:
        raise subprocess.CalledProcessError(1, "source directory is not the repository root")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    archive = subprocess.check_output(["git", "archive", "--format=tar", "HEAD"], cwd=ROOT)
    with tarfile.open(fileobj=io.BytesIO(archive)) as snapshot:
        files = {member.name: snapshot.extractfile(member).read()
                 for member in snapshot if member.isfile() and included(member.name)}
    if "StereoFine.py" not in files:
        raise subprocess.CalledProcessError(1, "git archive")
    return commit, files


def unpacked_sources() -> tuple[str, dict[str, bytes]]:
    files = {p.relative_to(ROOT).as_posix(): p.read_bytes()
             for p in ROOT.rglob("*") if p.is_file() and included(p.relative_to(ROOT).as_posix())}
    source_commit = ROOT / "SOURCE_COMMIT.txt"
    basis = source_commit.read_text().strip() if source_commit.exists() else "unknown"
    commit = basis if basis.startswith("source snapshot") else "source snapshot based on " + basis
    return commit, files


def verify(destination: Path) -> None:
    try:
        commit, expected = committed_sources()
    except (OSError, subprocess.CalledProcessError):
        commit, expected = unpacked_sources()
    expected["SOURCE_COMMIT.txt"] = (commit + "\n").encode()
    actual = {p.relative_to(destination).as_posix(): p for p in destination.rglob("*") if p.is_file()}
    if actual.keys() != expected.keys():
        raise RuntimeError("Source snapshot file inventory differs from the release commit.")
    for name, content in expected.items():
        if actual[name].read_bytes() != content:
            raise RuntimeError(f"Source snapshot differs from release commit: {name}")
    print(f"Verified {len(expected)} canonical source files for {commit}")


def main(destination: Path) -> None:
    try:
        commit, files = committed_sources()
        dirty = subprocess.check_output(
            ["git", "status", "--porcelain", "--", *sorted(FILES | DIRECTORIES)],
            cwd=ROOT, text=True,
        )
        if dirty.strip():
            raise RuntimeError("Release sources have local changes; commit them before packaging.")
    except (OSError, subprocess.CalledProcessError):
        # Rebuilding an unpacked source distribution without a Git repository.
        commit, files = unpacked_sources()
    destination.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        # Git archive preserves canonical bytes even on Windows EOL checkouts.
        target.write_bytes(content)
    (destination / "SOURCE_COMMIT.txt").write_bytes((commit + "\n").encode())


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--verify":
        verify(Path(sys.argv[2]).resolve())
    else:
        main(Path(sys.argv[1]).resolve())
