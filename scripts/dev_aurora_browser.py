#!/usr/bin/env python3
"""Open Aurora in an external browser for development and UI testing only."""

from __future__ import annotations

import argparse

from photon_cruncher.gui_aurora.server import run_development_server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Developer-only external-browser preview of the Aurora desktop UI. "
            "The supported Photon Cruncher product surface is the desktop app."
        )
    )
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Start the preview server without opening a browser tab.",
    )
    args = parser.parse_args(argv)
    run_development_server(
        host="127.0.0.1",
        port=args.port,
        open_browser=not args.no_open,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
