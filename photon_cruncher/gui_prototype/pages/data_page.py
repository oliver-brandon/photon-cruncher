from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from photon_cruncher.gui_prototype.components import (
    Card,
    MetricCard,
    NoticeBar,
    PageHeader,
    button,
    label,
    pill,
)
from photon_cruncher.gui_prototype.demo_data import DemoSession


class DataPage(QtWidgets.QWidget):
    toast_requested = QtCore.Signal(str)
    demo_state_changed = QtCore.Signal(str)

    def __init__(
        self,
        session: DemoSession,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.session = session
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(16)
        self.state_stack = QtWidgets.QStackedWidget()
        root.addWidget(self.state_stack)
        self.empty_state = self._build_empty_state()
        self.demo_state = self._build_demo_state()
        self.state_stack.addWidget(self.empty_state)
        self.state_stack.addWidget(self.demo_state)
        self.set_state("demo")

    def _build_empty_state(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        header = PageHeader(
            "Data workspace",
            "Start with a MATLAB export, a TDT block, or an entire TDT tank.",
        )
        demo_button = button("Open synthetic demo", "primary")
        demo_button.setToolTip("Populate every prototype page with safe synthetic data.")
        demo_button.clicked.connect(lambda: self._load_demo("Synthetic demo opened."))
        header.add_action(demo_button)
        layout.addWidget(header)

        drop_zone = QtWidgets.QFrame()
        drop_zone.setObjectName("DropZone")
        drop_zone.setMinimumHeight(310)
        drop_layout = QtWidgets.QVBoxLayout(drop_zone)
        drop_layout.setContentsMargins(32, 30, 32, 30)
        drop_layout.setSpacing(12)
        drop_layout.addStretch()
        mark = QtWidgets.QLabel("+")
        mark.setFixedSize(52, 52)
        mark.setAlignment(QtCore.Qt.AlignCenter)
        mark.setStyleSheet(
            "font-size: 30px; font-weight: 300; color: #137C8B; "
            "background: #DDF2F4; border: 1px solid #B8DCE1; border-radius: 26px;"
        )
        drop_layout.addWidget(mark, 0, QtCore.Qt.AlignHCenter)
        title = label("Drop photometry data here", "cardTitle")
        title.setAlignment(QtCore.Qt.AlignCenter)
        drop_layout.addWidget(title)
        description = label(
            "This design study will not read dropped files. Use one of the actions "
            "below to preview the populated synthetic state.",
            "muted",
        )
        description.setAlignment(QtCore.Qt.AlignCenter)
        description.setMaximumWidth(570)
        description.setMinimumHeight(42)
        drop_layout.addWidget(description, 0, QtCore.Qt.AlignHCenter)
        actions = QtWidgets.QHBoxLayout()
        actions.setSpacing(8)
        for text, message in (
            ("Choose MAT files", "MAT import mocked with synthetic data."),
            ("Choose TDT block", "TDT block import mocked with synthetic data."),
            ("Choose TDT tank", "TDT tank import mocked with synthetic data."),
        ):
            action = button(text)
            action.clicked.connect(lambda _, detail=message: self._load_demo(detail))
            actions.addWidget(action)
        action_widget = QtWidgets.QWidget()
        action_widget.setLayout(actions)
        drop_layout.addWidget(action_widget, 0, QtCore.Qt.AlignHCenter)
        drop_layout.addStretch()
        layout.addWidget(drop_zone, 1)
        layout.addWidget(
            NoticeBar(
                "Prototype safety: no file picker, loader, analysis function, or "
                "user setting is called from this window."
            )
        )
        return page

    def _build_demo_state(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        header = PageHeader(
            "Data workspace",
            "Review the loaded session before choosing an epoc and analysis window.",
        )
        empty_button = button("Show empty state", "ghost")
        empty_button.clicked.connect(lambda: self.set_state("empty"))
        header.add_action(empty_button)
        add_button = button("Add data", "primary")
        add_button.clicked.connect(
            lambda: self.toast_requested.emit(
                "Import is intentionally mocked; no file dialog was opened."
            )
        )
        header.add_action(add_button)
        layout.addWidget(header)

        session_card = Card()
        session_row = QtWidgets.QHBoxLayout()
        session_row.setSpacing(12)
        avatar = QtWidgets.QLabel("D42")
        avatar.setFixedSize(48, 48)
        avatar.setAlignment(QtCore.Qt.AlignCenter)
        avatar.setStyleSheet(
            "color: #0F6976; background: #DDF2F4; border: 1px solid #B8DCE1; "
            "border-radius: 9px; font-size: 13px; font-weight: 700;"
        )
        session_row.addWidget(avatar)
        session_text = QtWidgets.QVBoxLayout()
        session_text.setSpacing(2)
        session_text.addWidget(label(self.session.name, "cardTitle"))
        session_text.addWidget(label(self.session.subtitle, "muted"))
        session_row.addLayout(session_text, 1)
        session_row.addWidget(pill("SYNTHETIC DEMO", "teal"))
        session_row.addWidget(pill("READY", "success"))
        session_card.layout.addLayout(session_row)
        layout.addWidget(session_card)

        metrics = QtWidgets.QHBoxLayout()
        metrics.setSpacing(10)
        for value, title, detail in (
            (self.session.duration, "Duration", "Complete recording"),
            (
                f"{self.session.sample_rate:,.2f} Hz",
                "Sample rate",
                "Native stream rate",
            ),
            (str(len(self.session.epocs)), "Epocs", "Detected event stores"),
            (str(self.session.valid_trials), "Valid trials", "2 edge trials dropped"),
        ):
            metrics.addWidget(MetricCard(value, title, detail), 1)
        layout.addLayout(metrics)

        details = QtWidgets.QHBoxLayout()
        details.setSpacing(12)
        channel_card = Card(
            "Available channels",
            "Paired stores are shown as they would appear before analysis.",
        )
        channel_table = QtWidgets.QTableWidget(len(self.session.channels), 3)
        channel_table.setHorizontalHeaderLabels(["Channel", "Store pairing", "State"])
        channel_table.horizontalHeader().setSectionResizeMode(
            0, QtWidgets.QHeaderView.Stretch
        )
        channel_table.horizontalHeader().setSectionResizeMode(
            1, QtWidgets.QHeaderView.Stretch
        )
        channel_table.horizontalHeader().setSectionResizeMode(
            2, QtWidgets.QHeaderView.ResizeToContents
        )
        channel_table.verticalHeader().hide()
        channel_table.setAlternatingRowColors(True)
        channel_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        channel_table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        channel_table.setFixedHeight(140)
        for row, channel in enumerate(self.session.channels):
            channel_table.setItem(row, 0, QtWidgets.QTableWidgetItem(channel.title))
            channel_table.setItem(row, 1, QtWidgets.QTableWidgetItem(channel.store))
            channel_table.setItem(row, 2, QtWidgets.QTableWidgetItem("Ready"))
        channel_card.layout.addWidget(channel_table)
        channel_card.layout.addStretch()
        details.addWidget(channel_card, 3)

        event_card = Card("Session checks", "A compact preflight before alignment.")
        for title, value, tone in (
            ("Event timestamps", f"{self.session.event_count} found", "success"),
            ("Complete windows", f"{self.session.valid_trials} retained", "success"),
            ("Dropped edge trials", "1, 50", "warning"),
            ("Source access", "Synthetic only", "teal"),
        ):
            row = QtWidgets.QHBoxLayout()
            row.addWidget(label(title, "muted"))
            row.addStretch()
            row.addWidget(pill(value, tone))
            event_card.layout.addLayout(row)
        event_card.layout.addStretch()
        details.addWidget(event_card, 2)
        layout.addLayout(details, 1)

        layout.addWidget(
            NoticeBar(
                "Ready for preview. Continue to Align to explore the synthetic "
                "channel response and heatmap."
            )
        )
        return page

    def _load_demo(self, message: str) -> None:
        self.set_state("demo")
        self.toast_requested.emit(message)

    def set_state(self, state: str) -> None:
        normalized = "empty" if state == "empty" else "demo"
        self.state_stack.setCurrentWidget(
            self.empty_state if normalized == "empty" else self.demo_state
        )
        self.demo_state_changed.emit(normalized)

    def state(self) -> str:
        return "empty" if self.state_stack.currentWidget() is self.empty_state else "demo"
