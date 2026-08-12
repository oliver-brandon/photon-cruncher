"""In-process session cache for the Aurora local backend."""

from __future__ import annotations

import os
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any

import numpy as np

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
    def __init__(
        self,
        *,
        max_sessions: int | None = None,
        max_analysis_bytes: int | None = None,
    ) -> None:
        self._lock = Lock()
        self._max_sessions = max(
            1,
            int(
                max_sessions
                if max_sessions is not None
                else os.environ.get("AURORA_MAX_CACHED_SESSIONS", "8")
            ),
        )
        self._max_analysis_bytes = max(
            1,
            int(
                max_analysis_bytes
                if max_analysis_bytes is not None
                else int(os.environ.get("AURORA_ANALYSIS_CACHE_MB", "256"))
                * 1024
                * 1024
            ),
        )
        self._by_path: OrderedDict[str, CachedSession] = OrderedDict()
        self._analysis_lru: OrderedDict[tuple[str, str], int] = OrderedDict()
        self._analysis_bytes = 0
        self._current_path: str | None = None
        self._current_request = 0

    def clear(self) -> None:
        with self._lock:
            self._by_path.clear()
            self._analysis_lru.clear()
            self._analysis_bytes = 0
            self._current_path = None
            self._current_request += 1

    def open(
        self,
        path: str | Path,
        *,
        make_current: bool = True,
    ) -> CachedSession:
        resolved = str(Path(path).expanduser().resolve())
        with self._lock:
            request_id: int | None = None
            if make_current:
                self._current_request += 1
                request_id = self._current_request
            cached = self._by_path.get(resolved)
            if cached is not None:
                self._by_path.move_to_end(resolved)
                if request_id == self._current_request:
                    self._current_path = resolved
                return cached

        # Loading MAT/TDT data can take seconds. Keep the store lock available
        # so health checks and already-cached requests remain responsive.
        session = open_session(resolved)
        loaded = CachedSession(
            path=resolved,
            session=session,
            summary=session_summary(session),
        )
        with self._lock:
            cached = self._by_path.get(resolved)
            became_current = request_id == self._current_request
            if cached is None and make_current and not became_current:
                return loaded
            if cached is None:
                cached = loaded
                self._by_path[resolved] = cached
            else:
                self._by_path.move_to_end(resolved)
            if became_current:
                self._current_path = resolved
            self._evict_sessions_locked(
                protected_path=resolved if became_current else None
            )
            return cached

    def get(self, path: str | Path | None = None) -> CachedSession:
        with self._lock:
            key = str(Path(path).expanduser().resolve()) if path else self._current_path
            if not key or key not in self._by_path:
                raise ValueError("No open session. Open a MAT file or TDT block first.")
            self._by_path.move_to_end(key)
            return self._by_path[key]

    def current_path(self) -> str | None:
        with self._lock:
            return self._current_path

    def put_analysis(self, path: str, cache_key: str, results: list[AnalysisResult]) -> None:
        with self._lock:
            cached = self._by_path.get(path)
            if cached is not None:
                lru_key = (path, cache_key)
                previous_size = self._analysis_lru.pop(lru_key, 0)
                self._analysis_bytes -= previous_size
                size = _analysis_result_bytes(results)
                if size > self._max_analysis_bytes:
                    cached.analysis_cache.pop(cache_key, None)
                    return
                cached.analysis_cache[cache_key] = results
                self._analysis_lru[lru_key] = size
                self._analysis_bytes += size
                self._evict_analyses_locked(protected=lru_key)

    def get_analysis(self, path: str, cache_key: str) -> list[AnalysisResult] | None:
        with self._lock:
            cached = self._by_path.get(path)
            if cached is None:
                return None
            results = cached.analysis_cache.get(cache_key)
            if results is not None:
                lru_key = (path, cache_key)
                if lru_key in self._analysis_lru:
                    self._analysis_lru.move_to_end(lru_key)
                self._by_path.move_to_end(path)
            return results

    def evict_paths(
        self,
        paths: list[str | Path],
        *,
        keep_current: bool = False,
    ) -> int:
        resolved_paths = {
            str(Path(path).expanduser().resolve())
            for path in paths
        }
        with self._lock:
            removed = 0
            for path in resolved_paths:
                if keep_current and path == self._current_path:
                    continue
                if path in self._by_path:
                    self._drop_session_locked(path)
                    removed += 1
            return removed

    def clear_analysis(self, path: str | Path | None = None) -> int:
        with self._lock:
            target = (
                str(Path(path).expanduser().resolve())
                if path is not None
                else None
            )
            keys = [
                lru_key
                for lru_key in self._analysis_lru
                if target is None or lru_key[0] == target
            ]
            for lru_key in keys:
                self._drop_analysis_locked(lru_key)
            return len(keys)

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "cached_sessions": len(self._by_path),
                "max_sessions": self._max_sessions,
                "analysis_entries": len(self._analysis_lru),
                "analysis_bytes": self._analysis_bytes,
                "max_analysis_bytes": self._max_analysis_bytes,
            }

    def _evict_sessions_locked(self, *, protected_path: str | None) -> None:
        while len(self._by_path) > self._max_sessions:
            candidate = next(
                (
                    path
                    for path in self._by_path
                    if path not in {protected_path, self._current_path}
                ),
                None,
            )
            if candidate is None:
                break
            self._drop_session_locked(candidate)

    def _evict_analyses_locked(self, *, protected: tuple[str, str]) -> None:
        while (
            self._analysis_bytes > self._max_analysis_bytes
            and len(self._analysis_lru) > 1
        ):
            candidate = next(
                (key for key in self._analysis_lru if key != protected),
                None,
            )
            if candidate is None:
                break
            self._drop_analysis_locked(candidate)

    def _drop_analysis_locked(self, lru_key: tuple[str, str]) -> None:
        path, cache_key = lru_key
        size = self._analysis_lru.pop(lru_key, 0)
        self._analysis_bytes = max(0, self._analysis_bytes - size)
        cached = self._by_path.get(path)
        if cached is not None:
            cached.analysis_cache.pop(cache_key, None)

    def _drop_session_locked(self, path: str) -> None:
        cached = self._by_path.pop(path, None)
        if cached is None:
            return
        for cache_key in list(cached.analysis_cache):
            self._drop_analysis_locked((path, cache_key))
        if self._current_path == path:
            self._current_path = None


def _analysis_result_bytes(results: list[AnalysisResult]) -> int:
    """Estimate retained NumPy memory without double-counting shared arrays."""
    total = 0
    seen: set[int] = set()
    for result in results:
        processed = result.processed
        for value in vars(processed).values():
            if isinstance(value, np.ndarray) and id(value) not in seen:
                seen.add(id(value))
                total += int(value.nbytes)
    return total


STORE = SessionStore()
