"""In-process session cache for the Aurora local backend."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any

from photon_cruncher.model import PhotometrySession
from photon_cruncher.service import AnalysisResult, open_session, session_summary


@dataclass
class CachedSession:
    path: str
    session: PhotometrySession
    summary: dict[str, Any]
    # key: (epoc, channels_tuple, settings_fingerprint) -> results
    analysis_cache: dict[str, list[AnalysisResult]] = field(default_factory=dict)


class SessionStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._by_path: dict[str, CachedSession] = {}
        self._current_path: str | None = None

    def clear(self) -> None:
        with self._lock:
            self._by_path.clear()
            self._current_path = None

    def open(self, path: str | Path) -> CachedSession:
        resolved = str(Path(path).expanduser().resolve())
        with self._lock:
            cached = self._by_path.get(resolved)
            if cached is None:
                session = open_session(resolved)
                cached = CachedSession(
                    path=resolved,
                    session=session,
                    summary=session_summary(session),
                )
                self._by_path[resolved] = cached
            self._current_path = resolved
            return cached

    def get(self, path: str | Path | None = None) -> CachedSession:
        with self._lock:
            key = str(Path(path).expanduser().resolve()) if path else self._current_path
            if not key or key not in self._by_path:
                raise ValueError("No open session. Open a MAT file or TDT block first.")
            return self._by_path[key]

    def current_path(self) -> str | None:
        with self._lock:
            return self._current_path

    def put_analysis(self, path: str, cache_key: str, results: list[AnalysisResult]) -> None:
        with self._lock:
            cached = self._by_path.get(path)
            if cached is not None:
                cached.analysis_cache[cache_key] = results

    def get_analysis(self, path: str, cache_key: str) -> list[AnalysisResult] | None:
        with self._lock:
            cached = self._by_path.get(path)
            if cached is None:
                return None
            return cached.analysis_cache.get(cache_key)


STORE = SessionStore()
