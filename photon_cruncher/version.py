"""Canonical product and version metadata for stable Photon Cruncher."""

from __future__ import annotations

import platform


__version__ = "1.2.0"
APP_NAME = "Photon Cruncher"
BUNDLE_IDENTIFIER = "com.photoncruncher.app"
UPDATE_PACKAGE_ID = BUNDLE_IDENTIFIER
UPDATE_CHANNEL_PREFIX = "stable"
UPDATE_REPOSITORY_URL = "https://github.com/oliver-brandon/photon-cruncher"
UPDATE_TAG_PREFIX = "v"
VELOPACK_VERSION = "1.2.0"


def update_target(
    system_name: str | None = None,
    machine: str | None = None,
) -> tuple[str, str]:
    """Return the stable Velopack channel and runtime for this host."""
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


UI_VERSION = __version__
BUNDLE_APP_NAME = f"{APP_NAME} v{__version__}"
ARCHIVE_STEM = f"Photon-Cruncher-v{__version__}"
UPDATE_RELEASE_TAG = f"{UPDATE_TAG_PREFIX}{__version__}"
