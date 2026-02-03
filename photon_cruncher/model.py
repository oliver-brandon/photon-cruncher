from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import numpy as np


@dataclass
class Stream:
    name: str
    fs: float
    data: np.ndarray
    t0: float = 0.0

    def time(self) -> np.ndarray:
        return self.t0 + np.arange(self.data.size) / self.fs


@dataclass
class Epoc:
    name: str
    onset: np.ndarray
    offset: Optional[np.ndarray] = None
    values: Optional[np.ndarray] = None


@dataclass
class PhotometrySession:
    streams: dict[str, Stream]
    epocs: dict[str, Epoc]
    info: dict[str, Any]
    source_path: Path
    notes: dict[str, Any] = field(default_factory=dict)
