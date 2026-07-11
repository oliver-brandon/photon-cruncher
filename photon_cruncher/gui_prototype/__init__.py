"""Experimental Photon Cruncher v2 GUI design study.

This package is intentionally isolated from the production GUI and analysis
pipeline. Launch it with ``python -m photon_cruncher.gui_prototype`` after
installing the ``prototype`` optional dependency.
"""

from __future__ import annotations

__all__ = ["main"]


def main(argv: list[str] | None = None) -> int:
    """Launch the visual prototype without importing its optional UI eagerly."""

    from photon_cruncher.gui_prototype.app import main as app_main

    return app_main(argv)
