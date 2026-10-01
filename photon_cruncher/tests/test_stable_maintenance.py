from __future__ import annotations

import gc
import json
import tempfile
import unittest
import weakref
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np
from scipy.io import savemat

from photon_cruncher import __version__
from photon_cruncher.analysis import runner
from photon_cruncher.io.loader import load_session
from photon_cruncher.model import Epoc, PhotometrySession, Stream
from photon_cruncher.processing.pipeline import (
    ProcessingSettings,
    _moving_mean,
    process_channel,
)


def synthetic_session(path=Path("synthetic.mat")):
    rng = np.random.default_rng(42)
    fs = 100.0
    time = np.arange(5000) / fs
    control = 2 + 0.1 * np.sin(2 * np.pi * 0.5 * time) + rng.normal(0, 0.05, 5000)
    signal = (
        3 + 0.4 * control + 0.2 * np.sin(2 * np.pi * 1.3 * time)
        + rng.normal(0, 0.08, 5000)
    )
    return PhotometrySession(
        streams={
            "x405A": Stream("x405A", fs, control),
            "x465A": Stream("x465A", fs, signal),
        },
        epocs={"Cue": Epoc("Cue", np.array([10., 20., 30., 40., 45.5]))},
        info={}, source_path=Path(path),
    )


def settings():
    return ProcessingSettings(
        trange=(-2., 5.), baseline_per=(-2., -0.5), base_adjust=-1.5,
        downsample_factor=5, smooth_factor=7,
    )


class StablePipelineTests(unittest.TestCase):
    def test_corrected_pipeline_matches_frozen_reference(self):
        session = synthetic_session()
        result = process_channel(session, "x405A", "x465A", session.epocs["Cue"], settings())
        with np.load(Path(__file__).parent / "fixtures" / "golden_process_channel.npz") as golden:
            for key in ("ts", "zall", "zall_smooth", "mean_z", "sem_z", "mean_z_smooth", "sem_z_smooth"):
                np.testing.assert_allclose(getattr(result, key), golden[key], rtol=1e-12, atol=1e-12)
        self.assertEqual(result.trial_numbers, [1, 2, 3, 4])
        self.assertEqual(result.dropped_edge_trials, [5])

    def test_added_linear_control_contamination_does_not_change_recovered_signal(self):
        session = synthetic_session()
        original = process_channel(session, "x405A", "x465A", session.epocs["Cue"], settings())
        session.streams["x465A"].data += 7 + 3 * session.streams["x405A"].data
        contaminated = process_channel(session, "x405A", "x465A", session.epocs["Cue"], settings())
        np.testing.assert_allclose(original.zall, contaminated.zall, rtol=1e-10, atol=1e-10)
        np.testing.assert_allclose(original.zall_smooth, contaminated.zall_smooth, rtol=1e-10, atol=1e-10)

    def test_oversized_smoothing_matches_shrinking_window_reference(self):
        trace = np.array([2., 7., -1., 3., 6.])
        for window in (1, 2, 3, 5, 6, 7, 10, 100):
            with self.subTest(window=window):
                expected = [
                    trace[max(0, i - window // 2):min(len(trace), i + (window - 1) // 2 + 1)].mean()
                    for i in range(len(trace))
                ]
                np.testing.assert_allclose(_moving_mean(trace, window), expected)
        session = synthetic_session()
        result = process_channel(
            session, "x405A", "x465A", session.epocs["Cue"],
            replace(settings(), smooth_factor=1000),
        )
        self.assertEqual(result.zall.shape, result.zall_smooth.shape)

    def test_baseline_needs_two_samples_inside_extracted_window(self):
        session = synthetic_session()
        for baseline in ((-4., -3.), (-2., -1.94)):
            with self.subTest(baseline=baseline), self.assertRaisesRegex(ValueError, "at least two"):
                process_channel(
                    session, "x405A", "x465A", session.epocs["Cue"],
                    replace(settings(), baseline_per=baseline),
                )

    def test_artifact_in_both_channels_counts_as_one_removed_trial(self):
        session = synthetic_session()
        session.streams["x405A"].data[1950:2050] = 100
        session.streams["x465A"].data[1950:2050] = 100
        result = process_channel(
            session, "x405A", "x465A", session.epocs["Cue"],
            replace(settings(), artifact_405=50, artifact_465=50),
        )
        self.assertEqual(result.num_artifacts, 1)
        self.assertEqual(result.trial_numbers, [1, 3, 4])


class StableLoaderTests(unittest.TestCase):
    def test_mat_ignores_camera_and_clock_epocs(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "synthetic.mat"
            savemat(path, {"data": {"streams": {}, "epocs": {
                name: {"onset": np.array([1., 2.])}
                for name in ("Cam1", "cAM2", "Tick", "Cue")
            }}})
            self.assertEqual(list(load_session(path).epocs), ["Cue"])

    def test_tdt_ignores_camera_and_clock_before_converting_values(self):
        fake_tdt = SimpleNamespace(read_block=lambda _: SimpleNamespace(
            streams={}, epocs={
                "Cam1": SimpleNamespace(onset=object()),
                "CAM2": SimpleNamespace(onset=object()),
                "tick": SimpleNamespace(onset=object()),
                "Cue": SimpleNamespace(onset=np.array([1., 2.])),
            }, info={},
        ))
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict("sys.modules", {"tdt": fake_tdt}):
            path = Path(tmp)
            (path / "test.tsq").touch()
            self.assertEqual(list(load_session(path).epocs), ["Cue"])


class StableBatchTests(unittest.TestCase):
    def test_duplicate_names_are_isolated_in_csv_and_figure_destinations(self):
        for subfolders in (False, True):
            with self.subTest(subfolders=subfolders), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                paths = [root / "a" / "Block-1.mat", root / "b" / "Block-1.mat"]
                figures = []

                def save_figure(directory, result):
                    figures.append((directory, result.session.source_path))
                    return directory / "figure.png"

                with mock.patch.object(runner, "load_session", new=synthetic_session):
                    records = runner.run_batch_custom(
                        paths, [("Cue", ("Cue",))], root / "out", ["A_465"],
                        lambda _: settings(), per_session_subdir=subfolders,
                        figure_exporter=save_figure,
                    )
                self.assertEqual(len({record.csv_path for record in records}), 2)
                self.assertEqual(len({directory for directory, _ in figures}), 2)
                for record, source in zip(records, paths):
                    manifest = next(record.output_dir.glob("*_analysis.json"))
                    payload = json.loads(manifest.read_text())
                    self.assertEqual(payload["source"]["path"], str(source.resolve()))
                    self.assertEqual(payload["application"]["version"], __version__)
                    self.assertEqual(payload["analysis"]["pipeline"], "control_to_signal_linear_v1")

    def test_existing_manifest_prevents_replacement_by_another_source(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(runner, "load_session", new=synthetic_session):
            root = Path(tmp)
            first = runner.run_batch_custom(
                [root / "a" / "same.mat"], [("Cue", ("Cue",))], root / "out",
                ["A_465"], lambda _: settings(),
            )[0]
            original = first.csv_path.read_bytes()
            outcomes = []
            second = runner.run_batch_custom(
                [root / "b" / "same.mat"], [("Cue", ("Cue",))], root / "out",
                ["A_465"], lambda _: settings(), outcomes=outcomes,
            )[0]
            self.assertIsNone(second.csv_path)
            self.assertIn("another recording", outcomes[0].reason)
            self.assertEqual(first.csv_path.read_bytes(), original)

    def test_batch_releases_data_and_loads_each_source_once(self):
        sessions, matrices, loaded, figures = [], [], [], []

        def load(path):
            loaded.append(path)
            session = synthetic_session(path)
            sessions.append(weakref.ref(session))
            return session

        def save_figure(directory, result):
            matrices.append(weakref.ref(result.processed.zall))
            figures.append(result.session.source_path)
            return directory / "figure.png"

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(runner, "load_session", new=load):
            paths = [Path(tmp) / f"session-{i}.mat" for i in range(6)]
            records = runner.run_batch_custom(
                paths, [("Cue", ("Cue",))], Path(tmp) / "out", ["A_465"],
                lambda _: settings(), export_csv=False, figure_exporter=save_figure,
            )
            gc.collect()
            self.assertEqual(loaded, paths)
            self.assertEqual(figures, paths)
            self.assertEqual(len(records), 6)
            self.assertTrue(all(ref() is None for ref in sessions + matrices))

    def test_invalid_baseline_is_reported_without_writing_output(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(runner, "load_session", new=synthetic_session):
            outcomes = []
            records = runner.run_batch_custom(
                [Path("test.mat")], [("Cue", ("Cue",))], Path(tmp), ["A_465"],
                lambda _: replace(settings(), baseline_per=(-4., -3.)), outcomes=outcomes,
            )
            self.assertEqual(records, [])
            self.assertEqual(outcomes[0].status, "error")
            self.assertIn("at least two", outcomes[0].reason)
            self.assertEqual(list(Path(tmp).iterdir()), [])


class StableGuiExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6 import QtWidgets
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_batch_gui_saves_figures_during_the_single_processing_pass(self):
        from PySide6 import QtCore
        from photon_cruncher.gui.main_window import MainWindow

        for csv_enabled in (False, True):
            with self.subTest(csv_enabled=csv_enabled), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                settings_file = QtCore.QSettings(str(root / "settings.ini"), QtCore.QSettings.IniFormat)
                with mock.patch("photon_cruncher.gui.main_window.QtCore.QSettings", return_value=settings_file):
                    window = MainWindow()
                try:
                    window.session = synthetic_session()
                    window.batch_file_list.addItem("test source")
                    window.output_dir_input.setText(str(root / "out"))
                    window.batch_export_csv.setChecked(csv_enabled)
                    window.batch_export_figures.setChecked(True)
                    paths = [root / "a.mat", root / "b.mat"]
                    loaded = []

                    def load(path):
                        loaded.append(path)
                        return synthetic_session(path)

                    with (
                        mock.patch.object(window, "_batch_paths", return_value=paths),
                        mock.patch.object(window, "_selected_batch_epocs", return_value=[("Cue", ("Cue",))]),
                        mock.patch.object(window, "_selected_channels", return_value=["A_465"]),
                        mock.patch.object(window.thread_pool, "start", side_effect=lambda worker: worker.run()),
                        mock.patch.object(runner, "load_session", new=load),
                    ):
                        window._run_batch()
                    self.assertEqual(loaded, paths)
                    self.assertEqual(len(list((root / "out").rglob("*.png"))), 2)
                    self.assertEqual(len(list((root / "out").rglob("*.csv"))), 2 if csv_enabled else 0)
                    self.assertEqual(len(list((root / "out").rglob("*_analysis.json"))), 2)
                    self.assertIn("Exported 2 analysis result(s)", window.batch_progress.text())
                    self.assertIn("Errors: 0", window.batch_progress.text())
                finally:
                    window.close()


if __name__ == "__main__":
    unittest.main()
