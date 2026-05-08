from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from scipy.io import loadmat

from photon_cruncher.model import Epoc, PhotometrySession, Stream


TDT_BLOCK_EXTENSIONS = {".sev", ".tev", ".tsq", ".tdx", ".tbk"}


def is_tdt_block_path(path: Path) -> bool:
    path = Path(path)
    if not path.is_dir():
        return False
    try:
        return any(
            child.is_file() and child.suffix.lower() in TDT_BLOCK_EXTENSIONS
            for child in path.iterdir()
        )
    except OSError:
        return False


def discover_tdt_block_paths(folder: Path) -> list[Path]:
    folder = Path(folder)
    if not folder.is_dir():
        return []
    if is_tdt_block_path(folder):
        return [folder]

    block_paths: list[Path] = []
    try:
        children = sorted(folder.iterdir())
    except OSError:
        return []

    for child in children:
        if child.is_dir():
            block_paths.extend(discover_tdt_block_paths(child))
    return block_paths


def _mat_to_dict(obj: Any) -> Any:
    if isinstance(obj, np.ndarray) and obj.dtype == object:
        if obj.size == 1:
            return _mat_to_dict(obj.item())
        return np.array([_mat_to_dict(item) for item in obj])
    if hasattr(obj, "_fieldnames"):
        return {name: _mat_to_dict(getattr(obj, name)) for name in obj._fieldnames}
    return obj


def _object_to_dict(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {key: _object_to_dict(value) for key, value in obj.items()}
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    if hasattr(obj, "__dict__"):
        return {
            key: _object_to_dict(value)
            for key, value in vars(obj).items()
            if not key.startswith("_")
        }
    return str(obj)


def _field(obj: Any, name: str, default: Any = None) -> Any:
    if hasattr(obj, "__dict__") and name in vars(obj):
        return vars(obj)[name]
    if isinstance(obj, dict):
        return obj.get(name, default)
    if hasattr(obj, "get"):
        try:
            return obj.get(name, default)
        except TypeError:
            pass
    return getattr(obj, name, default)


def _items(obj: Any) -> list[tuple[str, Any]]:
    if obj is None:
        return []
    if hasattr(obj, "keys"):
        try:
            return [(str(key), _field(obj, key)) for key in obj.keys()]
        except (AttributeError, TypeError):
            pass
    if hasattr(obj, "__dict__"):
        return [
            (key, value)
            for key, value in vars(obj).items()
            if not key.startswith("_")
        ]
    return []


def _normalize_tdt_name(name: str) -> str:
    if len(name) > 1 and name[0] == "_" and name[1].isdigit():
        return f"x{name[1:]}"
    return name


def _flatten_stream_data(data: Any) -> np.ndarray:
    stream_data = np.asarray(data, dtype=float)
    if stream_data.ndim == 0:
        return stream_data.reshape(1)
    return stream_data.reshape(-1)


def _load_mat_session(path: Path) -> PhotometrySession:
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
            offset=(
                None
                if offset is None
                else np.asarray(offset, dtype=float).reshape(-1)
            ),
            values=(
                None
                if values is None
                else np.asarray(values, dtype=float).reshape(-1)
            ),
        )

    info = data.get("info", {}) if isinstance(data.get("info", {}), dict) else {}
    return PhotometrySession(
        streams=streams,
        epocs=epocs,
        info=info,
        source_path=Path(path),
    )


def _load_tdt_session(path: Path) -> PhotometrySession:
    try:
        import tdt
    except ImportError as exc:
        raise ImportError(
            "TDT block loading requires the 'tdt' package. "
            "Install it with: pip install tdt"
        ) from exc

    data = tdt.read_block(str(path))

    streams: dict[str, Stream] = {}
    for raw_name, entry in _items(_field(data, "streams", {})):
        name = _normalize_tdt_name(raw_name)
        fs = _field(entry, "fs")
        stream_data = _field(entry, "data")
        if fs is None or stream_data is None:
            continue
        streams[name] = Stream(
            name=name,
            fs=float(np.squeeze(fs)),
            data=_flatten_stream_data(stream_data),
            t0=float(np.squeeze(_field(entry, "start_time", 0.0))),
        )

    epocs: dict[str, Epoc] = {}
    for name, entry in _items(_field(data, "epocs", {})):
        onset = np.asarray(_field(entry, "onset", []), dtype=float).reshape(-1)
        offset = _field(entry, "offset")
        values = _field(entry, "data")
        if values is None:
            values = _field(entry, "values")
        epocs[name] = Epoc(
            name=name,
            onset=onset,
            offset=(
                None
                if offset is None
                else np.asarray(offset, dtype=float).reshape(-1)
            ),
            values=(
                None
                if values is None
                else np.asarray(values, dtype=float).reshape(-1)
            ),
        )

    info = _object_to_dict(_field(data, "info", {}))
    if not isinstance(info, dict):
        info = {"tdt_info": info}
    info["source_format"] = "tdt"

    return PhotometrySession(
        streams=streams,
        epocs=epocs,
        info=info,
        source_path=Path(path),
    )


def load_session(path: Path) -> PhotometrySession:
    path = Path(path)
    if path.is_dir():
        if not is_tdt_block_path(path):
            raise ValueError(f"Folder does not look like a TDT block: {path}")
        return _load_tdt_session(path)
    if path.suffix.lower() == ".mat":
        return _load_mat_session(path)
    raise ValueError(f"Unsupported input format: {path}")
