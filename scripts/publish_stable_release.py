#!/usr/bin/env python3
"""Publish two verified platform payloads together as one stable GitHub release."""

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def gh(*args):
    return subprocess.check_output(["gh", *args], text=True).strip()


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    version = os.environ["RELEASE_VERSION"]
    tag = os.environ["RELEASE_TAG"]
    repo = os.environ["GITHUB_REPOSITORY"]
    archive_stem = os.environ["INSTALLER_STEM"]
    if tag != f"v{version}":
        raise ValueError("Release tag does not match version")
    files = {}
    for channel, directory, extension, label in (
        ("stable-win-x64", Path("release-windows"), "exe", "Windows"),
        ("stable-osx-arm64", Path("release-macos"), "pkg", "macOS"),
    ):
        feed_name = f"releases.{channel}.json"
        feed_path = directory / feed_name
        feed = json.loads(feed_path.read_text(encoding="utf-8"))
        entries = [entry for entry in feed["Assets"] if entry["Version"] == version]
        if len(entries) != 2 or {entry["Type"] for entry in entries} != {"Full", "Delta"}:
            raise ValueError(f"{channel} must contain full and delta entries")
        for entry in entries:
            name = entry["FileName"]
            if Path(name).name != name or entry["PackageId"] != "com.photoncruncher.app":
                raise ValueError("Unexpected package name or identity")
            if f"-{version}-{channel}-" not in name:
                raise ValueError("Package version or channel mismatch")
            path = directory / name
            if path.stat().st_size != entry["Size"] or digest(path).lower() != entry["SHA256"].lower():
                raise ValueError(f"Package hash or size mismatch: {name}")
            files[name] = path
        files[feed_name] = feed_path
        installers = list(directory.glob(f"*-Setup.{extension}"))
        portable = list(directory.glob(f"*-{channel}-Portable.zip"))
        if len(installers) != 1 or len(portable) != 1:
            raise ValueError(f"{channel} must have one installer and portable archive")
        files[f"{archive_stem}-{label}.{extension}"] = installers[0]
        files[portable[0].name] = portable[0]

    with tempfile.TemporaryDirectory(prefix="stable-release-") as temporary:
        stage = Path(temporary)
        for name, source in files.items():
            shutil.copyfile(source, stage / name)
        # A published release is never overwritten; an interrupted draft can resume.
        result = subprocess.run(
            ["gh", "release", "view", tag, "--repo", repo, "--json", "isDraft"],
            text=True, capture_output=True,
        )
        if result.returncode:
            if "release not found" not in result.stderr.lower():
                raise RuntimeError(f"Cannot check release: {result.stderr.strip()}")
            gh("release", "create", tag, "--repo", repo, "--verify-tag", "--draft",
               "--title", f"Photon Cruncher Aurora v{version}",
               "--notes-file", "packaging/velopack/release-notes.md")
        elif not json.loads(result.stdout)["isDraft"]:
            raise ValueError("A published release already exists for this tag")
        existing = json.loads(gh("release", "view", tag, "--repo", repo, "--json", "assets"))["assets"]
        for asset in existing:
            path = stage / asset["name"]
            if asset.get("state") != "uploaded" or not path.is_file() or (asset.get("digest") or "").lower() != f"sha256:{digest(path)}":
                raise ValueError(f"Existing draft asset differs: {asset['name']}")
        uploaded = {asset["name"] for asset in existing}
        missing = [str(stage / name) for name in files if name not in uploaded]
        if missing:
            gh("release", "upload", tag, "--repo", repo, *missing)
        remote = json.loads(gh("release", "view", tag, "--repo", repo, "--json", "assets"))["assets"]
        if {asset["name"] for asset in remote} != set(files):
            raise ValueError("Draft release asset names are incomplete")
        for asset in remote:
            path = stage / asset["name"]
            if asset["size"] != path.stat().st_size or (asset.get("digest") or "").lower() != f"sha256:{digest(path)}":
                raise ValueError(f"Uploaded asset verification failed: {asset['name']}")
        gh("release", "edit", tag, "--repo", repo, "--draft=false", "--latest")
    print(f"Published verified stable release {tag}")


if __name__ == "__main__":
    main()
