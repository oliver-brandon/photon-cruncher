from __future__ import annotations

from pathlib import Path
from typing import Callable

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PySide6 import QtCore, QtWidgets

from photon_cruncher.analysis.runner import (
    AnalysisResult,
    epoc_names_for_selection,
    run_batch_custom,
)
from photon_cruncher.export.exporter import export_channel
from photon_cruncher.io.loader import discover_tdt_block_paths, load_session
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
        self.batch_tab = QtWidgets.QWidget()

        self.tabs.addTab(self.import_tab, "Import")
        self.tabs.addTab(self.visualize_tab, "Align + Visualize")
        self.tabs.addTab(self.batch_tab, "Batch Export")

        self._build_import()
        self._build_visualize()
        self._build_batch()

        self.session = None
        self._active_session_path: Path | None = None
        self.results_by_channel: dict[str, AnalysisResult] = {}
        self.channel_smooth_overrides: dict[str, int] = {}
        self.channel_smooth_inputs: dict[str, QtWidgets.QSpinBox] = {}
        self._batch_session_options: dict[
            str, tuple[tuple[str, ...], tuple[str, ...]]
        ] = {}
        self._active_worker: Worker | None = None

        self._set_run_state(is_running=False)

    def _build_import(self) -> None:
        layout = QtWidgets.QVBoxLayout()
        self.import_tab.setLayout(layout)

        import_buttons = QtWidgets.QHBoxLayout()
        self.file_picker = QtWidgets.QPushButton("Select MAT File(s)")
        self.file_picker.clicked.connect(self._select_file)
        import_buttons.addWidget(self.file_picker)
        self.tdt_folder_picker = QtWidgets.QPushButton("Select TDT Block Folder")
        self.tdt_folder_picker.clicked.connect(self._select_tdt_folder)
        import_buttons.addWidget(self.tdt_folder_picker)
        import_buttons.addStretch()
        layout.addLayout(import_buttons)

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
        splitter.setChildrenCollapsible(False)
        splitter.setCollapsible(0, False)
        self.visualize_splitter = splitter
        layout.addWidget(splitter)

        control_widget = QtWidgets.QWidget()
        control_layout = QtWidgets.QVBoxLayout()
        control_layout.setSizeConstraint(QtWidgets.QLayout.SetDefaultConstraint)
        control_widget.setLayout(control_layout)

        control_scroll = QtWidgets.QScrollArea()
        control_scroll.setWidgetResizable(True)
        control_scroll.setWidget(control_widget)
        control_scroll.setMinimumWidth(430)
        splitter.addWidget(control_scroll)

        plot_widget = QtWidgets.QWidget()
        plot_layout = QtWidgets.QVBoxLayout()
        plot_layout.setSizeConstraint(QtWidgets.QLayout.SetDefaultConstraint)
        plot_widget.setLayout(plot_layout)
        splitter.addWidget(plot_widget)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([520, 880])

        control_layout.addWidget(QtWidgets.QLabel("Preview file"))
        self.preview_file_combo = QtWidgets.QComboBox()
        self.preview_file_combo.currentIndexChanged.connect(self._on_preview_file_changed)
        control_layout.addWidget(self.preview_file_combo)

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

        channel_smooth_group = QtWidgets.QGroupBox("Channel Smoothing")
        channel_smooth_layout = QtWidgets.QFormLayout()
        channel_smooth_group.setLayout(channel_smooth_layout)
        self.channel_smooth_container = channel_smooth_group
        self.channel_smooth_layout = channel_smooth_layout
        control_layout.addWidget(channel_smooth_group)

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

        self.plot_smooth = QtWidgets.QCheckBox("Plot smoothed")
        self.plot_smooth.setChecked(True)
        settings_layout.addRow("", self.plot_smooth)

        self.set_baseline = QtWidgets.QCheckBox("Apply baseline correction")
        self.set_baseline.setChecked(True)
        settings_layout.addRow("", self.set_baseline)

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

    def _build_batch(self) -> None:
        layout = QtWidgets.QVBoxLayout()
        self.batch_tab.setLayout(layout)

        output_group = QtWidgets.QGroupBox("Export Output")
        output_layout = QtWidgets.QVBoxLayout()
        output_group.setLayout(output_layout)
        output_path_row = QtWidgets.QHBoxLayout()
        self.output_dir_input = QtWidgets.QLineEdit()
        saved_output = self.settings.value(
            "output_dir", str(Path.home() / "photometry_exports")
        )
        self.output_dir_input.setText(saved_output)
        output_path_row.addWidget(self.output_dir_input)
        self.output_dir_button = QtWidgets.QPushButton("Choose Output Folder")
        self.output_dir_button.clicked.connect(self._choose_output_dir)
        output_path_row.addWidget(self.output_dir_button)
        output_layout.addLayout(output_path_row)

        layout.addWidget(output_group)

        batch_group = QtWidgets.QGroupBox("Batch Processing")
        batch_layout = QtWidgets.QVBoxLayout()
        batch_group.setLayout(batch_layout)

        self.batch_file_list = QtWidgets.QListWidget()
        batch_layout.addWidget(QtWidgets.QLabel("Batch data sources"))
        batch_layout.addWidget(self.batch_file_list)

        batch_buttons = QtWidgets.QHBoxLayout()
        self.batch_add_files = QtWidgets.QPushButton("Add Files")
        self.batch_add_files.clicked.connect(self._add_batch_files)
        batch_buttons.addWidget(self.batch_add_files)
        self.batch_add_folder = QtWidgets.QPushButton("Add Folder")
        self.batch_add_folder.clicked.connect(self._add_batch_folder)
        batch_buttons.addWidget(self.batch_add_folder)
        self.batch_add_tdt_tank = QtWidgets.QPushButton("Add TDT Tank")
        self.batch_add_tdt_tank.clicked.connect(self._add_tdt_tank)
        batch_buttons.addWidget(self.batch_add_tdt_tank)
        self.batch_clear = QtWidgets.QPushButton("Clear")
        self.batch_clear.clicked.connect(self._clear_batch_files)
        batch_buttons.addWidget(self.batch_clear)
        batch_layout.addLayout(batch_buttons)

        batch_layout.addWidget(QtWidgets.QLabel("Epocs to include"))
        policy_row = QtWidgets.QHBoxLayout()
        policy_row.addWidget(QtWidgets.QLabel("Suffix handling"))
        self.batch_epoc_policy = QtWidgets.QComboBox()
        self.batch_epoc_policy.addItem("Exact checked epocs", "all")
        self.batch_epoc_policy.addItem(
            "Prefer A / 1_ when both exist", "prefer_left"
        )
        self.batch_epoc_policy.addItem(
            "Prefer C / 2_ when both exist", "prefer_right"
        )
        policy_row.addWidget(self.batch_epoc_policy)
        policy_row.addStretch()
        batch_layout.addLayout(policy_row)

        epoc_buttons = QtWidgets.QHBoxLayout()
        self.batch_epoc_all = QtWidgets.QPushButton("All")
        self.batch_epoc_all.clicked.connect(self._select_all_batch_epocs)
        epoc_buttons.addWidget(self.batch_epoc_all)
        self.batch_epoc_none = QtWidgets.QPushButton("None")
        self.batch_epoc_none.clicked.connect(self._clear_batch_epocs)
        epoc_buttons.addWidget(self.batch_epoc_none)
        self.batch_epoc_left_suffixes = QtWidgets.QPushButton("Only A / 1_")
        self.batch_epoc_left_suffixes.clicked.connect(
            self._select_left_suffix_batch_epocs
        )
        epoc_buttons.addWidget(self.batch_epoc_left_suffixes)
        self.batch_epoc_right_suffixes = QtWidgets.QPushButton("Only C / 2_")
        self.batch_epoc_right_suffixes.clicked.connect(
            self._select_right_suffix_batch_epocs
        )
        epoc_buttons.addWidget(self.batch_epoc_right_suffixes)
        epoc_buttons.addStretch()
        batch_layout.addLayout(epoc_buttons)

        self.batch_epoc_list = QtWidgets.QListWidget()
        self.batch_epoc_list.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        batch_layout.addWidget(self.batch_epoc_list)

        self.batch_run_button = QtWidgets.QPushButton("Run Batch")
        self.batch_run_button.clicked.connect(self._run_batch)
        batch_layout.addWidget(self.batch_run_button)

        self.batch_progress = QtWidgets.QLabel("")
        batch_layout.addWidget(self.batch_progress)
        layout.addWidget(batch_group)
        layout.addStretch()

    def _select_file(self) -> None:
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Select MAT File(s)", str(Path.home()), "MAT Files (*.mat)"
        )
        if not paths:
            return
        path_list = [Path(path) for path in paths]
        accepted = self._add_batch_paths(path_list, clear_existing=True)
        if accepted:
            self._set_session_from_path(accepted[0])

    def _select_tdt_folder(self) -> None:
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Select TDT Block Folder", str(Path.home())
        )
        if not folder:
            return
        path = Path(folder)
        accepted = self._add_batch_paths([path], clear_existing=True)
        if accepted:
            self._set_session_from_path(accepted[0])

    def _refresh_channels(self) -> None:
        channel_names = self._batch_channel_names()
        if not channel_names and self.session:
            channel_names = list(available_channels(self.session).keys())

        selected_channels = set(self._selected_channels())
        self.channel_list.clear()
        for idx in reversed(range(self.channel_smooth_layout.rowCount())):
            self.channel_smooth_layout.removeRow(idx)
        self.channel_smooth_inputs.clear()
        for channel in channel_names:
            item = QtWidgets.QListWidgetItem(channel)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(
                QtCore.Qt.Checked
                if not selected_channels or channel in selected_channels
                else QtCore.Qt.Unchecked
            )
            self.channel_list.addItem(item)

            default_smooth = default_settings_for_channel(channel).smooth_factor
            smooth_value = self.channel_smooth_overrides.get(channel, default_smooth)
            self.channel_smooth_overrides[channel] = smooth_value
            smooth_input = QtWidgets.QSpinBox()
            smooth_input.setRange(1, 200)
            smooth_input.setValue(smooth_value)
            smooth_input.valueChanged.connect(
                lambda value, key=channel: self._set_channel_smooth(key, value)
            )
            self.channel_smooth_inputs[channel] = smooth_input
            self.channel_smooth_layout.addRow(channel, smooth_input)

        known_channels = set(channel_names)
        self.channel_smooth_overrides = {
            key: value
            for key, value in self.channel_smooth_overrides.items()
            if key in known_channels
        }
        self.channel_smooth_container.setVisible(bool(known_channels))

    def _set_channel_smooth(self, channel_key: str, value: int) -> None:
        self.channel_smooth_overrides[channel_key] = int(value)

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
        selected_labels = set(self._selected_batch_epoc_labels())
        self.batch_epoc_list.clear()
        entries = self._batch_epoc_entries()
        if not entries and self.session:
            entries = [
                (epoc_name, (epoc_name,))
                for epoc_name in sorted(self.session.epocs.keys())
            ]
        for label, members in entries:
            item = QtWidgets.QListWidgetItem(label)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setData(QtCore.Qt.UserRole, list(members))
            item.setCheckState(
                QtCore.Qt.Checked
                if not selected_labels or label in selected_labels
                else QtCore.Qt.Unchecked
            )
            self.batch_epoc_list.addItem(item)

    def _set_batch_epoc_checks(self, should_check: Callable[[str], bool]) -> None:
        for idx in range(self.batch_epoc_list.count()):
            item = self.batch_epoc_list.item(idx)
            item.setCheckState(
                QtCore.Qt.Checked if should_check(item.text()) else QtCore.Qt.Unchecked
            )

    def _select_all_batch_epocs(self) -> None:
        self._set_batch_epoc_checks(lambda _: True)

    def _clear_batch_epocs(self) -> None:
        self._set_batch_epoc_checks(lambda _: False)

    def _select_left_suffix_batch_epocs(self) -> None:
        self._set_batch_epoc_checks(
            lambda name: self._batch_epoc_suffix_side(name) == "left"
        )

    def _select_right_suffix_batch_epocs(self) -> None:
        self._set_batch_epoc_checks(
            lambda name: self._batch_epoc_suffix_side(name) == "right"
        )

    def _refresh_preview_file_options(self) -> None:
        current_path = (
            str(self._active_session_path.resolve()) if self._active_session_path else None
        )
        self.preview_file_combo.blockSignals(True)
        self.preview_file_combo.clear()
        for idx in range(self.batch_file_list.count()):
            file_path = self.batch_file_list.item(idx).data(QtCore.Qt.UserRole)
            self.preview_file_combo.addItem(Path(file_path).name, file_path)
        if current_path:
            selected_idx = self.preview_file_combo.findData(current_path)
            if selected_idx >= 0:
                self.preview_file_combo.setCurrentIndex(selected_idx)
        self.preview_file_combo.blockSignals(False)

    def _on_preview_file_changed(self, _: int) -> None:
        file_path = self.preview_file_combo.currentData()
        if not file_path:
            return
        path = Path(file_path)
        if self._active_session_path and path.resolve() == self._active_session_path:
            return
        self._set_session_from_path(path)

    def _set_session_from_path(self, path: Path) -> None:
        self.session = load_session(path)
        self._active_session_path = path.resolve()
        self.session_label.setText(f"Loaded: {path.name}")
        self.metadata_view.setText(str(self.session.info))
        self._refresh_channels()
        self._refresh_epocs()
        self._refresh_preview_file_options()
        self._clear_results()

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

    def _selected_batch_epocs(
        self,
    ) -> list[tuple[str, tuple[str, ...]] | tuple[str, tuple[str, ...], str]]:
        selected_names: list[str] = []
        for idx in range(self.batch_epoc_list.count()):
            item = self.batch_epoc_list.item(idx)
            if item.checkState() == QtCore.Qt.Checked:
                selected_names.append(item.text())

        policy = self.batch_epoc_policy.currentData() or "all"
        if policy == "all":
            return [(name, (name,)) for name in selected_names]

        grouped: dict[tuple[str, str], list[str]] = {}
        ungrouped: list[str] = []
        for epoc_name in selected_names:
            suffix_info = self._batch_epoc_suffix_info(epoc_name)
            if suffix_info is None:
                ungrouped.append(epoc_name)
                continue
            base_name, suffix_family, _ = suffix_info
            grouped.setdefault((base_name, suffix_family), []).append(epoc_name)

        selections: list[
            tuple[str, tuple[str, ...]] | tuple[str, tuple[str, ...], str]
        ] = [(name, (name,)) for name in ungrouped]
        for (base_name, _), members in sorted(grouped.items()):
            label = (
                f"{base_name} (prefer A/1_)"
                if policy == "prefer_left"
                else f"{base_name} (prefer C/2_)"
            )
            selections.append((label, tuple(sorted(members)), policy))
        return selections

    def _selected_batch_epoc_labels(self) -> list[str]:
        labels = []
        for idx in range(self.batch_epoc_list.count()):
            item = self.batch_epoc_list.item(idx)
            if item.checkState() == QtCore.Qt.Checked:
                labels.append(item.text())
        return labels

    def _batch_paths(self) -> list[Path]:
        return [
            Path(self.batch_file_list.item(idx).data(QtCore.Qt.UserRole))
            for idx in range(self.batch_file_list.count())
        ]

    def _index_batch_path(self, path: Path) -> None:
        session = load_session(path)
        self._batch_session_options[str(path.resolve())] = (
            tuple(sorted(available_channels(session).keys())),
            tuple(sorted(session.epocs.keys())),
        )

    def _batch_channel_names(self) -> list[str]:
        channel_names = {
            channel
            for channels, _ in self._batch_session_options.values()
            for channel in channels
        }
        return sorted(channel_names)

    def _batch_epoc_suffix_info(
        self, epoc_name: str
    ) -> tuple[str, str, str] | None:
        if epoc_name.endswith("1_"):
            return epoc_name[:-2], "number_underscore", "left"
        if epoc_name.endswith("2_"):
            return epoc_name[:-2], "number_underscore", "right"
        if epoc_name.endswith("A"):
            return epoc_name[:-1], "letter", "left"
        if epoc_name.endswith("C"):
            return epoc_name[:-1], "letter", "right"
        return None

    def _batch_epoc_suffix_side(self, epoc_name: str) -> str | None:
        suffix_info = self._batch_epoc_suffix_info(epoc_name)
        return suffix_info[2] if suffix_info else None

    def _batch_epoc_entries(self) -> list[tuple[str, tuple[str, ...]]]:
        return [
            (epoc_name, (epoc_name,))
            for epoc_name in sorted(
                {
                    epoc_name
                    for _, epocs in self._batch_session_options.values()
                    for epoc_name in epocs
                }
            )
        ]

    def _build_settings_for_channel(self, channel_key: str) -> ProcessingSettings:
        settings = default_settings_for_channel(channel_key)
        settings.trange = (self.trange_start.value(), self.trange_end.value())
        settings.baseline_per = (self.baseline_start.value(), self.baseline_end.value())
        settings.base_adjust = self.base_adjust.value()
        settings.plot_smooth = self.plot_smooth.isChecked()
        settings.set_baseline = self.set_baseline.isChecked()
        settings.downsample_factor = int(self.downsample_factor.value())
        channel_smooth = self.channel_smooth_overrides.get(channel_key)
        if channel_smooth is not None:
            settings.smooth_factor = int(channel_smooth)
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
            channel_keys = self._batch_channel_names()
        if not channel_keys and self.session:
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
        grid = self.figure.add_gridspec(1, 2, width_ratios=[2, 1])
        ax_line = self.figure.add_subplot(grid[0, 0])
        ax_heatmap = self.figure.add_subplot(grid[0, 1])

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
        ax_heatmap.set_xlabel("Time (s)")
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

    def _choose_single_export_dir(self, title: str) -> Path | None:
        directory = QtWidgets.QFileDialog.getExistingDirectory(
            self, title, self.output_dir_input.text()
        )
        if not directory:
            return None
        self.output_dir_input.setText(directory)
        self.settings.setValue("output_dir", directory)
        return Path(directory).expanduser()

    def _export_csv(self) -> None:
        if not self.results_by_channel:
            self._show_error("Run preview first to generate results.")
            return
        output_dir = self._choose_single_export_dir("Choose Folder for CSV Export")
        if output_dir is None:
            return
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
        output_dir = self._choose_single_export_dir("Choose Folder for Figure Export")
        if output_dir is None:
            return
        output_dir.mkdir(parents=True, exist_ok=True)
        for result in self.results_by_channel.values():
            self._save_figures(output_dir, result)
        self.status_bar.showMessage(f"Figures exported to {output_dir}")

    def _save_figures(self, output_dir: Path, result: AnalysisResult) -> None:
        fig = Figure(figsize=(10, 4.5))
        grid = fig.add_gridspec(1, 2, width_ratios=[2, 1])
        ax_line = fig.add_subplot(grid[0, 0])
        ax_heatmap = fig.add_subplot(grid[0, 1])

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
        ax_heatmap.set_xlabel("Time (s)")
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
            self, "Select Folder Containing MAT Files or TDT Blocks", str(Path.home())
        )
        if not folder:
            return
        paths = self._discover_data_sources(Path(folder))
        self._add_batch_paths(paths)

    def _add_tdt_tank(self) -> None:
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Select TDT Tank Folder", str(Path.home())
        )
        if not folder:
            return
        paths = discover_tdt_block_paths(Path(folder))
        if not paths:
            self._show_error(f"No TDT blocks found in {Path(folder).name}.")
            return
        self._add_batch_paths(paths)

    def _discover_data_sources(self, folder: Path) -> list[Path]:
        paths = list(sorted(folder.glob("*.mat")))
        paths.extend(discover_tdt_block_paths(folder))
        return paths

    def _add_batch_paths(
        self,
        paths: list[Path],
        clear_existing: bool = False,
    ) -> list[Path]:
        if clear_existing:
            self.batch_file_list.clear()
            self._batch_session_options.clear()
        existing = {
            self.batch_file_list.item(idx).data(QtCore.Qt.UserRole)
            for idx in range(self.batch_file_list.count())
        }
        accepted: list[Path] = []
        for path in paths:
            resolved = str(path.resolve())
            if resolved in existing:
                continue
            try:
                self._index_batch_path(path)
            except Exception as exc:
                self._show_error(f"Could not load {path.name}: {exc}")
                continue
            item = QtWidgets.QListWidgetItem(path.name)
            item.setToolTip(resolved)
            item.setData(QtCore.Qt.UserRole, resolved)
            self.batch_file_list.addItem(item)
            existing.add(resolved)
            accepted.append(path)

        self._refresh_channels()
        self._refresh_batch_epocs()
        self._refresh_preview_file_options()
        if self.session is None and self.batch_file_list.count() > 0:
            first_path = Path(self.batch_file_list.item(0).data(QtCore.Qt.UserRole))
            self._set_session_from_path(first_path)
        return accepted

    def _clear_batch_files(self) -> None:
        self.batch_file_list.clear()
        self._batch_session_options.clear()
        self.preview_file_combo.clear()
        self.session = None
        self._active_session_path = None
        self.session_label.setText("No session loaded")
        self.metadata_view.clear()
        self.epoc_combo.clear()
        self.batch_epoc_list.clear()
        self.channel_list.clear()
        self._clear_results()

    def _run_batch(self) -> None:
        if self.batch_file_list.count() == 0:
            self._show_error("Add batch files before running.")
            return
        if not self.session:
            first_path = Path(self.batch_file_list.item(0).data(QtCore.Qt.UserRole))
            self._set_session_from_path(first_path)

        input_paths = self._batch_paths()
        epoc_selections = self._selected_batch_epocs()
        if not epoc_selections:
            self._show_error("Select at least one epoc for batch processing.")
            return

        def task() -> str:
            output_dir = Path(self.output_dir_input.text()).expanduser()
            output_dir.mkdir(parents=True, exist_ok=True)

            run_batch_custom(
                input_paths=input_paths,
                epoc_selections=epoc_selections,
                output_dir=output_dir,
                channel_keys=channel_keys,
                settings_factory=self._build_settings_for_channel,
                export_summary=False,
                per_session_subdir=True,
            )
            skipped: dict[str, list[str]] = {}
            for path in input_paths:
                session = load_session(path)
                combined: list[str] = []
                for selection in epoc_selections:
                    label = selection[0]
                    selected_members = epoc_names_for_selection(session, selection)
                    if not selected_members:
                        combined.append(label)
                        continue
                    if all(
                        session.epocs[epoc].onset.size == 0
                        for epoc in selected_members
                    ):
                        combined.append(label)
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
            channel_keys = self._batch_channel_names()
        if not channel_keys and self.session:
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
