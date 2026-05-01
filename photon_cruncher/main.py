from __future__ import annotations

import sys
from pathlib import Path

from PySide6 import QtGui, QtWidgets

from photon_cruncher.gui.main_window import MainWindow


def _assets_dir() -> Path:
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


def _set_app_icon(app: QtWidgets.QApplication) -> None:
    icons_dir = _assets_dir() / "icons"
    icns_path = icons_dir / "photon-cruncher.icns"
    ico_path = icons_dir / "photon-cruncher.ico"
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
    else:
        if png_dir.exists():
            for path in sorted(png_dir.glob("*.png")):
                icon.addFile(str(path))

    if not icon.isNull():
        app.setWindowIcon(icon)


def main() -> None:
    app = QtWidgets.QApplication(sys.argv)
    _set_app_icon(app)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
