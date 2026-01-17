from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtWidgets

from photometry_app.analysis.runner import run_session
from photometry_app.io.loader import load_session
from photometry_app.processing.pipeline import available_channels


class Worker(QtCore.QRunnable):
    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs

    @QtCore.Slot()
    def run(self) -> None:
        self.fn(*self.args, **self.kwargs)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Photometry App")
        self.resize(1200, 800)

        self.thread_pool = QtCore.QThreadPool()

        self.tabs = QtWidgets.QTabWidget()
        self.setCentralWidget(self.tabs)

        self.import_tab = QtWidgets.QWidget()
        self.mapping_tab = QtWidgets.QWidget()
        self.epoc_tab = QtWidgets.QWidget()
        self.preprocess_tab = QtWidgets.QWidget()
        self.visualize_tab = QtWidgets.QWidget()
        self.export_tab = QtWidgets.QWidget()

        self.tabs.addTab(self.import_tab, "Import")
        self.tabs.addTab(self.mapping_tab, "Channel Mapping")
        self.tabs.addTab(self.epoc_tab, "Epoc Selection")
        self.tabs.addTab(self.preprocess_tab, "Preprocess")
        self.tabs.addTab(self.visualize_tab, "Align + Visualize")
        self.tabs.addTab(self.export_tab, "Export")

        self._build_import()
        self._build_mapping()
        self._build_epoc()
        self._build_preprocess()
        self._build_visualize()
        self._build_export()

        self.session = None

    def _build_import(self) -> None:
        layout = QtWidgets.QVBoxLayout()
        self.import_tab.setLayout(layout)

        self.file_picker = QtWidgets.QPushButton("Select MAT File")
        self.file_picker.clicked.connect(self._select_file)
        layout.addWidget(self.file_picker)

        self.session_label = QtWidgets.QLabel("No session loaded")
        layout.addWidget(self.session_label)

        self.metadata_view = QtWidgets.QTextEdit()
        self.metadata_view.setReadOnly(True)
        layout.addWidget(self.metadata_view)

    def _build_mapping(self) -> None:
        layout = QtWidgets.QVBoxLayout()
        self.mapping_tab.setLayout(layout)
        self.mapping_label = QtWidgets.QLabel("Channels will appear after import.")
        layout.addWidget(self.mapping_label)

    def _build_epoc(self) -> None:
        layout = QtWidgets.QVBoxLayout()
        self.epoc_tab.setLayout(layout)
        self.epoc_combo = QtWidgets.QComboBox()
        layout.addWidget(QtWidgets.QLabel("Reference epoc"))
        layout.addWidget(self.epoc_combo)

    def _build_preprocess(self) -> None:
        layout = QtWidgets.QVBoxLayout()
        self.preprocess_tab.setLayout(layout)
        self.preprocess_label = QtWidgets.QLabel(
            "Defaults: TRANGE [-2, 7], BASELINE_PER [-3, -1], downsample 10x"
        )
        layout.addWidget(self.preprocess_label)

    def _build_visualize(self) -> None:
        layout = QtWidgets.QVBoxLayout()
        self.visualize_tab.setLayout(layout)
        self.run_button = QtWidgets.QPushButton("Run Analysis")
        self.run_button.clicked.connect(self._run_analysis)
        layout.addWidget(self.run_button)

        self.results_box = QtWidgets.QTextEdit()
        self.results_box.setReadOnly(True)
        layout.addWidget(self.results_box)

    def _build_export(self) -> None:
        layout = QtWidgets.QVBoxLayout()
        self.export_tab.setLayout(layout)
        self.export_label = QtWidgets.QLabel(
            "Exports include heatmap/time/PSTH CSV + settings JSON."
        )
        layout.addWidget(self.export_label)

    def _select_file(self) -> None:
        path_str, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select MAT File", str(Path.home()), "MAT Files (*.mat)"
        )
        if not path_str:
            return
        path = Path(path_str)
        self.session = load_session(path)
        self.session_label.setText(f"Loaded: {path.name}")
        self.metadata_view.setText(str(self.session.info))
        self._refresh_channels()
        self._refresh_epocs()

    def _refresh_channels(self) -> None:
        if not self.session:
            return
        channel_map = available_channels(self.session)
        channels = ", ".join(channel_map.keys()) or "No channels detected"
        self.mapping_label.setText(f"Detected channels: {channels}")

    def _refresh_epocs(self) -> None:
        if not self.session:
            return
        self.epoc_combo.clear()
        self.epoc_combo.addItems(sorted(self.session.epocs.keys()))

    def _run_analysis(self) -> None:
        if not self.session:
            self.results_box.setText("Load a session first.")
            return
        epoc_name = self.epoc_combo.currentText()
        if not epoc_name:
            self.results_box.setText("Select an epoc.")
            return

        def task() -> None:
            results = run_session(self.session, epoc_name)
            summary = [
                f"{result.channel_key}: trials={result.processed.zall.shape[0]}"
                for result in results
            ]
            QtCore.QMetaObject.invokeMethod(
                self.results_box,
                "setText",
                QtCore.Qt.QueuedConnection,
                QtCore.Q_ARG(str, "\n".join(summary) or "No results."),
            )

        worker = Worker(task)
        self.thread_pool.start(worker)
