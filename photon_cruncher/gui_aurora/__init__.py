"""Aurora — developer GUI surface for Photon Cruncher.

Codename for the v2 visual redesign. Uses the shared analysis service and does
not replace the lab-facing PySide app (`photon_cruncher.main`).
"""

from __future__ import annotations

from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parent / "static"

__all__ = ["STATIC_DIR", "serve"]


def serve(host: str = "127.0.0.1", port: int = 8766, open_browser: bool = True) -> None:
    from photon_cruncher.gui_aurora.server import run_server

    run_server(host=host, port=port, open_browser=open_browser)
