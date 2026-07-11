from __future__ import annotations

from PySide6 import QtGui, QtWidgets


COLORS = {
    "sidebar": "#20262E",
    "sidebar_hover": "#2A333D",
    "sidebar_active": "#174E58",
    "canvas": "#F4F7F9",
    "surface": "#FFFFFF",
    "surface_alt": "#F8FAFC",
    "primary": "#137C8B",
    "primary_hover": "#0F6976",
    "blue": "#2563EB",
    "text": "#17212B",
    "muted": "#667085",
    "border": "#D8E0E8",
    "success": "#15803D",
    "warning": "#B45309",
    "danger": "#B42318",
}


STYLESHEET = r"""
QWidget {
    color: #17212B;
    font-size: 13px;
}
QMainWindow, QWidget#PrototypeRoot, QStackedWidget#PageStack {
    background: #F4F7F9;
}
QFrame#AppHeader {
    background: #FFFFFF;
    border: none;
    border-bottom: 1px solid #D8E0E8;
}
QFrame#Sidebar {
    background: #20262E;
    border: none;
}
QFrame#Card {
    background: #FFFFFF;
    border: 1px solid #D8E0E8;
    border-radius: 10px;
}
QFrame#SubtleCard {
    background: #F8FAFC;
    border: 1px solid #E3E8EF;
    border-radius: 8px;
}
QFrame#DropZone {
    background: #F8FBFC;
    border: 2px dashed #9BBBC1;
    border-radius: 12px;
}
QFrame#NoticeInfo {
    background: #EEF8FA;
    border: 1px solid #B8DCE1;
    border-radius: 8px;
}
QFrame#NoticeWarning {
    background: #FFF8EB;
    border: 1px solid #F0D5A4;
    border-radius: 8px;
}
QLabel[kind="appTitle"] {
    color: #17212B;
    font-size: 16px;
    font-weight: 700;
}
QLabel[kind="pageTitle"] {
    color: #17212B;
    font-size: 24px;
    font-weight: 700;
}
QLabel[kind="pageSubtitle"] {
    color: #667085;
    font-size: 13px;
}
QLabel[kind="cardTitle"] {
    color: #17212B;
    font-size: 14px;
    font-weight: 700;
}
QLabel[kind="sectionEyebrow"] {
    color: #8D9AA8;
    font-size: 10px;
    font-weight: 700;
}
QLabel[kind="muted"] {
    color: #667085;
}
QLabel[kind="quiet"] {
    color: #8A97A5;
    font-size: 11px;
}
QLabel[kind="metricValue"] {
    color: #17212B;
    font-size: 23px;
    font-weight: 700;
}
QLabel[kind="metricLabel"] {
    color: #667085;
    font-size: 11px;
    font-weight: 600;
}
QLabel[kind="sidebarBrand"] {
    color: #FFFFFF;
    font-size: 15px;
    font-weight: 700;
}
QLabel[kind="sidebarMuted"] {
    color: #97A5B3;
    font-size: 11px;
}
QLabel[pill="true"] {
    border-radius: 11px;
    padding: 3px 9px;
    font-size: 11px;
    font-weight: 700;
}
QLabel[tone="teal"] {
    color: #0F6976;
    background: #DDF2F4;
    border: 1px solid #B8DCE1;
}
QLabel[tone="success"] {
    color: #15803D;
    background: #EAF8EF;
    border: 1px solid #BCE4C9;
}
QLabel[tone="warning"] {
    color: #9A4B0D;
    background: #FFF4DF;
    border: 1px solid #F0D5A4;
}
QLabel[tone="neutral"] {
    color: #536170;
    background: #EEF2F6;
    border: 1px solid #D8E0E8;
}
QPushButton {
    min-height: 32px;
    padding: 0 13px;
    border: 1px solid #C9D3DD;
    border-radius: 6px;
    background: #FFFFFF;
    color: #344054;
    font-weight: 600;
}
QPushButton:hover {
    background: #F6F8FA;
    border-color: #9EADB9;
}
QPushButton:pressed {
    background: #EEF2F6;
}
QPushButton:focus {
    border: 2px solid #4AA3AE;
}
QPushButton:disabled {
    color: #98A2B3;
    background: #F2F4F7;
    border-color: #E4E7EC;
}
QPushButton[variant="primary"] {
    color: #FFFFFF;
    background: #137C8B;
    border-color: #137C8B;
}
QPushButton[variant="primary"]:hover {
    background: #0F6976;
    border-color: #0F6976;
}
QPushButton[variant="primary"]:disabled {
    color: #98A2B3;
    background: #E9EDF1;
    border-color: #D8E0E8;
}
QPushButton[variant="ghost"] {
    background: transparent;
    border-color: transparent;
    color: #536170;
}
QPushButton[variant="filter"] {
    min-height: 28px;
    padding: 0 9px;
    background: #FFFFFF;
    border-color: #D8E0E8;
    font-size: 11px;
}
QPushButton[variant="filter"]:checked {
    color: #0F6976;
    background: #E5F4F6;
    border-color: #7EBBC3;
}
QPushButton[nav="true"] {
    min-height: 42px;
    padding: 0 15px;
    text-align: left;
    color: #C7D0D9;
    background: transparent;
    border: none;
    border-radius: 7px;
    font-weight: 600;
}
QPushButton[nav="true"]:hover {
    color: #FFFFFF;
    background: #2A333D;
}
QPushButton[nav="true"]:checked {
    color: #FFFFFF;
    background: #174E58;
}
QToolButton {
    min-width: 30px;
    min-height: 30px;
    border: 1px solid #D8E0E8;
    border-radius: 5px;
    background: #FFFFFF;
    color: #536170;
    font-weight: 600;
}
QToolButton:hover {
    background: #F2F6F8;
    border-color: #9BBBC1;
}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    min-height: 31px;
    padding: 0 8px;
    background: #FFFFFF;
    border: 1px solid #C9D3DD;
    border-radius: 5px;
    selection-background-color: #137C8B;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border: 2px solid #4AA3AE;
}
QComboBox::drop-down {
    width: 24px;
    border: none;
}
QComboBox QAbstractItemView {
    background: #FFFFFF;
    border: 1px solid #C9D3DD;
    selection-background-color: #DDF2F4;
    selection-color: #17212B;
    outline: none;
}
QCheckBox {
    min-height: 24px;
    spacing: 7px;
    color: #344054;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
}
QListWidget, QTableWidget {
    background: #FFFFFF;
    alternate-background-color: #F8FAFC;
    border: 1px solid #D8E0E8;
    border-radius: 6px;
    outline: none;
    gridline-color: #E7ECF1;
}
QListWidget::item {
    min-height: 31px;
    padding: 3px 7px;
    border-bottom: 1px solid #EDF1F4;
}
QListWidget::item:selected {
    color: #17212B;
    background: #E5F4F6;
}
QHeaderView::section {
    min-height: 31px;
    padding: 0 8px;
    color: #667085;
    background: #F5F7FA;
    border: none;
    border-bottom: 1px solid #D8E0E8;
    font-size: 11px;
    font-weight: 700;
}
QTableWidget::item {
    padding: 5px 7px;
}
QScrollArea {
    background: transparent;
    border: none;
}
QScrollBar:vertical {
    width: 10px;
    margin: 2px;
    background: transparent;
}
QScrollBar::handle:vertical {
    min-height: 30px;
    background: #C8D1DA;
    border-radius: 4px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QProgressBar {
    min-height: 12px;
    max-height: 12px;
    color: transparent;
    background: #E6EBF0;
    border: none;
    border-radius: 6px;
}
QProgressBar::chunk {
    background: #137C8B;
    border-radius: 6px;
}
QSplitter::handle {
    background: #E4E9EE;
    width: 1px;
}
QToolTip {
    color: #FFFFFF;
    background: #20262E;
    border: 1px solid #3A4550;
    padding: 5px;
}
"""


def apply_theme(app: QtWidgets.QApplication) -> None:
    """Apply deterministic cross-platform styling to the prototype only."""

    app.setStyle("Fusion")
    font = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.GeneralFont)
    font.setPointSize(10)
    app.setFont(font)
    app.setStyleSheet(STYLESHEET)
