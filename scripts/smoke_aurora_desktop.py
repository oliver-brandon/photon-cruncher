"""Optional native desktop smoke test. All recordings and outputs are synthetic."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
from PySide6 import QtCore, QtTest, QtWidgets
from scipy.io import savemat

from photon_cruncher.gui_aurora.shell import AuroraShellWindow


def main(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="aurora-desktop-smoke-") as temporary:
        temp = Path(temporary)
        os.environ["XDG_CONFIG_HOME"] = str(temp / "config")
        os.environ["XDG_DATA_HOME"] = str(temp / "data")
        os.environ["XDG_CACHE_HOME"] = str(temp / "cache")
        QtCore.QSettings.setDefaultFormat(QtCore.QSettings.Format.IniFormat)
        QtCore.QSettings.setPath(
            QtCore.QSettings.Format.IniFormat,
            QtCore.QSettings.Scope.UserScope,
            str(temp / "settings"),
        )
        QtCore.QCoreApplication.setAttribute(
            QtCore.Qt.ApplicationAttribute.AA_ShareOpenGLContexts
        )
        app = QtWidgets.QApplication([])
        app.setOrganizationName("PhotonCruncher")
        app.setApplicationName("Aurora desktop smoke")
        recording = temp / "synthetic.mat"
        fs = 100.0
        t = np.arange(10000) / fs
        savemat(recording, {"data": {
            "streams": {
                "x405A": {"data": 5 + np.sin(t / 9), "fs": fs},
                "x465A": {"data": 8 + np.sin(t / 9) + np.sin(t), "fs": fs},
            },
            "epocs": {"Cue": {"onset": np.array([12, 25, 40, 60, 80])}},
        }})
        QtWidgets.QFileDialog.getOpenFileNames = staticmethod(
            lambda *args, **kwargs: ([str(recording)], "MATLAB (*.mat)")
        )

        window = AuroraShellWindow()
        compact_size = window.minimumSize()
        # Small remote desktops otherwise clamp the initial window to compact width.
        window.setMinimumSize(1480, 940)
        window.resize(1480, 940)
        window.show()

        def wait_until(predicate, label, timeout=30):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                app.processEvents()
                if predicate():
                    return
                time.sleep(0.02)
            raise TimeoutError(f"Timed out waiting for {label}")

        def javascript(expression):
            result = []
            window.view.page().runJavaScript(expression, result.append)
            wait_until(lambda: bool(result), "JavaScript", timeout=5)
            return result[0]

        def inspect():
            data = javascript("""JSON.stringify({
                ready: !!window.auroraBridge && !!window.Aurora?.ready,
                page: window.Aurora?.state.view,
                status: document.querySelector('#alignRunStatus')?.dataset.status,
                checked: document.querySelectorAll('#alignChannelSelectors input:checked').length,
                exportEnabled: !document.querySelector('#alignExportCsv')?.disabled,
                platform: document.documentElement?.dataset.platform,
                railVisible: !!document.querySelector('.rail')?.getClientRects().length,
                shortcut: document.querySelector('.nav-item[data-page=align]')?.getAttribute('aria-keyshortcuts'),
                scroll: document.documentElement?.scrollWidth > innerWidth,
            })""")
            return json.loads(data) if data else {"ready": False}

        def capture(name):
            # Chromium compositing can lag page load, especially on hosted runners.
            QtTest.QTest.qWait(1500)
            image = window.grab().toImage()
            colors = {
                image.pixel(x, y)
                for y in range(image.height() // 8, 7 * image.height() // 8, max(1, image.height() // 32))
                for x in range(0, image.width(), max(1, image.width() // 32))
            }
            if image.isNull() or len(colors) < 16 or not image.save(str(output / name)):
                raise RuntimeError(f"Desktop screenshot is blank or could not be saved: {name}")

        try:
            wait_until(lambda: inspect()["ready"], "desktop bridge")
            if sys.platform == "win32":
                state = inspect()
                if state["platform"] != "windows" or state["shortcut"] != "Control+2":
                    raise AssertionError(f"Incorrect Windows workspace or shortcut: {state}")
            window.activateWindow()
            window.view.setFocus()
            javascript("document.querySelector('#openSessionBtn').focus()")
            capture("intake.png")
            # Simulate a real OS-level keyboard shortcut through Qt WebEngine.
            QtTest.QTest.keyClick(
                window.view.focusProxy() or window.view,
                QtCore.Qt.Key.Key_2,
                QtCore.Qt.KeyboardModifier.ControlModifier,
            )
            wait_until(lambda: inspect()["page"] == "align", "Ctrl+2 navigation")
            javascript("document.querySelector('[data-page=data]').click()")
            javascript("document.querySelector('#openSessionBtn').click()")
            wait_until(lambda: inspect()["status"] == "current", "recording analysis")
            state = inspect()
            if not state["railVisible"] or state["checked"] != 1 or not state["exportEnabled"]:
                raise AssertionError(f"Analysis controls are inconsistent: {state}")
            # A styled select remains a native keyboard-operable HTML control.
            javascript("document.querySelector('#alignHeatScaleMode').focus()")
            target = window.view.focusProxy() or window.view
            QtTest.QTest.keyClick(target, QtCore.Qt.Key.Key_End)
            wait_until(
                lambda: javascript("document.querySelector('#alignHeatScaleMode').value") == "locked",
                "locked heatmap scale",
            )
            QtTest.QTest.keyClick(target, QtCore.Qt.Key.Key_Home)
            wait_until(
                lambda: javascript("document.querySelector('#alignHeatScaleMode').value") == "auto",
                "automatic heatmap scale",
            )
            capture("align.png")
            window.setMinimumSize(compact_size)
            window.resize(compact_size)
            QtTest.QTest.qWait(1000)
            state = inspect()
            if state["railVisible"] or state["scroll"]:
                raise AssertionError(f"Incorrect compact layout: {state}")
            capture("compact.png")
            print(f"Desktop smoke passed: {state}")
        finally:
            window.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python scripts/smoke_aurora_desktop.py OUTPUT_DIR")
    main(Path(sys.argv[1]))
