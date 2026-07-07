from __future__ import annotations

from pathlib import Path
from typing import Callable

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PySide6 import QtCore, QtWidgets

from photon_cruncher import app_title
from photon_cruncher.analysis.runner import (
    AnalysisResult,
    epoc_names_for_selection,
    run_batch_custom,
)
from photon_cruncher.analysis.trial_classifier import (
    ClassifiedTrialSource,
    classified_trial_sources,
)
from photon_cruncher.export.exporter import (
    export_channel,
    heatmap_trial_ticks,
    populate_result_figure,
    result_figure_title,
    save_result_figure,
)
from photon_cruncher.io.loader import discover_tdt_block_paths, load_session
from photon_cruncher.model import Epoc
from photon_cruncher.processing.pipeline import (
    ProcessingSettings,
    available_channels,
    default_settings_for_channel,
    process_channel,
    subset_processed_signal,
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
        self.setWindowTitle(app_title())
        self.resize(1400, 900)
        self.setMinimumSize(900, 700)
        self.setMaximumSize(QtCore.QSize(16777215, 16777215))

        QtCore.QCoreApplication.setOrganizationName("PhotonCruncher")
        QtCore.QCoreApplication.setApplicationName("PhotonCruncher")
        self.settings = QtCore.QSettings()

        self.thread_pool = QtCore.QThreadPool()
        self._preview_refresh_pending = False
        self._preview_refresh_timer = QtCore.QTimer(self)
        self._preview_refresh_timer.setSingleShot(True)
        self._preview_refresh_timer.setInterval(200)
        self._preview_refresh_timer.timeout.connect(self._run_preview_refresh)
        self.channel_smooth_overrides: dict[str, int] = {}
        self.channel_smooth_inputs: dict[str, QtWidgets.QSpinBox] = {}
        self.trial_channel_smooth_inputs: dict[str, QtWidgets.QSpinBox] = {}

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding
        )
        self.setCentralWidget(self.tabs)

        self.import_tab = QtWidgets.QWidget()
        self.visualize_tab = QtWidgets.QWidget()
        self.trial_explorer_tab = QtWidgets.QWidget()
        self.batch_tab = QtWidgets.QWidget()

        self.tabs.addTab(self.import_tab, "Import")
        self.tabs.addTab(self.visualize_tab, "Align + Visualize")
        self.tabs.addTab(self.trial_explorer_tab, "Trial Explorer")
        self.tabs.addTab(self.batch_tab, "Batch Export")

        self._build_import()
        self._build_visualize()
        self._build_trial_explorer()
        self._connect_processing_setting_persistence()
        self._build_batch()

        self.session = None
        self._active_session_path: Path | None = None
        self.results_by_channel: dict[str, AnalysisResult] = {}
        self.trial_results_by_channel: dict[str, AnalysisResult] = {}
        self.trial_sources_by_key: dict[str, ClassifiedTrialSource] = {}
        self.active_trial_source: ClassifiedTrialSource | None = None
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
        self.visualize_splitter = splitter
        layout.addWidget(splitter)

        control_widget = QtWidgets.QWidget()
        control_layout = QtWidgets.QVBoxLayout()
        control_layout.setSizeConstraint(QtWidgets.QLayout.SetDefaultConstraint)
        control_widget.setLayout(control_layout)

        control_scroll = QtWidgets.QScrollArea()
        control_scroll.setWidgetResizable(True)
        control_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
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
        self.epoc_combo.currentTextChanged.connect(self._on_preview_epoc_changed)
        control_layout.addWidget(self.epoc_combo)
        self.epoc_display = QtWidgets.QLabel("No epoc selected")
        control_layout.addWidget(self.epoc_display)

        self.channel_list = QtWidgets.QListWidget()
        self.channel_list.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.channel_list.itemChanged.connect(
            lambda _: self._request_preview_refresh()
        )
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
        self.trange_start.setValue(
            self._settings_float("processing/trange_start", -2.0)
        )
        self.trange_end = QtWidgets.QDoubleSpinBox()
        self.trange_end.setRange(-60.0, 120.0)
        self.trange_end.setDecimals(2)
        self.trange_end.setValue(self._settings_float("processing/trange_end", 5.0))
        settings_layout.addRow("TRANGE start", self.trange_start)
        settings_layout.addRow("TRANGE end after epoc", self.trange_end)

        self.baseline_start = QtWidgets.QDoubleSpinBox()
        self.baseline_start.setRange(-60.0, 60.0)
        self.baseline_start.setDecimals(2)
        self.baseline_start.setValue(
            self._settings_float("processing/baseline_start", -3.0)
        )
        self.baseline_end = QtWidgets.QDoubleSpinBox()
        self.baseline_end.setRange(-60.0, 60.0)
        self.baseline_end.setDecimals(2)
        self.baseline_end.setValue(
            self._settings_float("processing/baseline_end", -1.0)
        )
        settings_layout.addRow("Baseline start", self.baseline_start)
        settings_layout.addRow("Baseline end", self.baseline_end)

        self.base_adjust = QtWidgets.QDoubleSpinBox()
        self.base_adjust.setRange(-120.0, 0.0)
        self.base_adjust.setDecimals(1)
        self.base_adjust.setValue(
            self._settings_float("processing/base_adjust", -2.0)
        )
        settings_layout.addRow("Baseline adjust", self.base_adjust)

        self.downsample_factor = QtWidgets.QSpinBox()
        self.downsample_factor.setRange(1, 200)
        self.downsample_factor.setValue(
            self._settings_int("processing/downsample_factor", 10)
        )
        settings_layout.addRow("Downsample factor", self.downsample_factor)

        self.plot_smooth = QtWidgets.QCheckBox("Plot smoothed")
        self.plot_smooth.setChecked(self._settings_bool("processing/plot_smooth", True))
        settings_layout.addRow("", self.plot_smooth)

        self.set_baseline = QtWidgets.QCheckBox("Apply baseline correction")
        self.set_baseline.setChecked(
            self._settings_bool("processing/set_baseline", True)
        )
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

    def _build_trial_explorer(self) -> None:
        layout = QtWidgets.QVBoxLayout()
        layout.setSizeConstraint(QtWidgets.QLayout.SetDefaultConstraint)
        self.trial_explorer_tab.setLayout(layout)

        splitter = QtWidgets.QSplitter()
        splitter.setOrientation(QtCore.Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter)

        control_widget = QtWidgets.QWidget()
        control_layout = QtWidgets.QVBoxLayout()
        control_layout.setSizeConstraint(QtWidgets.QLayout.SetDefaultConstraint)
        control_widget.setLayout(control_layout)

        control_scroll = QtWidgets.QScrollArea()
        control_scroll.setWidgetResizable(True)
        control_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
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
        self.trial_file_combo = QtWidgets.QComboBox()
        self.trial_file_combo.currentIndexChanged.connect(
            self._on_trial_file_changed
        )
        control_layout.addWidget(self.trial_file_combo)

        control_layout.addWidget(QtWidgets.QLabel("Reference epoc"))
        self.trial_epoc_combo = QtWidgets.QComboBox()
        self.trial_epoc_combo.currentTextChanged.connect(
            lambda _: self._clear_trial_results()
        )
        control_layout.addWidget(self.trial_epoc_combo)

        self.trial_channel_list = QtWidgets.QListWidget()
        self.trial_channel_list.setSelectionMode(
            QtWidgets.QAbstractItemView.NoSelection
        )
        control_layout.addWidget(QtWidgets.QLabel("Channels to analyze"))
        control_layout.addWidget(self.trial_channel_list)

        trial_channel_smooth_group = QtWidgets.QGroupBox("Channel Smoothing")
        trial_channel_smooth_layout = QtWidgets.QFormLayout()
        trial_channel_smooth_group.setLayout(trial_channel_smooth_layout)
        self.trial_channel_smooth_container = trial_channel_smooth_group
        self.trial_channel_smooth_layout = trial_channel_smooth_layout
        control_layout.addWidget(trial_channel_smooth_group)

        trial_settings_group = QtWidgets.QGroupBox("Processing Settings")
        trial_settings_layout = QtWidgets.QFormLayout()
        trial_settings_group.setLayout(trial_settings_layout)

        self.trial_trange_start = QtWidgets.QDoubleSpinBox()
        self.trial_trange_start.setRange(-60.0, 60.0)
        self.trial_trange_start.setDecimals(2)
        self.trial_trange_start.setValue(self.trange_start.value())
        self.trial_trange_end = QtWidgets.QDoubleSpinBox()
        self.trial_trange_end.setRange(-60.0, 120.0)
        self.trial_trange_end.setDecimals(2)
        self.trial_trange_end.setValue(self.trange_end.value())
        trial_settings_layout.addRow("TRANGE start", self.trial_trange_start)
        trial_settings_layout.addRow(
            "TRANGE end after epoc", self.trial_trange_end
        )

        self.trial_baseline_start = QtWidgets.QDoubleSpinBox()
        self.trial_baseline_start.setRange(-60.0, 60.0)
        self.trial_baseline_start.setDecimals(2)
        self.trial_baseline_start.setValue(self.baseline_start.value())
        self.trial_baseline_end = QtWidgets.QDoubleSpinBox()
        self.trial_baseline_end.setRange(-60.0, 60.0)
        self.trial_baseline_end.setDecimals(2)
        self.trial_baseline_end.setValue(self.baseline_end.value())
        trial_settings_layout.addRow("Baseline start", self.trial_baseline_start)
        trial_settings_layout.addRow("Baseline end", self.trial_baseline_end)

        self.trial_base_adjust = QtWidgets.QDoubleSpinBox()
        self.trial_base_adjust.setRange(-120.0, 0.0)
        self.trial_base_adjust.setDecimals(1)
        self.trial_base_adjust.setValue(self.base_adjust.value())
        trial_settings_layout.addRow("Baseline adjust", self.trial_base_adjust)

        self.trial_downsample_factor = QtWidgets.QSpinBox()
        self.trial_downsample_factor.setRange(1, 200)
        self.trial_downsample_factor.setValue(self.downsample_factor.value())
        trial_settings_layout.addRow(
            "Downsample factor", self.trial_downsample_factor
        )

        self.trial_plot_smooth = QtWidgets.QCheckBox("Plot smoothed")
        self.trial_plot_smooth.setChecked(self.plot_smooth.isChecked())
        trial_settings_layout.addRow("", self.trial_plot_smooth)

        self.trial_set_baseline = QtWidgets.QCheckBox("Apply baseline correction")
        self.trial_set_baseline.setChecked(self.set_baseline.isChecked())
        trial_settings_layout.addRow("", self.trial_set_baseline)

        control_layout.addWidget(trial_settings_group)

        self.trial_load_button = QtWidgets.QPushButton("Load Trials")
        self.trial_load_button.clicked.connect(self._load_trial_explorer)
        control_layout.addWidget(self.trial_load_button)

        trial_buttons = QtWidgets.QHBoxLayout()
        self.trial_select_all = QtWidgets.QPushButton("All")
        self.trial_select_all.clicked.connect(self._select_all_trials)
        trial_buttons.addWidget(self.trial_select_all)
        self.trial_select_none = QtWidgets.QPushButton("None")
        self.trial_select_none.clicked.connect(self._clear_selected_trials)
        trial_buttons.addWidget(self.trial_select_none)
        self.trial_select_invert = QtWidgets.QPushButton("Invert")
        self.trial_select_invert.clicked.connect(self._invert_selected_trials)
        trial_buttons.addWidget(self.trial_select_invert)
        control_layout.addLayout(trial_buttons)

        trial_type_buttons = QtWidgets.QGridLayout()
        self.trial_type_buttons: dict[str, QtWidgets.QPushButton] = {}
        trial_type_labels = [
            ("correct rewarded", "Correct Rewarded"),
            ("correct not rewarded", "Correct No Reward"),
            ("incorrect rewarded", "Incorrect Rewarded"),
            ("incorrect not rewarded", "Incorrect No Reward"),
            ("unclassified", "Unclassified"),
        ]
        for idx, (trial_type, button_label) in enumerate(trial_type_labels):
            button = QtWidgets.QPushButton(button_label)
            button.setSizePolicy(
                QtWidgets.QSizePolicy.Expanding,
                QtWidgets.QSizePolicy.Fixed,
            )
            button.clicked.connect(
                lambda _, selected_type=trial_type: self._select_trials_by_type(
                    selected_type
                )
            )
            self.trial_type_buttons[trial_type] = button
            trial_type_buttons.addWidget(button, idx // 2, idx % 2)
        trial_type_buttons.setColumnStretch(0, 1)
        trial_type_buttons.setColumnStretch(1, 1)
        control_layout.addLayout(trial_type_buttons)

        self.trial_list = QtWidgets.QListWidget()
        self.trial_list.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.trial_list.itemChanged.connect(self._on_trial_selection_changed)
        control_layout.addWidget(QtWidgets.QLabel("Trials"))
        control_layout.addWidget(self.trial_list)

        export_buttons = QtWidgets.QHBoxLayout()
        self.trial_export_csv_button = QtWidgets.QPushButton("Export Selected CSV")
        self.trial_export_csv_button.clicked.connect(self._export_selected_trial_csv)
        export_buttons.addWidget(self.trial_export_csv_button)
        self.trial_export_fig_button = QtWidgets.QPushButton("Export Selected Figures")
        self.trial_export_fig_button.clicked.connect(
            self._export_selected_trial_figures
        )
        export_buttons.addWidget(self.trial_export_fig_button)
        control_layout.addLayout(export_buttons)

        self.trial_results_box = QtWidgets.QTextEdit()
        self.trial_results_box.setReadOnly(True)
        control_layout.addWidget(self.trial_results_box)

        plot_controls = QtWidgets.QHBoxLayout()
        plot_controls.addWidget(QtWidgets.QLabel("Display channel"))
        self.trial_display_channel = QtWidgets.QComboBox()
        self.trial_display_channel.currentTextChanged.connect(
            self._update_trial_plot_for_channel
        )
        plot_controls.addWidget(self.trial_display_channel)
        plot_controls.addStretch()
        plot_layout.addLayout(plot_controls)

        self.trial_figure = Figure(figsize=(7, 6))
        self.trial_canvas = FigureCanvas(self.trial_figure)
        plot_layout.addWidget(self.trial_canvas)

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

        export_type_row = QtWidgets.QHBoxLayout()
        export_type_row.addWidget(QtWidgets.QLabel("Export"))
        self.batch_export_csv = QtWidgets.QCheckBox("CSV files")
        self.batch_export_csv.setChecked(True)
        export_type_row.addWidget(self.batch_export_csv)
        self.batch_export_figures = QtWidgets.QCheckBox("Figures")
        self.batch_export_figures.setChecked(False)
        export_type_row.addWidget(self.batch_export_figures)
        export_type_row.addWidget(QtWidgets.QLabel("Figure format"))
        self.batch_figure_format = QtWidgets.QComboBox()
        self.batch_figure_format.addItem("PNG", "png")
        self.batch_figure_format.addItem("PDF", "pdf")
        self.batch_figure_format.addItem("TIFF", "tiff")
        self.batch_figure_format.setEnabled(False)
        self.batch_export_figures.toggled.connect(self.batch_figure_format.setEnabled)
        export_type_row.addWidget(self.batch_figure_format)
        export_type_row.addStretch()
        output_layout.addLayout(export_type_row)

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

    def _populate_channel_checklist(
        self,
        channel_list: QtWidgets.QListWidget,
        channel_names: list[str],
        selected_channels: set[str],
    ) -> None:
        channel_list.blockSignals(True)
        channel_list.clear()
        for channel in channel_names:
            item = QtWidgets.QListWidgetItem(channel)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(
                QtCore.Qt.Checked
                if not selected_channels or channel in selected_channels
                else QtCore.Qt.Unchecked
            )
            channel_list.addItem(item)
        channel_list.blockSignals(False)

    def _clear_form_layout(self, layout: QtWidgets.QFormLayout) -> None:
        for idx in reversed(range(layout.rowCount())):
            layout.removeRow(idx)

    def _add_channel_smooth_input(
        self,
        layout: QtWidgets.QFormLayout,
        input_store: dict[str, QtWidgets.QSpinBox],
        channel: str,
        smooth_value: int,
    ) -> None:
        smooth_input = QtWidgets.QSpinBox()
        smooth_input.setRange(1, 200)
        smooth_input.setValue(smooth_value)
        smooth_input.valueChanged.connect(
            lambda value, key=channel: self._set_channel_smooth(key, value)
        )
        input_store[channel] = smooth_input
        layout.addRow(channel, smooth_input)

    def _refresh_channels(self) -> None:
        channel_names = self._batch_channel_names()
        if not channel_names and self.session:
            channel_names = list(available_channels(self.session).keys())

        selected_channels = set(self._selected_channels())
        selected_trial_channels = set(self._selected_trial_channels())
        self._populate_channel_checklist(
            self.channel_list, channel_names, selected_channels
        )
        self._populate_channel_checklist(
            self.trial_channel_list, channel_names, selected_trial_channels
        )

        self._clear_form_layout(self.channel_smooth_layout)
        self._clear_form_layout(self.trial_channel_smooth_layout)
        self.channel_smooth_inputs.clear()
        self.trial_channel_smooth_inputs.clear()
        for channel in channel_names:
            default_smooth = self._settings_int(
                f"processing/channel_smooth/{channel}",
                default_settings_for_channel(channel).smooth_factor,
            )
            smooth_value = self.channel_smooth_overrides.get(channel, default_smooth)
            self.channel_smooth_overrides[channel] = smooth_value
            self._add_channel_smooth_input(
                self.channel_smooth_layout,
                self.channel_smooth_inputs,
                channel,
                smooth_value,
            )
            self._add_channel_smooth_input(
                self.trial_channel_smooth_layout,
                self.trial_channel_smooth_inputs,
                channel,
                smooth_value,
            )

        known_channels = set(channel_names)
        self.channel_smooth_overrides = {
            key: value
            for key, value in self.channel_smooth_overrides.items()
            if key in known_channels
        }
        self.channel_smooth_container.setVisible(bool(known_channels))
        self.trial_channel_smooth_container.setVisible(bool(known_channels))

    def _set_channel_smooth(self, channel_key: str, value: int) -> None:
        smooth_value = int(value)
        self.channel_smooth_overrides[channel_key] = smooth_value
        self.settings.setValue(f"processing/channel_smooth/{channel_key}", smooth_value)
        for input_store in (
            self.channel_smooth_inputs,
            self.trial_channel_smooth_inputs,
        ):
            smooth_input = input_store.get(channel_key)
            if smooth_input is None or smooth_input.value() == smooth_value:
                continue
            smooth_input.blockSignals(True)
            smooth_input.setValue(smooth_value)
            smooth_input.blockSignals(False)
        self._request_preview_refresh()

    def _settings_float(self, key: str, default: float) -> float:
        value = self.settings.value(key, default)
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _settings_int(self, key: str, default: int) -> int:
        value = self.settings.value(key, default)
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _settings_bool(self, key: str, default: bool) -> bool:
        value = self.settings.value(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in {"1", "true", "yes", "on"}
        return bool(value)

    def _sync_spin_setting(
        self,
        target: QtWidgets.QAbstractSpinBox,
        key: str,
        value: int | float,
    ) -> None:
        self.settings.setValue(key, value)
        target.blockSignals(True)
        target.setValue(value)
        target.blockSignals(False)
        self._request_preview_refresh()

    def _sync_checkbox_setting(
        self,
        target: QtWidgets.QCheckBox,
        key: str,
        checked: bool,
    ) -> None:
        self.settings.setValue(key, checked)
        target.blockSignals(True)
        target.setChecked(checked)
        target.blockSignals(False)
        self._request_preview_refresh()

    def _connect_processing_setting_persistence(self) -> None:
        spin_pairs = [
            (self.trange_start, self.trial_trange_start, "processing/trange_start", float),
            (self.trange_end, self.trial_trange_end, "processing/trange_end", float),
            (
                self.baseline_start,
                self.trial_baseline_start,
                "processing/baseline_start",
                float,
            ),
            (
                self.baseline_end,
                self.trial_baseline_end,
                "processing/baseline_end",
                float,
            ),
            (self.base_adjust, self.trial_base_adjust, "processing/base_adjust", float),
            (
                self.downsample_factor,
                self.trial_downsample_factor,
                "processing/downsample_factor",
                int,
            ),
        ]
        for left, right, key, caster in spin_pairs:
            left.valueChanged.connect(
                lambda value, target=right, setting_key=key, cast=caster: self._sync_spin_setting(
                    target, setting_key, cast(value)
                )
            )
            right.valueChanged.connect(
                lambda value, target=left, setting_key=key, cast=caster: self._sync_spin_setting(
                    target, setting_key, cast(value)
                )
            )

        check_pairs = [
            (self.plot_smooth, self.trial_plot_smooth, "processing/plot_smooth"),
            (self.set_baseline, self.trial_set_baseline, "processing/set_baseline"),
        ]
        for left, right, key in check_pairs:
            left.toggled.connect(
                lambda checked, target=right, setting_key=key: self._sync_checkbox_setting(
                    target, setting_key, checked
                )
            )
            right.toggled.connect(
                lambda checked, target=left, setting_key=key: self._sync_checkbox_setting(
                    target, setting_key, checked
                )
            )

    def _refresh_epocs(self) -> None:
        if not self.session:
            return
        current_preview_epoc = self.epoc_combo.currentText()
        current_trial_data = self.trial_epoc_combo.currentData()
        self.epoc_combo.blockSignals(True)
        self.epoc_combo.clear()
        self.epoc_combo.addItems(sorted(self.session.epocs.keys()))
        if current_preview_epoc:
            selected_preview_idx = self.epoc_combo.findText(current_preview_epoc)
            if selected_preview_idx >= 0:
                self.epoc_combo.setCurrentIndex(selected_preview_idx)
        self.epoc_combo.blockSignals(False)

        self.trial_sources_by_key = {
            source.key: source for source in classified_trial_sources(self.session)
        }
        self.trial_epoc_combo.blockSignals(True)
        self.trial_epoc_combo.clear()
        for epoc_name in sorted(self.session.epocs.keys()):
            self.trial_epoc_combo.addItem(epoc_name, ("epoc", epoc_name))
        if self.trial_sources_by_key:
            self.trial_epoc_combo.insertSeparator(self.trial_epoc_combo.count())
        for source in self.trial_sources_by_key.values():
            self.trial_epoc_combo.addItem(source.label, ("classified", source.key))
        selected_idx = (
            self.trial_epoc_combo.findData(current_trial_data)
            if current_trial_data is not None
            else -1
        )
        if selected_idx >= 0:
            self.trial_epoc_combo.setCurrentIndex(selected_idx)
        self.trial_epoc_combo.blockSignals(False)
        self._update_epoc_display(self.epoc_combo.currentText())
        self._refresh_batch_epocs()

    def _on_preview_epoc_changed(self, value: str) -> None:
        self._update_epoc_display(value)
        self._request_preview_refresh()

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
        self.trial_file_combo.blockSignals(True)
        self.trial_file_combo.clear()
        for idx in range(self.batch_file_list.count()):
            file_path = self.batch_file_list.item(idx).data(QtCore.Qt.UserRole)
            self.preview_file_combo.addItem(Path(file_path).name, file_path)
            self.trial_file_combo.addItem(Path(file_path).name, file_path)
        if current_path:
            selected_idx = self.preview_file_combo.findData(current_path)
            if selected_idx >= 0:
                self.preview_file_combo.setCurrentIndex(selected_idx)
            selected_trial_idx = self.trial_file_combo.findData(current_path)
            if selected_trial_idx >= 0:
                self.trial_file_combo.setCurrentIndex(selected_trial_idx)
        self.preview_file_combo.blockSignals(False)
        self.trial_file_combo.blockSignals(False)

    def _on_preview_file_changed(self, _: int) -> None:
        file_path = self.preview_file_combo.currentData()
        if not file_path:
            return
        path = Path(file_path)
        if self._active_session_path and path.resolve() == self._active_session_path:
            return
        self._set_session_from_path(path)

    def _on_trial_file_changed(self, _: int) -> None:
        file_path = self.trial_file_combo.currentData()
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
        self.trial_load_button.setEnabled(not is_running)
        has_trial_export = (
            bool(self.trial_results_by_channel)
            and bool(self._selected_trial_numbers())
            and bool(self.trial_display_channel.currentText())
        )
        self.trial_export_csv_button.setEnabled(has_trial_export and not is_running)
        self.trial_export_fig_button.setEnabled(has_trial_export and not is_running)
        self.batch_run_button.setEnabled(not is_running)
        self.status_bar.showMessage("Running analysis..." if is_running else "Ready")

    def _finish_run(self) -> None:
        was_running = self._active_worker is not None
        self._set_run_state(False)
        self._active_worker = None
        if was_running and self._preview_refresh_pending:
            self._preview_refresh_pending = False
            self._request_preview_refresh()

    def _clear_results(self) -> None:
        self._preview_refresh_pending = False
        self._preview_refresh_timer.stop()
        self.results_by_channel = {}
        self.display_channel.clear()
        self.results_box.clear()
        self.figure.clear()
        self.canvas.draw_idle()
        self._clear_trial_results()
        self._set_run_state(is_running=False)

    def _clear_trial_results(self) -> None:
        self.trial_results_by_channel = {}
        self.active_trial_source = None
        self.trial_display_channel.clear()
        self.trial_list.blockSignals(True)
        self.trial_list.clear()
        self.trial_list.blockSignals(False)
        self.trial_results_box.clear()
        self.trial_figure.clear()
        self.trial_canvas.draw_idle()
        self._set_run_state(is_running=False)

    def _selected_channels_from(self, channel_list: QtWidgets.QListWidget) -> list[str]:
        channels = []
        for idx in range(channel_list.count()):
            item = channel_list.item(idx)
            if item.checkState() == QtCore.Qt.Checked:
                channels.append(item.text())
        return channels

    def _selected_channels(self) -> list[str]:
        return self._selected_channels_from(self.channel_list)

    def _selected_trial_channels(self) -> list[str]:
        return self._selected_channels_from(self.trial_channel_list)

    def _request_preview_refresh(self) -> None:
        if not self.session or not self.results_by_channel:
            return
        if self._active_worker is not None:
            self._preview_refresh_pending = True
            return
        self._preview_refresh_timer.start()

    def _run_preview_refresh(self) -> None:
        if not self.session or not self.results_by_channel:
            return
        if self._active_worker is not None:
            self._preview_refresh_pending = True
            return
        self._preview_signals()

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

    def _build_settings_for_channel(
        self,
        channel_key: str,
        source: str = "visualize",
    ) -> ProcessingSettings:
        if source == "trial":
            trange_start = self.trial_trange_start.value()
            trange_end = self.trial_trange_end.value()
            baseline_start = self.trial_baseline_start.value()
            baseline_end = self.trial_baseline_end.value()
            base_adjust = self.trial_base_adjust.value()
            plot_smooth = self.trial_plot_smooth.isChecked()
            set_baseline = self.trial_set_baseline.isChecked()
            downsample_factor = int(self.trial_downsample_factor.value())
        else:
            trange_start = self.trange_start.value()
            trange_end = self.trange_end.value()
            baseline_start = self.baseline_start.value()
            baseline_end = self.baseline_end.value()
            base_adjust = self.base_adjust.value()
            plot_smooth = self.plot_smooth.isChecked()
            set_baseline = self.set_baseline.isChecked()
            downsample_factor = int(self.downsample_factor.value())

        settings = default_settings_for_channel(channel_key)
        settings.trange = (trange_start, trange_end)
        settings.baseline_per = (baseline_start, baseline_end)
        settings.base_adjust = base_adjust
        settings.plot_smooth = plot_smooth
        settings.set_baseline = set_baseline
        settings.downsample_factor = downsample_factor
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

        current_display_channel = self.display_channel.currentText()

        def task() -> list[AnalysisResult]:
            epoc = self._selected_preview_epoc()
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
                self._annotate_processed_trials(processed, epoc, None)
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

            summary = [self._result_summary_line(result) for result in results]
            self.results_box.setText("\n".join(summary) or "No results.")
            if results:
                display_channel = (
                    current_display_channel
                    if current_display_channel in self.results_by_channel
                    else results[0].channel_key
                )
                self.display_channel.setCurrentText(display_channel)
                self._plot_result(self.results_by_channel[display_channel])
            self._finish_run()

        worker = Worker(task)
        worker.setAutoDelete(False)
        worker.signals.result.connect(handle_results)
        worker.signals.error.connect(self._show_error)
        worker.signals.finished.connect(self._finish_run)
        self._set_run_state(True)
        self._active_worker = worker
        self.thread_pool.start(worker)

    def _result_summary_line(self, result: AnalysisResult) -> str:
        processed = result.processed
        line = f"{result.channel_key}: trials={processed.zall.shape[0]}"
        if processed.num_edge_trials:
            line += (
                f", dropped incomplete edge trials={processed.num_edge_trials} "
                f"({self._format_trial_numbers(processed.dropped_edge_trials)})"
            )
        if processed.num_artifacts:
            line += f", artifact removals={processed.num_artifacts}"
        return line

    def _format_trial_numbers(self, trial_numbers: list[int]) -> str:
        if len(trial_numbers) <= 8:
            return ", ".join(str(number) for number in trial_numbers)
        shown = ", ".join(str(number) for number in trial_numbers[:8])
        return f"{shown}, ..."

    def _update_plot_for_channel(self, channel_key: str) -> None:
        if not channel_key:
            return
        result = self.results_by_channel.get(channel_key)
        if result:
            self._plot_result(result)

    def _plot_result(self, result: AnalysisResult) -> None:
        self.figure.clear()
        self._populate_result_figure(self.figure, result)
        self.canvas.draw_idle()

    def _plot_trial_result(self, result: AnalysisResult) -> None:
        self.trial_figure.clear()
        self._populate_result_figure(self.trial_figure, result)
        self.trial_canvas.draw_idle()

    def _result_figure_title(self, result: AnalysisResult) -> str:
        return result_figure_title(result)

    def _heatmap_trial_ticks(
        self,
        processed,
        num_rows: int,
        max_ticks: int = 12,
    ) -> tuple[list[int], list[str]]:
        return heatmap_trial_ticks(processed, num_rows, max_ticks)

    def _populate_result_figure(self, figure: Figure, result: AnalysisResult) -> None:
        populate_result_figure(figure, result)

    def _selected_preview_epoc(self) -> Epoc:
        epoc_name = self.epoc_combo.currentText()
        if epoc_name not in self.session.epocs:
            raise ValueError(f"Epoc '{epoc_name}' not found.")
        return self.session.epocs[epoc_name]

    def _selected_trial_epoc(self) -> tuple[Epoc, ClassifiedTrialSource | None]:
        selection = self.trial_epoc_combo.currentData()
        if isinstance(selection, tuple) and selection[0] == "classified":
            source = self.trial_sources_by_key[selection[1]]
            return source.epoc, source
        epoc_name = (
            selection[1]
            if isinstance(selection, tuple) and selection[0] == "epoc"
            else self.trial_epoc_combo.currentText()
        )
        if epoc_name not in self.session.epocs:
            raise ValueError(f"Epoc '{epoc_name}' not found.")
        return self.session.epocs[epoc_name], None

    def _annotate_processed_trials(
        self,
        processed,
        epoc: Epoc,
        source: ClassifiedTrialSource | None,
    ) -> None:
        if source is not None:
            trials_by_number = {
                trial.trial_number: trial for trial in source.trials
            }
            processed.trial_labels = [
                trials_by_number[number].trial_type if number in trials_by_number else ""
                for number in processed.trial_numbers
            ]
            processed.trial_times = [
                trials_by_number[number].onset if number in trials_by_number else float("nan")
                for number in processed.trial_numbers
            ]
            return

        processed.trial_labels = []
        processed.trial_times = [
            float(epoc.onset[number - 1])
            if 0 < number <= epoc.onset.size
            else float("nan")
            for number in processed.trial_numbers
        ]

    def _load_trial_explorer(self) -> None:
        if not self.session:
            self.trial_results_box.setText("Load a session first.")
            return
        if self.trial_epoc_combo.currentData() is None:
            self.trial_results_box.setText("Select an epoc.")
            return
        try:
            trial_epoc, trial_source = self._selected_trial_epoc()
        except (KeyError, ValueError) as exc:
            self.trial_results_box.setText(str(exc))
            return

        channel_keys = self._selected_trial_channels()
        if not channel_keys:
            channel_keys = self._selected_channels()
        if not channel_keys:
            channel_keys = self._batch_channel_names()
        if not channel_keys and self.session:
            channel_keys = list(available_channels(self.session).keys())
        if not channel_keys:
            self.trial_results_box.setText("No channels available.")
            return

        current_display_channel = self.trial_display_channel.currentText()

        def task() -> list[AnalysisResult]:
            channel_map = available_channels(self.session)
            results: list[AnalysisResult] = []
            for channel_key in channel_keys:
                if channel_key not in channel_map:
                    continue
                iso_stream, signal_stream, _ = channel_map[channel_key]
                settings = self._build_settings_for_channel(channel_key, source="trial")
                processed = process_channel(
                    self.session, iso_stream, signal_stream, trial_epoc, settings
                )
                self._annotate_processed_trials(processed, trial_epoc, trial_source)
                results.append(
                    AnalysisResult(
                        session=self.session,
                        epoc=trial_epoc,
                        channel_key=channel_key,
                        processed=processed,
                        settings=settings,
                        stream_store=(iso_stream, signal_stream),
                    )
                )
            return results

        def handle_results(results: list[AnalysisResult]) -> None:
            self.active_trial_source = trial_source
            self.trial_results_by_channel = {
                result.channel_key: result for result in results
            }
            self.trial_display_channel.blockSignals(True)
            self.trial_display_channel.clear()
            self.trial_display_channel.addItems(list(self.trial_results_by_channel.keys()))
            self.trial_display_channel.blockSignals(False)

            trial_numbers = self._common_trial_numbers(results)
            self._populate_trial_list(trial_numbers, results)
            if results and trial_numbers:
                display_channel = (
                    current_display_channel
                    if current_display_channel in self.trial_results_by_channel
                    else results[0].channel_key
                )
                self.trial_display_channel.setCurrentText(display_channel)
                self._update_trial_plot_for_channel(display_channel)
            elif results:
                self.trial_results_box.setText(
                    "No shared trials remain after edge/artifact filtering."
                )
                self.trial_figure.clear()
                self.trial_canvas.draw_idle()
            else:
                self.trial_results_box.setText("No results.")
            self._finish_run()

        worker = Worker(task)
        worker.setAutoDelete(False)
        worker.signals.result.connect(handle_results)
        worker.signals.error.connect(self._show_trial_error)
        worker.signals.finished.connect(self._finish_run)
        self.trial_results_box.setText("Loading trials...")
        self._set_run_state(True)
        self._active_worker = worker
        self.thread_pool.start(worker)

    def _common_trial_numbers(self, results: list[AnalysisResult]) -> list[int]:
        trial_sets: list[set[int]] = []
        for result in results:
            processed = result.processed
            trial_numbers = (
                processed.trial_numbers
                if processed.trial_numbers
                else list(range(1, processed.zall.shape[0] + 1))
            )
            trial_sets.append({int(number) for number in trial_numbers})
        if not trial_sets:
            return []
        common = set.intersection(*trial_sets)
        return sorted(common)

    def _populate_trial_list(
        self,
        trial_numbers: list[int],
        results: list[AnalysisResult],
    ) -> None:
        selected = set(self._selected_trial_numbers())
        metadata_by_number = self._trial_metadata_by_number(results)
        self.trial_list.blockSignals(True)
        self.trial_list.clear()
        for number in trial_numbers:
            trial_time, trial_label = metadata_by_number.get(number, (None, ""))
            item = QtWidgets.QListWidgetItem(
                self._trial_list_label(number, trial_time, trial_label)
            )
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setData(QtCore.Qt.UserRole, number)
            item.setData(QtCore.Qt.UserRole + 1, trial_label)
            item.setData(QtCore.Qt.UserRole + 2, trial_time)
            should_check = not selected or number in selected
            item.setCheckState(QtCore.Qt.Checked if should_check else QtCore.Qt.Unchecked)
            self.trial_list.addItem(item)
        self.trial_list.blockSignals(False)

    def _trial_metadata_by_number(
        self,
        results: list[AnalysisResult],
    ) -> dict[int, tuple[float | None, str]]:
        metadata: dict[int, tuple[float | None, str]] = {}
        for result in results:
            processed = result.processed
            for idx, number in enumerate(processed.trial_numbers):
                if number in metadata:
                    continue
                trial_time = (
                    processed.trial_times[idx]
                    if idx < len(processed.trial_times)
                    else None
                )
                trial_label = (
                    processed.trial_labels[idx]
                    if idx < len(processed.trial_labels)
                    else ""
                )
                metadata[number] = (trial_time, trial_label)
        return metadata

    def _trial_list_label(
        self,
        trial_number: int,
        trial_time: float | None,
        trial_label: str,
    ) -> str:
        parts = [f"Trial {trial_number}"]
        if trial_time is not None and trial_time == trial_time:
            parts.append(f"{trial_time:.3f}s")
        if trial_label:
            parts.append(trial_label)
        return " | ".join(parts)

    def _selected_trial_numbers(self) -> list[int]:
        trial_numbers: list[int] = []
        for idx in range(self.trial_list.count()):
            item = self.trial_list.item(idx)
            if item.checkState() == QtCore.Qt.Checked:
                trial_numbers.append(int(item.data(QtCore.Qt.UserRole)))
        return trial_numbers

    def _set_trial_checks(self, should_check: Callable[[int, str], bool]) -> None:
        self.trial_list.blockSignals(True)
        for idx in range(self.trial_list.count()):
            item = self.trial_list.item(idx)
            trial_number = int(item.data(QtCore.Qt.UserRole))
            trial_label = item.data(QtCore.Qt.UserRole + 1) or ""
            item.setCheckState(
                QtCore.Qt.Checked
                if should_check(trial_number, trial_label)
                else QtCore.Qt.Unchecked
            )
        self.trial_list.blockSignals(False)
        self._update_trial_plot_for_channel(self.trial_display_channel.currentText())
        self._set_run_state(False)

    def _select_all_trials(self) -> None:
        self._set_trial_checks(lambda _, __: True)

    def _clear_selected_trials(self) -> None:
        self._set_trial_checks(lambda _, __: False)

    def _invert_selected_trials(self) -> None:
        selected = set(self._selected_trial_numbers())
        self._set_trial_checks(lambda number, _: number not in selected)

    def _select_trials_by_type(self, trial_type: str) -> None:
        self._set_trial_checks(lambda _, label: label == trial_type)

    def _on_trial_selection_changed(self, _: QtWidgets.QListWidgetItem) -> None:
        self._update_trial_plot_for_channel(self.trial_display_channel.currentText())
        self._set_run_state(False)

    def _update_trial_plot_for_channel(self, channel_key: str) -> None:
        if not channel_key or channel_key not in self.trial_results_by_channel:
            return
        selected_result = self._current_trial_subset_result(show_error=False)
        if selected_result is None:
            self.trial_figure.clear()
            self.trial_canvas.draw_idle()
            self.trial_results_box.setText("No trials selected.")
            self._set_run_state(False)
            return
        self._plot_trial_result(selected_result)
        full_result = self.trial_results_by_channel[channel_key]
        self.trial_results_box.setText(
            self._trial_result_summary_line(full_result, selected_result)
        )
        self._set_run_state(False)

    def _current_trial_subset_result(
        self,
        show_error: bool = True,
    ) -> AnalysisResult | None:
        channel_key = self.trial_display_channel.currentText()
        result = self.trial_results_by_channel.get(channel_key)
        if result is None:
            if show_error:
                self._show_trial_error("Load trials first.")
            return None
        try:
            processed = subset_processed_signal(
                result.processed, self._selected_trial_numbers()
            )
        except ValueError as exc:
            if show_error:
                self._show_trial_error(str(exc))
            return None
        return AnalysisResult(
            session=result.session,
            epoc=result.epoc,
            channel_key=result.channel_key,
            processed=processed,
            settings=result.settings,
            stream_store=result.stream_store,
        )

    def _trial_result_summary_line(
        self,
        full_result: AnalysisResult,
        selected_result: AnalysisResult,
    ) -> str:
        full_processed = full_result.processed
        selected_processed = selected_result.processed
        line = (
            f"{full_result.channel_key}: selected trials="
            f"{selected_processed.zall.shape[0]} of {full_processed.zall.shape[0]}"
        )
        if selected_processed.trial_numbers:
            line += f" ({self._format_trial_numbers(selected_processed.trial_numbers)})"
        if self.active_trial_source is not None:
            line += f"\nSource: {self.active_trial_source.label}"
        type_counts = self._trial_type_counts(selected_processed.trial_labels)
        if type_counts:
            line += "\nSelected types: " + ", ".join(
                f"{trial_type}={count}" for trial_type, count in type_counts.items()
            )
        if full_processed.num_edge_trials:
            line += (
                f", dropped incomplete edge trials={full_processed.num_edge_trials} "
                f"({self._format_trial_numbers(full_processed.dropped_edge_trials)})"
            )
        if full_processed.num_artifacts:
            line += f", artifact removals={full_processed.num_artifacts}"
        if self.active_trial_source and self.active_trial_source.warnings:
            line += "\nWarnings: " + " ".join(self.active_trial_source.warnings)
        return line

    def _trial_type_counts(self, trial_labels: list[str]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for label in trial_labels:
            if not label:
                continue
            counts[label] = counts.get(label, 0) + 1
        return counts

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

    def _export_selected_trial_csv(self) -> None:
        result = self._current_trial_subset_result()
        if result is None:
            return
        output_dir = self._choose_single_export_dir(
            "Choose Folder for Selected Trial CSV Export"
        )
        if output_dir is None:
            return
        output_dir.mkdir(parents=True, exist_ok=True)
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
            filename_suffix="_selected_trials",
        )
        self.status_bar.showMessage(f"Selected trial CSV exported to {output_dir}")

    def _export_selected_trial_figures(self) -> None:
        result = self._current_trial_subset_result()
        if result is None:
            return
        output_dir = self._choose_single_export_dir(
            "Choose Folder for Selected Trial Figure Export"
        )
        if output_dir is None:
            return
        output_dir.mkdir(parents=True, exist_ok=True)
        self._save_figures(output_dir, result, filename_suffix="_selected_trials")
        self.status_bar.showMessage(f"Selected trial figure exported to {output_dir}")

    def _save_figures(
        self,
        output_dir: Path,
        result: AnalysisResult,
        filename_suffix: str = "",
        figure_format: str = "png",
    ) -> None:
        save_result_figure(output_dir, result, filename_suffix, figure_format)

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
        self.trial_file_combo.clear()
        self.trial_sources_by_key.clear()
        self.active_trial_source = None
        self.session = None
        self._active_session_path = None
        self.session_label.setText("No session loaded")
        self.metadata_view.clear()
        self.epoc_combo.clear()
        self.trial_epoc_combo.clear()
        self.batch_epoc_list.clear()
        self.channel_list.clear()
        self.trial_channel_list.clear()
        self._clear_results()

    def _batch_export_done_message(
        self,
        input_paths: list[Path],
        export_csv: bool,
        export_figures: bool,
    ) -> str:
        if export_csv and export_figures:
            export_label = "CSV and figure export"
        elif export_figures:
            export_label = "Figure export"
        else:
            export_label = "CSV export"
        return f"{export_label} complete ({len(input_paths)} files)."

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
        export_csv = self.batch_export_csv.isChecked()
        export_figures = self.batch_export_figures.isChecked()
        figure_format = self.batch_figure_format.currentData() or "png"
        if not export_csv and not export_figures:
            self._show_error("Choose CSV files, figures, or both for batch export.")
            return

        def task() -> str:
            output_dir = Path(self.output_dir_input.text()).expanduser()
            output_dir.mkdir(parents=True, exist_ok=True)

            exported_results = run_batch_custom(
                input_paths=input_paths,
                epoc_selections=epoc_selections,
                output_dir=output_dir,
                channel_keys=channel_keys,
                settings_factory=self._build_settings_for_channel,
                export_summary=False,
                per_session_subdir=True,
                export_csv=export_csv,
            )
            if export_figures:
                for exported in exported_results:
                    exported.output_dir.mkdir(parents=True, exist_ok=True)
                    self._save_figures(
                        exported.output_dir,
                        exported.result,
                        figure_format=figure_format,
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
                    f"{self._batch_export_done_message(input_paths, export_csv, export_figures)} "
                    f"Skipped epocs: {skipped_details}"
                )
            return self._batch_export_done_message(
                input_paths, export_csv, export_figures
            )

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

    def _show_trial_error(self, message: str) -> None:
        self.trial_results_box.setText(message)
        self.status_bar.showMessage(message)
