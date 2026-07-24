"""Local HTTP API + static file server for Aurora."""

from __future__ import annotations

import hashlib
import json
import http.server
import socketserver
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
    force = bool(body.get("force", False))
    channels_key = tuple(channel_keys) if channel_keys else ("__all__",)
    cache_key = f"{epoc}|{channels_key}|{_settings_fingerprint(overrides)}"

    results = None if force else STORE.get_analysis(cached.path, cache_key)
    if results is None:
        results = service.analyze(
            cached.session,
            str(epoc),
            channel_keys=channel_keys,
            settings_overrides=overrides if overrides else None,
        )
        STORE.put_analysis(cached.path, cache_key, results)

    trial_numbers = body.get("trial_numbers")
    trial_types = body.get("trial_types")
    payloads = []
    for result in results:
        processed = result.processed
        if trial_numbers or trial_types:
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
    results = service.analyze(
        cached.session,
        str(epoc),
        channel_keys=channel_keys,
        settings_overrides=overrides if overrides else None,
    )
    if body.get("trial_numbers") or body.get("trial_types"):
        filtered = []
        for result in results:
            processed = service.filter_trials(
                result.processed,
                trial_numbers=body.get("trial_numbers"),
                trial_types=body.get("trial_types"),
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
    written: list[dict[str, str]] = []
    for result in results:
        paths = service.export_result(
            result,
            output_dir,
            export_csv=export_csv,
            export_figure=export_figure,
            figure_format=figure_format,
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
                            "lab_gui": "photon_cruncher.main",
                            "aurora_gui": "photon_cruncher.aurora_main",
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
                if parsed.path == "/api/close":
                    STORE.clear()
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
        print("Lab GUI remains: python -m photon_cruncher.main")
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
