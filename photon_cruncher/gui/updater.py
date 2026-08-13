"""Qt controls for the stable Photon Cruncher updater."""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from photon_cruncher import __version__
from photon_cruncher.updates import (
    UpdateService,
    UpdateSnapshot,
    UpdateState,
    create_update_service,
    velopack_runtime_available,
)


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
        self.heading.setText(f"Photon Cruncher v{release.version} is available")
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
        if snapshot.state in {
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


class UpdateController(QtCore.QObject):
    """Attach automatic and manual update controls to a main window."""

    def __init__(
        self,
        window: QtWidgets.QMainWindow,
        *,
        service: UpdateService | None = None,
    ) -> None:
        super().__init__(window)
        self._window = window
        self._status = window.statusBar()
        self._update_tasks: set[_UpdateTask] = set()
        self._update_busy = False
        self._update_dialog: UpdateDialog | None = None
        self._update_service = service
        if self._update_service is None:
            try:
                self._update_service = create_update_service()
            except ValueError:
                self._update_service = None

        self._build_menu()
        self._build_update_indicator()

        self._update_timer = QtCore.QTimer(self)
        self._update_timer.setInterval(6 * 60 * 60 * 1000)
        self._update_timer.timeout.connect(
            lambda: self.check_for_updates(manual=False)
        )
        if self._update_service is not None and velopack_runtime_available():
            self._update_timer.start()
            QtCore.QTimer.singleShot(
                5000, lambda: self.check_for_updates(manual=False)
            )

    def _build_menu(self) -> None:
        help_menu = self._window.menuBar().addMenu("&Help")
        self.check_updates_action = help_menu.addAction("Check for Updates…")
        self.check_updates_action.triggered.connect(
            lambda: self.check_for_updates(manual=True)
        )

    def _build_update_indicator(self) -> None:
        self._update_indicator = QtWidgets.QToolButton(self._window)
        self._update_indicator.setToolButtonStyle(
            QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self._update_indicator.setIcon(
            self._window.style().standardIcon(
                QtWidgets.QStyle.StandardPixmap.SP_BrowserReload
            )
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
                self._status.showMessage(
                    "An update operation is already running.", 5000
                )
            return
        if self._update_service is None or not velopack_runtime_available():
            if manual:
                QtWidgets.QMessageBox.information(
                    self._window,
                    "Check for updates",
                    (
                        "Automatic updates are available in the installed "
                        "Photon Cruncher app. This source launch is not managed "
                        "by Velopack."
                    ),
                )
            return

        self._update_busy = True
        self._status.showMessage("Checking for Photon Cruncher updates...")
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
                self._window, "Check for updates", snapshot.message
            )
        elif snapshot.state in {UpdateState.UNAVAILABLE, UpdateState.DISABLED}:
            QtWidgets.QMessageBox.warning(
                self._window, "Check for updates", snapshot.message
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
            f"Photon Cruncher v{version} is available. Click for release notes."
        )
        self._update_indicator.show()

    def show_update_dialog(self) -> None:
        if self._update_dialog is not None and self._update_dialog.isVisible():
            self._update_dialog.raise_()
            self._update_dialog.activateWindow()
            return
        if self._update_service is None:
            self.check_for_updates(manual=True)
            return
        snapshot = self._update_service.snapshot
        if not snapshot.update_visible or snapshot.release is None:
            self.check_for_updates(manual=True)
            return
        dialog = UpdateDialog(snapshot, self._window)
        dialog.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.installRequested.connect(lambda: self._install_update(dialog))
        dialog.destroyed.connect(
            lambda _object=None: setattr(self, "_update_dialog", None)
        )
        self._update_dialog = dialog
        dialog.open()

    def _install_update(self, dialog: UpdateDialog) -> None:
        if self._update_busy or self._update_service is None:
            return
        if self._update_service.snapshot.state == UpdateState.READY:
            self._apply_downloaded_update(dialog)
            return

        release = self._update_service.snapshot.release
        if release is None:
            return
        self._update_busy = True
        downloading = UpdateSnapshot(
            UpdateState.DOWNLOADING,
            __version__,
            self._update_service.snapshot.channel,
            release=release,
            progress=0,
            message=f"Downloading Photon Cruncher v{release.version}...",
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
        if self._update_service is None:
            return
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
        if self._update_service is None:
            return
        snapshot = self._update_service.install_and_restart()
        dialog.set_snapshot(snapshot)
        self._sync_update_indicator(snapshot)
        self._status.showMessage(snapshot.message, 8000)
