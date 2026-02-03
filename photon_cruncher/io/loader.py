from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from scipy.io import loadmat

from photon_cruncher.model import Epoc, PhotometrySession, Stream


def _mat_to_dict(obj: Any) -> Any:
    if isinstance(obj, np.ndarray) and obj.dtype == object:
        if obj.size == 1:
            return _mat_to_dict(obj.item())
        return np.array([_mat_to_dict(item) for item in obj])
    if hasattr(obj, "_fieldnames"):
        return {name: _mat_to_dict(getattr(obj, name)) for name in obj._fieldnames}
    return obj


def load_session(path: Path) -> PhotometrySession:
    mat = loadmat(path, squeeze_me=True, struct_as_record=False)
    if "data" not in mat:
        raise ValueError("Expected 'data' variable in MAT file.")
    data = _mat_to_dict(mat["data"])

    streams: dict[str, Stream] = {}
    for name, entry in data.get("streams", {}).items():
        fs = float(np.squeeze(entry["fs"]))
        stream_data = np.asarray(entry["data"], dtype=float).reshape(-1)
        streams[name] = Stream(name=name, fs=fs, data=stream_data)

    epocs: dict[str, Epoc] = {}
    for name, entry in data.get("epocs", {}).items():
        onset = np.asarray(entry.get("onset", []), dtype=float).reshape(-1)
        offset = entry.get("offset")
        values = entry.get("data")
        if values is None:
            values = entry.get("values")
        epocs[name] = Epoc(
            name=name,
            onset=onset,
            offset=None if offset is None else np.asarray(offset, dtype=float).reshape(-1),
            values=None if values is None else np.asarray(values, dtype=float).reshape(-1),
        )

    info = data.get("info", {}) if isinstance(data.get("info", {}), dict) else {}
    return PhotometrySession(
        streams=streams,
        epocs=epocs,
        info=info,
        source_path=Path(path),
    )
