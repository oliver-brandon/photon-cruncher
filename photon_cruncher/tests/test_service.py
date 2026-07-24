from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

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

    def test_aurora_product_title(self) -> None:
        self.assertIn("Aurora", AURORA_APP_NAME)
        # Window title has no version suffix; version lives in the UI rail.
        self.assertEqual(aurora_app_title(), "Photon Cruncher Aurora")
        from photon_cruncher.product import AURORA_UI_VERSION, aurora_brand_label

        self.assertEqual(AURORA_UI_VERSION, "2.0")
        self.assertEqual(aurora_brand_label(), "Aurora v2.0")


if __name__ == "__main__":
    unittest.main()
