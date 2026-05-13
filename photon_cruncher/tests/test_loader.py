from __future__ import annotations

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
from photon_cruncher.model import Epoc, PhotometrySession, Stream
from photon_cruncher.processing.pipeline import (
    ProcessingSettings,
    _extract_trials,
    process_channel,
)


class Struct:
    def __init__(self, **kwargs: object) -> None:
        self.__dict__.update(kwargs)


class LoaderTests(unittest.TestCase):
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
