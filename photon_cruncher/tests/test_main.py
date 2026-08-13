from __future__ import annotations

import sys
import types
import unittest
from unittest import mock

from photon_cruncher import main as app_main


class MainEntryTests(unittest.TestCase):
    def test_velopack_startup_runs_before_qt_application(self) -> None:
        events: list[str] = []
        application = mock.Mock()
        application.exec.return_value = 0
        application_type = mock.Mock(
            side_effect=lambda _argv: (events.append("qt"), application)[1]
        )
        window = mock.Mock()
        main_window_type = mock.Mock(return_value=window)
        pyside_module = types.ModuleType("PySide6")
        pyside_module.QtWidgets = types.SimpleNamespace(
            QApplication=application_type
        )
        main_window_module = types.ModuleType("photon_cruncher.gui.main_window")
        main_window_module.MainWindow = main_window_type

        with (
            mock.patch.dict(
                sys.modules,
                {
                    "PySide6": pyside_module,
                    "photon_cruncher.gui.main_window": main_window_module,
                },
            ),
            mock.patch.object(
                app_main,
                "run_velopack_startup",
                side_effect=lambda: events.append("startup"),
            ) as startup,
            mock.patch.object(app_main, "_set_app_icon") as set_icon,
        ):
            result = app_main.main()

        self.assertEqual(result, 0)
        self.assertEqual(events, ["startup", "qt"])
        startup.assert_called_once_with()
        set_icon.assert_called_once_with(application)
        main_window_type.assert_called_once_with()
        window.show.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
