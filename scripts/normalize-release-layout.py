"""Rename only portable archive roots; verify every member before publishing."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import zipfile

def gh(*args):
    return subprocess.check_output(["gh", *args], text=True)

def digest(path):
    with path.open("rb") as stream:
        return "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()

def rename(name, old, app):
    if name.startswith("/") or ".." in name.split("/"):
        raise ValueError("Unsafe archive path: " + name)
    if not old:
        return app + "/" + name
    if name == old or name.startswith(old + "/"):
        return app + name[len(old):]
    prefix = "__MACOSX/" + old
    if name == prefix or name.startswith(prefix + "/"):
        return "__MACOSX/" + app + name[len(prefix):]
    if name.rstrip("/") == "__MACOSX":
        return name
    raise ValueError("Unexpected archive root: " + name)

def manifest(path, old, app):
    result = {}
    if path.name.endswith(".zip"):
        with zipfile.ZipFile(path) as archive:
            for member in archive.infolist():
                name = rename(member.filename, old, app)
                assert name not in result, name
                with archive.open(member) as stream:
                    sha = hashlib.file_digest(stream, "sha256").hexdigest()
                result[name] = [member.external_attr, member.create_system, member.date_time,
                                member.extra, member.comment, sha]
    else:
        with tarfile.open(path, "r:gz") as archive:
            for member in archive:
                name = rename(member.name, old, app)
                assert name not in result, name
                target = member.linkname
                if old and (target == old or target.startswith(old + "/")):
                    target = rename(target, old, app)
                stream = archive.extractfile(member) if member.isfile() else None
                sha = hashlib.file_digest(stream, "sha256").hexdigest() if stream else None
                if stream:
                    stream.close()
                result[name] = [member.type, member.mode, member.uid, member.gid,
                                member.uname, member.gname, member.mtime, target, sha]
    return result

def repack(source, destination, old, app):
    if source.name.endswith(".zip"):
        with zipfile.ZipFile(source) as incoming, zipfile.ZipFile(destination, "w") as outgoing:
            outgoing.comment = incoming.comment
            for original in incoming.infolist():
                member = copy.copy(original)
                member.filename = rename(original.filename, old, app)
                with incoming.open(original) as reader, outgoing.open(member, "w") as writer:
                    shutil.copyfileobj(reader, writer, 1024 * 1024)
    else:
        with tarfile.open(source, "r:gz") as incoming, tarfile.open(destination, "w:gz") as outgoing:
            for original in incoming:
                member = copy.copy(original)
                member.name = rename(original.name, old, app)
                member.pax_headers = dict(original.pax_headers)
                if "path" in member.pax_headers:
                    member.pax_headers["path"] = member.name
                if member.linkname == old or member.linkname.startswith(old + "/"):
                    member.linkname = rename(member.linkname, old, app)
                    if "linkpath" in member.pax_headers:
                        member.pax_headers["linkpath"] = member.linkname
                stream = incoming.extractfile(original) if original.isfile() else None
                outgoing.addfile(member, stream)
                if stream:
                    stream.close()
    before = manifest(source, old, app)
    after = manifest(destination, app, app)
    assert before == after, "Archive member payload or metadata changed"
    print(source.name, len(after), "members verified; only the enclosing folder changed", flush=True)

plan = json.loads(Path("scripts/release-layout-plan.json").read_text())
repo, tag, app = plan["repo"], plan["tag"], plan["app"]
backup = Path("layout-backup")
output = Path("layout-ready")
backup.mkdir(exist_ok=True)
output.mkdir(exist_ok=True)
release = json.loads(gh("api", f"repos/{repo}/releases/tags/{tag}"))
assert release["id"] == plan["release_id"] and not release["draft"]
current = {asset["name"]:asset for asset in release["assets"]}
for asset in plan["assets"]:
    original = current[asset["name"]]
    assert original["id"] == asset["id"] and original["digest"] == asset["digest"]
    gh("release", "download", tag, "--repo", repo, "--dir", str(backup), "--pattern", asset["name"])
    source = backup / asset["name"]
    assert digest(source) == asset["digest"]
    repack(source, output / asset["name"], asset["root"], app)
if "SHA256SUMS.txt" in current:
    gh("release", "download", tag, "--repo", repo, "--dir", str(backup), "--pattern", "SHA256SUMS.txt")
checksums = "".join(digest(path).removeprefix("sha256:") + "  " + path.name + "\n"
                    for path in sorted(output.iterdir()))
(output / "SHA256SUMS.txt").write_text(checksums, encoding="ascii")
report = {path.name:digest(path) for path in output.iterdir()}
(output / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
if "--publish" in sys.argv:
    uploaded = []
    try:
        for path in sorted(output.iterdir()):
            if path.name == "verification.json":
                continue
            gh("release", "upload", tag, str(path), "--repo", repo, "--clobber")
            uploaded.append(path.name)
        published = json.loads(gh("api", f"repos/{repo}/releases/tags/{tag}"))
        actual = {asset["name"]:asset["digest"] for asset in published["assets"]}
        assert all(actual[name] == value for name,value in report.items() if name != "verification.json")
        print("Published archives and SHA256SUMS verified:", json.dumps(report), flush=True)
    except Exception:
        for name in uploaded:
            if (backup / name).exists():
                gh("release", "upload", tag, str(backup / name), "--repo", repo, "--clobber")
            else:
                gh("release", "delete-asset", tag, name, "--repo", repo, "--yes")
        raise
