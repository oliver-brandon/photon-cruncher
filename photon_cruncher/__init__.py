"""Photometry analysis application (Aurora / dev)."""

from photon_cruncher.version import APP_NAME as __app_name__
from photon_cruncher.version import __version__


def app_title() -> str:
    # Version is displayed in the Aurora UI rail, not the window title.
    return __app_name__
