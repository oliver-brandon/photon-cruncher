"""Photon Cruncher Aurora — developer desktop GUI entry point.

Default desktop surface on the dev branch. Native shell (Qt WebEngine) by default;
optional --browser mode. Analysis goes through photon_cruncher.service.
"""

from __future__ import annotations

import argparse

from photon_cruncher.product import aurora_app_title, aurora_brand_label


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="photon-cruncher",
        description=(
            f"{aurora_app_title()} ({aurora_brand_label()}) — "
            "desktop GUI. Live analysis via photon_cruncher.service."
        ),
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Backend port (default: ephemeral free port in shell mode, 8766 in --browser).",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--window",
        action="store_true",
        default=True,
        help="Open native desktop shell (default).",
    )
    mode.add_argument(
        "--browser",
        action="store_true",
        help="Serve in a normal browser tab instead of the native shell.",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="With --browser, serve without auto-opening a tab.",
    )
    args = parser.parse_args(argv)

    print(f"{aurora_app_title()} · {aurora_brand_label()}")

    if args.browser:
        from photon_cruncher.gui_aurora.server import run_server

        port = 8766 if args.port is None else args.port
        run_server(host=args.host, port=port, open_browser=not args.no_browser)
        return 0

    from photon_cruncher.gui_aurora.shell import run_shell

    return run_shell(host=args.host, port=args.port)


if __name__ == "__main__":
    raise SystemExit(main())
