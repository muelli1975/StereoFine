"""Prepare a Windows-only update while retaining verified existing platform archives."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import urllib.request

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--checks", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    repo = os.environ["GITHUB_REPOSITORY"]
    assert repo == config["repository"]
    request = urllib.request.Request(
        "https://api.github.com/repos/" + repo + "/releases/tags/" + config["tag"],
        headers={"Authorization": "Bearer " + os.environ["GH_TOKEN"],
                 "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        release = json.load(response)
    assert release["target_commitish"] == config["previous_tag"]
    assets = {item["name"]: item for item in release["assets"]}
    previous_checks = None
    retained = {}
    for name, expected in config["assets"].items():
        assert assets[name]["digest"] == expected, name
        if name == "BUILD_CHECKS.json":
            with urllib.request.urlopen(assets[name]["browser_download_url"], timeout=60) as response:
                data = response.read()
            assert "sha256:" + hashlib.sha256(data).hexdigest() == expected
            previous_checks = json.loads(data)
        elif name not in config["replace"]:
            target = args.root / name
            with urllib.request.urlopen(assets[name]["browser_download_url"], timeout=300) as source, target.open("wb") as output:
                while block := source.read(4 * 1024 * 1024):
                    output.write(block)
            with target.open("rb") as stream:
                actual = "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()
            assert actual == expected and target.stat().st_size == assets[name]["size"], name
            target.with_name(name + ".sha256").write_text(actual.split(":", 1)[1] + "  " + name + "\n")
            retained[name] = {"source_commit": release["target_commitish"], "sha256": actual}
    checks = {str(p.relative_to(args.checks)): json.loads(p.read_text())
              for p in args.checks.rglob("*.json")}
    assert checks and previous_checks
    windows = "StereoFine_1.1_Windows_x64.zip"
    assert (args.root / windows).is_file()
    report = {
        "build_url": "https://github.com/" + repo + "/actions/runs/" + os.environ["GITHUB_RUN_ID"],
        "platform_source_commits": {
            windows: os.environ["GITHUB_SHA"],
            **{name: value["source_commit"] for name, value in retained.items()}},
        "windows_checks": checks,
        "retained_platform_assets": retained,
        "previous_platform_checks": previous_checks}
    (args.root / "BUILD_CHECKS.json").write_text(json.dumps(report, indent=2) + "\n")
    subprocess.run(["python", "scripts/release_checksums.py", str(args.root)], check=True)

if __name__ == "__main__":
    main()
