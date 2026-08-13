"""Photometry analysis application."""

from photon_cruncher.version import APP_NAME as __app_name__
from photon_cruncher.version import __version__


def app_title() -> str:
    return f"{__app_name__} v{__version__}"
