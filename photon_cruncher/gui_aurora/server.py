"""Local HTTP API + static file server for Aurora."""

from __future__ import annotations

import atexit
import hashlib
import json
import http.server
import os
import re
import shutil
import socketserver
import tempfile
import threading
import time
import traceback
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Any

from photon_cruncher import __version__
from photon_cruncher.gui_aurora import STATIC_DIR
from photon_cruncher.gui_aurora.session_store import STORE
from photon_cruncher.product import (
    AURORA_APP_NAME,
    AURORA_CODENAME,
    AURORA_UI_VERSION,
    aurora_app_title,
    aurora_brand_label,
)
from photon_cruncher import service
from photon_cruncher.analysis.runner import (
    BatchEpocSelection,
    BatchOutcome,
    run_batch_custom,
)


_MAX_UPLOAD_BYTES = 4 * 1024 * 1024 * 1024
_UPLOAD_CHUNK_BYTES = 1024 * 1024
_UPLOAD_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_UPLOAD_ROOT = Path(tempfile.mkdtemp(prefix="photon-cruncher-aurora-upload-"))
_UPLOAD_DIRS: dict[str, Path] = {}
_UPLOAD_LOCK = threading.Lock()


def _cleanup_uploads() -> None:
    shutil.rmtree(_UPLOAD_ROOT, ignore_errors=True)


atexit.register(_cleanup_uploads)


class _ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True


def _json_response(
    handler: http.server.BaseHTTPRequestHandler,
    payload: dict[str, Any],
    status: int = 200,
) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(body)


def _read_json(handler: http.server.BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0"))
    raw = handler.rfile.read(length) if length else b"{}"
    if not raw:
        return {}
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("JSON body must be an object")
    return data


def _settings_fingerprint(overrides: dict[str, Any] | None) -> str:
    blob = json.dumps(overrides or {}, sort_keys=True, default=str)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]


def _analyze_request(body: dict[str, Any]) -> dict[str, Any]:
    path = body.get("path") or STORE.current_path()
    epoc = body.get("epoc")
    if not path:
        raise ValueError("path is required (open a session first)")
    if not epoc:
        raise ValueError("epoc is required")

    cached = STORE.open(path)
    channel_keys = body.get("channels")
    overrides = body.get("settings") or {}
    channel_settings = body.get("channel_settings") or {}
    force = bool(body.get("force", False))
    channels_key = tuple(channel_keys) if channel_keys else ("__all__",)
    settings_key = {
        "settings": overrides,
        "channel_settings": channel_settings,
    }
    cache_key = f"{epoc}|{channels_key}|{_settings_fingerprint(settings_key)}"

    results = None if force else STORE.get_analysis(cached.path, cache_key)
    if results is None:

        def settings_factory(channel_key: str):
            per_channel = dict(overrides)
            per_channel.update(channel_settings.get(channel_key) or {})
            return service.settings_for_channel(channel_key, overrides=per_channel)

        results = service.analyze(
            cached.session,
            str(epoc),
            channel_keys=channel_keys,
            settings_factory=settings_factory,
        )
        STORE.put_analysis(cached.path, cache_key, results)

    trial_numbers = body.get("trial_numbers")
    trial_types = body.get("trial_types")
    filter_requested = trial_numbers is not None or trial_types is not None
    all_payloads = (
        [service.result_plot_payload(result) for result in results]
        if filter_requested
        else None
    )
    payloads = []
    for result in results:
        processed = result.processed
        if filter_requested:
            if trial_numbers == [] and not trial_types:
                continue
            processed = service.filter_trials(
                processed,
                trial_numbers=trial_numbers,
                trial_types=trial_types,
            )
            # shallow copy result with filtered processed
            filtered = service.AnalysisResult(
                session=result.session,
                epoc=result.epoc,
                channel_key=result.channel_key,
                processed=processed,
                settings=result.settings,
                stream_store=result.stream_store,
            )
            payloads.append(service.result_plot_payload(filtered))
        else:
            payloads.append(service.result_plot_payload(result))

    return {
        "ok": True,
        "path": cached.path,
        "session": cached.summary,
        "epoc": str(epoc),
        "results": payloads,
        **({"all_results": all_payloads} if all_payloads is not None else {}),
    }


def _export_request(body: dict[str, Any]) -> dict[str, Any]:
    path = body.get("path") or STORE.current_path()
    epoc = body.get("epoc")
    output_dir = body.get("output_dir")
    if not path or not epoc or not output_dir:
        raise ValueError("path, epoc, and output_dir are required")

    cached = STORE.open(path)
    channel_keys = body.get("channels")
    overrides = body.get("settings") or {}
    channel_settings = body.get("channel_settings") or {}

    def settings_factory(channel_key: str):
        per_channel = dict(overrides)
        per_channel.update(channel_settings.get(channel_key) or {})
        return service.settings_for_channel(channel_key, overrides=per_channel)

    results = service.analyze(
        cached.session,
        str(epoc),
        channel_keys=channel_keys,
        settings_factory=settings_factory,
    )
    trial_numbers = body.get("trial_numbers")
    trial_types = body.get("trial_types")
    if trial_numbers is not None or trial_types is not None:
        if trial_numbers == [] and not trial_types:
            raise ValueError("Select at least one trial before exporting.")
        filtered = []
        for result in results:
            processed = service.filter_trials(
                result.processed,
                trial_numbers=trial_numbers,
                trial_types=trial_types,
            )
            filtered.append(
                service.AnalysisResult(
                    session=result.session,
                    epoc=result.epoc,
                    channel_key=result.channel_key,
                    processed=processed,
                    settings=result.settings,
                    stream_store=result.stream_store,
                )
            )
        results = filtered

    export_csv = bool(body.get("export_csv", True))
    export_figure = bool(body.get("export_figure", False))
    figure_format = str(body.get("figure_format", "png"))
    if not export_csv and not export_figure:
        raise ValueError("Choose CSV and/or figure export.")
    if figure_format not in {"png", "pdf", "tiff"}:
        raise ValueError("figure_format must be png, pdf, or tiff")
    written: list[dict[str, str]] = []
    for result in results:
        paths = service.export_result(
            result,
            output_dir,
            export_csv=export_csv,
            export_figure=export_figure,
            figure_format=figure_format,
            filename_suffix=(
                "_selected_trials" if body.get("selected_trials") else ""
            ),
        )
        written.append(
            {
                "channel": result.channel_key,
                "csv": paths.get("csv", ""),
                "figure": paths.get("figure", ""),
            }
        )
    return {
        "ok": True,
        "output_dir": str(Path(output_dir).expanduser().resolve()),
        "exports": written,
    }


def _inspect_paths_request(body: dict[str, Any]) -> dict[str, Any]:
    raw_paths = body.get("paths") or []
    if not isinstance(raw_paths, list):
        raise ValueError("paths must be a list")
    sources: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw_path in raw_paths:
        try:
            cached = STORE.open(str(raw_path), make_current=False)
        except Exception as exc:  # noqa: BLE001 - collect per-source failures
            errors.append({"path": str(raw_path), "error": str(exc)})
            continue
        if cached.path in seen:
            continue
        seen.add(cached.path)
        sources.append({"path": cached.path, "session": cached.summary})
    return {"ok": True, "sources": sources, "errors": errors}


def _batch_selection(raw: dict[str, Any]) -> BatchEpocSelection:
    label = str(raw.get("label") or "").strip()
    members = tuple(str(item) for item in (raw.get("members") or []) if item)
    mode = str(raw.get("mode") or "all")
    if not label or not members:
        raise ValueError("Each batch epoc selection needs a label and members.")
    if mode not in {"all", "prefer_left", "prefer_right"}:
        raise ValueError(f"Unsupported epoc policy: {mode}")
    return (label, members, mode)


def _batch_export_request(body: dict[str, Any]) -> dict[str, Any]:
    raw_paths = body.get("paths") or []
    raw_selections = body.get("epoc_selections") or []
    output_dir = body.get("output_dir")
    if not raw_paths:
        raise ValueError("Add at least one MAT file or TDT block.")
    if not raw_selections:
        raise ValueError("Select at least one epoc.")
    if not output_dir:
        raise ValueError("Choose an output folder.")

    input_paths = [Path(str(path)).expanduser().resolve() for path in raw_paths]
    epoc_selections = [_batch_selection(item) for item in raw_selections]
    channel_keys = [str(key) for key in (body.get("channels") or [])]
    if not channel_keys:
        raise ValueError("Select at least one channel.")

    export_csv = bool(body.get("export_csv", True))
    export_figure = bool(body.get("export_figure", False))
    figure_format = str(body.get("figure_format", "png"))
    if not export_csv and not export_figure:
        raise ValueError("Choose CSV and/or figure export.")
    if figure_format not in {"png", "pdf", "tiff"}:
        raise ValueError("figure_format must be png, pdf, or tiff")

    overrides = body.get("settings") or {}
    channel_settings = body.get("channel_settings") or {}

    def settings_factory(channel_key: str):
        per_channel = dict(overrides)
        per_channel.update(channel_settings.get(channel_key) or {})
        return service.settings_for_channel(channel_key, overrides=per_channel)

    destination = Path(str(output_dir)).expanduser().resolve()
    outcomes: list[BatchOutcome] = []
    exported = run_batch_custom(
        input_paths=input_paths,
        epoc_selections=epoc_selections,
        output_dir=destination,
        channel_keys=channel_keys,
        settings_factory=settings_factory,
        export_summary=False,
        per_session_subdir=True,
        export_csv=export_csv,
        outcomes=outcomes,
    )
    written: list[dict[str, str]] = []
    for item in exported:
        figure_path = ""
        if export_figure:
            figure_path = service.export_result(
                item.result,
                item.output_dir,
                export_csv=False,
                export_figure=True,
                figure_format=figure_format,
            )["figure"]
        csv_path = str(getattr(item, "csv_path", None) or "")
        if csv_path or figure_path:
            written.append(
                {
                    "session": item.result.session.source_path.stem,
                    "epoc": item.result.epoc.name,
                    "channel": item.result.channel_key,
                    "csv": csv_path,
                    "figure": figure_path,
                }
            )

    def outcome_payload(outcome: BatchOutcome) -> dict[str, Any]:
        return {
            "input_path": str(outcome.input_path),
            "session": outcome.session,
            "epoc": outcome.epoc,
            "channels": list(outcome.channels),
            "reason": outcome.reason,
        }

    return {
        "ok": True,
        "output_dir": str(destination),
        "input_count": len(input_paths),
        "exports": written,
        "skipped": [
            outcome_payload(outcome)
            for outcome in outcomes
            if outcome.status == "skipped"
        ],
        "errors": [
            outcome_payload(outcome)
            for outcome in outcomes
            if outcome.status == "error"
        ],
    }


def _upload_destination(upload_id: str, relative_path: str) -> tuple[Path, Path]:
    if not _UPLOAD_ID_RE.fullmatch(upload_id):
        raise ValueError("upload_id must contain only letters, numbers, '_' or '-'.")
    normalized = str(relative_path or "").replace("\\", "/")
    if not normalized or len(normalized) > 2048:
        raise ValueError(
            "relative_path is required and must be at most 2048 characters."
        )
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:/", normalized):
        raise ValueError("relative_path must stay within the upload folder.")
    parts = [part for part in normalized.split("/") if part not in {"", "."}]
    if not parts or any(part == ".." or "\x00" in part for part in parts):
        raise ValueError("relative_path must stay within the upload folder.")
    relative = Path(*parts)
    with _UPLOAD_LOCK:
        upload_dir = _UPLOAD_DIRS.get(upload_id)
        if upload_dir is None:
            upload_dir = _UPLOAD_ROOT / upload_id
            upload_dir.mkdir(mode=0o700)
            _UPLOAD_DIRS[upload_id] = upload_dir
    root = upload_dir.resolve()
    destination = (upload_dir / relative).resolve()
    if destination != root and root not in destination.parents:
        raise ValueError("relative_path must stay within the upload folder.")
    return upload_dir, destination


def _upload_request(
    handler: http.server.BaseHTTPRequestHandler,
    query: dict[str, list[str]],
) -> dict[str, Any]:
    upload_id = (query.get("upload_id") or [""])[0]
    relative_path = (query.get("relative_path") or [""])[0]
    final = (query.get("final") or ["0"])[0].lower() in {"1", "true", "yes"}
    _upload_dir, destination = _upload_destination(upload_id, relative_path)
    raw_length = handler.headers.get("Content-Length")
    if raw_length is None:
        raise ValueError("Content-Length is required for browser uploads.")
    try:
        length = int(raw_length)
    except ValueError as exc:
        raise ValueError("Content-Length must be an integer.") from exc
    if length < 0 or length > _MAX_UPLOAD_BYTES:
        raise ValueError(
            f"uploaded files must be no larger than {_MAX_UPLOAD_BYTES} bytes."
        )

    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temp_path: Path | None = None
    received = 0
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{destination.name}.",
            suffix=".part",
            dir=destination.parent,
            delete=False,
        ) as stream:
            temp_path = Path(stream.name)
            while received < length:
                chunk = handler.rfile.read(min(_UPLOAD_CHUNK_BYTES, length - received))
                if not chunk:
                    raise ValueError(
                        "browser upload ended before Content-Length bytes were received."
                    )
                stream.write(chunk)
                received += len(chunk)
        os.replace(temp_path, destination)
        temp_path = None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)

    payload: dict[str, Any] = {
        "ok": True,
        "upload_id": upload_id,
        "relative_path": relative_path,
        "received": received,
    }
    if final:
        payload["paths"] = [str(path) for path in service.discover_data_sources(_upload_dir)]
    return payload


def _handler_class(directory: str) -> type[http.server.SimpleHTTPRequestHandler]:
    class AuroraHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, directory=directory, **kwargs)

        def log_message(self, format: str, *args) -> None:  # noqa: A003
            return

        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/api/health":
                _json_response(
                    self,
                    {
                        "ok": True,
                        "app": AURORA_APP_NAME,
                        "codename": AURORA_CODENAME,
                        "version": __version__,
                        "ui_version": AURORA_UI_VERSION,
                        "brand": aurora_brand_label(),
                        "title": aurora_app_title(),
                        "backend": "photon_cruncher.service",
                        "current_session": STORE.current_path(),
                    },
                )
                return
            if parsed.path == "/api/meta":
                _json_response(
                    self,
                    {
                        "ok": True,
                        "app": AURORA_APP_NAME,
                        "codename": AURORA_CODENAME,
                        "version": __version__,
                        "ui_version": AURORA_UI_VERSION,
                        "brand": aurora_brand_label(),
                        "title": aurora_app_title(),
                        "surfaces": {
                            "desktop_gui": "photon_cruncher.aurora_main",
                            "cli": "photon_cruncher.cli",
                            "service": "photon_cruncher.service",
                        },
                    },
                )
                return
            if parsed.path == "/api/current":
                try:
                    cached = STORE.get()
                    _json_response(
                        self,
                        {"ok": True, "path": cached.path, "session": cached.summary},
                    )
                except ValueError as exc:
                    _json_response(self, {"ok": False, "error": str(exc)}, status=404)
                return
            super().do_GET()

        def do_POST(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            try:
                if parsed.path == "/api/upload":
                    _json_response(
                        self,
                        _upload_request(self, urllib.parse.parse_qs(parsed.query)),
                    )
                    return
                if parsed.path in {"/api/open", "/api/inspect"}:
                    body = _read_json(self)
                    path = body.get("path")
                    if not path:
                        raise ValueError("path is required")
                    cached = STORE.open(path)
                    _json_response(
                        self,
                        {"ok": True, "path": cached.path, "session": cached.summary},
                    )
                    return
                if parsed.path == "/api/analyze":
                    body = _read_json(self)
                    _json_response(self, _analyze_request(body))
                    return
                if parsed.path == "/api/export":
                    body = _read_json(self)
                    _json_response(self, _export_request(body))
                    return
                if parsed.path == "/api/inspect-paths":
                    body = _read_json(self)
                    _json_response(self, _inspect_paths_request(body))
                    return
                if parsed.path == "/api/batch-export":
                    body = _read_json(self)
                    _json_response(self, _batch_export_request(body))
                    return
                if parsed.path == "/api/close":
                    STORE.clear()
                    with _UPLOAD_LOCK:
                        upload_dirs = list(_UPLOAD_DIRS.values())
                        _UPLOAD_DIRS.clear()
                    for upload_dir in upload_dirs:
                        shutil.rmtree(upload_dir, ignore_errors=True)
                    _json_response(self, {"ok": True})
                    return
                _json_response(self, {"ok": False, "error": "not found"}, status=404)
            except Exception as exc:  # noqa: BLE001 - API boundary
                _json_response(
                    self,
                    {
                        "ok": False,
                        "error": str(exc),
                        "detail": traceback.format_exc(limit=4),
                    },
                    status=400,
                )

    return AuroraHandler


def run_server(
    host: str = "127.0.0.1",
    port: int = 8766,
    open_browser: bool = True,
) -> None:
    if not STATIC_DIR.exists():
        raise FileNotFoundError(f"Missing Aurora assets: {STATIC_DIR}")

    handler = _handler_class(str(STATIC_DIR.resolve()))
    with _ReusableTCPServer((host, port), handler) as httpd:
        url = f"http://{host}:{port}/"
        print(f"{aurora_app_title()} → {url}")
        print("Shared backend: photon_cruncher.service")
        print("Ctrl+C to stop.")
        if open_browser:
            threading.Timer(0.35, lambda: webbrowser.open(url)).start()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")


def find_free_port(host: str = "127.0.0.1") -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def serve_in_background(
    host: str = "127.0.0.1",
    port: int | None = None,
) -> tuple[_ReusableTCPServer, threading.Thread, int]:
    if not STATIC_DIR.exists():
        raise FileNotFoundError(f"Missing Aurora assets: {STATIC_DIR}")
    bind_port = find_free_port(host) if port is None else port
    handler = _handler_class(str(STATIC_DIR.resolve()))
    httpd = _ReusableTCPServer((host, bind_port), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.15)
    return httpd, thread, bind_port


def static_files() -> list[Path]:
    return sorted(path for path in STATIC_DIR.rglob("*") if path.is_file())
