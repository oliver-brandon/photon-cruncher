"""Stable entry point and settings compatibility for the Aurora upgrade."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PySide6 import QtCore

from photon_cruncher import aurora_main, main
from photon_cruncher.gui_aurora import shell


class MainEntryTests(unittest.TestCase):
    def test_stable_launcher_starts_velopack_before_shell(self):
        events = []
        with (
            mock.patch.object(aurora_main, "development_mode_enabled", return_value=False),
            mock.patch.object(aurora_main, "run_velopack_startup", side_effect=lambda: events.append("startup")),
            mock.patch.object(shell, "run_shell", side_effect=lambda: events.append("shell") or 0),
        ):
            self.assertEqual(main.main([]), 0)
        self.assertEqual(events, ["startup", "shell"])

    def test_installed_settings_domain_and_legacy_values(self):
        app = mock.Mock()
        app.exec.return_value = 0
        with (
            mock.patch.object(shell.QtWidgets.QApplication, "instance", return_value=app),
            mock.patch.object(shell, "AuroraShellWindow"),
            mock.patch.object(shell.QtCore.QCoreApplication, "setAttribute"),
            mock.patch("photon_cruncher.product.set_app_icon"),
        ):
            self.assertEqual(shell.run_shell(), 0)
        app.setOrganizationName.assert_called_once_with("PhotonCruncher")
        app.setApplicationName.assert_called_once_with("PhotonCruncher")
        app.setApplicationDisplayName.assert_called_once_with("Photon Cruncher Aurora")

        with tempfile.TemporaryDirectory() as tmp:
            settings = QtCore.QSettings(str(Path(tmp) / "v1.ini"), QtCore.QSettings.Format.IniFormat)
            settings.setValue("processing/trange_end", 4.0)
            settings.setValue("processing/channel_smooth/A_465", 17)
            settings.setValue("output_dir", tmp)
            with mock.patch.object(shell.QtCore, "QSettings", return_value=settings):
                config = json.loads(shell.AuroraBridge.savedProcessingSettings(None))
                self.assertEqual(shell.AuroraBridge.savedExportDir(None), tmp)
            self.assertEqual(config["trange_end"], 4.0)
            self.assertEqual(config["channel_smoothing"]["A_465"], 17)
