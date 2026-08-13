from __future__ import annotations

import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets

from photon_cruncher.gui.updater import UpdateController, UpdateDialog
from photon_cruncher.updates import (
    UpdateRelease,
    UpdateService,
    UpdateSnapshot,
    UpdateState,
)


class GuiUpdaterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_dialog_shows_stable_release_details(self) -> None:
        snapshot = UpdateSnapshot(
            UpdateState.AVAILABLE,
            "1.2.0",
            "stable-win-x64",
            release=UpdateRelease("1.2.1", "- Fixed an update issue."),
            message="Photon Cruncher v1.2.1 is available.",
        )

        dialog = UpdateDialog(snapshot)

        self.assertEqual(
            dialog.heading.text(),
            "Photon Cruncher v1.2.1 is available",
        )
        self.assertIn("Installed: v1.2.0", dialog.version_detail.text())
        self.assertEqual(dialog.install_button.text(), "Install and restart")
        dialog.close()

    def test_controller_adds_manual_action_and_update_indicator(self) -> None:
        backend = mock.Mock(
            channel="stable-win-x64",
            package_id="com.photoncruncher.app",
        )
        with mock.patch(
            "photon_cruncher.updates.update_channel",
            return_value="stable-win-x64",
        ):
            service = UpdateService(lambda: backend, channel="stable-win-x64")
        window = QtWidgets.QMainWindow()

        with mock.patch(
            "photon_cruncher.gui.updater.velopack_runtime_available",
            return_value=False,
        ):
            controller = UpdateController(window, service=service)

        self.assertEqual(controller.check_updates_action.text(), "Check for Updates…")
        self.assertFalse(controller._update_timer.isActive())

        snapshot = UpdateSnapshot(
            UpdateState.AVAILABLE,
            "1.2.0",
            "stable-win-x64",
            release=UpdateRelease("1.2.1"),
        )
        controller._sync_update_indicator(snapshot)
        self.assertEqual(controller._update_indicator.text(), "Update 1.2.1")
        self.assertFalse(controller._update_indicator.isHidden())
        window.close()


if __name__ == "__main__":
    unittest.main()
