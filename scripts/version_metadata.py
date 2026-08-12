#!/usr/bin/env python3
"""Read and validate the canonical Photon Cruncher version metadata."""

from __future__ import annotations

import argparse
import json
import os
import re
import runpy
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = PROJECT_ROOT / "photon_cruncher" / "version.py"


def metadata() -> dict[str, str]:
    values = runpy.run_path(str(VERSION_FILE))
    update_channel, update_runtime = values["update_target"](
        os.environ.get("PHOTON_CRUNCHER_UPDATE_SYSTEM"),
        os.environ.get("PHOTON_CRUNCHER_UPDATE_MACHINE"),
    )
    return {
        "version": values["__version__"],
        "ui_version": values["AURORA_UI_VERSION"],
        "app_name": values["APP_NAME"],
        "bundle_app_name": values["BUNDLE_APP_NAME"],
        "archive_stem": values["ARCHIVE_STEM"],
        "bundle_identifier": values["BUNDLE_IDENTIFIER"],
        "update_package_id": values["UPDATE_PACKAGE_ID"],
        "update_channel": update_channel,
        "update_runtime": update_runtime,
        "update_repository_url": values["UPDATE_REPOSITORY_URL"],
        "update_release_tag": values["UPDATE_RELEASE_TAG"],
        "velopack_version": values["VELOPACK_VERSION"],
    }


def validate_repo(values: dict[str, str]) -> list[str]:
    errors: list[str] = []
    if not re.fullmatch(r"\d+\.\d+\.\d+", values["version"]):
        errors.append("version must use numeric MAJOR.MINOR.PATCH format")

    if values["ui_version"] != values["version"]:
        errors.append("ui_version must match the full canonical version")
    if values["bundle_app_name"] != f"{values['app_name']} v{values['version']}":
        errors.append("bundle_app_name does not match app_name and full version")
    if values["update_package_id"] != values["bundle_identifier"]:
        errors.append("update_package_id and bundle_identifier must match on dev")
    if not values["update_channel"].startswith("aurora-dev-"):
        errors.append("update_channel must remain isolated to Aurora dev")
    if values["update_release_tag"] != f"aurora-dev-v{values['version']}":
        errors.append("update_release_tag does not match the canonical version")

    required_text = {
        PROJECT_ROOT / "photon_cruncher" / "pyproject.toml": (
            'dynamic = ["version"]',
            'version = { attr = "photon_cruncher.version.__version__" }',
            f'"velopack=={values["velopack_version"]}"',
        ),
        PROJECT_ROOT / "scripts" / "build_macos_app.sh": (
            "version_metadata.py",
            "--field bundle_app_name",
        ),
        PROJECT_ROOT / "scripts" / "build_windows_app.ps1": (
            "version_metadata.py",
            "--field bundle_app_name",
        ),
        PROJECT_ROOT / "packaging" / "macos" / "PhotonCruncher.spec": (
            "version.py",
            'version_meta["BUNDLE_APP_NAME"]',
            "velopack_hiddenimports",
        ),
        PROJECT_ROOT / "packaging" / "windows" / "PhotonCruncher.spec": (
            "version.py",
            'version_meta["BUNDLE_APP_NAME"]',
            "velopack_hiddenimports",
        ),
        PROJECT_ROOT / ".github" / "workflows" / "build-desktop-apps.yml": (
            "aurora-dev-v*",
            "vpk upload github",
            "--pre true",
            "MACOS_DEVELOPER_ID_APPLICATION_P12_BASE64",
        ),
        PROJECT_ROOT / "scripts" / "package_macos_update.sh": (
            "--field update_channel",
            "--mainExe",
            "--signAppIdentity",
            "--notaryProfile",
            "notarytool log",
        ),
        PROJECT_ROOT / "scripts" / "package_windows_update.ps1": (
            "--field update_channel",
            "--mainExe",
            "*-full.nupkg",
        ),
        PROJECT_ROOT / "packaging" / "velopack" / "release-notes.md": (
            f"# Photon Cruncher Aurora {values['version']}",
        ),
    }
    for path, needles in required_text.items():
        text = path.read_text(encoding="utf-8")
        for needle in needles:
            if needle not in text:
                errors.append(f"{path.relative_to(PROJECT_ROOT)} is missing {needle!r}")

    literal_targets = (
        PROJECT_ROOT / "photon_cruncher" / "__init__.py",
        PROJECT_ROOT / "photon_cruncher" / "product.py",
        PROJECT_ROOT / "photon_cruncher" / "gui_aurora" / "static" / "index.html",
        PROJECT_ROOT / "photon_cruncher" / "gui_aurora" / "static" / "js" / "app.js",
        PROJECT_ROOT / "scripts" / "build_macos_app.sh",
        PROJECT_ROOT / "scripts" / "build_windows_app.ps1",
        PROJECT_ROOT / "packaging" / "macos" / "PhotonCruncher.spec",
        PROJECT_ROOT / "packaging" / "windows" / "PhotonCruncher.spec",
        PROJECT_ROOT / ".github" / "workflows" / "build-desktop-apps.yml",
    )
    forbidden = (values["version"], f"v{values['ui_version']}")
    for path in literal_targets:
        text = path.read_text(encoding="utf-8")
        for literal in forbidden:
            if literal in text:
                errors.append(
                    f"{path.relative_to(PROJECT_ROOT)} hard-codes canonical value {literal!r}"
                )
    return errors


def main(argv: list[str] | None = None) -> int:
    values = metadata()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--field", choices=sorted(values))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    if args.check:
        errors = validate_repo(values)
        if errors:
            for error in errors:
                print(f"ERROR: {error}", file=sys.stderr)
            return 1
        print(
            f"Version metadata OK: {values['version']} "
            f"({values['bundle_app_name']})"
        )
        return 0
    if args.field:
        print(values[args.field])
    else:
        print(json.dumps(values, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
