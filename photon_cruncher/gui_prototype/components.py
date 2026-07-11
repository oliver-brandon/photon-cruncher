from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtGui, QtSvg, QtWidgets


ASSET_DIR = Path(__file__).resolve().parent / "assets"


def label(text: str, kind: str = "muted") -> QtWidgets.QLabel:
    widget = QtWidgets.QLabel(text)
    widget.setProperty("kind", kind)
    widget.setWordWrap(True)
    widget.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Maximum)
    return widget


def button(
    text: str,
    variant: str | None = None,
    accessible_name: str | None = None,
) -> QtWidgets.QPushButton:
    widget = QtWidgets.QPushButton(text)
    if variant:
        widget.setProperty("variant", variant)
    widget.setAccessibleName(accessible_name or text)
    return widget


def pill(text: str, tone: str = "neutral") -> QtWidgets.QLabel:
    widget = QtWidgets.QLabel(text)
    widget.setProperty("pill", True)
    widget.setProperty("tone", tone)
    widget.setAlignment(QtCore.Qt.AlignCenter)
    widget.setSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Fixed)
    return widget


def svg_icon(name: str, color: str = "#A8B3C0", size: int = 20) -> QtGui.QIcon:
    source = (ASSET_DIR / f"{name}.svg").read_text(encoding="utf-8")
    source = source.replace("currentColor", color)
    renderer = QtSvg.QSvgRenderer(QtCore.QByteArray(source.encode("utf-8")))
    pixmap = QtGui.QPixmap(size, size)
    pixmap.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QtGui.QIcon(pixmap)


class Card(QtWidgets.QFrame):
    def __init__(
        self,
        title: str | None = None,
        subtitle: str | None = None,
        parent: QtWidgets.QWidget | None = None,
        subtle: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("SubtleCard" if subtle else "Card")
        self.layout = QtWidgets.QVBoxLayout(self)
        self.layout.setContentsMargins(16, 14, 16, 14)
        self.layout.setSpacing(10)
        if title:
            title_row = QtWidgets.QVBoxLayout()
            title_row.setSpacing(2)
            title_row.addWidget(label(title, "cardTitle"))
            if subtitle:
                title_row.addWidget(label(subtitle, "quiet"))
            self.layout.addLayout(title_row)


class PageHeader(QtWidgets.QWidget):
    def __init__(
        self,
        title: str,
        subtitle: str,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        text_layout = QtWidgets.QVBoxLayout()
        text_layout.setSpacing(2)
        text_layout.addWidget(label(title, "pageTitle"))
        text_layout.addWidget(label(subtitle, "pageSubtitle"))
        layout.addLayout(text_layout, 1)
        self.actions = QtWidgets.QHBoxLayout()
        self.actions.setSpacing(8)
        layout.addLayout(self.actions)

    def add_action(self, widget: QtWidgets.QWidget) -> None:
        self.actions.addWidget(widget)


class MetricCard(Card):
    def __init__(
        self,
        value: str,
        title: str,
        detail: str,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent=parent)
        self.layout.setSpacing(3)
        self.layout.addWidget(label(title.upper(), "metricLabel"))
        self.layout.addWidget(label(value, "metricValue"))
        self.layout.addWidget(label(detail, "quiet"))


class NoticeBar(QtWidgets.QFrame):
    def __init__(
        self,
        text: str,
        tone: str = "info",
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("NoticeWarning" if tone == "warning" else "NoticeInfo")
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(9)
        marker = QtWidgets.QLabel("!" if tone == "warning" else "i")
        marker.setAlignment(QtCore.Qt.AlignCenter)
        marker.setFixedSize(20, 20)
        marker.setStyleSheet(
            "border-radius: 10px; font-weight: 700; "
            + (
                "color: #9A4B0D; background: #FBE8C3;"
                if tone == "warning"
                else "color: #0F6976; background: #CDECEF;"
            )
        )
        layout.addWidget(marker)
        layout.addWidget(label(text, "muted"), 1)


class FieldLabel(QtWidgets.QLabel):
    def __init__(self, text: str, tooltip: str = "") -> None:
        super().__init__(text)
        self.setProperty("kind", "muted")
        if tooltip:
            self.setToolTip(tooltip)


def add_form_row(
    layout: QtWidgets.QGridLayout,
    row: int,
    text: str,
    widget: QtWidgets.QWidget,
    tooltip: str = "",
) -> None:
    field_label = FieldLabel(text, tooltip)
    field_label.setBuddy(widget)
    layout.addWidget(field_label, row, 0)
    layout.addWidget(widget, row, 1)


def horizontal_separator() -> QtWidgets.QFrame:
    separator = QtWidgets.QFrame()
    separator.setFrameShape(QtWidgets.QFrame.HLine)
    separator.setStyleSheet("color: #E6EBF0;")
    return separator
