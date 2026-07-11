from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from photon_cruncher.gui_prototype.components import (
    Card,
    NoticeBar,
    PageHeader,
    add_form_row,
    button,
    label,
    pill,
)
from photon_cruncher.gui_prototype.demo_data import DemoSession
from photon_cruncher.gui_prototype.plots import AnalysisPlotWidget


def _double_spin(
    value: float,
    minimum: float,
    maximum: float,
    suffix: str = " s",
) -> QtWidgets.QDoubleSpinBox:
    widget = QtWidgets.QDoubleSpinBox()
    widget.setDecimals(2)
    widget.setRange(minimum, maximum)
    widget.setValue(value)
    widget.setSuffix(suffix)
    return widget


class AlignPage(QtWidgets.QWidget):
    toast_requested = QtCore.Signal(str)

    def __init__(
        self,
        session: DemoSession,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.session = session
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(12)

        header = PageHeader(
            "Align + visualize",
            "Tune the event window and inspect linked synthetic traces before export.",
        )
        export_button = button("Export preview", "ghost")
        export_button.clicked.connect(
            lambda: self.toast_requested.emit(
                "Preview export is mocked; no file was written."
            )
        )
        header.add_action(export_button)
        preview_button = button("Refresh preview", "primary")
        preview_button.clicked.connect(self._refresh_preview)
        header.add_action(preview_button)
        root.addWidget(header)
        root.addWidget(
            NoticeBar(
                "48 complete windows retained · edge trials 1 and 50 are excluded "
                "from this synthetic preview.",
                tone="warning",
            )
        )

        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, 1)

        controls_scroll = QtWidgets.QScrollArea()
        controls_scroll.setWidgetResizable(True)
        controls_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        controls_scroll.setMinimumWidth(330)
        controls_scroll.setMaximumWidth(390)
        controls = QtWidgets.QWidget()
        controls_layout = QtWidgets.QVBoxLayout(controls)
        controls_layout.setContentsMargins(0, 0, 8, 0)
        controls_layout.setSpacing(10)
        controls_scroll.setWidget(controls)
        splitter.addWidget(controls_scroll)

        source_card = Card("Analysis source")
        source_grid = QtWidgets.QGridLayout()
        source_grid.setHorizontalSpacing(10)
        source_grid.setVerticalSpacing(7)
        source_grid.setColumnStretch(1, 1)
        self.file_combo = QtWidgets.QComboBox()
        self.file_combo.addItems(
            [self.session.name, "Demo_Mouse_043_Acq", "Demo_Mouse_044_Acq"]
        )
        self.file_combo.setAccessibleName("Preview session")
        self.epoc_combo = QtWidgets.QComboBox()
        self.epoc_combo.addItems(self.session.epocs)
        self.epoc_combo.setAccessibleName("Reference epoc")
        add_form_row(source_grid, 0, "Preview file", self.file_combo)
        add_form_row(
            source_grid,
            1,
            "Reference epoc",
            self.epoc_combo,
            "The event placed at time zero in the linked plots.",
        )
        source_card.layout.addLayout(source_grid)
        channels_title = QtWidgets.QHBoxLayout()
        channels_title.addWidget(label("Channels to analyze", "muted"))
        channels_title.addStretch()
        channels_title.addWidget(pill("3 available", "neutral"))
        source_card.layout.addLayout(channels_title)
        self.channel_checks: list[QtWidgets.QCheckBox] = []
        for channel in self.session.channels:
            check = QtWidgets.QCheckBox(channel.title)
            check.setChecked(channel.key != "control")
            check.setToolTip(f"Synthetic store mapping: {channel.store}")
            self.channel_checks.append(check)
            source_card.layout.addWidget(check)
        controls_layout.addWidget(source_card)

        window_card = Card("Processing window")
        window_grid = QtWidgets.QGridLayout()
        window_grid.setHorizontalSpacing(10)
        window_grid.setVerticalSpacing(7)
        window_grid.setColumnStretch(1, 1)
        self.trange_start = _double_spin(-2.0, -60.0, 60.0)
        self.trange_end = _double_spin(5.0, -60.0, 120.0)
        self.baseline_start = _double_spin(-2.0, -60.0, 60.0)
        self.baseline_end = _double_spin(-1.0, -60.0, 60.0)
        self.baseline_adjust = _double_spin(-2.0, -120.0, 0.0)
        self.downsample = QtWidgets.QSpinBox()
        self.downsample.setRange(1, 200)
        self.downsample.setValue(10)
        self.downsample.setSuffix("×")
        add_form_row(
            window_grid,
            0,
            "TRANGE start",
            self.trange_start,
            "Seconds before the selected epoc.",
        )
        add_form_row(
            window_grid,
            1,
            "TRANGE end",
            self.trange_end,
            "Seconds after the selected epoc, not total window length.",
        )
        add_form_row(window_grid, 2, "Baseline start", self.baseline_start)
        add_form_row(window_grid, 3, "Baseline end", self.baseline_end)
        add_form_row(window_grid, 4, "Baseline adjust", self.baseline_adjust)
        add_form_row(window_grid, 5, "Downsample", self.downsample)
        window_card.layout.addLayout(window_grid)
        self.plot_smoothed = QtWidgets.QCheckBox("Plot smoothed traces")
        self.plot_smoothed.setChecked(True)
        self.apply_baseline = QtWidgets.QCheckBox("Apply baseline correction")
        self.apply_baseline.setChecked(True)
        window_card.layout.addWidget(self.plot_smoothed)
        window_card.layout.addWidget(self.apply_baseline)
        controls_layout.addWidget(window_card)

        smoothing_card = Card("Channel smoothing")
        smoothing_grid = QtWidgets.QGridLayout()
        smoothing_grid.setHorizontalSpacing(10)
        smoothing_grid.setVerticalSpacing(7)
        smoothing_grid.setColumnStretch(1, 1)
        self.smoothing_inputs: list[QtWidgets.QSpinBox] = []
        for row, channel in enumerate(self.session.channels):
            value = QtWidgets.QSpinBox()
            value.setRange(1, 200)
            value.setValue(10 if channel.key != "control" else 5)
            value.setSuffix(" samples")
            self.smoothing_inputs.append(value)
            add_form_row(smoothing_grid, row, channel.key, value)
        smoothing_card.layout.addLayout(smoothing_grid)
        controls_layout.addWidget(smoothing_card)

        action_row = QtWidgets.QHBoxLayout()
        reset = button("Defaults", "ghost")
        reset.clicked.connect(self._restore_defaults)
        action_row.addWidget(reset)
        action_row.addStretch()
        apply_button = button("Apply settings", "primary")
        apply_button.clicked.connect(self._refresh_preview)
        action_row.addWidget(apply_button)
        controls_layout.addLayout(action_row)
        controls_layout.addStretch()

        self.plot = AnalysisPlotWidget(session, "Event-aligned response")
        self.plot.toast_requested.connect(self.toast_requested)
        splitter.addWidget(self.plot)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([350, 980])

        self.baseline_start.valueChanged.connect(self._sync_baseline_region)
        self.baseline_end.valueChanged.connect(self._sync_baseline_region)
        self.epoc_combo.currentTextChanged.connect(self._update_epoc_summary)

    def _sync_baseline_region(self, *_: object) -> None:
        start = self.baseline_start.value()
        end = self.baseline_end.value()
        if start < end:
            self.plot.set_baseline_region(start, end)

    def _update_epoc_summary(self, epoc: str) -> None:
        self.plot.summary_label.setText(
            f"{self.plot.selected_trial_count()} selected · aligned to {epoc}"
        )

    def _refresh_preview(self) -> None:
        if self.trange_start.value() >= self.trange_end.value():
            self.toast_requested.emit("TRANGE start must be earlier than TRANGE end.")
            return
        if self.baseline_start.value() >= self.baseline_end.value():
            self.toast_requested.emit("Baseline start must be earlier than baseline end.")
            return
        self.plot.reset_view()
        self.toast_requested.emit(
            "Synthetic preview refreshed; the analysis pipeline was not called."
        )

    def _restore_defaults(self) -> None:
        self.trange_start.setValue(-2.0)
        self.trange_end.setValue(5.0)
        self.baseline_start.setValue(-2.0)
        self.baseline_end.setValue(-1.0)
        self.baseline_adjust.setValue(-2.0)
        self.downsample.setValue(10)
        self.toast_requested.emit("Prototype controls restored to defaults.")
