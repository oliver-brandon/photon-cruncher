from __future__ import annotations

from pathlib import Path
from typing import Callable

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PySide6 import QtCore, QtWidgets

from photon_cruncher.analysis.runner import AnalysisResult, run_batch_custom
from photon_cruncher.export.exporter import export_channel
from photon_cruncher.io.loader import load_session
from photon_cruncher.processing.pipeline import (
    ProcessingSettings,
    available_channels,
    default_settings_for_channel,
    process_channel,
)


class WorkerSignals(QtCore.QObject):
    result = QtCore.Signal(object)
    error = QtCore.Signal(str)
    finished = QtCore.Signal()


class Worker(QtCore.QRunnable):
    def __init__(self, fn: Callable[[], object]):
        super().__init__()
        self.fn = fn
        self.signals = WorkerSignals()

    @QtCore.Slot()
    def run(self) -> None:
        try:
            result = self.fn()
        except Exception as exc:  # pragma: no cover - UI feedback
            self.signals.error.emit(str(exc))
        else:
            self.signals.result.emit(result)
        finally:
            self.signals.finished.emit()


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Photon Cruncher")
        self.resize(1400, 900)
        self.setMinimumSize(900, 700)
        self.setMaximumSize(QtCore.QSize(16777215, 16777215))

        QtCore.QCoreApplication.setOrganizationName("PhotonCruncher")
        QtCore.QCoreApplication.setApplicationName("PhotonCruncher")
        self.settings = QtCore.QSettings()

        self.thread_pool = QtCore.QThreadPool()

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding
        )
        self.setCentralWidget(self.tabs)

        self.import_tab = QtWidgets.QWidget()
        self.visualize_tab = QtWidgets.QWidget()

        self.tabs.addTab(self.import_tab, "Import")
        self.tabs.addTab(self.visualize_tab, "Align + Visualize")

        self._build_import()
        self._build_visualize()

        self.session = None
        self.results_by_channel: dict[str, AnalysisResult] = {}
        self._active_worker: Worker | None = None

        self._set_run_state(is_running=False)

    def _build_import(self) -> None:
        layout = QtWidgets.QVBoxLayout()
        self.import_tab.setLayout(layout)

        self.file_picker = QtWidgets.QPushButton("Select MAT File(s)")
        self.file_picker.clicked.connect(self._select_file)
        layout.addWidget(self.file_picker)

        self.session_label = QtWidgets.QLabel("No session loaded")
        layout.addWidget(self.session_label)

        self.metadata_view = QtWidgets.QTextEdit()
        self.metadata_view.setReadOnly(True)
        layout.addWidget(self.metadata_view)

    def _build_visualize(self) -> None:
        layout = QtWidgets.QVBoxLayout()
        layout.setSizeConstraint(QtWidgets.QLayout.SetDefaultConstraint)
        self.visualize_tab.setLayout(layout)

        splitter = QtWidgets.QSplitter()
        splitter.setOrientation(QtCore.Qt.Horizontal)
        layout.addWidget(splitter)

        control_widget = QtWidgets.QWidget()
        control_layout = QtWidgets.QVBoxLayout()
        control_layout.setSizeConstraint(QtWidgets.QLayout.SetDefaultConstraint)
        control_widget.setLayout(control_layout)

        control_scroll = QtWidgets.QScrollArea()
        control_scroll.setWidgetResizable(True)
        control_scroll.setWidget(control_widget)
        splitter.addWidget(control_scroll)

        plot_widget = QtWidgets.QWidget()
        plot_layout = QtWidgets.QVBoxLayout()
        plot_layout.setSizeConstraint(QtWidgets.QLayout.SetDefaultConstraint)
        plot_widget.setLayout(plot_layout)
        splitter.addWidget(plot_widget)
        splitter.setStretchFactor(1, 1)

        control_layout.addWidget(QtWidgets.QLabel("Reference epoc"))
        self.epoc_combo = QtWidgets.QComboBox()
        self.epoc_combo.currentTextChanged.connect(self._update_epoc_display)
        control_layout.addWidget(self.epoc_combo)
        self.epoc_display = QtWidgets.QLabel("No epoc selected")
        control_layout.addWidget(self.epoc_display)

        self.channel_list = QtWidgets.QListWidget()
        self.channel_list.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        control_layout.addWidget(QtWidgets.QLabel("Channels to analyze"))
        control_layout.addWidget(self.channel_list)

        settings_group = QtWidgets.QGroupBox("Processing Settings")
        settings_layout = QtWidgets.QFormLayout()
        settings_group.setLayout(settings_layout)

        self.trange_start = QtWidgets.QDoubleSpinBox()
        self.trange_start.setRange(-60.0, 60.0)
        self.trange_start.setDecimals(2)
        self.trange_start.setValue(-2.0)
        self.trange_end = QtWidgets.QDoubleSpinBox()
        self.trange_end.setRange(-60.0, 120.0)
        self.trange_end.setDecimals(2)
        self.trange_end.setValue(5.0)
        settings_layout.addRow("TRANGE start", self.trange_start)
        settings_layout.addRow("TRANGE end", self.trange_end)

        self.baseline_start = QtWidgets.QDoubleSpinBox()
        self.baseline_start.setRange(-60.0, 60.0)
        self.baseline_start.setDecimals(2)
        self.baseline_start.setValue(-3.0)
        self.baseline_end = QtWidgets.QDoubleSpinBox()
        self.baseline_end.setRange(-60.0, 60.0)
        self.baseline_end.setDecimals(2)
        self.baseline_end.setValue(-1.0)
        settings_layout.addRow("Baseline start", self.baseline_start)
        settings_layout.addRow("Baseline end", self.baseline_end)

        self.base_adjust = QtWidgets.QDoubleSpinBox()
        self.base_adjust.setRange(-120.0, 0.0)
        self.base_adjust.setDecimals(1)
        self.base_adjust.setValue(-2.0)
        settings_layout.addRow("Baseline adjust", self.base_adjust)

        self.downsample_factor = QtWidgets.QSpinBox()
        self.downsample_factor.setRange(1, 200)
        self.downsample_factor.setValue(10)
        settings_layout.addRow("Downsample factor", self.downsample_factor)

        self.smooth_factor = QtWidgets.QSpinBox()
        self.smooth_factor.setRange(1, 200)
        self.smooth_factor.setValue(10)
        settings_layout.addRow("Smooth factor", self.smooth_factor)

        self.use_channel_smooth = QtWidgets.QCheckBox("Use channel default smoothing")
        self.use_channel_smooth.setChecked(True)
        settings_layout.addRow("", self.use_channel_smooth)

        self.plot_smooth = QtWidgets.QCheckBox("Plot smoothed")
        self.plot_smooth.setChecked(True)
        settings_layout.addRow("", self.plot_smooth)

        self.set_baseline = QtWidgets.QCheckBox("Apply baseline correction")
        self.set_baseline.setChecked(True)
        settings_layout.addRow("", self.set_baseline)

        self.artifact_405 = QtWidgets.QDoubleSpinBox()
        self.artifact_405.setRange(0.0, 1e6)
        self.artifact_405.setDecimals(2)
        self.artifact_405.setValue(1e6)
        settings_layout.addRow("Artifact 405", self.artifact_405)

        self.artifact_465 = QtWidgets.QDoubleSpinBox()
        self.artifact_465.setRange(0.0, 1e6)
        self.artifact_465.setDecimals(2)
        self.artifact_465.setValue(1e6)
        settings_layout.addRow("Artifact 465", self.artifact_465)

        control_layout.addWidget(settings_group)

        button_row = QtWidgets.QHBoxLayout()
        self.preview_button = QtWidgets.QPushButton("Preview Signals")
        self.preview_button.clicked.connect(self._preview_signals)
        button_row.addWidget(self.preview_button)

        self.export_csv_button = QtWidgets.QPushButton("Export CSV")
        self.export_csv_button.clicked.connect(self._export_csv)
        button_row.addWidget(self.export_csv_button)

        self.export_fig_button = QtWidgets.QPushButton("Export Figures")
        self.export_fig_button.clicked.connect(self._export_figures)
        button_row.addWidget(self.export_fig_button)

        control_layout.addLayout(button_row)

        folder_row = QtWidgets.QHBoxLayout()
        self.output_dir_input = QtWidgets.QLineEdit()
        saved_output = self.settings.value("output_dir", str(Path.home() / "photometry_exports"))
        self.output_dir_input.setText(saved_output)
        folder_row.addWidget(self.output_dir_input)
        self.output_dir_button = QtWidgets.QPushButton("Choose Output Folder")
        self.output_dir_button.clicked.connect(self._choose_output_dir)
        folder_row.addWidget(self.output_dir_button)
        control_layout.addLayout(folder_row)

        batch_group = QtWidgets.QGroupBox("Batch Processing")
        batch_layout = QtWidgets.QVBoxLayout()
        batch_group.setLayout(batch_layout)

        self.batch_file_list = QtWidgets.QListWidget()
        batch_layout.addWidget(QtWidgets.QLabel("Batch files (.mat)"))
        batch_layout.addWidget(self.batch_file_list)

        batch_buttons = QtWidgets.QHBoxLayout()
        self.batch_add_files = QtWidgets.QPushButton("Add Files")
        self.batch_add_files.clicked.connect(self._add_batch_files)
        batch_buttons.addWidget(self.batch_add_files)
        self.batch_add_folder = QtWidgets.QPushButton("Add Folder")
        self.batch_add_folder.clicked.connect(self._add_batch_folder)
        batch_buttons.addWidget(self.batch_add_folder)
        self.batch_clear = QtWidgets.QPushButton("Clear")
        self.batch_clear.clicked.connect(self._clear_batch_files)
        batch_buttons.addWidget(self.batch_clear)
        batch_layout.addLayout(batch_buttons)

        batch_layout.addWidget(QtWidgets.QLabel("Epocs to include"))
        self.batch_epoc_list = QtWidgets.QListWidget()
        self.batch_epoc_list.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        batch_layout.addWidget(self.batch_epoc_list)

        self.batch_run_button = QtWidgets.QPushButton("Run Batch")
        self.batch_run_button.clicked.connect(self._run_batch)
        batch_layout.addWidget(self.batch_run_button)

        self.batch_progress = QtWidgets.QLabel("")
        batch_layout.addWidget(self.batch_progress)

        control_layout.addWidget(batch_group)

        self.results_box = QtWidgets.QTextEdit()
        self.results_box.setReadOnly(True)
        control_layout.addWidget(self.results_box)

        plot_controls = QtWidgets.QHBoxLayout()
        plot_controls.addWidget(QtWidgets.QLabel("Display channel"))
        self.display_channel = QtWidgets.QComboBox()
        self.display_channel.currentTextChanged.connect(self._update_plot_for_channel)
        plot_controls.addWidget(self.display_channel)
        plot_controls.addStretch()
        plot_layout.addLayout(plot_controls)

        self.figure = Figure(figsize=(7, 6))
        self.canvas = FigureCanvas(self.figure)
        plot_layout.addWidget(self.canvas)

        self.status_bar = QtWidgets.QStatusBar()
        self.setStatusBar(self.status_bar)

    def _select_file(self) -> None:
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Select MAT File(s)", str(Path.home()), "MAT Files (*.mat)"
        )
        if not paths:
            return
        path_list = [Path(path) for path in paths]
        primary = path_list[0]
        self.session = load_session(primary)
        self.session_label.setText(f"Loaded: {primary.name}")
        self.metadata_view.setText(str(self.session.info))
        self._refresh_channels()
        self._refresh_epocs()
        self._clear_results()
        if len(path_list) > 1:
            self._add_batch_paths(path_list)

    def _refresh_channels(self) -> None:
        if not self.session:
            return
        channel_map = available_channels(self.session)
        self.channel_list.clear()
        for channel in channel_map.keys():
            item = QtWidgets.QListWidgetItem(channel)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Checked)
            self.channel_list.addItem(item)

    def _refresh_epocs(self) -> None:
        if not self.session:
            return
        self.epoc_combo.clear()
        self.epoc_combo.addItems(sorted(self.session.epocs.keys()))
        self._update_epoc_display(self.epoc_combo.currentText())
        self._refresh_batch_epocs()

    def _update_epoc_display(self, value: str) -> None:
        self.epoc_display.setText(value or "No epoc selected")

    def _refresh_batch_epocs(self) -> None:
        self.batch_epoc_list.clear()
        if not self.session:
            return
        for epoc_name in sorted(self.session.epocs.keys()):
            item = QtWidgets.QListWidgetItem(epoc_name)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Checked)
            self.batch_epoc_list.addItem(item)

    def _set_run_state(self, is_running: bool) -> None:
        self.preview_button.setEnabled(not is_running)
        self.export_csv_button.setEnabled(bool(self.results_by_channel) and not is_running)
        self.export_fig_button.setEnabled(bool(self.results_by_channel) and not is_running)
        self.batch_run_button.setEnabled(not is_running)
        self.status_bar.showMessage("Running analysis..." if is_running else "Ready")

    def _finish_run(self) -> None:
        self._set_run_state(False)
        self._active_worker = None

    def _clear_results(self) -> None:
        self.results_by_channel = {}
        self.display_channel.clear()
        self.results_box.clear()
        self.figure.clear()
        self.canvas.draw_idle()
        self._set_run_state(is_running=False)

    def _selected_channels(self) -> list[str]:
        channels = []
        for idx in range(self.channel_list.count()):
            item = self.channel_list.item(idx)
            if item.checkState() == QtCore.Qt.Checked:
                channels.append(item.text())
        return channels

    def _selected_batch_epocs(self) -> list[str]:
        epocs = []
        for idx in range(self.batch_epoc_list.count()):
            item = self.batch_epoc_list.item(idx)
            if item.checkState() == QtCore.Qt.Checked:
                epocs.append(item.text())
        return epocs

    def _build_settings_for_channel(self, channel_key: str) -> ProcessingSettings:
        settings = default_settings_for_channel(channel_key)
        settings.trange = (self.trange_start.value(), self.trange_end.value())
        settings.baseline_per = (self.baseline_start.value(), self.baseline_end.value())
        settings.base_adjust = self.base_adjust.value()
        settings.plot_smooth = self.plot_smooth.isChecked()
        settings.set_baseline = self.set_baseline.isChecked()
        settings.downsample_factor = int(self.downsample_factor.value())
        settings.artifact_405 = self.artifact_405.value()
        settings.artifact_465 = self.artifact_465.value()
        if not self.use_channel_smooth.isChecked():
            settings.smooth_factor = int(self.smooth_factor.value())
        return settings

    def _preview_signals(self) -> None:
        if not self.session:
            self.results_box.setText("Load a session first.")
            return
        epoc_name = self.epoc_combo.currentText()
        if not epoc_name:
            self.results_box.setText("Select an epoc.")
            return

        channel_keys = self._selected_channels()
        if not channel_keys:
            channel_keys = list(available_channels(self.session).keys())
        if not channel_keys:
            self.results_box.setText("No channels available.")
            return

        def task() -> list[AnalysisResult]:
            if epoc_name not in self.session.epocs:
                raise ValueError(f"Epoc '{epoc_name}' not found.")
            epoc = self.session.epocs[epoc_name]
            channel_map = available_channels(self.session)
            results: list[AnalysisResult] = []
            for channel_key in channel_keys:
                if channel_key not in channel_map:
                    continue
                iso_stream, signal_stream, _ = channel_map[channel_key]
                settings = self._build_settings_for_channel(channel_key)
                processed = process_channel(
                    self.session, iso_stream, signal_stream, epoc, settings
                )
                results.append(
                    AnalysisResult(
                        session=self.session,
                        epoc=epoc,
                        channel_key=channel_key,
                        processed=processed,
                        settings=settings,
                        stream_store=(iso_stream, signal_stream),
                    )
                )
            return results

        def handle_results(results: list[AnalysisResult]) -> None:
            self.results_by_channel = {result.channel_key: result for result in results}
            self.display_channel.blockSignals(True)
            self.display_channel.clear()
            self.display_channel.addItems(list(self.results_by_channel.keys()))
            self.display_channel.blockSignals(False)

            summary = [
                f"{result.channel_key}: trials={result.processed.zall.shape[0]}"
                for result in results
            ]
            self.results_box.setText("\n".join(summary) or "No results.")
            if results:
                self.display_channel.setCurrentText(results[0].channel_key)
                self._plot_result(results[0])
            self._finish_run()

        worker = Worker(task)
        worker.setAutoDelete(False)
        worker.signals.result.connect(handle_results)
        worker.signals.error.connect(self._show_error)
        worker.signals.finished.connect(self._finish_run)
        self._set_run_state(True)
        self._active_worker = worker
        self.thread_pool.start(worker)

    def _update_plot_for_channel(self, channel_key: str) -> None:
        if not channel_key:
            return
        result = self.results_by_channel.get(channel_key)
        if result:
            self._plot_result(result)

    def _plot_result(self, result: AnalysisResult) -> None:
        self.figure.clear()
        ax_heatmap = self.figure.add_subplot(2, 1, 1)
        ax_line = self.figure.add_subplot(2, 1, 2)

        processed = result.processed
        ts = processed.ts
        if result.settings.plot_smooth:
            z_data = processed.zall_smooth
            mean = processed.mean_z_smooth
            sem = processed.sem_z_smooth
        else:
            z_data = processed.zall
            mean = processed.mean_z
            sem = processed.sem_z

        heatmap = ax_heatmap.imshow(
            z_data,
            aspect="auto",
            origin="lower",
            extent=[ts[0], ts[-1], 1, z_data.shape[0]],
            cmap="viridis",
            interpolation="nearest",
        )
        ax_heatmap.set_title(f"{result.channel_key} z-score heatmap")
        ax_heatmap.set_ylabel("Trial")
        self.figure.colorbar(heatmap, ax=ax_heatmap, orientation="vertical")

        ax_line.plot(ts, mean, color="#1f77b4", linewidth=2, label="Mean z")
        ax_line.fill_between(
            ts, mean - sem, mean + sem, color="#1f77b4", alpha=0.2, label="SEM"
        )
        ax_line.axvline(0, color="#222222", linestyle="--", linewidth=1)
        ax_line.set_xlabel("Time (s)")
        ax_line.set_ylabel("Z-score")
        ax_line.set_title("Mean ± SEM")
        ax_line.legend(loc="upper right")

        self.figure.tight_layout()
        self.canvas.draw_idle()

    def _choose_output_dir(self) -> None:
        directory = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Select Output Folder", self.output_dir_input.text()
        )
        if directory:
            self.output_dir_input.setText(directory)
            self.settings.setValue("output_dir", directory)

    def _export_csv(self) -> None:
        if not self.results_by_channel:
            self._show_error("Run preview first to generate results.")
            return
        output_dir = Path(self.output_dir_input.text()).expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)
        for result in self.results_by_channel.values():
            export_channel(
                output_dir=output_dir,
                session_name=result.session.source_path.stem,
                epoc_name=result.epoc.name,
                channel_key=result.channel_key,
                processed=result.processed,
                settings=result.settings,
                dropped_trials=[],
                stream_store=result.stream_store,
                metadata={
                    "source_path": str(result.session.source_path),
                    **result.session.info,
                },
                export_smoothed=result.settings.plot_smooth,
            )
        self.status_bar.showMessage(f"CSV exported to {output_dir}")

    def _export_figures(self) -> None:
        if not self.results_by_channel:
            self._show_error("Run preview first to generate results.")
            return
        output_dir = Path(self.output_dir_input.text()).expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)
        for result in self.results_by_channel.values():
            self._save_figures(output_dir, result)
        self.status_bar.showMessage(f"Figures exported to {output_dir}")

    def _save_figures(self, output_dir: Path, result: AnalysisResult) -> None:
        fig = Figure(figsize=(7, 6))
        ax_heatmap = fig.add_subplot(2, 1, 1)
        ax_line = fig.add_subplot(2, 1, 2)

        processed = result.processed
        ts = processed.ts
        if result.settings.plot_smooth:
            z_data = processed.zall_smooth
            mean = processed.mean_z_smooth
            sem = processed.sem_z_smooth
        else:
            z_data = processed.zall
            mean = processed.mean_z
            sem = processed.sem_z

        heatmap = ax_heatmap.imshow(
            z_data,
            aspect="auto",
            origin="lower",
            extent=[ts[0], ts[-1], 1, z_data.shape[0]],
            cmap="viridis",
            interpolation="nearest",
        )
        ax_heatmap.set_title(f"{result.channel_key} z-score heatmap")
        ax_heatmap.set_ylabel("Trial")
        fig.colorbar(heatmap, ax=ax_heatmap, orientation="vertical")

        ax_line.plot(ts, mean, color="#1f77b4", linewidth=2, label="Mean z")
        ax_line.fill_between(
            ts, mean - sem, mean + sem, color="#1f77b4", alpha=0.2, label="SEM"
        )
        ax_line.axvline(0, color="#222222", linestyle="--", linewidth=1)
        ax_line.set_xlabel("Time (s)")
        ax_line.set_ylabel("Z-score")
        ax_line.set_title("Mean ± SEM")
        ax_line.legend(loc="upper right")

        fig.tight_layout()
        prefix = f"{result.session.source_path.stem}_{result.epoc.name}_{result.channel_key}"
        fig.savefig(output_dir / f"{prefix}_summary.png", dpi=300)

    def _add_batch_files(self) -> None:
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Select MAT Files", str(Path.home()), "MAT Files (*.mat)"
        )
        if not paths:
            return
        self._add_batch_paths([Path(path) for path in paths])

    def _add_batch_folder(self) -> None:
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Select Folder", str(Path.home())
        )
        if not folder:
            return
        paths = sorted(Path(folder).glob("*.mat"))
        self._add_batch_paths(paths)

    def _add_batch_paths(self, paths: list[Path]) -> None:
        existing = {
            self.batch_file_list.item(idx).data(QtCore.Qt.UserRole)
            for idx in range(self.batch_file_list.count())
        }
        first_loaded = False
        for path in paths:
            resolved = str(path.resolve())
            if resolved in existing:
                continue
            item = QtWidgets.QListWidgetItem(path.name)
            item.setToolTip(resolved)
            item.setData(QtCore.Qt.UserRole, resolved)
            self.batch_file_list.addItem(item)
            if self.session is None and not first_loaded:
                self.session = load_session(path)
                self.session_label.setText(f"Loaded: {path.name}")
                self.metadata_view.setText(str(self.session.info))
                self._refresh_channels()
                self._refresh_epocs()
                first_loaded = True

    def _clear_batch_files(self) -> None:
        self.batch_file_list.clear()

    def _run_batch(self) -> None:
        if self.batch_file_list.count() == 0:
            self._show_error("Add batch files before running.")
            return
        if not self.session:
            first_path = Path(self.batch_file_list.item(0).data(QtCore.Qt.UserRole))
            self.session = load_session(first_path)
            self.session_label.setText(f"Loaded: {first_path.name}")
            self.metadata_view.setText(str(self.session.info))
            self._refresh_channels()
            self._refresh_epocs()

        input_paths = [
            Path(self.batch_file_list.item(idx).data(QtCore.Qt.UserRole))
            for idx in range(self.batch_file_list.count())
        ]
        epoc_names = self._selected_batch_epocs()
        if not epoc_names:
            self._show_error("Select at least one epoc for batch processing.")
            return

        def task() -> str:
            output_dir = Path(self.output_dir_input.text()).expanduser()
            output_dir.mkdir(parents=True, exist_ok=True)
            empty_epocs: dict[str, list[str]] = {}
            for path in input_paths:
                session = load_session(path)
                empty = [
                    epoc
                    for epoc in epoc_names
                    if epoc in session.epocs and session.epocs[epoc].onset.size == 0
                ]
                if empty:
                    empty_epocs[str(path)] = empty

            run_batch_custom(
                input_paths=input_paths,
                epoc_names=epoc_names,
                output_dir=output_dir,
                channel_keys=channel_keys,
                settings_factory=self._build_settings_for_channel,
                export_summary=False,
                per_session_subdir=True,
            )
            skipped = {}
            for path in input_paths:
                session = load_session(path)
                missing = [epoc for epoc in epoc_names if epoc not in session.epocs]
                empty = [
                    epoc
                    for epoc in epoc_names
                    if epoc in session.epocs and session.epocs[epoc].onset.size == 0
                ]
                combined = missing + empty
                if combined:
                    skipped[str(path)] = combined

            if skipped:
                skipped_details = "; ".join(
                    f"{Path(path).name}: {', '.join(epocs)}"
                    for path, epocs in skipped.items()
                )
                return (
                    f"Batch export complete ({len(input_paths)} files). "
                    f"Skipped epocs: {skipped_details}"
                )
            return f"Batch export complete ({len(input_paths)} files)."

        channel_keys = self._selected_channels()
        if not channel_keys:
            channel_keys = list(available_channels(self.session).keys())

        def handle_done(message: str) -> None:
            self.batch_progress.setText(message)
            self.status_bar.showMessage(message)
            self._finish_run()

        worker = Worker(task)
        worker.setAutoDelete(False)
        worker.signals.result.connect(handle_done)
        worker.signals.error.connect(self._show_error)
        worker.signals.finished.connect(self._finish_run)
        self.batch_progress.setText("Running batch...")
        self._set_run_state(True)
        self._active_worker = worker
        self.thread_pool.start(worker)

    def _show_error(self, message: str) -> None:
        self.results_box.setText(message)
        if hasattr(self, "batch_progress"):
            self.batch_progress.setText(message)
        self.status_bar.showMessage(message)
