from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from photon_cruncher.gui_prototype.components import button, label, pill
from photon_cruncher.gui_prototype.demo_data import DemoSession


class AnalysisPlotWidget(QtWidgets.QFrame):
    """Interactive PyQtGraph study backed only by deterministic demo data."""

    toast_requested = QtCore.Signal(str)

    def __init__(
        self,
        session: DemoSession,
        title: str,
        allow_display_mode: bool = False,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setAccessibleName(f"{title} interactive plot")
        self.session = session
        self._trial_indices = np.arange(len(session.trials), dtype=int)
        self._individual_curves: list[pg.PlotDataItem] = []

        pg.setConfigOptions(antialias=True, imageAxisOrder="row-major")

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(8)

        title_row = QtWidgets.QHBoxLayout()
        title_row.setSpacing(8)
        title_layout = QtWidgets.QVBoxLayout()
        title_layout.setSpacing(1)
        title_layout.addWidget(label(title, "cardTitle"))
        self.summary_label = label("48 valid trials · aligned to LeverA", "quiet")
        title_layout.addWidget(self.summary_label)
        title_row.addLayout(title_layout)
        title_row.addStretch()

        self.trial_pill = pill("48 trials", "teal")
        title_row.addWidget(self.trial_pill)
        outer.addLayout(title_row)

        toolbar = QtWidgets.QHBoxLayout()
        toolbar.setSpacing(8)
        toolbar.addWidget(label("Display", "quiet"))
        self.channel_combo = QtWidgets.QComboBox()
        self.channel_combo.setAccessibleName("Displayed channel")
        self.channel_combo.setToolTip("Choose the synthetic channel shown in both plots.")
        self.channel_combo.setMinimumWidth(170)
        for channel in session.channels:
            self.channel_combo.addItem(channel.title, channel.key)
        toolbar.addWidget(self.channel_combo)

        self.display_mode: QtWidgets.QComboBox | None = None
        if allow_display_mode:
            self.display_mode = QtWidgets.QComboBox()
            self.display_mode.addItem("Mean ± SEM", "mean")
            self.display_mode.addItem("Individual overlay", "individual")
            self.display_mode.setAccessibleName("Trace display mode")
            self.display_mode.setToolTip(
                "Switch between the selected-trial mean and individual trial overlays."
            )
            toolbar.addWidget(self.display_mode)

        toolbar.addStretch()
        self.autoscale_button = button("Autoscale", "ghost")
        self.autoscale_button.setToolTip("Fit the visible synthetic data to the plot.")
        toolbar.addWidget(self.autoscale_button)
        self.reset_button = button("Reset view", "ghost")
        self.reset_button.setToolTip("Restore the full -4 to +8 second window.")
        toolbar.addWidget(self.reset_button)
        outer.addLayout(toolbar)

        self.graphics = pg.GraphicsLayoutWidget()
        self.graphics.setBackground("#FFFFFF")
        self.graphics.setAccessibleName("Linked event trace and trial heatmap")
        self.graphics.setMinimumHeight(310)
        self.graphics.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Expanding,
        )
        outer.addWidget(self.graphics, 1)

        self.trace_plot = self.graphics.addPlot(row=0, col=0)
        self.trace_plot.setLabel("left", "Z-score")
        self.trace_plot.setLabel("bottom", "Time from epoc", units="s")
        self.trace_plot.showGrid(x=True, y=True, alpha=0.13)
        self.trace_plot.setClipToView(True)
        self.trace_plot.setDownsampling(auto=True, mode="peak")
        self.trace_plot.getViewBox().setMouseMode(pg.ViewBox.PanMode)

        self.lower_curve = self.trace_plot.plot(pen=None)
        self.upper_curve = self.trace_plot.plot(pen=None)
        self.sem_fill = pg.FillBetweenItem(
            self.lower_curve,
            self.upper_curve,
            brush=pg.mkBrush(37, 99, 235, 42),
        )
        self.trace_plot.addItem(self.sem_fill)
        self.mean_curve = self.trace_plot.plot(
            pen=pg.mkPen("#2563EB", width=2.2),
            name="Mean z",
        )
        for _ in range(12):
            curve = self.trace_plot.plot(
                pen=pg.mkPen(37, 99, 235, 50, width=1.0),
            )
            curve.hide()
            self._individual_curves.append(curve)

        self.zero_time = pg.InfiniteLine(
            pos=0.0,
            angle=90,
            movable=False,
            pen=pg.mkPen("#52606D", width=1.2, style=QtCore.Qt.DashLine),
            label="epoc",
            labelOpts={"position": 0.96, "color": "#52606D"},
        )
        self.trace_plot.addItem(self.zero_time)
        self.zero_z = pg.InfiniteLine(
            pos=0.0,
            angle=0,
            movable=False,
            pen=pg.mkPen("#AAB4BE", width=0.8),
        )
        self.trace_plot.addItem(self.zero_z)
        self.baseline_region = pg.LinearRegionItem(
            values=(-2.0, -1.0),
            bounds=(-4.0, 0.0),
            movable=True,
            brush=pg.mkBrush(19, 124, 139, 28),
            pen=pg.mkPen("#137C8B", width=1.0),
            hoverBrush=pg.mkBrush(19, 124, 139, 46),
            hoverPen=pg.mkPen("#0F6976", width=1.4),
        )
        self.baseline_region.setZValue(-5)
        self.trace_plot.addItem(self.baseline_region)

        self.crosshair_v = pg.InfiniteLine(
            angle=90,
            movable=False,
            pen=pg.mkPen("#98A2B3", width=0.8, style=QtCore.Qt.DotLine),
        )
        self.crosshair_h = pg.InfiniteLine(
            angle=0,
            movable=False,
            pen=pg.mkPen("#98A2B3", width=0.8, style=QtCore.Qt.DotLine),
        )
        self.trace_plot.addItem(self.crosshair_v, ignoreBounds=True)
        self.trace_plot.addItem(self.crosshair_h, ignoreBounds=True)

        self.heat_plot = self.graphics.addPlot(row=1, col=0)
        self.heat_plot.setLabel("left", "Trial")
        self.heat_plot.setLabel("bottom", "Time from epoc", units="s")
        self.heat_plot.setMaximumHeight(260)
        self.heat_plot.setXLink(self.trace_plot)
        self.heat_plot.setMouseEnabled(x=True, y=False)
        self.heat_plot.getViewBox().setMouseMode(pg.ViewBox.PanMode)
        self.heat_image = pg.ImageItem(axisOrder="row-major")
        self.heat_plot.addItem(self.heat_image)
        self.color_bar = pg.ColorBarItem(
            values=(-3.0, 3.0),
            colorMap=pg.colormap.get("viridis"),
            interactive=False,
            width=13,
            colorMapMenu=False,
            label="z",
        )
        self.color_bar.setImageItem(self.heat_image, insert_in=self.heat_plot)
        self.heat_zero_time = pg.InfiniteLine(
            pos=0.0,
            angle=90,
            movable=False,
            pen=pg.mkPen("#F8FAFC", width=1.2, style=QtCore.Qt.DashLine),
        )
        self.heat_plot.addItem(self.heat_zero_time)
        self.graphics.ci.layout.setRowStretchFactor(0, 3)
        self.graphics.ci.layout.setRowStretchFactor(1, 2)

        footer = QtWidgets.QHBoxLayout()
        footer.setSpacing(8)
        footer.addWidget(pill("PAN / ZOOM ENABLED", "neutral"))
        footer.addWidget(label("Drag teal baseline handles.", "quiet"))
        footer.addStretch()
        self.coordinate_label = label("Time —  ·  Z —", "quiet")
        self.coordinate_label.setWordWrap(False)
        self.coordinate_label.setMinimumWidth(125)
        self.coordinate_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        footer.addWidget(self.coordinate_label)
        outer.addLayout(footer)

        self.channel_combo.currentIndexChanged.connect(self._update_data)
        if self.display_mode is not None:
            self.display_mode.currentIndexChanged.connect(self._update_data)
        self.autoscale_button.clicked.connect(self.autoscale)
        self.reset_button.clicked.connect(self.reset_view)
        self.baseline_region.sigRegionChangeFinished.connect(
            self._announce_baseline_change
        )
        self._mouse_proxy = pg.SignalProxy(
            self.graphics.scene().sigMouseMoved,
            rateLimit=45,
            slot=self._mouse_moved,
        )

        self._style_axes()
        self._update_data()
        self.reset_view()

    @property
    def heat_tick_labels(self) -> list[str]:
        return [text for _, text in self._heat_ticks()]

    def _style_axes(self) -> None:
        axis_pen = pg.mkPen("#AAB4BE", width=0.8)
        text_pen = pg.mkPen("#667085")
        for plot in (self.trace_plot, self.heat_plot):
            for axis_name in ("left", "bottom"):
                axis = plot.getAxis(axis_name)
                axis.setPen(axis_pen)
                axis.setTextPen(text_pen)
                axis.setStyle(tickTextOffset=7)

    def _selected_channel(self):
        index = max(0, self.channel_combo.currentIndex())
        return self.session.channels[index]

    def set_channel(self, channel_key: str) -> None:
        index = self.channel_combo.findData(channel_key)
        if index >= 0:
            self.channel_combo.setCurrentIndex(index)

    def set_trial_indices(self, indices: Iterable[int]) -> None:
        unique = sorted(
            {
                int(index)
                for index in indices
                if 0 <= int(index) < len(self.session.trials)
            }
        )
        self._trial_indices = np.asarray(unique, dtype=int)
        self._update_data()

    def selected_trial_count(self) -> int:
        return int(self._trial_indices.size)

    def _displaying_individual(self) -> bool:
        return bool(
            self.display_mode is not None
            and self.display_mode.currentData() == "individual"
        )

    def _update_data(self, *_: object) -> None:
        channel = self._selected_channel()
        times = self.session.times
        if self._trial_indices.size:
            matrix = channel.trials[self._trial_indices]
            mean = matrix.mean(axis=0)
            sem = (
                matrix.std(axis=0, ddof=1) / np.sqrt(matrix.shape[0])
                if matrix.shape[0] > 1
                else np.zeros(matrix.shape[1], dtype=float)
            )
        else:
            matrix = np.zeros((1, times.size), dtype=np.float32)
            mean = np.full(times.size, np.nan)
            sem = np.zeros(times.size, dtype=float)

        pen = pg.mkPen(channel.color, width=2.2)
        brush_color = QtGui.QColor(channel.color)
        brush_color.setAlpha(42)
        self.mean_curve.setPen(pen)
        self.sem_fill.setBrush(pg.mkBrush(brush_color))
        self.mean_curve.setData(times, mean)
        self.lower_curve.setData(times, mean - sem)
        self.upper_curve.setData(times, mean + sem)

        show_individual = (
            self._displaying_individual() and self._trial_indices.size > 0
        )
        for curve_index, curve in enumerate(self._individual_curves):
            if show_individual and curve_index < min(
                matrix.shape[0], len(self._individual_curves)
            ):
                curve.setPen(pg.mkPen(brush_color, width=1.0))
                curve.setData(times, matrix[curve_index])
                curve.show()
            else:
                curve.hide()
        self.mean_curve.setOpacity(0.75 if show_individual else 1.0)

        levels = (-3.0, 3.0)
        self.heat_image.setImage(matrix, autoLevels=False, levels=levels)
        self.heat_image.setRect(
            QtCore.QRectF(
                float(times[0]),
                0.5,
                float(times[-1] - times[0]),
                float(matrix.shape[0]),
            )
        )
        self.heat_plot.setYRange(0.5, matrix.shape[0] + 0.5, padding=0.0)
        self.heat_plot.setLimits(yMin=0.5, yMax=matrix.shape[0] + 0.5)
        self.heat_plot.getAxis("left").setTicks([self._heat_ticks()])

        count = int(self._trial_indices.size)
        self.trial_pill.setText(f"{count} trial" + ("" if count == 1 else "s"))
        self.summary_label.setText(
            f"{count} selected · aligned to LeverA · {channel.store}"
        )

    def _heat_ticks(self) -> list[tuple[float, str]]:
        count = int(self._trial_indices.size)
        if count <= 0:
            return []
        max_ticks = 9
        if count <= max_ticks:
            positions = list(range(count))
        else:
            positions = sorted(
                {
                    round(index * (count - 1) / (max_ticks - 1))
                    for index in range(max_ticks)
                }
            )
        return [
            (
                float(position + 1),
                str(self.session.trials[int(self._trial_indices[position])].number),
            )
            for position in positions
        ]

    def reset_view(self) -> None:
        self.trace_plot.setXRange(-4.0, 8.0, padding=0.0)
        self.heat_plot.setXRange(-4.0, 8.0, padding=0.0)
        self.trace_plot.enableAutoRange(axis=pg.ViewBox.YAxis, enable=True)
        self.toast_requested.emit("Plot view reset to the complete synthetic window.")

    def autoscale(self) -> None:
        self.trace_plot.autoRange(padding=0.08)
        self.trace_plot.setXRange(-4.0, 8.0, padding=0.0)
        self.toast_requested.emit("Visible synthetic traces autoscaled.")

    def set_baseline_region(self, start: float, end: float) -> None:
        self.baseline_region.setRegion((float(start), float(end)))

    def _announce_baseline_change(self) -> None:
        start, end = self.baseline_region.getRegion()
        self.toast_requested.emit(
            f"Baseline preview moved to {start:.2f} through {end:.2f} seconds."
        )

    def _mouse_moved(self, event: tuple[QtCore.QPointF]) -> None:
        if not event:
            return
        position = event[0]
        if not self.trace_plot.sceneBoundingRect().contains(position):
            return
        point = self.trace_plot.getViewBox().mapSceneToView(position)
        self.crosshair_v.setPos(point.x())
        self.crosshair_h.setPos(point.y())
        self.coordinate_label.setText(f"Time {point.x():+.2f}s  ·  Z {point.y():+.2f}")
