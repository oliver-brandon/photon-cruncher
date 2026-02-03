from __future__ import annotations

import sys
from pathlib import Path

from PySide6 import QtGui, QtWidgets

from photon_cruncher.gui.main_window import MainWindow


def _set_app_icon(app: QtWidgets.QApplication) -> None:
    icons_dir = Path(__file__).resolve().parent / "assets" / "icons"
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
