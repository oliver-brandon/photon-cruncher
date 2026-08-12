from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from urllib.request import urlopen

from PySide6 import QtCore, QtWidgets

from photon_cruncher.gui_aurora.server import find_free_port, serve_in_background, static_files
from photon_cruncher.gui_aurora import STATIC_DIR
from photon_cruncher.product import AURORA_UI_VERSION, aurora_app_title, aurora_brand_label


class AuroraShellSpikeTests(unittest.TestCase):
    def test_shell_module_imports(self) -> None:
        from photon_cruncher.gui_aurora import shell

        self.assertTrue(callable(shell.run_shell))
        self.assertTrue(callable(shell.AuroraShellWindow))
        for method in (
            "selectMatFiles",
            "selectDataFolder",
            "selectTdtTank",
            "savedProcessingSettings",
            "saveProcessingSettings",
        ):
            self.assertTrue(hasattr(shell.AuroraBridge, method))

    def test_free_port_and_background_server_tuple(self) -> None:
        port = find_free_port("127.0.0.1")
        self.assertIsInstance(port, int)
        self.assertGreater(port, 0)
        httpd, _thread, bound = serve_in_background(host="127.0.0.1", port=None)
        try:
            self.assertGreater(bound, 0)
            with urlopen(f"http://127.0.0.1:{bound}/api/health", timeout=2) as resp:
                health = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(health["ok"])
            self.assertEqual(health["backend"], "photon_cruncher.service")
            self.assertIn("Aurora", health["title"])
            self.assertEqual(health["title"], aurora_app_title())
            self.assertEqual(health.get("brand"), aurora_brand_label())
            self.assertEqual(health.get("ui_version"), AURORA_UI_VERSION)
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_static_bundle_still_present(self) -> None:
        names = {path.name for path in static_files()}
        self.assertIn("index.html", names)
        self.assertTrue((STATIC_DIR / "js" / "app.js").is_file())
        app_js = (STATIC_DIR / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIn("onShellMessage", app_js)
        self.assertNotIn("AuroraDemo", app_js)
        self.assertNotIn("demo.js", {path.name for path in static_files()})

    def test_title(self) -> None:
        self.assertIn("Aurora", aurora_app_title())

    def test_native_update_controls_are_wired(self) -> None:
        shell_text = (
            Path(__file__).resolve().parents[1] / "gui_aurora" / "shell.py"
        ).read_text(encoding="utf-8")
        self.assertIn('addAction("Check for Updates…")', shell_text)
        self.assertIn('setObjectName("updateIndicator")', shell_text)
        self.assertIn('"Install and restart"', shell_text)
        self.assertIn("create_update_service()", shell_text)
        self.assertIn("restore_window_geometry(self)", shell_text)
        self.assertIn("save_window_geometry(self)", shell_text)

    def test_window_geometry_round_trip(self) -> None:
        from photon_cruncher.gui_aurora.shell import (
            restore_window_geometry,
            save_window_geometry,
        )

        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        self.assertIsNotNone(app)
        with tempfile.TemporaryDirectory() as tmp:
            settings = QtCore.QSettings(
                str(Path(tmp) / "window.ini"),
                QtCore.QSettings.Format.IniFormat,
            )
            original = QtWidgets.QMainWindow()
            original.setGeometry(90, 110, 600, 500)
            save_window_geometry(original, settings)

            restored = QtWidgets.QMainWindow()
            self.assertTrue(restore_window_geometry(restored, settings))
            self.assertEqual(restored.geometry(), original.geometry())


if __name__ == "__main__":
    unittest.main()
