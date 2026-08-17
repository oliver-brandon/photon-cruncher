"""Native desktop shell for Aurora (PySide6 + Qt WebEngine).

Desktop window for the Aurora web UI with native file dialogs and the shared
analysis service. Live sessions only.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView

from photon_cruncher import __version__
from photon_cruncher.gui_aurora.server import serve_in_background
from photon_cruncher.io.loader import discover_tdt_block_paths, is_tdt_block_path
from photon_cruncher.product import aurora_app_title
from photon_cruncher.service import discover_data_sources
from photon_cruncher.updates import (
    UpdateSnapshot,
    UpdateState,
    create_update_service,
    update_channel,
    velopack_runtime_available,
)


WINDOW_GEOMETRY_KEY = "window/geometry"


def restore_window_geometry(
    window: QtWidgets.QWidget,
    settings: QtCore.QSettings | None = None,
) -> bool:
    """Restore the last native window size, position, and maximized state."""
    saved = (settings or QtCore.QSettings()).value(WINDOW_GEOMETRY_KEY)
    if not saved:
        return False
    try:
        return bool(window.restoreGeometry(saved))
    except (TypeError, ValueError):
        return False


def save_window_geometry(
    window: QtWidgets.QWidget,
    settings: QtCore.QSettings | None = None,
) -> None:
    """Persist native window geometry for the next launch."""
    target = settings or QtCore.QSettings()
    target.setValue(WINDOW_GEOMETRY_KEY, window.saveGeometry())
    target.sync()


def _paths_from_tdt_selection(folders: list[str] | list[Path] | list[str | Path]) -> list[str]:
    """Expand selected tanks/blocks into unique TDT block paths."""
    resolved: list[str] = []
    seen: set[str] = set()
    for folder in folders:
        root = Path(folder).expanduser()
        if not root.exists():
            continue
        blocks = discover_tdt_block_paths(root)
        if not blocks and is_tdt_block_path(root):
            blocks = [root.resolve()]
        for block in blocks:
            key = str(block.resolve())
            if key not in seen:
                seen.add(key)
                resolved.append(key)
    return resolved


def _pick_directories(
    parent: QtWidgets.QWidget | None,
    title: str,
    *,
    multiple: bool = True,
) -> list[str]:
    """Folder picker. When multiple=True, use a non-native dialog with multi-select."""
    if not multiple:
        path = QtWidgets.QFileDialog.getExistingDirectory(parent, title, "")
        return [path] if path else []

    dialog = QtWidgets.QFileDialog(parent, title)
    dialog.setFileMode(QtWidgets.QFileDialog.FileMode.Directory)
    dialog.setOption(QtWidgets.QFileDialog.Option.ShowDirsOnly, True)
    # Native macOS/Windows pickers usually allow only one directory.
    dialog.setOption(QtWidgets.QFileDialog.Option.DontUseNativeDialog, True)
    dialog.setOption(QtWidgets.QFileDialog.Option.ReadOnly, True)

    # Enable multi-select on the embedded list/tree views.
    for view in dialog.findChildren(QtWidgets.QListView) + dialog.findChildren(
        QtWidgets.QTreeView
    ):
        view.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)

    if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
        return []
    return [str(Path(path)) for path in dialog.selectedFiles() if path]


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
        """Multi-select MAT files. Returns JSON list of paths (may be empty)."""
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self._window,
            "Open MATLAB photometry exports",
            "",
            "MATLAB (*.mat);;All files (*)",
        )
        return json.dumps(paths)

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
        folders = _pick_directories(
            self._window,
            "Add TDT tank folder(s) — multi-select supported",
            multiple=True,
        )
        return json.dumps(_paths_from_tdt_selection(folders))

    @QtCore.Slot(result=str)
    def openTdtDialog(self) -> str:
        """Multi-select TDT tanks/blocks. Tanks expand to nested blocks. JSON list."""
        folders = _pick_directories(
            self._window,
            "Open TDT tank or block folder(s) — multi-select supported",
            multiple=True,
        )
        return json.dumps(_paths_from_tdt_selection(folders))

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

    @QtCore.Slot(result=str)
    def savedAnalysisPresets(self) -> str:
        return str(QtCore.QSettings().value("processing/presets_json", "{}") or "{}")

    @QtCore.Slot(str)
    def saveAnalysisPresets(self, presets_json: str) -> None:
        try:
            payload = json.loads(presets_json or "{}")
        except (TypeError, ValueError):
            return
        if isinstance(payload, dict):
            QtCore.QSettings().setValue(
                "processing/presets_json",
                json.dumps(payload, sort_keys=True),
            )

    @QtCore.Slot(result=str)
    def openAnalysisPresetFile(self) -> str:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self._window,
            "Import analysis preset",
            "",
            "Photon Cruncher preset (*.json);;JSON files (*.json)",
        )
        if not path:
            return ""
        return Path(path).read_text(encoding="utf-8")

    @QtCore.Slot(str, result=str)
    def saveAnalysisPresetFile(self, request_json: str) -> str:
        request = json.loads(request_json or "{}")
        name = str(request.get("name") or "analysis-preset").strip()
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.")
        suggested = f"{safe_name or 'analysis-preset'}.json"
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self._window,
            "Export analysis preset",
            suggested,
            "Photon Cruncher preset (*.json);;JSON files (*.json)",
        )
        if not path:
            return ""
        Path(path).write_text(
            json.dumps(request.get("preset") or {}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return path

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


class _UpdateTaskSignals(QtCore.QObject):
    finished = QtCore.Signal(object)
    failed = QtCore.Signal(str)
    progress = QtCore.Signal(int)


class _UpdateTask(QtCore.QRunnable):
    def __init__(self, operation, *, with_progress: bool = False) -> None:
        super().__init__()
        self.operation = operation
        self.with_progress = with_progress
        self.signals = _UpdateTaskSignals()

    @QtCore.Slot()
    def run(self) -> None:
        try:
            if self.with_progress:
                result = self.operation(self.signals.progress.emit)
            else:
                result = self.operation()
            self.signals.finished.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.signals.failed.emit(str(exc))


class UpdateDialog(QtWidgets.QDialog):
    installRequested = QtCore.Signal()

    def __init__(
        self,
        snapshot: UpdateSnapshot,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._busy = False
        self.setWindowTitle("Photon Cruncher update")
        self.setModal(True)
        self.setMinimumWidth(520)
        self.resize(580, 430)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(14)

        self.heading = QtWidgets.QLabel()
        heading_font = self.heading.font()
        heading_font.setPointSize(17)
        heading_font.setBold(True)
        self.heading.setFont(heading_font)
        layout.addWidget(self.heading)

        self.version_detail = QtWidgets.QLabel()
        self.version_detail.setStyleSheet("color: #587083;")
        layout.addWidget(self.version_detail)

        notes_label = QtWidgets.QLabel("What's new")
        notes_label.setStyleSheet("font-weight: 600;")
        layout.addWidget(notes_label)

        self.notes = QtWidgets.QTextBrowser()
        self.notes.setOpenExternalLinks(False)
        self.notes.setMinimumHeight(180)
        layout.addWidget(self.notes, 1)

        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.hide()
        layout.addWidget(self.progress)

        buttons = QtWidgets.QDialogButtonBox()
        self.later_button = buttons.addButton(
            "Later", QtWidgets.QDialogButtonBox.ButtonRole.RejectRole
        )
        self.install_button = buttons.addButton(
            "Install and restart",
            QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole,
        )
        self.install_button.setDefault(True)
        self.later_button.clicked.connect(self.reject)
        self.install_button.clicked.connect(self.installRequested.emit)
        layout.addWidget(buttons)

        self.set_snapshot(snapshot)

    def set_snapshot(self, snapshot: UpdateSnapshot) -> None:
        release = snapshot.release
        if release is None:
            return
        self.heading.setText(f"Aurora v{release.version} is available")
        self.version_detail.setText(
            f"Installed: v{snapshot.current_version}    Update: v{release.version}"
        )
        self.notes.setMarkdown(
            release.notes_markdown.strip() or "No release notes were provided."
        )
        self.status.setText(snapshot.message)

        busy = snapshot.state in {UpdateState.DOWNLOADING, UpdateState.INSTALLING}
        self._busy = busy
        self.install_button.setEnabled(not busy)
        self.later_button.setEnabled(not busy)
        self.progress.setVisible(
            snapshot.state
            in {UpdateState.DOWNLOADING, UpdateState.READY, UpdateState.INSTALLING}
        )
        if snapshot.progress is not None:
            self.progress.setValue(snapshot.progress)
        if snapshot.state == UpdateState.READY:
            self.install_button.setText("Install and restart")
        elif snapshot.state in {
            UpdateState.DOWNLOAD_FAILED,
            UpdateState.INSTALL_FAILED,
        }:
            self.install_button.setText("Try again")
        else:
            self.install_button.setText("Install and restart")

    def set_download_progress(self, value: int) -> None:
        self.progress.show()
        self.progress.setValue(max(0, min(100, int(value))))
        self.status.setText(f"Downloading update... {self.progress.value()}%")

    def reject(self) -> None:
        if not self._busy:
            super().reject()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # noqa: N802
        if self._busy:
            event.ignore()
            return
        super().closeEvent(event)


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
        restore_window_geometry(self)
        self.setStyleSheet("QMainWindow { background: #05060c; }")

        self._host = host
        self._httpd, self._thread, bound_port = serve_in_background(host=host, port=port)
        self._port = bound_port
        self._base_url = f"http://{host}:{bound_port}"
        self._session_path: str | None = None
        self._update_service = create_update_service()
        self._update_tasks: set[_UpdateTask] = set()
        self._update_busy = False
        self._update_dialog: UpdateDialog | None = None

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
        self._build_update_indicator()

        self._build_menu()
        self.view.loadFinished.connect(self._on_load_finished)
        self._load_ui()

        self._update_timer = QtCore.QTimer(self)
        self._update_timer.setInterval(6 * 60 * 60 * 1000)
        self._update_timer.timeout.connect(
            lambda: self.check_for_updates(manual=False)
        )
        if velopack_runtime_available():
            self._update_timer.start()
            QtCore.QTimer.singleShot(
                5000, lambda: self.check_for_updates(manual=False)
            )

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
        open_mat = file_menu.addAction("Open MAT Files…")
        open_mat.setShortcut(QtGui.QKeySequence.StandardKey.Open)
        open_mat.triggered.connect(self.open_mat_file)

        open_tdt = file_menu.addAction("Open TDT Tank / Blocks…")
        open_tdt.triggered.connect(self.open_tdt_block)

        file_menu.addSeparator()
        analyze = file_menu.addAction("Re-analyze Current Settings")
        analyze.setShortcut(QtGui.QKeySequence("Ctrl+R"))
        analyze.triggered.connect(lambda: self._send_to_ui({"type": "reanalyze"}))

        export_action = file_menu.addAction("Export Current…")
        export_action.setShortcut(QtGui.QKeySequence("Ctrl+E"))
        export_action.triggered.connect(lambda: self._send_to_ui({"type": "export"}))

        file_menu.addSeparator()
        close_session = file_menu.addAction("Clear All Imports")
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
            ("Trial Explorer", "trials"),
            ("Batch Export", "batch"),
        ):
            action = view_menu.addAction(name)
            action.triggered.connect(lambda _=False, p=page: self._goto_page(p))

        help_menu = menu.addMenu("&Help")
        check_updates = help_menu.addAction("Check for Updates…")
        check_updates.triggered.connect(
            lambda: self.check_for_updates(manual=True)
        )
        help_menu.addSeparator()
        health = help_menu.addAction("Backend Health")
        health.triggered.connect(self.show_health)
        diagnostics = help_menu.addAction("Export Diagnostic Report…")
        diagnostics.triggered.connect(self.export_diagnostic_report)
        about = help_menu.addAction("About Aurora")
        about.triggered.connect(self.show_about)

    def _build_update_indicator(self) -> None:
        self._update_indicator = QtWidgets.QToolButton(self)
        self._update_indicator.setObjectName("updateIndicator")
        self._update_indicator.setToolButtonStyle(
            QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self._update_indicator.setIcon(
            self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_BrowserReload)
        )
        self._update_indicator.setStyleSheet(
            "QToolButton { color: #d8fbff; background: #155e63; "
            "border: 1px solid #2dd4bf; border-radius: 4px; "
            "padding: 3px 8px; margin: 1px 5px; } "
            "QToolButton:hover { background: #18747a; }"
        )
        self._update_indicator.clicked.connect(self.show_update_dialog)
        self._update_indicator.hide()
        self._status.addPermanentWidget(self._update_indicator)

    def _run_update_task(
        self,
        operation,
        on_finished,
        *,
        with_progress: bool = False,
        on_progress=None,
    ) -> None:
        task = _UpdateTask(operation, with_progress=with_progress)
        self._update_tasks.add(task)

        def finish(result) -> None:
            self._update_tasks.discard(task)
            on_finished(result)

        def fail(message: str) -> None:
            self._update_tasks.discard(task)
            self._update_busy = False
            self._status.showMessage(f"Update operation failed: {message}", 8000)

        task.signals.finished.connect(finish)
        task.signals.failed.connect(fail)
        if on_progress is not None:
            task.signals.progress.connect(on_progress)
        QtCore.QThreadPool.globalInstance().start(task)

    def check_for_updates(self, *, manual: bool = False) -> None:
        if self._update_busy:
            if manual:
                self._status.showMessage("An update operation is already running.", 5000)
            return
        if not velopack_runtime_available():
            if manual:
                QtWidgets.QMessageBox.information(
                    self,
                    "Check for updates",
                    (
                        "Automatic updates are available in the installed "
                        "Aurora dev app. This source/development launch is not "
                        "managed by Velopack."
                    ),
                )
            return

        self._update_busy = True
        self._status.showMessage("Checking for Aurora dev updates...")
        self._run_update_task(
            self._update_service.check,
            lambda snapshot: self._finish_update_check(snapshot, manual=manual),
        )

    def _finish_update_check(
        self,
        snapshot: UpdateSnapshot,
        *,
        manual: bool,
    ) -> None:
        self._update_busy = False
        self._sync_update_indicator(snapshot)
        self._status.showMessage(snapshot.message, 7000)

        if snapshot.state == UpdateState.AVAILABLE:
            if manual:
                self.show_update_dialog()
            return
        if not manual:
            return
        if snapshot.state == UpdateState.CURRENT:
            QtWidgets.QMessageBox.information(
                self, "Check for updates", snapshot.message
            )
        elif snapshot.state in {UpdateState.UNAVAILABLE, UpdateState.DISABLED}:
            QtWidgets.QMessageBox.warning(
                self, "Check for updates", snapshot.message
            )

    def _sync_update_indicator(self, snapshot: UpdateSnapshot) -> None:
        if not snapshot.update_visible or snapshot.release is None:
            self._update_indicator.hide()
            return
        version = snapshot.release.version
        if snapshot.state == UpdateState.DOWNLOADING and snapshot.progress is not None:
            text = f"Updating {snapshot.progress}%"
        elif snapshot.state == UpdateState.READY:
            text = "Restart to update"
        else:
            text = f"Update {version}"
        self._update_indicator.setText(text)
        self._update_indicator.setToolTip(
            f"Aurora v{version} is available. Click for release notes."
        )
        self._update_indicator.show()

    def show_update_dialog(self) -> None:
        if self._update_dialog is not None and self._update_dialog.isVisible():
            self._update_dialog.raise_()
            self._update_dialog.activateWindow()
            return
        snapshot = self._update_service.snapshot
        if not snapshot.update_visible or snapshot.release is None:
            self.check_for_updates(manual=True)
            return
        dialog = UpdateDialog(snapshot, self)
        dialog.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.installRequested.connect(lambda: self._install_update(dialog))
        dialog.destroyed.connect(
            lambda _object=None: setattr(self, "_update_dialog", None)
        )
        self._update_dialog = dialog
        dialog.open()

    def _install_update(self, dialog: UpdateDialog) -> None:
        if self._update_busy:
            return
        if self._update_service.snapshot.state == UpdateState.READY:
            self._apply_downloaded_update(dialog)
            return

        self._update_busy = True
        release = self._update_service.snapshot.release
        if release is None:
            self._update_busy = False
            return
        downloading = UpdateSnapshot(
            UpdateState.DOWNLOADING,
            __version__,
            update_channel(),
            release=release,
            progress=0,
            message=f"Downloading Aurora v{release.version}...",
        )
        dialog.set_snapshot(downloading)
        self._sync_update_indicator(downloading)
        self._run_update_task(
            self._update_service.download,
            lambda snapshot: self._finish_update_download(snapshot, dialog),
            with_progress=True,
            on_progress=lambda value: self._show_update_progress(value, dialog),
        )

    def _show_update_progress(self, value: int, dialog: UpdateDialog) -> None:
        if dialog.isVisible():
            dialog.set_download_progress(value)
        snapshot = self._update_service.snapshot
        if snapshot.release is not None:
            progress_snapshot = UpdateSnapshot(
                UpdateState.DOWNLOADING,
                snapshot.current_version,
                snapshot.channel,
                release=snapshot.release,
                progress=int(value),
                message=snapshot.message,
            )
            self._sync_update_indicator(progress_snapshot)

    def _finish_update_download(
        self,
        snapshot: UpdateSnapshot,
        dialog: UpdateDialog,
    ) -> None:
        self._update_busy = False
        dialog.set_snapshot(snapshot)
        self._sync_update_indicator(snapshot)
        self._status.showMessage(snapshot.message, 8000)
        if snapshot.state == UpdateState.READY:
            QtCore.QTimer.singleShot(
                150, lambda: self._apply_downloaded_update(dialog)
            )

    def _apply_downloaded_update(self, dialog: UpdateDialog) -> None:
        save_window_geometry(self)
        snapshot = self._update_service.install_and_restart()
        dialog.set_snapshot(snapshot)
        self._sync_update_indicator(snapshot)
        self._status.showMessage(snapshot.message, 8000)

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
        raw = self._bridge.openMatDialog()
        try:
            paths = json.loads(raw) if raw else []
        except json.JSONDecodeError:
            paths = [raw] if raw else []
        if not paths:
            return
        self.open_mat_paths(paths)

    def open_mat_paths(self, paths: list[str]) -> None:
        if not paths:
            return
        loaded: list[dict[str, Any]] = []
        errors: list[str] = []
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        try:
            for path in paths:
                try:
                    payload = self.api("POST", "/api/open", {"path": path})
                    if not payload.get("ok"):
                        raise RuntimeError(payload.get("error") or "open failed")
                    loaded.append(
                        {
                            "path": payload.get("path") or path,
                            "session": payload["session"],
                        }
                    )
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{Path(path).name}: {exc}")
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

        if not loaded:
            QtWidgets.QMessageBox.critical(
                self,
                "Open failed",
                "\n".join(errors) or "No files could be opened.",
            )
            return

        primary = loaded[0]
        self._session_path = primary["path"]
        self._send_to_ui(
            {
                "type": "sessions",
                "paths": [item["path"] for item in loaded],
                "primary": primary,
                "sources": loaded[1:],
                "toast": (
                    f"Loaded {len(loaded)} file(s)"
                    + (f" · {len(errors)} failed" if errors else "")
                ),
            }
        )
        self._status.showMessage(f"Loaded {len(loaded)} session(s)", 6000)

    def open_tdt_block(self) -> None:
        raw = self._bridge.openTdtDialog()
        try:
            paths = json.loads(raw) if raw else []
        except json.JSONDecodeError:
            paths = [raw] if raw else []
        if not paths:
            return
        self.open_mat_paths(paths)

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
        except Exception as exc:  # noqa: BLE001 - native UI boundary
            self._status.showMessage(f"Could not clear imports: {exc}", 6000)
            return
        self._session_path = None
        self._send_to_ui({"type": "close", "toast": "Imports cleared"})
        self._status.showMessage("All imported sessions cleared", 3000)

    def show_health(self) -> None:
        try:
            health = self.api("GET", "/api/health")
            QtWidgets.QMessageBox.information(
                self, "Backend health", json.dumps(health, indent=2)
            )
        except URLError as exc:
            QtWidgets.QMessageBox.warning(self, "Backend health", str(exc))

    def export_diagnostic_report(self) -> None:
        suggested = (
            f"Photon-Cruncher-Aurora-Diagnostics-"
            f"{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
        )
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Export diagnostic report",
            str(Path.home() / suggested),
            "JSON report (*.json)",
        )
        if not path:
            return
        try:
            report = self.api("GET", "/api/diagnostics")
            snapshot = self._update_service.snapshot
            report["updater"] = {
                "state": snapshot.state.value,
                "current_version": snapshot.current_version,
                "channel": snapshot.channel,
                "available_version": (
                    snapshot.release.version if snapshot.release else None
                ),
                "message": snapshot.message,
                "runtime_available": velopack_runtime_available(),
            }
            Path(path).write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            self._status.showMessage(f"Diagnostic report saved to {path}", 8000)
            QtWidgets.QMessageBox.information(
                self,
                "Diagnostic report saved",
                (
                    f"Saved to:\n{path}\n\n"
                    "The report contains app/runtime details and recent errors, "
                    "but no raw photometry signal data."
                ),
            )
        except Exception as exc:  # noqa: BLE001 - user-facing diagnostic action
            QtWidgets.QMessageBox.warning(
                self,
                "Diagnostic export failed",
                str(exc),
            )

    def show_about(self) -> None:
        QtWidgets.QMessageBox.about(
            self,
            "Aurora",
            (
                f"{aurora_app_title()}\n\n"
                f"Version: {__version__}\n"
                f"Update channel: {update_channel()}\n\n"
                "Desktop app: Qt WebEngine shell + Aurora UI.\n"
                "Analysis backend: photon_cruncher.service (shared with CLI).\n"
            ),
        )

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # noqa: N802
        save_window_geometry(self)
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
    app.setApplicationName(aurora_app_title())
    app.setOrganizationName("PhotonCruncher")
    try:
        from photon_cruncher.product import set_app_icon

        set_app_icon(app)
    except Exception:
        pass

    window = AuroraShellWindow(host=host, port=port)
    window.show()
    return app.exec()
