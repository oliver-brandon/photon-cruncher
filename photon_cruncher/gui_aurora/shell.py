"""Native desktop shell for Aurora (PySide6 + Qt WebEngine).

Desktop window for the Aurora web UI with native file dialogs and the shared
analysis service. Live sessions only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView

from photon_cruncher.gui_aurora.server import serve_in_background
from photon_cruncher.io.loader import discover_tdt_block_paths
from photon_cruncher.product import aurora_app_title
from photon_cruncher.service import discover_data_sources


class _QuietPage(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, line, source):  # noqa: N802
        text = str(message)
        if any(token in text.lower() for token in ("error", "fail", "uncaught")):
            print(f"[aurora-js] {source}:{line} {text}")


class AuroraBridge(QtCore.QObject):
    """JS ↔ Python bridge exposed as window.auroraBridge via QWebChannel."""

    def __init__(self, window: "AuroraShellWindow") -> None:
        super().__init__(window)
        self._window = window

    @QtCore.Slot(result=str)
    def openMatDialog(self) -> str:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self._window,
            "Open MATLAB photometry export",
            "",
            "MATLAB (*.mat);;All files (*)",
        )
        return path or ""

    @QtCore.Slot(result=str)
    def selectMatFiles(self) -> str:
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self._window,
            "Add MATLAB photometry exports",
            "",
            "MATLAB (*.mat);;All files (*)",
        )
        return json.dumps(paths)

    @QtCore.Slot(result=str)
    def selectDataFolder(self) -> str:
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self._window,
            "Add folder containing MAT files or TDT blocks",
            "",
        )
        if not folder:
            return "[]"
        return json.dumps([str(path) for path in discover_data_sources(folder)])

    @QtCore.Slot(result=str)
    def selectTdtTank(self) -> str:
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self._window,
            "Add TDT tank folder",
            "",
        )
        if not folder:
            return "[]"
        return json.dumps(
            [str(path.resolve()) for path in discover_tdt_block_paths(Path(folder))]
        )

    @QtCore.Slot(result=str)
    def openTdtDialog(self) -> str:
        path = QtWidgets.QFileDialog.getExistingDirectory(
            self._window,
            "Open TDT block folder",
            "",
        )
        return path or ""

    @QtCore.Slot(result=str)
    def savedExportDir(self) -> str:
        settings = QtCore.QSettings()
        saved = str(
            settings.value(
                "export/output_dir",
                settings.value("output_dir", ""),
            )
            or ""
        )
        return saved or str(Path.home() / "photometry_exports")

    @QtCore.Slot(str, result=str)
    def chooseExportDir(self, start_dir: str = "") -> str:
        initial = start_dir.strip() or self.savedExportDir()
        path = QtWidgets.QFileDialog.getExistingDirectory(
            self._window,
            "Choose export folder",
            initial,
        )
        if path:
            settings = QtCore.QSettings()
            settings.setValue("export/output_dir", path)
            settings.setValue("output_dir", path)
        return path or ""

    @QtCore.Slot(result=str)
    def savedProcessingSettings(self) -> str:
        settings = QtCore.QSettings()
        defaults: dict[str, Any] = {
            "trange_start": -2.0,
            "trange_end": 5.0,
            "baseline_start": -3.0,
            "baseline_end": -1.0,
            "baseline_adjust": -2.0,
            "downsample_factor": 10,
            "plot_smoothed": True,
            "baseline_correction": True,
            "use_isosbestic": True,
            "polynomial_degree": 1,
            "channel_smoothing": {},
        }
        raw = str(settings.value("processing/settings_json", "") or "")
        if raw:
            try:
                saved = json.loads(raw)
                if isinstance(saved, dict):
                    defaults.update(saved)
            except (TypeError, ValueError):
                pass
        else:
            legacy_keys = {
                "trange_start": "processing/trange_start",
                "trange_end": "processing/trange_end",
                "baseline_start": "processing/baseline_start",
                "baseline_end": "processing/baseline_end",
                "baseline_adjust": "processing/base_adjust",
                "downsample_factor": "processing/downsample_factor",
                "plot_smoothed": "processing/plot_smooth",
                "baseline_correction": "processing/set_baseline",
                "use_isosbestic": "processing/use_isosbestic",
                "polynomial_degree": "processing/polynomial_degree",
            }
            for key, legacy_key in legacy_keys.items():
                value = settings.value(legacy_key)
                if value is not None:
                    if key in {
                        "plot_smoothed",
                        "baseline_correction",
                        "use_isosbestic",
                    }:
                        value = (
                            value
                            if isinstance(value, bool)
                            else str(value).lower() in {"1", "true", "yes", "on"}
                        )
                    elif key in {"downsample_factor", "polynomial_degree"}:
                        value = int(value)
                    else:
                        value = float(value)
                    defaults[key] = value
            smoothing_prefix = "processing/channel_smooth/"
            defaults["channel_smoothing"] = {
                key.removeprefix(smoothing_prefix): int(settings.value(key))
                for key in settings.allKeys()
                if key.startswith(smoothing_prefix)
            }
        return json.dumps(defaults)

    @QtCore.Slot(str)
    def saveProcessingSettings(self, settings_json: str) -> None:
        try:
            payload = json.loads(settings_json or "{}")
        except (TypeError, ValueError):
            return
        if isinstance(payload, dict):
            settings = QtCore.QSettings()
            settings.setValue(
                "processing/settings_json",
                json.dumps(payload, sort_keys=True),
            )
            legacy_values = {
                "processing/trange_start": payload.get("trange_start"),
                "processing/trange_end": payload.get("trange_end"),
                "processing/baseline_start": payload.get("baseline_start"),
                "processing/baseline_end": payload.get("baseline_end"),
                "processing/base_adjust": payload.get("baseline_adjust"),
                "processing/downsample_factor": payload.get("downsample_factor"),
                "processing/plot_smooth": payload.get("plot_smoothed"),
                "processing/set_baseline": payload.get("baseline_correction"),
                "processing/use_isosbestic": payload.get("use_isosbestic"),
                "processing/polynomial_degree": payload.get("polynomial_degree"),
            }
            for key, value in legacy_values.items():
                if value is not None:
                    settings.setValue(key, value)
            smoothing = payload.get("channel_smoothing") or {}
            if isinstance(smoothing, dict):
                for channel, value in smoothing.items():
                    settings.setValue(
                        f"processing/channel_smooth/{channel}",
                        value,
                    )

    @QtCore.Slot(str, result=str)
    def openSession(self, path: str) -> str:
        try:
            payload = self._window.open_session_path(path, notify_ui=False)
            return json.dumps(payload)
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"ok": False, "error": str(exc)})

    @QtCore.Slot(str, result=str)
    def analyze(self, request_json: str) -> str:
        try:
            body = json.loads(request_json or "{}")
            payload = self._window.api("POST", "/api/analyze", body)
            return json.dumps(payload)
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"ok": False, "error": str(exc)})

    @QtCore.Slot(str, result=str)
    def export(self, request_json: str) -> str:
        try:
            body = json.loads(request_json or "{}")
            payload = self._window.api("POST", "/api/export", body)
            return json.dumps(payload)
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"ok": False, "error": str(exc)})

    @QtCore.Slot(result=str)
    def health(self) -> str:
        try:
            return json.dumps(self._window.api("GET", "/api/health"))
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"ok": False, "error": str(exc)})

    @QtCore.Slot(str)
    def setStatus(self, message: str) -> None:
        self._window.statusBar().showMessage(message, 6000)


class AuroraShellWindow(QtWidgets.QMainWindow):
    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int | None = None,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(aurora_app_title())
        self.resize(1480, 940)
        self.setMinimumSize(1180, 760)
        self.setStyleSheet("QMainWindow { background: #05060c; }")

        self._host = host
        self._httpd, self._thread, bound_port = serve_in_background(host=host, port=port)
        self._port = bound_port
        self._base_url = f"http://{host}:{bound_port}"
        self._session_path: str | None = None

        self.view = QWebEngineView(self)
        page = _QuietPage(self.view)
        self.view.setPage(page)
        settings = self.view.settings()
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True
        )
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True
        )
        self.setCentralWidget(self.view)

        self._bridge = AuroraBridge(self)
        self._channel = QWebChannel(self.view.page())
        self._channel.registerObject("auroraBridge", self._bridge)
        self.view.page().setWebChannel(self._channel)

        self._status = self.statusBar()
        self._status.setStyleSheet(
            "QStatusBar { background: #0b1220; color: #8ba3b8; "
            "border-top: 1px solid #1b2a3a; }"
        )
        self._status.showMessage(f"Backend {self._base_url} · photon_cruncher.service")

        self._build_menu()
        self.view.loadFinished.connect(self._on_load_finished)
        self._load_ui()

    def api(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json"} if body is not None else {}
        request = Request(
            f"{self._base_url}{path}",
            data=data,
            method=method,
            headers=headers,
        )
        with urlopen(request, timeout=300) as response:
            return json.loads(response.read().decode("utf-8"))

    def _build_menu(self) -> None:
        menu = self.menuBar()
        menu.setStyleSheet(
            """
            QMenuBar { background: #0b1220; color: #e8f7ff; padding: 2px; }
            QMenuBar::item:selected { background: #12343a; }
            QMenu { background: #0f1724; color: #e8f7ff; border: 1px solid #1f3347; }
            QMenu::item:selected { background: #164e56; }
            """
        )

        file_menu = menu.addMenu("&File")
        open_mat = file_menu.addAction("Open MAT File…")
        open_mat.setShortcut(QtGui.QKeySequence.StandardKey.Open)
        open_mat.triggered.connect(self.open_mat_file)

        open_tdt = file_menu.addAction("Open TDT Block Folder…")
        open_tdt.triggered.connect(self.open_tdt_block)

        file_menu.addSeparator()
        analyze = file_menu.addAction("Re-analyze Current Settings")
        analyze.setShortcut(QtGui.QKeySequence("Ctrl+R"))
        analyze.triggered.connect(lambda: self._send_to_ui({"type": "reanalyze"}))

        export_action = file_menu.addAction("Export Current…")
        export_action.setShortcut(QtGui.QKeySequence("Ctrl+E"))
        export_action.triggered.connect(lambda: self._send_to_ui({"type": "export"}))

        file_menu.addSeparator()
        close_session = file_menu.addAction("Close Session")
        close_session.triggered.connect(self.close_session)

        file_menu.addSeparator()
        quit_action = file_menu.addAction("Quit")
        quit_action.setShortcut(QtGui.QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(QtWidgets.QApplication.instance().quit)

        view_menu = menu.addMenu("&View")
        reload_action = view_menu.addAction("Reload UI")
        reload_action.setShortcut(QtGui.QKeySequence.StandardKey.Refresh)
        reload_action.triggered.connect(self._load_ui)
        for name, page in (
            ("Ingest", "data"),
            ("Align", "align"),
            ("Spectrum", "trials"),
            ("Launch", "batch"),
        ):
            action = view_menu.addAction(name)
            action.triggered.connect(lambda _=False, p=page: self._goto_page(p))

        help_menu = menu.addMenu("&Help")
        health = help_menu.addAction("Backend Health")
        health.triggered.connect(self.show_health)
        about = help_menu.addAction("About Aurora")
        about.triggered.connect(self.show_about)

    def _load_ui(self) -> None:
        self.view.load(QtCore.QUrl(f"{self._base_url}/index.html?shell=1&app=1"))

    def _on_load_finished(self, ok: bool) -> None:
        if not ok:
            self._status.showMessage("Failed to load Aurora UI", 8000)
            return
        self._inject_shell_bootstrap()
        self._status.showMessage(f"Aurora ready · {self._base_url}", 4000)

    def _inject_shell_bootstrap(self) -> None:
        js = """
        (() => {
          function attach() {
            if (typeof qt === 'undefined' || !qt.webChannelTransport) {
              setTimeout(attach, 50);
              return;
            }
            new QWebChannel(qt.webChannelTransport, function(channel) {
              window.auroraBridge = channel.objects.auroraBridge;
              window.AuroraShell = window.AuroraShell || {};
              window.AuroraShell.native = true;
              window.AuroraShell.bridge = window.auroraBridge;
              window.AuroraShell.receive = function(message) {
                if (window.Aurora && typeof window.Aurora.onShellMessage === 'function') {
                  window.Aurora.onShellMessage(message);
                  return true;
                }
                return false;
              };
              document.documentElement.classList.add('aurora-shell');
              if (window.Aurora && typeof window.Aurora.onShellReady === 'function') {
                window.Aurora.onShellReady();
              }
            });
          }
          if (!document.querySelector('script[data-qwebchannel]')) {
            var s = document.createElement('script');
            s.src = 'qrc:///qtwebchannel/qwebchannel.js';
            s.dataset.qwebchannel = '1';
            s.onload = attach;
            document.head.appendChild(s);
          } else {
            attach();
          }
          true;
        })();
        """
        self.view.page().runJavaScript(js)

    def _send_to_ui(self, message: dict[str, Any]) -> None:
        payload = json.dumps(message)
        self.view.page().runJavaScript(
            f"window.AuroraShell && window.AuroraShell.receive && "
            f"window.AuroraShell.receive({payload});"
        )

    def _goto_page(self, page: str) -> None:
        self._send_to_ui({"type": "goto", "page": page})

    def open_mat_file(self) -> None:
        path = self._bridge.openMatDialog()
        if path:
            self.open_session_path(path)

    def open_tdt_block(self) -> None:
        path = self._bridge.openTdtDialog()
        if path:
            self.open_session_path(path)

    def open_session_path(
        self,
        path: str,
        *,
        notify_ui: bool = True,
    ) -> dict[str, Any]:
        self._status.showMessage(f"Loading {Path(path).name}…")
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        try:
            payload = self.api("POST", "/api/open", {"path": path})
            if not payload.get("ok"):
                raise RuntimeError(payload.get("error") or "open failed")
            self._session_path = payload.get("path") or path
            if notify_ui:
                self._send_to_ui(
                    {
                        "type": "session",
                        "path": self._session_path,
                        "session": payload["session"],
                        "toast": f"Loaded {Path(str(self._session_path)).name}",
                    }
                )
            self._status.showMessage(
                f"Loaded {Path(str(self._session_path)).name}", 5000
            )
            return payload
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

    def close_session(self) -> None:
        try:
            self.api("POST", "/api/close", {})
        except Exception:
            pass
        self._session_path = None
        self._send_to_ui({"type": "close", "toast": "Session closed"})
        self._status.showMessage("Session closed", 3000)

    def show_health(self) -> None:
        try:
            health = self.api("GET", "/api/health")
            QtWidgets.QMessageBox.information(
                self, "Backend health", json.dumps(health, indent=2)
            )
        except URLError as exc:
            QtWidgets.QMessageBox.warning(self, "Backend health", str(exc))

    def show_about(self) -> None:
        QtWidgets.QMessageBox.about(
            self,
            "Aurora",
            (
                f"{aurora_app_title()}\n\n"
                "Desktop app: Qt WebEngine shell + Aurora UI.\n"
                "Analysis backend: photon_cruncher.service (shared with CLI).\n"
            ),
        )

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # noqa: N802
        try:
            self._httpd.shutdown()
            self._httpd.server_close()
        except Exception:
            pass
        super().closeEvent(event)


def run_shell(*, host: str = "127.0.0.1", port: int | None = None) -> int:
    QtCore.QCoreApplication.setAttribute(
        QtCore.Qt.ApplicationAttribute.AA_ShareOpenGLContexts
    )
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    app.setApplicationName("Photon Cruncher Aurora")
    app.setOrganizationName("PhotonCruncher")
    try:
        from photon_cruncher.product import set_app_icon

        set_app_icon(app)
    except Exception:
        pass

    window = AuroraShellWindow(host=host, port=port)
    window.show()
    return app.exec()
