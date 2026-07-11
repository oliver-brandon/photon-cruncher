from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from photon_cruncher.gui_prototype.components import (
    Card,
    NoticeBar,
    PageHeader,
    button,
    label,
    pill,
)
from photon_cruncher.gui_prototype.demo_data import DemoSession


class BatchPage(QtWidgets.QWidget):
    toast_requested = QtCore.Signal(str)

    def __init__(
        self,
        session: DemoSession,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.session = session
        self._progress_value = 0
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(160)
        self._timer.timeout.connect(self._advance_progress)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(12)
        header = PageHeader(
            "Batch export",
            "Review sources, epocs, and output choices before starting a repeatable export.",
        )
        validate = button("Validate batch", "ghost")
        validate.clicked.connect(
            lambda: self.toast_requested.emit(
                "Synthetic batch validated: 6 sources and 3 epocs are ready."
            )
        )
        header.add_action(validate)
        self.header_run_button = button("Run demo batch", "primary")
        self.header_run_button.clicked.connect(self.start_demo_batch)
        header.add_action(self.header_run_button)
        root.addWidget(header)

        content = QtWidgets.QHBoxLayout()
        content.setSpacing(12)
        root.addLayout(content, 1)

        left = QtWidgets.QVBoxLayout()
        left.setSpacing(10)
        sources_card = Card(
            "Data sources",
            "Synthetic sessions model a mixed MAT and TDT batch.",
        )
        source_actions = QtWidgets.QHBoxLayout()
        for text in ("Add files", "Add folder", "Add TDT tank"):
            action = button(text, "ghost")
            action.clicked.connect(
                lambda _, name=text: self.toast_requested.emit(
                    f"{name} is mocked; no file dialog was opened."
                )
            )
            source_actions.addWidget(action)
        source_actions.addStretch()
        clear = button("Clear", "ghost")
        clear.clicked.connect(
            lambda: self.toast_requested.emit(
                "Clear is disabled for the deterministic screenshot state."
            )
        )
        source_actions.addWidget(clear)
        sources_card.layout.addLayout(source_actions)

        self.source_table = QtWidgets.QTableWidget(len(session.batch_sources), 4)
        self.source_table.setHorizontalHeaderLabels(
            ["Session", "Source", "Duration", "State"]
        )
        self.source_table.horizontalHeader().setSectionResizeMode(
            0, QtWidgets.QHeaderView.Stretch
        )
        for column in (1, 2, 3):
            self.source_table.horizontalHeader().setSectionResizeMode(
                column, QtWidgets.QHeaderView.ResizeToContents
            )
        self.source_table.verticalHeader().hide()
        self.source_table.setAlternatingRowColors(True)
        self.source_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.source_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.source_table.setMinimumHeight(250)
        for row, source in enumerate(session.batch_sources):
            for column, value in enumerate(
                (source.name, source.source_type, source.duration, source.status)
            ):
                self.source_table.setItem(row, column, QtWidgets.QTableWidgetItem(value))
        sources_card.layout.addWidget(self.source_table, 1)
        left.addWidget(sources_card, 1)

        epoc_card = Card("Epocs and suffix handling")
        policy_row = QtWidgets.QHBoxLayout()
        policy_row.addWidget(label("Suffix policy", "muted"))
        self.suffix_policy = QtWidgets.QComboBox()
        self.suffix_policy.addItems(
            [
                "Prefer A / 1_ when both exist",
                "Prefer C / 2_ when both exist",
                "Use exact checked epocs",
            ]
        )
        policy_row.addWidget(self.suffix_policy, 1)
        epoc_card.layout.addLayout(policy_row)
        epoc_checks = QtWidgets.QHBoxLayout()
        for epoc in ("LeverA / 1_", "Reward", "Timeout"):
            check = QtWidgets.QCheckBox(epoc)
            check.setChecked(True)
            epoc_checks.addWidget(check)
        epoc_checks.addStretch()
        epoc_card.layout.addLayout(epoc_checks)
        left.addWidget(epoc_card)
        content.addLayout(left, 3)

        right = QtWidgets.QVBoxLayout()
        right.setSpacing(10)
        output_card = Card("Export output")
        output_card.layout.addWidget(label("Destination", "muted"))
        path_row = QtWidgets.QHBoxLayout()
        self.output_path = QtWidgets.QLineEdit("Demo exports / Photon Cruncher")
        self.output_path.setReadOnly(True)
        self.output_path.setAccessibleName("Synthetic output destination")
        path_row.addWidget(self.output_path, 1)
        choose = button("Choose", "ghost")
        choose.clicked.connect(
            lambda: self.toast_requested.emit(
                "Output selection is mocked; no folder dialog was opened."
            )
        )
        path_row.addWidget(choose)
        output_card.layout.addLayout(path_row)
        export_row = QtWidgets.QHBoxLayout()
        self.csv_check = QtWidgets.QCheckBox("CSV files")
        self.csv_check.setChecked(True)
        self.figures_check = QtWidgets.QCheckBox("Figures")
        self.figures_check.setChecked(True)
        self.figure_format = QtWidgets.QComboBox()
        self.figure_format.addItems(["PNG", "PDF", "TIFF"])
        export_row.addWidget(self.csv_check)
        export_row.addWidget(self.figures_check)
        export_row.addWidget(self.figure_format)
        export_row.addStretch()
        output_card.layout.addLayout(export_row)
        self.session_folders = QtWidgets.QCheckBox("Create one folder per session")
        self.session_folders.setChecked(True)
        output_card.layout.addWidget(self.session_folders)
        right.addWidget(output_card)

        summary_card = Card("Batch summary")
        summary_grid = QtWidgets.QGridLayout()
        summary_grid.setHorizontalSpacing(14)
        summary_grid.setVerticalSpacing(9)
        for index, (value, title, tone) in enumerate(
            (
                ("6", "sources", "teal"),
                ("3", "epocs", "neutral"),
                ("18", "analyses", "neutral"),
                ("54", "outputs", "success"),
            )
        ):
            cell = QtWidgets.QVBoxLayout()
            cell.setSpacing(1)
            value_label = label(value, "metricValue")
            value_label.setAlignment(QtCore.Qt.AlignCenter)
            title_label = label(title.upper(), "metricLabel")
            title_label.setAlignment(QtCore.Qt.AlignCenter)
            cell.addWidget(value_label)
            cell.addWidget(title_label)
            summary_grid.addLayout(cell, index // 2, index % 2)
        summary_card.layout.addLayout(summary_grid)
        right.addWidget(summary_card)

        self.progress_card = Card("Export progress", "Ready to run the synthetic batch.")
        status_row = QtWidgets.QHBoxLayout()
        self.progress_status = pill("READY", "neutral")
        status_row.addWidget(self.progress_status)
        self.progress_detail = label("6 sessions queued", "muted")
        status_row.addWidget(self.progress_detail)
        status_row.addStretch()
        self.progress_percent = label("0%", "cardTitle")
        status_row.addWidget(self.progress_percent)
        self.progress_card.layout.addLayout(status_row)
        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_card.layout.addWidget(self.progress_bar)
        progress_actions = QtWidgets.QHBoxLayout()
        self.cancel_button = button("Cancel", "ghost")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_demo_batch)
        progress_actions.addWidget(self.cancel_button)
        progress_actions.addStretch()
        self.run_button = button("Run demo batch", "primary")
        self.run_button.clicked.connect(self.start_demo_batch)
        progress_actions.addWidget(self.run_button)
        self.progress_card.layout.addLayout(progress_actions)
        right.addWidget(self.progress_card)
        right.addStretch()
        content.addLayout(right, 2)

        root.addWidget(
            NoticeBar(
                "The simulation updates only this progress card. It never invokes "
                "batch analysis or writes an export."
            )
        )

    def start_demo_batch(self) -> None:
        self._progress_value = 0
        self._set_progress(0, "Preparing synthetic sessions…", "RUNNING", "teal")
        self.run_button.setEnabled(False)
        self.header_run_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self._timer.start()
        self.toast_requested.emit("Synthetic batch simulation started.")

    def cancel_demo_batch(self) -> None:
        self._timer.stop()
        self._set_progress(
            self._progress_value,
            "Simulation cancelled · no files were created",
            "CANCELLED",
            "warning",
        )
        self.run_button.setEnabled(True)
        self.header_run_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.toast_requested.emit("Synthetic batch simulation cancelled.")

    def _advance_progress(self) -> None:
        self._progress_value = min(100, self._progress_value + 4)
        session_number = min(6, 1 + self._progress_value // 17)
        self._set_progress(
            self._progress_value,
            f"Processing demo session {session_number} of 6",
            "RUNNING",
            "teal",
        )
        if self._progress_value >= 100:
            self._timer.stop()
            self._set_progress(
                100,
                "Synthetic batch complete · 54 mock outputs",
                "COMPLETE",
                "success",
            )
            self.run_button.setEnabled(True)
            self.header_run_button.setEnabled(True)
            self.cancel_button.setEnabled(False)
            self.toast_requested.emit("Synthetic batch simulation complete.")

    def _set_progress(self, value: int, detail: str, status: str, tone: str) -> None:
        self._progress_value = value
        self.progress_bar.setValue(value)
        self.progress_percent.setText(f"{value}%")
        self.progress_detail.setText(detail)
        self.progress_status.setText(status)
        self.progress_status.setProperty("tone", tone)
        self.progress_status.style().unpolish(self.progress_status)
        self.progress_status.style().polish(self.progress_status)

    def prepare_capture(self) -> None:
        self._timer.stop()
        self._set_progress(
            68,
            "Processing demo session 5 of 6",
            "RUNNING",
            "teal",
        )
        self.run_button.setEnabled(False)
        self.header_run_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
