"""Photon Cruncher — default desktop entry (Aurora on dev)."""

from __future__ import annotations

from photon_cruncher.aurora_main import main

__all__ = ["main"]


if __name__ == "__main__":
    raise SystemExit(main())
