from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

import numpy as np

from photon_cruncher.gui_prototype.demo_data import create_demo_session
from photon_cruncher.gui_prototype.theme import COLORS


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_SCALE_FACTOR", "1")

HAS_PYQTGRAPH = importlib.util.find_spec("pyqtgraph") is not None

if HAS_PYQTGRAPH:
    from PySide6 import QtGui, QtWidgets

    from photon_cruncher.gui_prototype.shell import PrototypeWindow
    from photon_cruncher.gui_prototype.theme import apply_theme


class DemoDataTests(unittest.TestCase):
    def test_demo_data_is_deterministic_and_complete(self) -> None:
        first = create_demo_session()
        second = create_demo_session()

        self.assertEqual(first.name, "Demo_Mouse_042_Acq")
        self.assertEqual(len(first.trials), 48)
        self.assertEqual(first.dropped_trials, (1, 50))
        self.assertEqual(len(first.channels), 3)
        for first_channel, second_channel in zip(first.channels, second.channels):
            np.testing.assert_array_equal(first_channel.trials, second_channel.trials)
            self.assertEqual(first_channel.trials.shape, (48, 721))

    def test_primary_theme_colors_meet_contrast_targets(self) -> None:
        self.assertGreaterEqual(_contrast(COLORS["text"], COLORS["surface"]), 7.0)
        self.assertGreaterEqual(_contrast(COLORS["muted"], COLORS["surface"]), 4.5)
        self.assertGreaterEqual(_contrast("#FFFFFF", COLORS["primary"]), 4.5)


@unittest.skipUnless(HAS_PYQTGRAPH, "prototype extra is not installed")
class PrototypeGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        apply_theme(cls.app)

    def setUp(self) -> None:
        self.window = PrototypeWindow(create_demo_session())
        self.window.show()
        self.app.processEvents()

    def tearDown(self) -> None:
        self.window.close()
        self.app.processEvents()

    def test_navigation_and_demo_states_are_isolated(self) -> None:
        self.assertEqual(self.window.minimumWidth(), 1180)
        self.assertEqual(self.window.minimumHeight(), 760)
        for page_name in self.window.PAGE_NAMES:
            self.window.show_page(page_name)
            self.assertEqual(self.window.current_page_name(), page_name)
            self.assertTrue(self.window.nav_buttons[page_name].isChecked())

        self.window.set_demo_state("empty")
        self.assertEqual(self.window.data_page.state(), "empty")
        self.assertEqual(self.window.header_session.text(), "No session loaded")
        self.window.set_demo_state("demo")
        self.assertEqual(self.window.data_page.state(), "demo")
        self.assertEqual(self.window.header_session.text(), "Demo_Mouse_042_Acq")

    def test_trial_selection_updates_plot_and_integer_heat_ticks(self) -> None:
        page = self.window.trials_page
        self.assertEqual(len(page.selected_indices()), 48)
        self.assertEqual(page.plot.selected_trial_count(), 48)
        self.assertTrue(all(value.isdigit() for value in page.plot.heat_tick_labels))

        page._select_none()
        self.assertEqual(page.selected_indices(), [])
        self.assertEqual(page.plot.selected_trial_count(), 0)
        page._select_all_visible()
        self.assertEqual(len(page.selected_indices()), 48)

        page.search_input.setText("artifact")
        self.app.processEvents()
        self.assertEqual(len(page._visible_items()), 3)

    def test_minimum_viewport_and_mock_interactions_remain_usable(self) -> None:
        self.window.resize(1180, 760)
        self.window.show_page("align")
        self.app.processEvents()
        align_plot = self.window.align_page.plot
        self.assertGreaterEqual(align_plot.graphics.height(), 310)
        self.assertFalse(align_plot.coordinate_label.wordWrap())

        self.window.align_page.baseline_start.setValue(-2.5)
        self.window.align_page.baseline_end.setValue(-1.25)
        start, end = align_plot.baseline_region.getRegion()
        self.assertAlmostEqual(start, -2.5)
        self.assertAlmostEqual(end, -1.25)

        batch_page = self.window.batch_page
        batch_page.start_demo_batch()
        self.assertTrue(batch_page._timer.isActive())
        self.assertTrue(batch_page.cancel_button.isEnabled())
        batch_page.cancel_demo_batch()
        self.assertFalse(batch_page._timer.isActive())
        self.assertEqual(batch_page.progress_status.text(), "CANCELLED")

    def test_accessible_names_and_synthetic_paths(self) -> None:
        for page_name, nav_button in self.window.nav_buttons.items():
            self.assertIn(page_name.split("_")[0].lower(), nav_button.accessibleName().lower())
        self.assertTrue(self.window.align_page.plot.accessibleName())
        self.assertTrue(self.window.trials_page.trial_list.accessibleName())

        text_widgets = self.window.findChildren(QtWidgets.QLabel)
        text_widgets.extend(self.window.findChildren(QtWidgets.QLineEdit))
        visible_text = "\n".join(widget.text() for widget in text_widgets)
        self.assertNotIn("/Users/", visible_text)
        self.assertNotIn("local-test-data", visible_text)

    def test_capture_all_produces_five_review_images(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            paths = self.window.capture_all(Path(temporary_dir))
            self.assertEqual(
                [path.name for path in paths],
                [
                    "data-empty.png",
                    "data-demo.png",
                    "align-demo.png",
                    "trials-demo.png",
                    "batch-demo.png",
                ],
            )
            for path in paths:
                image = QtGui.QImage(str(path))
                self.assertFalse(image.isNull())
                self.assertGreaterEqual(image.width(), 1440)
                self.assertGreaterEqual(image.height(), 900)


def _contrast(first: str, second: str) -> float:
    def luminance(value: str) -> float:
        channels = [int(value[index : index + 2], 16) / 255 for index in (1, 3, 5)]
        adjusted = [
            channel / 12.92
            if channel <= 0.04045
            else ((channel + 0.055) / 1.055) ** 2.4
            for channel in channels
        ]
        return 0.2126 * adjusted[0] + 0.7152 * adjusted[1] + 0.0722 * adjusted[2]

    lighter, darker = sorted((luminance(first), luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


if __name__ == "__main__":
    unittest.main()
