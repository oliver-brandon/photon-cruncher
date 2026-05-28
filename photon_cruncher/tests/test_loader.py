from __future__ import annotations

import csv
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

import numpy as np

from photon_cruncher.io.loader import (
    discover_tdt_block_paths,
    is_tdt_block_path,
    load_session,
)
from photon_cruncher.analysis.trial_classifier import (
    CORRECT_NOT_REWARDED,
    CORRECT_REWARDED,
    INCORRECT_NOT_REWARDED,
    INCORRECT_REWARDED,
    classified_trial_sources,
)
from photon_cruncher.export.exporter import export_channel
from photon_cruncher.model import Epoc, PhotometrySession, Stream
from photon_cruncher.processing.pipeline import (
    ProcessedSignal,
    ProcessingSettings,
    _extract_trials,
    default_settings_for_channel,
    process_channel,
    subset_processed_signal,
)


class Struct:
    def __init__(self, **kwargs: object) -> None:
        self.__dict__.update(kwargs)


class LoaderTests(unittest.TestCase):
    def _load_local_mat_fixture(self, filename: str):
        path = Path("local-test-data") / "mat" / filename
        if not path.exists():
            self.skipTest(f"Local fixture not available: {path}")
        return load_session(path)

    def test_default_trange_end_is_seconds_after_epoc(self) -> None:
        settings = default_settings_for_channel("A_465")

        self.assertEqual(settings.trange, (-2.0, 5.0))

    def test_tdt_block_detection_requires_known_block_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            self.assertFalse(is_tdt_block_path(folder))

            (folder / "Subject-250101-120000.tsq").write_bytes(b"")
            self.assertTrue(is_tdt_block_path(folder))

    def test_discover_tdt_block_paths_finds_blocks_in_tank(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tank = Path(tmp)
            block_a = tank / "BlockA"
            block_b = tank / "Nested" / "BlockB"
            non_block = tank / "Notes"
            block_a.mkdir()
            block_b.mkdir(parents=True)
            non_block.mkdir()
            (block_a / "BlockA.tsq").write_bytes(b"")
            (block_b / "BlockB.tev").write_bytes(b"")
            (non_block / "README.txt").write_text("not a block")

            self.assertEqual(
                discover_tdt_block_paths(tank),
                [block_a, block_b],
            )
            self.assertEqual(discover_tdt_block_paths(block_a), [block_a])

    def test_load_session_reads_tdt_streams_and_epocs(self) -> None:
        fake_tdt = types.SimpleNamespace()
        fake_tdt.read_block = lambda _: Struct(
            streams={
                "x405A": Struct(fs=1017.25, data=np.array([1.0, 2.0, 3.0])),
                "x465A": Struct(
                    fs=1017.25,
                    data=np.array([4.0, 5.0, 6.0]),
                    start_time=0.5,
                ),
            },
            epocs={
                "CueA": Struct(
                    onset=np.array([10.0, 20.0]),
                    offset=np.array([11.0, 21.0]),
                    data=np.array([1, 2]),
                )
            },
            info=Struct(subject="Mouse1"),
        )

        original_tdt = sys.modules.get("tdt")
        sys.modules["tdt"] = fake_tdt
        try:
            with tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp)
                (folder / "Subject-250101-120000.tsq").write_bytes(b"")

                session = load_session(folder)

            self.assertEqual(sorted(session.streams), ["x405A", "x465A"])
            self.assertEqual(session.streams["x405A"].fs, 1017.25)
            np.testing.assert_array_equal(
                session.streams["x465A"].data,
                np.array([4.0, 5.0, 6.0]),
            )
            self.assertEqual(session.streams["x465A"].t0, 0.5)
            np.testing.assert_array_equal(
                session.epocs["CueA"].onset,
                np.array([10.0, 20.0]),
            )
            self.assertEqual(session.info["source_format"], "tdt")
            self.assertEqual(session.info["subject"], "Mouse1")
        finally:
            if original_tdt is None:
                sys.modules.pop("tdt", None)
            else:
                sys.modules["tdt"] = original_tdt

    def test_trial_extraction_uses_stream_start_time(self) -> None:
        stream = np.arange(10, dtype=float)
        trials = _extract_trials(
            stream=stream,
            fs=1.0,
            onsets=np.array([102.0]),
            trange=(-1.0, 1.0),
            t0=100.0,
        )

        self.assertEqual(len(trials), 1)
        np.testing.assert_array_equal(trials[0], np.array([1.0, 2.0, 3.0]))

    def test_trial_extraction_drops_incomplete_edge_trials(self) -> None:
        stream = np.arange(10, dtype=float)
        trials = _extract_trials(
            stream=stream,
            fs=1.0,
            onsets=np.array([0.0, 5.0, 9.0]),
            trange=(-1.0, 1.0),
        )

        self.assertEqual(len(trials), 1)
        np.testing.assert_array_equal(trials[0], np.array([4.0, 5.0, 6.0]))

    def test_process_channel_reports_dropped_edge_trials(self) -> None:
        session = PhotometrySession(
            streams={
                "x405A": Stream(
                    name="x405A",
                    fs=1.0,
                    data=np.linspace(1.0, 20.0, 20),
                ),
                "x465A": Stream(
                    name="x465A",
                    fs=1.0,
                    data=np.linspace(2.0, 40.0, 20) ** 1.01,
                ),
            },
            epocs={
                "Cue": Epoc(
                    name="Cue",
                    onset=np.array([0.0, 6.0, 10.0, 18.0]),
                )
            },
            info={},
            source_path=Path("synthetic.mat"),
        )
        settings = ProcessingSettings(
            trange=(-2.0, 2.0),
            baseline_per=(-2.0, 1.0),
            set_baseline=False,
            downsample_factor=1,
            smooth_factor=1,
        )

        processed = process_channel(
            session=session,
            iso_stream="x405A",
            signal_stream="x465A",
            epoc=session.epocs["Cue"],
            settings=settings,
        )

        self.assertEqual(processed.num_edge_trials, 2)
        self.assertEqual(processed.dropped_edge_trials, [1, 4])
        self.assertEqual(processed.zall.shape[0], 2)
        self.assertEqual(processed.trial_numbers, [2, 3])

    def test_subset_processed_signal_recomputes_selected_trials(self) -> None:
        processed = ProcessedSignal(
            ts=np.array([0.0, 1.0]),
            zall=np.array([[1.0, 3.0], [2.0, 4.0], [5.0, 7.0]]),
            zall_smooth=np.array([[10.0, 12.0], [20.0, 22.0], [30.0, 32.0]]),
            mean_z=np.array([0.0, 0.0]),
            sem_z=np.array([0.0, 0.0]),
            mean_z_smooth=np.array([0.0, 0.0]),
            sem_z_smooth=np.array([0.0, 0.0]),
            num_artifacts=1,
            trial_numbers=[11, 12, 13],
        )

        subset = subset_processed_signal(processed, [13, 11])

        self.assertEqual(subset.trial_numbers, [11, 13])
        np.testing.assert_array_equal(
            subset.zall,
            np.array([[1.0, 3.0], [5.0, 7.0]]),
        )
        np.testing.assert_array_equal(subset.mean_z, np.array([3.0, 5.0]))
        np.testing.assert_array_equal(subset.sem_z, np.array([2.0, 2.0]))

    def test_subset_processed_signal_uses_zero_sem_for_single_trial(self) -> None:
        processed = ProcessedSignal(
            ts=np.array([0.0, 1.0]),
            zall=np.array([[1.0, 3.0], [2.0, 4.0]]),
            zall_smooth=np.array([[10.0, 12.0], [20.0, 22.0]]),
            mean_z=np.array([0.0, 0.0]),
            sem_z=np.array([0.0, 0.0]),
            mean_z_smooth=np.array([0.0, 0.0]),
            sem_z_smooth=np.array([0.0, 0.0]),
            num_artifacts=0,
            trial_numbers=[21, 22],
        )

        subset = subset_processed_signal(processed, [22])

        self.assertEqual(subset.trial_numbers, [22])
        np.testing.assert_array_equal(subset.mean_z, np.array([2.0, 4.0]))
        np.testing.assert_array_equal(subset.sem_z, np.array([0.0, 0.0]))

    def test_subset_processed_signal_rejects_missing_trials(self) -> None:
        processed = ProcessedSignal(
            ts=np.array([0.0, 1.0]),
            zall=np.array([[1.0, 3.0]]),
            zall_smooth=np.array([[10.0, 12.0]]),
            mean_z=np.array([0.0, 0.0]),
            sem_z=np.array([0.0, 0.0]),
            mean_z_smooth=np.array([0.0, 0.0]),
            sem_z_smooth=np.array([0.0, 0.0]),
            num_artifacts=0,
            trial_numbers=[5],
        )

        with self.assertRaises(ValueError):
            subset_processed_signal(processed, [6])

    def test_export_channel_uses_original_trial_labels(self) -> None:
        processed = ProcessedSignal(
            ts=np.array([0.0, 1.0]),
            zall=np.array([[1.0, 3.0], [5.0, 7.0]]),
            zall_smooth=np.array([[10.0, 12.0], [30.0, 32.0]]),
            mean_z=np.array([3.0, 5.0]),
            sem_z=np.array([2.0, 2.0]),
            mean_z_smooth=np.array([20.0, 22.0]),
            sem_z_smooth=np.array([10.0, 10.0]),
            num_artifacts=0,
            trial_numbers=[7, 11],
        )

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            export_channel(
                output_dir=output_dir,
                session_name="session",
                epoc_name="Cue",
                channel_key="A_465",
                processed=processed,
                settings=ProcessingSettings(),
                dropped_trials=[],
                stream_store=("x405A", "x465A"),
                metadata={},
                filename_suffix="_selected_trials",
            )

            with (output_dir / "session_Cue_A_465_selected_trials_heatmap.csv").open(
                newline=""
            ) as handle:
                rows = list(csv.reader(handle))

        self.assertEqual(rows[2][0], "TRIAL_007")
        self.assertEqual(rows[3][0], "TRIAL_011")

    def test_export_channel_includes_trial_type_labels(self) -> None:
        processed = ProcessedSignal(
            ts=np.array([0.0, 1.0]),
            zall=np.array([[1.0, 3.0]]),
            zall_smooth=np.array([[10.0, 12.0]]),
            mean_z=np.array([1.0, 3.0]),
            sem_z=np.array([0.0, 0.0]),
            mean_z_smooth=np.array([10.0, 12.0]),
            sem_z_smooth=np.array([0.0, 0.0]),
            num_artifacts=0,
            trial_numbers=[7],
            trial_labels=[CORRECT_REWARDED],
        )

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            export_channel(
                output_dir=output_dir,
                session_name="session",
                epoc_name="Cue",
                channel_key="A_465",
                processed=processed,
                settings=ProcessingSettings(),
                dropped_trials=[],
                stream_store=("x405A", "x465A"),
                metadata={},
            )

            with (output_dir / "session_Cue_A_465_heatmap.csv").open(
                newline=""
            ) as handle:
                rows = list(csv.reader(handle))

        self.assertEqual(rows[2][0], "TRIAL_007_correct_rewarded")

    def test_rev_fixture_explicit_outcomes_partition_levers(self) -> None:
        session = self._load_local_mat_fixture("2143_Rev1_JZL18.mat")

        sources = classified_trial_sources(session)

        self.assertEqual(len(sources), 1)
        source = sources[0]
        self.assertEqual(source.label, "Classified trials levers")
        self.assertEqual(len(source.trials), session.epocs["levers"].onset.size)
        counts = self._trial_type_counts(source)
        self.assertEqual(counts[CORRECT_REWARDED], 3)
        self.assertEqual(counts[CORRECT_NOT_REWARDED], 1)
        self.assertEqual(counts[INCORRECT_REWARDED], 5)
        self.assertEqual(counts[INCORRECT_NOT_REWARDED], 21)

    def test_fr_fixture_side_two_classifies_cl_il_pe_trials(self) -> None:
        session = self._load_local_mat_fixture("1996_FR1-4_NA.mat")

        sources = {source.label: source for source in classified_trial_sources(session)}
        source = sources["Classified trials 2_"]

        counts = self._trial_type_counts(source)
        self.assertEqual(len(source.trials), 90)
        self.assertEqual(counts[CORRECT_REWARDED], 49)
        self.assertEqual(counts[CORRECT_NOT_REWARDED], 18)
        self.assertEqual(counts[INCORRECT_NOT_REWARDED], 23)

    def test_fr_fixture_ignores_startup_zero_events(self) -> None:
        session = self._load_local_mat_fixture("1996_FR3-3_NA.mat")

        sources = {source.label: source for source in classified_trial_sources(session)}
        source = sources["Classified trials 1_"]

        self.assertEqual(len(source.trials), 456)
        self.assertGreater(source.trials[0].onset, 0.0)

    def test_trial_explorer_lists_classified_sources_for_local_fixture(self) -> None:
        path = Path("local-test-data") / "mat" / "2143_Rev1_JZL18.mat"
        if not path.exists():
            self.skipTest(f"Local fixture not available: {path}")
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir())))
        from PySide6 import QtWidgets
        from photon_cruncher.gui.main_window import MainWindow

        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        _ = app
        window = MainWindow()
        window._add_batch_paths([path], clear_existing=True)

        labels = [
            window.trial_epoc_combo.itemText(idx)
            for idx in range(window.trial_epoc_combo.count())
        ]
        self.assertIn("Classified trials levers", labels)

    def _trial_type_counts(self, source) -> dict[str, int]:
        counts: dict[str, int] = {}
        for trial in source.trials:
            counts[trial.trial_type] = counts.get(trial.trial_type, 0) + 1
        return counts

    def test_trial_extraction_tolerates_export_timestamp_roundoff(self) -> None:
        stream = np.arange(260_000, dtype=float)
        mat_trials = _extract_trials(
            stream=stream,
            fs=1017.25,
            onsets=np.array([230.53172826766968]),
            trange=(-2.0, 7.0),
        )
        tdt_trials = _extract_trials(
            stream=stream,
            fs=1017.25,
            onsets=np.array([230.53172736]),
            trange=(-2.0, 7.0),
        )

        self.assertEqual(len(mat_trials), 1)
        self.assertEqual(len(tdt_trials), 1)
        np.testing.assert_array_equal(mat_trials[0], tdt_trials[0])


if __name__ == "__main__":
    unittest.main()
