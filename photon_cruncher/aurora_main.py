"""Photon Cruncher Aurora desktop application entry point."""

from __future__ import annotations

import argparse

from photon_cruncher import __version__
from photon_cruncher.product import aurora_app_title, aurora_brand_label
from photon_cruncher.updates import development_mode_enabled, run_velopack_startup


def main(argv: list[str] | None = None) -> int:
    if not development_mode_enabled():
        run_velopack_startup()
    parser = argparse.ArgumentParser(
        prog="photon-cruncher",
        description=(
            f"{aurora_app_title()} ({aurora_brand_label()}) — "
            "desktop GUI. Live analysis via photon_cruncher.service."
        ),
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.parse_args(argv)

    print(f"{aurora_app_title()} · {aurora_brand_label()}")

    from photon_cruncher.gui_aurora.shell import run_shell

    return run_shell()


if __name__ == "__main__":
    raise SystemExit(main())
