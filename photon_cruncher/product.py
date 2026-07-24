"""Product surface names for lab vs Aurora builds."""

from __future__ import annotations

from photon_cruncher import __version__

# Lab-facing desktop app (current PySide GUI). On the dev branch this may still
# say "Dev" via __app_name__; main releases use the stable lab name.
LAB_APP_NAME = "Photon Cruncher"

# Developer / v2 experimental surface. Always branded Aurora.
AURORA_APP_NAME = "Photon Cruncher Aurora"
AURORA_CODENAME = "aurora"
# UI-facing Aurora surface version (shown next to "Aurora" in the rail).
# Kept separate from package __version__ so lab builds can stay on 1.x while
# Aurora presents as v2.0 in-product.
AURORA_UI_VERSION = "2.0"


def lab_app_title(version: str | None = None) -> str:
    from photon_cruncher import __app_name__

    return f"{__app_name__} v{version or __version__}"


def aurora_app_title(version: str | None = None) -> str:
    """Window / process title. Version is intentionally omitted — show it in-UI."""
    del version  # unused; kept for call-site compatibility
    return AURORA_APP_NAME


def aurora_brand_label(version: str | None = None) -> str:
    """In-app rail label, e.g. 'Aurora v2.0'."""
    return f"Aurora v{version or AURORA_UI_VERSION}"
