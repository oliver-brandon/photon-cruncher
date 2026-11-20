"""Generated photometry recordings shared by regression and API tests."""

from pathlib import Path

import numpy as np
from scipy.io import savemat

from photon_cruncher.model import Epoc, PhotometrySession, Stream


def synthetic_session(path: Path) -> PhotometrySession:
    fs = 100.0
    time = np.arange(6000) / fs
    control = 20 + 0.01 * time + np.sin(time * 0.2)
    signal = 1.1 * control + np.sin(time * 3) + 0.2 * np.sin(time * 13)
    return PhotometrySession(
        streams={
            "x405A": Stream("x405A", fs, control),
            "x465A": Stream("x465A", fs, signal),
        },
        epocs={"Cue": Epoc("Cue", np.array([10.0, 20.0, 40.0]))},
        info={},
        source_path=Path(path),
    )


def write_synthetic_mat(path: Path) -> Path:
    session = synthetic_session(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    savemat(path, {"data": {
        "streams": {key: {"data": value.data, "fs": value.fs}
                    for key, value in session.streams.items()},
        "epocs": {"Cue": {"onset": session.epocs["Cue"].onset}},
    }})
    return path
