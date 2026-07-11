from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from photon_cruncher import app_title
from photon_cruncher.gui_prototype.components import button, label, pill, svg_icon
from photon_cruncher.gui_prototype.demo_data import DemoSession
from photon_cruncher.gui_prototype.pages.align_page import AlignPage
from photon_cruncher.gui_prototype.pages.batch_page import BatchPage
from photon_cruncher.gui_prototype.pages.data_page import DataPage
from photon_cruncher.gui_prototype.pages.trials_page import TrialsPage


class PrototypeWindow(QtWidgets.QMainWindow):
    PAGE_NAMES = ("data", "align", "trials", "batch")

    def __init__(
        self,
        session: DemoSession,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.session = session
        self.setWindowTitle(f"{app_title()} — GUI v2 Prototype")
        self.resize(1440, 900)
        self.setMinimumSize(1180, 760)
        self.setAccessibleName("Photon Cruncher GUI v2 visual prototype")
        icon_path = (
            Path(__file__).resolve().parents[1]
            / "assets"
            / "icons"
            / "png"
            / "photon-cruncher-128.png"
        )
        if icon_path.exists():
            self.setWindowIcon(QtGui.QIcon(str(icon_path)))

        root = QtWidgets.QWidget()
        root.setObjectName("PrototypeRoot")
        root_layout = QtWidgets.QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.setCentralWidget(root)

        root_layout.addWidget(self._build_header())
        body = QtWidgets.QWidget()
        body_layout = QtWidgets.QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        root_layout.addWidget(body, 1)

        body_layout.addWidget(self._build_sidebar())
        self.page_stack = QtWidgets.QStackedWidget()
        self.page_stack.setObjectName("PageStack")
        body_layout.addWidget(self.page_stack, 1)

        self.data_page = DataPage(session)
        self.align_page = AlignPage(session)
        self.trials_page = TrialsPage(session)
        self.batch_page = BatchPage(session)
        self.pages = {
            "data": self.data_page,
            "align": self.align_page,
            "trials": self.trials_page,
            "batch": self.batch_page,
        }
        for page_name in self.PAGE_NAMES:
            page = self.pages[page_name]
            page.toast_requested.connect(self.show_toast)
            self.page_stack.addWidget(page)
        self.data_page.demo_state_changed.connect(self._demo_state_changed)

        self._toast_timer = QtCore.QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.setInterval(4200)
        self._toast_timer.timeout.connect(self._restore_default_status)
        self._install_shortcuts()
        self.show_page("data")
        self._restore_default_status()

    def _build_header(self) -> QtWidgets.QWidget:
        header = QtWidgets.QFrame()
        header.setObjectName("AppHeader")
        header.setFixedHeight(68)
        layout = QtWidgets.QHBoxLayout(header)
        layout.setContentsMargins(18, 10, 20, 10)
        layout.setSpacing(12)

        icon_path = (
            Path(__file__).resolve().parents[1]
            / "assets"
            / "icons"
            / "png"
            / "photon-cruncher-48.png"
        )
        logo = QtWidgets.QLabel()
        logo.setFixedSize(40, 40)
        if icon_path.exists():
            pixmap = QtGui.QPixmap(str(icon_path))
            logo.setPixmap(
                pixmap.scaled(
                    40,
                    40,
                    QtCore.Qt.KeepAspectRatio,
                    QtCore.Qt.SmoothTransformation,
                )
            )
        layout.addWidget(logo)

        brand = QtWidgets.QVBoxLayout()
        brand.setSpacing(0)
        brand.addWidget(label("Photon Cruncher", "appTitle"))
        brand.addWidget(label("Fiber photometry workspace", "quiet"))
        layout.addLayout(brand)
        layout.addWidget(pill("V2 PROTOTYPE", "teal"))
        layout.addSpacing(18)

        divider = QtWidgets.QFrame()
        divider.setFrameShape(QtWidgets.QFrame.VLine)
        divider.setStyleSheet("color: #D8E0E8;")
        layout.addWidget(divider)
        session_layout = QtWidgets.QVBoxLayout()
        session_layout.setSpacing(1)
        self.header_session = label(self.session.name, "cardTitle")
        self.header_session_detail = label("Synthetic TDT block · ready", "quiet")
        session_layout.addWidget(self.header_session)
        session_layout.addWidget(self.header_session_detail)
        layout.addLayout(session_layout)
        layout.addStretch()

        self.toast_label = QtWidgets.QLabel()
        self.toast_label.setProperty("pill", True)
        self.toast_label.setProperty("tone", "neutral")
        self.toast_label.setAlignment(QtCore.Qt.AlignCenter)
        self.toast_label.setMinimumWidth(275)
        layout.addWidget(self.toast_label)
        self.demo_status = pill("DEMO DATA", "success")
        layout.addWidget(self.demo_status)
        return header

    def _build_sidebar(self) -> QtWidgets.QWidget:
        sidebar = QtWidgets.QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(218)
        layout = QtWidgets.QVBoxLayout(sidebar)
        layout.setContentsMargins(12, 18, 12, 16)
        layout.setSpacing(6)

        workspace = label("WORKSPACE", "sectionEyebrow")
        workspace.setStyleSheet("color: #7F8C99; padding: 0 10px 5px 10px;")
        layout.addWidget(workspace)
        self.nav_group = QtWidgets.QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons: dict[str, QtWidgets.QPushButton] = {}
        for index, (name, title) in enumerate(
            (
                ("data", "Data"),
                ("align", "Align + visualize"),
                ("trials", "Trial explorer"),
                ("batch", "Batch export"),
            )
        ):
            nav = QtWidgets.QPushButton(title)
            nav.setCheckable(True)
            nav.setProperty("nav", True)
            nav.setIcon(svg_icon(name))
            nav.setIconSize(QtCore.QSize(19, 19))
            nav.setAccessibleName(f"Open {name} page: {title}")
            nav.setToolTip(f"Ctrl+{index + 1} · Open {title}")
            nav.clicked.connect(lambda _, page_name=name: self.show_page(page_name))
            self.nav_group.addButton(nav)
            self.nav_buttons[name] = nav
            layout.addWidget(nav)

        layout.addSpacing(18)
        review = label("DESIGN REVIEW", "sectionEyebrow")
        review.setStyleSheet("color: #7F8C99; padding: 0 10px 5px 10px;")
        layout.addWidget(review)
        notes = label(
            "Scientific light theme\nExpert-dense controls\nPyQtGraph interaction study",
            "sidebarMuted",
        )
        notes.setStyleSheet("padding: 0 10px; line-height: 1.5;")
        layout.addWidget(notes)
        layout.addStretch()

        safety = QtWidgets.QFrame()
        safety.setStyleSheet(
            "background: #28313A; border: 1px solid #35414C; border-radius: 8px;"
        )
        safety_layout = QtWidgets.QVBoxLayout(safety)
        safety_layout.setContentsMargins(11, 10, 11, 10)
        safety_layout.setSpacing(3)
        safety_layout.addWidget(label("SYNTHETIC ONLY", "sidebarBrand"))
        safety_layout.addWidget(
            label("No lab files are opened or written.", "sidebarMuted")
        )
        layout.addWidget(safety)
        version = label(app_title(), "sidebarMuted")
        version.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(version)
        return sidebar

    def _install_shortcuts(self) -> None:
        for index, page_name in enumerate(self.PAGE_NAMES, start=1):
            shortcut = QtGui.QShortcut(QtGui.QKeySequence(f"Ctrl+{index}"), self)
            shortcut.activated.connect(
                lambda selected=page_name: self.show_page(selected)
            )

    def show_page(self, page_name: str) -> None:
        normalized = page_name if page_name in self.pages else "data"
        self.page_stack.setCurrentWidget(self.pages[normalized])
        self.nav_buttons[normalized].setChecked(True)

    def current_page_name(self) -> str:
        current = self.page_stack.currentWidget()
        for name, page in self.pages.items():
            if current is page:
                return name
        return "data"

    def set_demo_state(self, state: str) -> None:
        self.data_page.set_state(state)

    def _demo_state_changed(self, state: str) -> None:
        if state == "empty":
            self.header_session.setText("No session loaded")
            self.header_session_detail.setText("Choose a safe synthetic import action")
            self.demo_status.setText("EMPTY STATE")
            self.demo_status.setProperty("tone", "neutral")
        else:
            self.header_session.setText(self.session.name)
            self.header_session_detail.setText("Synthetic TDT block · ready")
            self.demo_status.setText("DEMO DATA")
            self.demo_status.setProperty("tone", "success")
        self.demo_status.style().unpolish(self.demo_status)
        self.demo_status.style().polish(self.demo_status)

    def show_toast(self, message: str) -> None:
        self.toast_label.setText(message)
        self.toast_label.setToolTip(message)
        self._toast_timer.start()

    def _restore_default_status(self) -> None:
        self.toast_label.setText("Visual study · analysis pipeline isolated")
        self.toast_label.setToolTip(
            "This prototype does not load, analyze, export, or persist user data."
        )

    def capture_all(self, output_dir: Path) -> list[Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        self.resize(1440, 900)
        self.show()
        app = QtWidgets.QApplication.instance()
        if app is None:
            raise RuntimeError("A QApplication is required for screenshot capture.")

        captures: list[tuple[str, str, str]] = [
            ("data-empty", "data", "empty"),
            ("data-demo", "data", "demo"),
            ("align-demo", "align", "demo"),
            ("trials-demo", "trials", "demo"),
            ("batch-demo", "batch", "demo"),
        ]
        paths: list[Path] = []
        for filename, page_name, state in captures:
            self.set_demo_state(state)
            self.show_page(page_name)
            if page_name == "batch":
                self.batch_page.prepare_capture()
            self._restore_default_status()
            app.processEvents(QtCore.QEventLoop.AllEvents, 120)
            app.processEvents(QtCore.QEventLoop.AllEvents, 120)
            destination = output_dir / f"{filename}.png"
            pixmap = QtGui.QPixmap(self.size())
            pixmap.fill(QtGui.QColor("#F4F7F9"))
            self.render(pixmap)
            if not pixmap.save(str(destination), "PNG"):
                raise RuntimeError(f"Could not save prototype screenshot: {destination}")
            paths.append(destination)

        self.set_demo_state("demo")
        self.show_page("data")
        return paths
