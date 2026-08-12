from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from photon_cruncher.analysis.trial_classifier import (
    CORRECT_NOT_REWARDED,
    CORRECT_REWARDED,
)
from photon_cruncher.model import Epoc, PhotometrySession, Stream
from photon_cruncher import service
from photon_cruncher.product import AURORA_APP_NAME, aurora_app_title


class ServiceFacadeTests(unittest.TestCase):
    def _session(self) -> PhotometrySession:
        return PhotometrySession(
            streams={
                "x405A": Stream(
                    name="x405A",
                    fs=10.0,
                    data=np.linspace(1.0, 40.0, 400),
                ),
                "x465A": Stream(
                    name="x465A",
                    fs=10.0,
                    data=np.linspace(2.0, 80.0, 400) ** 1.01,
                ),
            },
            epocs={"Cue": Epoc(name="Cue", onset=np.array([10.0, 20.0, 30.0]))},
            info={"subject": "service-test"},
            source_path=Path("service-test.mat"),
        )

    def test_list_channels_and_analyze(self) -> None:
        session = self._session()
        channels = service.list_channels(session)
        self.assertEqual([channel.key for channel in channels], ["A_465"])

        results = service.analyze(
            session,
            "Cue",
            channel_keys=["A_465"],
            settings_overrides={
                "trange": (-2.0, 5.0),
                "baseline_per": (-2.0, -0.5),
                "downsample_factor": 1,
                "smooth_factor": 3,
                "set_baseline": False,
            },
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].channel_key, "A_465")
        self.assertGreater(results[0].processed.zall.shape[0], 0)
        self.assertEqual(
            len(results[0].processed.trial_times),
            results[0].processed.zall.shape[0],
        )

    def test_signal_only_session_analyzes_when_isosbestic_is_disabled(self) -> None:
        paired = self._session()
        session = PhotometrySession(
            streams={"x465A": paired.streams["x465A"]},
            epocs=paired.epocs,
            info=paired.info,
            source_path=Path("signal-only.mat"),
        )

        self.assertEqual([channel.key for channel in service.list_channels(session)], ["A_465"])
        result = service.analyze(
            session,
            "Cue",
            settings_overrides={
                "use_isosbestic": False,
                "trange": (-2.0, 5.0),
                "baseline_per": (-2.0, -0.5),
                "downsample_factor": 1,
                "smooth_factor": 3,
                "set_baseline": False,
            },
        )[0]
        self.assertEqual(result.stream_store, ("", "x465A"))
        self.assertTrue(np.isfinite(result.processed.zall).all())
        warning = service.quality_summary(result)["warnings"][0]
        self.assertEqual(warning["code"], "signal_only")
        self.assertEqual(warning["severity"], "warning")

        with self.assertRaisesRegex(ValueError, "paired 405"):
            service.analyze(session, "Cue", channel_keys=["A_465"])

    def test_session_summary_and_plot_payload(self) -> None:
        session = self._session()
        summary = service.session_summary(session)
        self.assertEqual(summary["session_name"], "service-test")
        self.assertIn("Cue", summary["epocs"])
        self.assertEqual(summary["channels"], ["A_465"])

        result = service.analyze(
            session,
            "Cue",
            settings_overrides={
                "trange": (-2.0, 5.0),
                "baseline_per": (-2.0, -0.5),
                "downsample_factor": 1,
                "smooth_factor": 3,
                "set_baseline": False,
            },
        )[0]
        payload = service.result_plot_payload(result)
        self.assertEqual(payload["channel"], "A_465")
        self.assertEqual(len(payload["times"]), result.processed.ts.size)
        self.assertEqual(len(payload["mean"]), result.processed.ts.size)
        self.assertEqual(len(payload["z"]), result.processed.zall.shape[0])
        self.assertEqual(payload["trial_times"], [10.0, 20.0, 30.0])
        self.assertTrue(payload["settings"]["use_isosbestic"])
        self.assertEqual(payload["settings"]["polynomial_degree"], 1)
        self.assertIn("quality", payload)

        compact = service.result_plot_payload(result, include_matrix=False)
        self.assertNotIn("z", compact)
        self.assertEqual(
            compact["matrix_shape"],
            list(result.processed.zall_smooth.shape),
        )
        result.processed.mean_z_smooth[0] = np.nan
        compact = service.result_plot_payload(result, include_matrix=False)
        self.assertIsNone(compact["mean"][0])

    def test_session_summary_reports_classified_trial_type_counts(self) -> None:
        session = self._session()
        session.epocs.update(
            {
                "cRewA": Epoc(name="cRewA", onset=np.array([10.0, 30.0])),
                "cNoRewA": Epoc(name="cNoRewA", onset=np.array([20.0])),
            }
        )

        summary = service.session_summary(session)

        self.assertEqual(len(summary["classified_sources"]), 1)
        source = summary["classified_sources"][0]
        self.assertEqual(source["label"], "Classified trials")
        self.assertEqual(
            source["trial_type_counts"],
            {CORRECT_NOT_REWARDED: 1, CORRECT_REWARDED: 2},
        )

    def test_quality_summary_reports_scientific_qc_conditions(self) -> None:
        result = service.analyze(
            self._session(),
            "Cue",
            settings_overrides={
                "trange": (-2.0, 5.0),
                "baseline_per": (-2.0, -0.5),
                "downsample_factor": 1,
                "smooth_factor": 1,
                "set_baseline": False,
            },
        )[0]
        result.processed.num_edge_trials = 1
        result.processed.num_artifacts = 1
        result.processed.baseline_standard_deviations[0] = 0.0
        result.processed.zall[0, 0] = 25.0

        quality = service.quality_summary(result)

        codes = {item["code"] for item in quality["warnings"]}
        self.assertIn("incomplete_edge_trials", codes)
        self.assertIn("artifact_removals", codes)
        self.assertIn("low_baseline_variance", codes)
        self.assertIn("extreme_zscores", codes)
        self.assertEqual(quality["evaluated_trace"], "raw_zscore")

    def test_isosbestic_settings_overrides(self) -> None:
        settings = service.settings_for_channel(
            "A_465",
            overrides={
                "use_isosbestic": False,
                "polynomial_degree": 3,
            },
        )
        self.assertFalse(settings.use_isosbestic)
        self.assertEqual(settings.polynomial_degree, 3)

        with self.assertRaisesRegex(ValueError, "polynomial_degree"):
            service.settings_for_channel(
                "A_465",
                overrides={"polynomial_degree": 0},
            )

    def test_export_result_writes_csv(self) -> None:
        session = self._session()
        result = service.analyze(
            session,
            "Cue",
            settings_overrides={
                "trange": (-2.0, 5.0),
                "baseline_per": (-2.0, -0.5),
                "downsample_factor": 1,
                "smooth_factor": 3,
                "set_baseline": False,
            },
        )[0]
        with tempfile.TemporaryDirectory() as tmp:
            paths = service.export_result(result, tmp, export_csv=True, export_figure=False)
            self.assertTrue(paths["csv"])
            self.assertTrue(Path(paths["csv"]).exists())
            self.assertTrue(Path(paths["manifest"]).exists())
            manifest = json.loads(Path(paths["manifest"]).read_text(encoding="utf-8"))
            self.assertEqual(manifest["application"]["version"], service.__version__)
            self.assertEqual(manifest["analysis"]["epoc"], "Cue")
            self.assertEqual(manifest["analysis"]["channel"], "A_465")
            self.assertEqual(manifest["analysis"]["settings"]["trange_end"], 5.0)
            self.assertEqual(manifest["trials"]["kept"], 3)
            self.assertEqual(manifest["outputs"]["csv"], paths["csv"])

    def test_aurora_product_title(self) -> None:
        self.assertIn("Aurora", AURORA_APP_NAME)
        # Window title has no version suffix; version lives in the UI rail.
        self.assertEqual(aurora_app_title(), AURORA_APP_NAME)
        from photon_cruncher.product import AURORA_UI_VERSION, aurora_brand_label
        from photon_cruncher.version import __version__

        self.assertEqual(AURORA_UI_VERSION, __version__)
        self.assertEqual(aurora_brand_label(), f"Aurora v{__version__}")


if __name__ == "__main__":
    unittest.main()
