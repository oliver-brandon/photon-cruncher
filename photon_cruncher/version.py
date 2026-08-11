"""Canonical product and version metadata for Photon Cruncher Aurora."""

from __future__ import annotations

import platform


__version__ = "2.0.0"
APP_NAME = "Photon Cruncher Aurora"
AURORA_CODENAME = "aurora"
BUNDLE_IDENTIFIER = "com.photoncruncher.aurora.dev"
UPDATE_PACKAGE_ID = "com.photoncruncher.aurora.dev"
UPDATE_CHANNEL_PREFIX = "aurora-dev"
UPDATE_REPOSITORY_URL = "https://github.com/oliver-brandon/photon-cruncher"
UPDATE_TAG_PREFIX = "aurora-dev-v"
VELOPACK_VERSION = "1.2.0"


def major_minor(version: str = __version__) -> str:
    """Return the display version used in app and archive names."""
    parts = version.split(".")
    if len(parts) < 2 or not all(part.isdigit() for part in parts):
        raise ValueError(f"Expected a numeric semantic version, got {version!r}")
    return ".".join(parts[:2])


def update_target(
    system_name: str | None = None,
    machine: str | None = None,
) -> tuple[str, str]:
    """Return the isolated Velopack channel and runtime for this host."""
    system_key = (system_name or platform.system()).strip().lower()
    machine_key = (machine or platform.machine()).strip().lower()

    if machine_key in {"amd64", "x86_64", "x64"}:
        architecture = "x64"
    elif machine_key in {"arm64", "aarch64"}:
        architecture = "arm64"
    else:
        raise ValueError(f"Unsupported update architecture: {machine_key or 'unknown'}")

    if system_key == "windows":
        operating_system = "win"
    elif system_key in {"darwin", "macos"}:
        operating_system = "osx"
    else:
        raise ValueError(f"Unsupported update platform: {system_key or 'unknown'}")

    runtime = f"{operating_system}-{architecture}"
    return f"{UPDATE_CHANNEL_PREFIX}-{runtime}", runtime


AURORA_UI_VERSION = major_minor()
BUNDLE_APP_NAME = f"{APP_NAME} v{__version__}"
ARCHIVE_STEM = f"Photon-Cruncher-Aurora-v{__version__}"
UPDATE_RELEASE_TAG = f"{UPDATE_TAG_PREFIX}{__version__}"
