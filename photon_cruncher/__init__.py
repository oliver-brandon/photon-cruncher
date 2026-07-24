"""Photometry analysis application (Aurora / dev)."""

__version__ = "2.0.0"
__app_name__ = "Photon Cruncher Aurora"


def app_title() -> str:
    # Version is displayed in the Aurora UI rail, not the window title.
    return __app_name__
