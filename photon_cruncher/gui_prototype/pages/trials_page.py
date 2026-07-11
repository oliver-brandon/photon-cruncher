from __future__ import annotations

from collections.abc import Callable

from PySide6 import QtCore, QtGui, QtWidgets

from photon_cruncher.gui_prototype.components import (
    Card,
    NoticeBar,
    PageHeader,
    button,
    label,
    pill,
)
from photon_cruncher.gui_prototype.demo_data import (
    TRIAL_TYPES,
    TRIAL_TYPE_TITLES,
    DemoSession,
)
from photon_cruncher.gui_prototype.plots import AnalysisPlotWidget


class TrialsPage(QtWidgets.QWidget):
    toast_requested = QtCore.Signal(str)

    def __init__(
        self,
        session: DemoSession,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.session = session
        self._updating_checks = False

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(12)
        header = PageHeader(
            "Trial explorer",
            "Filter classified outcomes and inspect how selected trials shape the response.",
        )
        export_csv = button("Export selected CSV", "ghost")
        export_csv.clicked.connect(
            lambda: self.toast_requested.emit(
                "Selected-trial CSV export is mocked; no file was written."
            )
        )
        header.add_action(export_csv)
        export_figure = button("Export selected figure", "primary")
        export_figure.clicked.connect(
            lambda: self.toast_requested.emit(
                "Selected-trial figure export is mocked; no file was written."
            )
        )
        header.add_action(export_figure)
        root.addWidget(header)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, 1)

        controls = Card()
        controls.setMinimumWidth(335)
        controls.setMaximumWidth(390)
        controls.layout.setSpacing(9)
        title_row = QtWidgets.QHBoxLayout()
        title_group = QtWidgets.QVBoxLayout()
        title_group.setSpacing(1)
        title_group.addWidget(label("Trial selection", "cardTitle"))
        title_group.addWidget(label("LeverA · classified outcomes", "quiet"))
        title_row.addLayout(title_group, 1)
        self.selected_pill = pill("48 selected", "teal")
        title_row.addWidget(self.selected_pill)
        controls.layout.addLayout(title_row)

        self.search_input = QtWidgets.QLineEdit()
        self.search_input.setPlaceholderText("Search trial number or outcome…")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setAccessibleName("Search trial list")
        controls.layout.addWidget(self.search_input)

        controls.layout.addWidget(label("OUTCOME FILTERS", "sectionEyebrow"))
        filter_grid = QtWidgets.QGridLayout()
        filter_grid.setSpacing(6)
        self.filter_buttons: dict[str, QtWidgets.QPushButton] = {}
        for index, outcome in enumerate(TRIAL_TYPES):
            filter_button = button(TRIAL_TYPE_TITLES[outcome], "filter")
            filter_button.setCheckable(True)
            filter_button.setChecked(True)
            filter_button.setToolTip(f"Show or hide {outcome} trials.")
            filter_button.toggled.connect(self._apply_filters)
            self.filter_buttons[outcome] = filter_button
            filter_grid.addWidget(filter_button, index // 2, index % 2)
        filter_grid.setColumnStretch(0, 1)
        filter_grid.setColumnStretch(1, 1)
        controls.layout.addLayout(filter_grid)

        selection_actions = QtWidgets.QHBoxLayout()
        selection_actions.setSpacing(6)
        for text, action in (
            ("All visible", self._select_all_visible),
            ("None", self._select_none),
            ("Invert", self._invert_visible),
        ):
            action_button = button(text, "ghost")
            action_button.clicked.connect(action)
            selection_actions.addWidget(action_button)
        controls.layout.addLayout(selection_actions)

        self.trial_list = QtWidgets.QListWidget()
        self.trial_list.setAlternatingRowColors(True)
        self.trial_list.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.trial_list.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.trial_list.setAccessibleName("Classified synthetic trials")
        controls.layout.addWidget(self.trial_list, 1)

        footer = QtWidgets.QHBoxLayout()
        self.visible_label = label("48 visible", "quiet")
        footer.addWidget(self.visible_label)
        footer.addStretch()
        footer.addWidget(pill("3 artifacts", "warning"))
        controls.layout.addLayout(footer)
        splitter.addWidget(controls)

        plot_column = QtWidgets.QWidget()
        plot_layout = QtWidgets.QVBoxLayout(plot_column)
        plot_layout.setContentsMargins(0, 0, 0, 0)
        plot_layout.setSpacing(10)
        plot_layout.addWidget(
            NoticeBar(
                "Selections update only the deterministic visual model; no processed "
                "result is changed or exported."
            )
        )
        self.plot = AnalysisPlotWidget(
            session,
            "Selected-trial response",
            allow_display_mode=True,
        )
        self.plot.toast_requested.connect(self.toast_requested)
        plot_layout.addWidget(self.plot, 1)
        splitter.addWidget(plot_column)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([360, 970])

        self._populate_trials()
        self.search_input.textChanged.connect(self._apply_filters)
        self.trial_list.itemChanged.connect(self._selection_changed)
        self._selection_changed()

    def _populate_trials(self) -> None:
        self.trial_list.clear()
        for index, trial in enumerate(self.session.trials):
            artifact_suffix = "  ·  artifact" if trial.artifact else ""
            title = TRIAL_TYPE_TITLES[trial.outcome]
            item = QtWidgets.QListWidgetItem(
                f"Trial {trial.number:02d}   ·   {title}{artifact_suffix}"
            )
            item.setData(QtCore.Qt.UserRole, index)
            item.setData(QtCore.Qt.UserRole + 1, trial.outcome)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Checked)
            if trial.artifact:
                item.setForeground(QtGui.QColor("#9A4B0D"))
                item.setToolTip("Synthetic artifact flag included for visual review.")
            self.trial_list.addItem(item)

    def _apply_filters(self, *_: object) -> None:
        query = self.search_input.text().strip().lower()
        visible = 0
        for row in range(self.trial_list.count()):
            item = self.trial_list.item(row)
            outcome = str(item.data(QtCore.Qt.UserRole + 1))
            matches_outcome = self.filter_buttons[outcome].isChecked()
            matches_query = not query or query in item.text().lower()
            item.setHidden(not (matches_outcome and matches_query))
            if not item.isHidden():
                visible += 1
        self.visible_label.setText(f"{visible} visible")

    def _visible_items(self) -> list[QtWidgets.QListWidgetItem]:
        return [
            self.trial_list.item(row)
            for row in range(self.trial_list.count())
            if not self.trial_list.item(row).isHidden()
        ]

    def _set_checks(
        self,
        items: list[QtWidgets.QListWidgetItem],
        state_for: Callable[[QtWidgets.QListWidgetItem], bool],
    ) -> None:
        self._updating_checks = True
        try:
            for item in items:
                item.setCheckState(
                    QtCore.Qt.Checked if state_for(item) else QtCore.Qt.Unchecked
                )
        finally:
            self._updating_checks = False
        self._selection_changed()

    def _select_all_visible(self) -> None:
        self._set_checks(self._visible_items(), lambda _: True)

    def _select_none(self) -> None:
        self._set_checks(
            [self.trial_list.item(row) for row in range(self.trial_list.count())],
            lambda _: False,
        )

    def _invert_visible(self) -> None:
        self._set_checks(
            self._visible_items(),
            lambda item: item.checkState() != QtCore.Qt.Checked,
        )

    def _selection_changed(self, _: QtWidgets.QListWidgetItem | None = None) -> None:
        if self._updating_checks:
            return
        selected = [
            int(self.trial_list.item(row).data(QtCore.Qt.UserRole))
            for row in range(self.trial_list.count())
            if self.trial_list.item(row).checkState() == QtCore.Qt.Checked
        ]
        self.selected_pill.setText(f"{len(selected)} selected")
        self.plot.set_trial_indices(selected)

    def selected_indices(self) -> list[int]:
        return [
            int(self.trial_list.item(row).data(QtCore.Qt.UserRole))
            for row in range(self.trial_list.count())
            if self.trial_list.item(row).checkState() == QtCore.Qt.Checked
        ]
