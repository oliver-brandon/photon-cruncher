from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m photon_cruncher.gui_prototype",
        description=(
            "Launch the isolated Photon Cruncher GUI v2 visual prototype. "
            "The prototype uses synthetic data and never invokes the analysis pipeline."
        ),
    )
    parser.add_argument(
        "--page",
        choices=("data", "align", "trials", "batch"),
        default="data",
        help="Prototype page to show at launch (default: data).",
    )
    parser.add_argument(
        "--state",
        choices=("empty", "demo"),
        default="demo",
        help="Data-page state to show at launch (default: demo).",
    )
    parser.add_argument(
        "--capture-all",
        metavar="DIRECTORY",
        type=Path,
        help="Capture five deterministic 1440x900 PNGs and exit.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.capture_all is not None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        os.environ.setdefault("QT_SCALE_FACTOR", "1")

    if importlib.util.find_spec("pyqtgraph") is None:
        print(
            "The GUI v2 prototype requires its optional plotting dependency.\n"
            "Install it with:\n"
            "  .build-venv/bin/python -m pip install -e 'photon_cruncher[prototype]'",
            file=sys.stderr,
        )
        return 2

    from PySide6 import QtCore, QtWidgets

    from photon_cruncher.gui_prototype.demo_data import create_demo_session
    from photon_cruncher.gui_prototype.shell import PrototypeWindow
    from photon_cruncher.gui_prototype.theme import apply_theme

    app = QtWidgets.QApplication.instance()
    owns_app = app is None
    if app is None:
        app = QtWidgets.QApplication(sys.argv[:1])
    app.setApplicationName("Photon Cruncher GUI v2 Prototype")
    app.setOrganizationName("PhotonCruncherPrototype")
    apply_theme(app)

    window = PrototypeWindow(create_demo_session())
    window.set_demo_state(args.state)
    window.show_page(args.page)

    if args.capture_all is not None:
        for path in window.capture_all(args.capture_all.expanduser().resolve()):
            print(path)
        window.close()
        app.processEvents(QtCore.QEventLoop.AllEvents, 100)
        return 0

    window.show()
    if not owns_app:
        return 0
    return app.exec()
