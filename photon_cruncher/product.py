"""Product surface names and desktop branding for Aurora (dev branch)."""

from __future__ import annotations

import sys
from pathlib import Path

from photon_cruncher import __version__

# Dev branch ships Aurora only.
APP_NAME = "Photon Cruncher Aurora"
AURORA_APP_NAME = APP_NAME
AURORA_CODENAME = "aurora"
# UI-facing version next to "Aurora" in the rail (and package version on this branch).
AURORA_UI_VERSION = "2.0"

# Kept for older call sites that still say "lab".
LAB_APP_NAME = APP_NAME


def assets_dir() -> Path:
    """Resolve packaged or source assets directory."""
    source_assets = Path(__file__).resolve().parent / "assets"
    candidates = [source_assets]

    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).resolve()
        if len(executable.parents) > 1:
            candidates.append(
                executable.parents[1] / "Resources" / "photon_cruncher" / "assets"
            )
        bundle_root = getattr(sys, "_MEIPASS", None)
        if bundle_root:
            candidates.append(Path(bundle_root) / "photon_cruncher" / "assets")

    for path in candidates:
        if path.exists():
            return path
    return source_assets


def set_app_icon(app) -> None:
    """Apply the Aurora monogram icon to a Qt application."""
    from PySide6 import QtGui

    icons_dir = assets_dir() / "icons"
    icns_path = icons_dir / "photon-cruncher-aurora.icns"
    ico_path = icons_dir / "photon-cruncher-aurora.ico"
    png_dir = icons_dir / "png"

    icon = QtGui.QIcon()
    if sys.platform == "darwin" and icns_path.exists():
        icon.addFile(str(icns_path))
        try:
            from AppKit import NSApplication, NSImage  # type: ignore

            ns_icon = NSImage.alloc().initWithContentsOfFile_(str(icns_path))
            NSApplication.sharedApplication().setApplicationIconImage_(ns_icon)
        except Exception:
            pass
    elif sys.platform.startswith("win") and ico_path.exists():
        icon.addFile(str(ico_path))
    elif png_dir.exists():
        for path in sorted(png_dir.glob("photon-cruncher-aurora-*.png")):
            icon.addFile(str(path))
        if icon.isNull():
            for path in sorted(png_dir.glob("*.png")):
                icon.addFile(str(path))

    if not icon.isNull():
        app.setWindowIcon(icon)


def lab_app_title(version: str | None = None) -> str:
    """Compatibility alias — dev branch titles are Aurora."""
    return aurora_app_title(version)


def aurora_app_title(version: str | None = None) -> str:
    """Window / process title. Version is shown in-UI, not the title bar."""
    del version
    return AURORA_APP_NAME


def aurora_brand_label(version: str | None = None) -> str:
    """In-app rail label, e.g. 'Aurora v2.0'."""
    return f"Aurora v{version or AURORA_UI_VERSION}"


def bundle_app_name(version: str | None = None) -> str:
    """Filesystem / installer bundle stem."""
    return f"{AURORA_APP_NAME} v{version or AURORA_UI_VERSION}"
