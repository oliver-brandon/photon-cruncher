from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from photon_cruncher.export.exporter import export_channel
from photon_cruncher.model import Epoc, PhotometrySession, Stream
from photon_cruncher.processing.pipeline import ProcessingSettings, process_channel


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
GOLDEN_PATH = FIXTURE_DIR / "golden_process_channel.npz"


def _golden_session() -> PhotometrySession:
    rng = np.random.default_rng(42)
    fs = 100.0
    n = 5000
    t = np.arange(n) / fs
    control = 2.0 + 0.1 * np.sin(2 * np.pi * 0.5 * t) + rng.normal(0, 0.05, n)
    signal = (
        3.0
        + 0.4 * control
        + 0.2 * np.sin(2 * np.pi * 1.3 * t)
        + rng.normal(0, 0.08, n)
    )
    onsets = np.array([10.0, 20.0, 30.0, 40.0, 45.5])
    return PhotometrySession(
        streams={
            "x405A": Stream(name="x405A", fs=fs, data=control),
            "x465A": Stream(name="x465A", fs=fs, data=signal),
        },
        epocs={"Cue": Epoc(name="Cue", onset=onsets)},
        info={},
        source_path=Path("golden.mat"),
    )


def _golden_settings() -> ProcessingSettings:
    return ProcessingSettings(
        trange=(-2.0, 5.0),
        baseline_per=(-2.0, -0.5),
        base_adjust=-1.5,
        plot_smooth=True,
        set_baseline=True,
        downsample_factor=5,
        smooth_factor=7,
        artifact_405=np.inf,
        artifact_465=np.inf,
    )


class PipelineEquivalenceTests(unittest.TestCase):
    def test_process_channel_matches_frozen_golden_arrays(self) -> None:
        if not GOLDEN_PATH.exists():
            self.skipTest(f"Missing golden fixture: {GOLDEN_PATH}")

        golden = np.load(GOLDEN_PATH)
        session = _golden_session()
        processed = process_channel(
            session=session,
            iso_stream="x405A",
            signal_stream="x465A",
            epoc=session.epocs["Cue"],
            settings=_golden_settings(),
        )

        self.assertEqual(processed.trial_numbers, [1, 2, 3, 4])
        self.assertEqual(processed.dropped_edge_trials, [5])
        self.assertEqual(processed.num_edge_trials, 1)
        np.testing.assert_allclose(processed.ts, golden["ts"], rtol=0.0, atol=0.0)
        np.testing.assert_allclose(processed.zall, golden["zall"], rtol=1e-12, atol=1e-12)
        np.testing.assert_allclose(
            processed.zall_smooth,
            golden["zall_smooth"],
            rtol=1e-12,
            atol=1e-12,
        )
        np.testing.assert_allclose(
            processed.mean_z, golden["mean_z"], rtol=1e-12, atol=1e-12
        )
        np.testing.assert_allclose(
            processed.sem_z, golden["sem_z"], rtol=1e-12, atol=1e-12
        )
        np.testing.assert_allclose(
            processed.mean_z_smooth,
            golden["mean_z_smooth"],
            rtol=1e-12,
            atol=1e-12,
        )
        np.testing.assert_allclose(
            processed.sem_z_smooth,
            golden["sem_z_smooth"],
            rtol=1e-12,
            atol=1e-12,
        )

    def test_signal_only_processing_does_not_access_isosbestic_stream(self) -> None:
        session = _golden_session()
        settings = _golden_settings()
        settings.use_isosbestic = False
        settings.artifact_405 = 0.0

        processed = process_channel(
            session=session,
            iso_stream="missing-isosbestic-stream",
            signal_stream="x465A",
            epoc=session.epocs["Cue"],
            settings=settings,
        )

        self.assertEqual(processed.trial_numbers, [1, 2, 3, 4])
        self.assertEqual(processed.dropped_edge_trials, [5])
        self.assertEqual(processed.num_artifacts, 0)
        self.assertTrue(np.isfinite(processed.zall).all())

    def test_polynomial_degree_changes_isosbestic_fit(self) -> None:
        session = _golden_session()
        linear_settings = _golden_settings()
        quadratic_settings = _golden_settings()
        quadratic_settings.polynomial_degree = 2

        linear = process_channel(
            session=session,
            iso_stream="x405A",
            signal_stream="x465A",
            epoc=session.epocs["Cue"],
            settings=linear_settings,
        )
        quadratic = process_channel(
            session=session,
            iso_stream="x405A",
            signal_stream="x465A",
            epoc=session.epocs["Cue"],
            settings=quadratic_settings,
        )

        self.assertEqual(linear.zall.shape, quadratic.zall.shape)
        self.assertFalse(np.allclose(linear.zall, quadratic.zall))

    def test_linear_control_artifact_is_removed_by_linear_fit(self) -> None:
        fs = 20.0
        time = np.arange(0.0, 40.0, 1.0 / fs)
        control = 1.0 + 0.15 * np.sin(time) + 0.01 * time
        signal = 2.5 + 1.8 * control
        session = PhotometrySession(
            streams={
                "x405A": Stream("x405A", fs, control),
                "x465A": Stream("x465A", fs, signal),
            },
            epocs={"Cue": Epoc("Cue", np.array([10.0, 20.0, 30.0]))},
            info={},
            source_path=Path("linear-artifact.mat"),
        )
        settings = ProcessingSettings(
            trange=(-2.0, 5.0),
            baseline_per=(-2.0, -0.5),
            set_baseline=False,
            downsample_factor=1,
            smooth_factor=1,
            polynomial_degree=1,
        )

        with mock.patch(
            "photon_cruncher.processing.pipeline._zscore_trials",
            side_effect=lambda corrected, _baseline_mask: corrected,
        ):
            processed = process_channel(
                session, "x405A", "x465A", session.epocs["Cue"], settings
            )

        self.assertLess(np.nanmax(np.abs(processed.zall)), 1e-10)

    def test_quadratic_control_artifact_is_removed_by_quadratic_fit(self) -> None:
        fs = 20.0
        time = np.arange(0.0, 40.0, 1.0 / fs)
        control = 1.0 + 0.15 * np.sin(time) + 0.01 * time
        signal = 2.5 + 1.8 * control + 0.7 * control**2
        session = PhotometrySession(
            streams={
                "x405A": Stream("x405A", fs, control),
                "x465A": Stream("x465A", fs, signal),
            },
            epocs={"Cue": Epoc("Cue", np.array([10.0, 20.0, 30.0]))},
            info={},
            source_path=Path("quadratic-artifact.mat"),
        )
        settings = ProcessingSettings(
            trange=(-2.0, 5.0),
            baseline_per=(-2.0, -0.5),
            set_baseline=False,
            downsample_factor=1,
            smooth_factor=1,
            polynomial_degree=2,
        )

        with mock.patch(
            "photon_cruncher.processing.pipeline._zscore_trials",
            side_effect=lambda corrected, _baseline_mask: corrected,
        ):
            processed = process_channel(
                session, "x405A", "x465A", session.epocs["Cue"], settings
            )

        self.assertLess(np.nanmax(np.abs(processed.zall)), 1e-9)

    def test_polynomial_degree_must_be_positive_when_fit_is_enabled(self) -> None:
        session = _golden_session()
        settings = _golden_settings()
        settings.polynomial_degree = 0

        with self.assertRaisesRegex(ValueError, "degree must be at least 1"):
            process_channel(
                session=session,
                iso_stream="x405A",
                signal_stream="x465A",
                epoc=session.epocs["Cue"],
                settings=settings,
            )

    def test_export_channel_preserves_labels_and_numeric_values(self) -> None:
        session = _golden_session()
        processed = process_channel(
            session=session,
            iso_stream="x405A",
            signal_stream="x465A",
            epoc=session.epocs["Cue"],
            settings=_golden_settings(),
        )
        processed.trial_labels = [
            "correct rewarded",
            "",
            "incorrect not rewarded",
            "",
        ]

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            path = export_channel(
                output_dir=output_dir,
                session_name="session",
                epoc_name="Cue",
                channel_key="A_465",
                processed=processed,
                settings=_golden_settings(),
                dropped_trials=[],
                stream_store=("x405A", "x465A"),
                metadata={},
                export_smoothed=True,
            )
            rows = np.loadtxt(path, delimiter=",", dtype=str)
            self.assertEqual(rows[0, 0], "TIME")
            self.assertEqual(rows[1, 0], "MEAN")
            self.assertEqual(rows[2, 0], "TRIAL_001_correct_rewarded")
            self.assertEqual(rows[3, 0], "TRIAL_002")
            self.assertEqual(rows[4, 0], "TRIAL_003_incorrect_not_rewarded")
            self.assertEqual(rows[5, 0], "TRIAL_004")

            values = rows[:, 1:].astype(float)
            np.testing.assert_allclose(values[0], processed.ts, rtol=1e-9, atol=1e-9)
            np.testing.assert_allclose(
                values[1],
                processed.zall_smooth.mean(axis=0),
                rtol=1e-9,
                atol=1e-9,
            )
            np.testing.assert_allclose(
                values[2:],
                processed.zall_smooth,
                rtol=1e-9,
                atol=1e-9,
            )


if __name__ == "__main__":
    unittest.main()
