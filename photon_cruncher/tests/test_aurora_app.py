from __future__ import annotations

import json
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from urllib.request import Request, urlopen

import numpy as np

from photon_cruncher import service
from photon_cruncher.gui_aurora.server import (
    _analyze_request,
    _batch_export_request,
    _export_request,
    _inspect_paths_request,
    _plot_matrix_request,
    serve_in_background,
)
from photon_cruncher.gui_aurora.session_store import STORE
from photon_cruncher.analysis.runner import BatchOutcome
from photon_cruncher.model import Epoc, PhotometrySession, Stream


def _post(port: int, path: str, body: dict) -> dict:
    req = Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get(port: int, path: str) -> dict:
    with urlopen(f"http://127.0.0.1:{port}{path}", timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _upload(
    port: int,
    upload_id: str,
    relative_path: str,
    data: bytes,
    *,
    final: bool,
) -> dict:
    query = urllib.parse.urlencode(
        {
            "upload_id": upload_id,
            "relative_path": relative_path,
            "final": "1" if final else "0",
        }
    )
    req = Request(
        f"http://127.0.0.1:{port}/api/upload?{query}",
        data=data,
        method="POST",
        headers={"Content-Type": "application/octet-stream"},
    )
    with urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


class AuroraAppTests(unittest.TestCase):
    def setUp(self) -> None:
        STORE.clear()

    def tearDown(self) -> None:
        STORE.clear()

    def _synthetic_mat(self, folder: Path) -> Path:
        # Build a tiny in-memory session via service path using a real load is hard
        # without writing mat; instead exercise store/API with monkeypatch-style
        # direct store open using a temp path registered manually is awkward.
        # Use local fixture if present, else skip.
        fixture = Path("local-test-data/mat/2149_Rev1_JZL18.mat")
        if fixture.exists():
            return fixture.resolve()
        self.skipTest("local mat fixture unavailable")

    def test_figure_export_uses_source_named_directory(self) -> None:
        cached = SimpleNamespace(
            session=SimpleNamespace(source_path=Path("/recordings/mouse-01.mat"))
        )
        result = SimpleNamespace(channel_key="A_465")
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp).resolve() / "mouse-01"
            paths = {
                "csv": "",
                "figure": str(destination / "mouse-01_Cue_A_465_summary.png"),
                "manifest": str(destination / "mouse-01_Cue_A_465_analysis.json"),
            }
            with (
                mock.patch.object(STORE, "open", return_value=cached),
                mock.patch.object(service, "analyze", return_value=[result]),
                mock.patch.object(
                    service,
                    "export_result",
                    return_value=paths,
                ) as export_result,
                mock.patch.object(
                    service,
                    "quality_summary",
                    return_value={"warnings": []},
                ),
            ):
                payload = _export_request(
                    {
                        "path": "/recordings/mouse-01.mat",
                        "epoc": "Cue",
                        "channels": ["A_465"],
                        "output_dir": tmp,
                        "export_csv": False,
                        "export_figure": True,
                    }
                )

        self.assertEqual(export_result.call_args.args[1], destination)
        self.assertTrue(export_result.call_args.kwargs["export_figure"])
        self.assertEqual(payload["output_dir"], str(destination))
        self.assertEqual(payload["exports"][0]["figure"], paths["figure"])
        self.assertEqual(payload["exports"][0]["manifest"], paths["manifest"])

    def test_open_analyze_export_roundtrip(self) -> None:
        mat = self._synthetic_mat(Path("."))
        httpd, _thread, port = serve_in_background(host="127.0.0.1", port=None)
        try:
            opened = _post(port, "/api/open", {"path": str(mat)})
            self.assertTrue(opened["ok"])
            self.assertIn("session", opened)
            channels = opened["session"]["channels"]
            self.assertTrue(channels)
            epocs = list(opened["session"]["epocs"])
            self.assertTrue(epocs)
            epoc = next(
                (e for e in epocs if e.lower() not in {"tick", "cam1"}),
                epocs[0],
            )
            analyzed = _post(
                port,
                "/api/analyze",
                {
                    "path": opened["path"],
                    "epoc": epoc,
                    "channels": channels[:1],
                    "settings": {
                        "trange_start": -2.0,
                        "trange_end": 5.0,
                        "baseline_start": -2.0,
                        "baseline_end": -0.5,
                    },
                },
            )
            self.assertTrue(analyzed["ok"])
            self.assertGreaterEqual(len(analyzed["results"]), 1)
            result = analyzed["results"][0]
            self.assertIn("times", result)
            self.assertIn("mean", result)
            self.assertIn("z", result)
            self.assertIn("trial_times", result)
            self.assertEqual(len(result["trial_times"]), result["num_trials"])
            self.assertGreater(len(result["times"]), 10)

            with tempfile.TemporaryDirectory() as tmp:
                exported = _post(
                    port,
                    "/api/export",
                    {
                        "path": opened["path"],
                        "epoc": epoc,
                        "channels": channels[:1],
                        "output_dir": tmp,
                        "export_csv": True,
                        "export_figure": False,
                        "settings": {
                            "trange_start": -2.0,
                            "trange_end": 5.0,
                            "baseline_start": -2.0,
                            "baseline_end": -0.5,
                        },
                    },
                )
                self.assertTrue(exported["ok"])
                self.assertEqual(len(exported["exports"]), 1)
                self.assertEqual(exported["exports"][0]["channel"], channels[0])
                csv_path = Path(exported["exports"][0]["csv"])
                self.assertTrue(csv_path.exists())
                manifest_path = Path(exported["exports"][0]["manifest"])
                self.assertTrue(manifest_path.exists())
                text = csv_path.read_text(encoding="utf-8").splitlines()
                self.assertTrue(text[0].startswith("TIME,"))
                self.assertTrue(text[1].startswith("MEAN,"))

            health = _get(port, "/api/health")
            self.assertEqual(health["backend"], "photon_cruncher.service")
            self.assertEqual(health["current_session"], opened["path"])
            diagnostics = _get(port, "/api/diagnostics")
            self.assertEqual(diagnostics["application"]["version"], health["version"])
            self.assertNotIn("streams", diagnostics)
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_shell_and_bridge_import(self) -> None:
        from photon_cruncher.gui_aurora.shell import AuroraBridge, AuroraShellWindow, run_shell

        self.assertTrue(callable(run_shell))
        self.assertTrue(AuroraBridge)
        self.assertTrue(AuroraShellWindow)

    def test_browser_upload_streams_files_and_discovers_mat_sources(self) -> None:
        httpd, _thread, port = serve_in_background(host="127.0.0.1", port=None)
        try:
            payload = _upload(
                port,
                "browser-test",
                "selected/sample.mat",
                b"not-a-real-mat",
                final=True,
            )
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["received"], len(b"not-a-real-mat"))
            self.assertEqual(len(payload["paths"]), 1)
            uploaded = Path(payload["paths"][0])
            self.assertTrue(uploaded.exists())
            self.assertEqual(uploaded.read_bytes(), b"not-a-real-mat")
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_browser_upload_preserves_tdt_folder_layout(self) -> None:
        httpd, _thread, port = serve_in_background(host="127.0.0.1", port=None)
        try:
            partial = _upload(
                port,
                "browser-tdt-test",
                "Tank/Block/Block.tev",
                b"tev",
                final=False,
            )
            self.assertTrue(partial["ok"])
            self.assertNotIn("paths", partial)
            payload = _upload(
                port,
                "browser-tdt-test",
                "Tank/Block/Block.tsq",
                b"tsq",
                final=True,
            )
            self.assertTrue(payload["ok"])
            self.assertEqual(len(payload["paths"]), 1)
            self.assertTrue(payload["paths"][0].endswith("/Tank/Block"))
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_inspect_paths_does_not_replace_current_session(self) -> None:
        cached = SimpleNamespace(
            path="/data/session-a.mat",
            summary={"session_name": "session-a"},
        )
        with mock.patch.object(STORE, "open", return_value=cached) as opened:
            payload = _inspect_paths_request(
                {"paths": ["/data/session-a.mat", "/data/session-a.mat"]}
            )
        opened.assert_any_call("/data/session-a.mat", make_current=False)
        self.assertEqual(len(payload["sources"]), 1)
        self.assertEqual(payload["errors"], [])

    def test_batch_export_uses_multi_source_runner_and_policy(self) -> None:
        epoc = Epoc(name="CueA", onset=np.array([1.0]))
        session = SimpleNamespace(epocs={"CueA": epoc})
        result = SimpleNamespace(
            session=SimpleNamespace(source_path=Path("/data/a.mat")),
            epoc=epoc,
            channel_key="A_465",
        )
        exported = SimpleNamespace(
            output_dir=Path("/exports/a"),
            result=result,
            csv_path=Path("/exports/a/a_CueA_A_465_heatmap.csv"),
        )
        failed_export = SimpleNamespace(
            output_dir=Path("/exports/b"),
            result=SimpleNamespace(
                session=SimpleNamespace(source_path=Path("/data/b.mat")),
                epoc=epoc,
                channel_key="A_465",
            ),
            csv_path=None,
        )

        def batch_runner(**kwargs):
            kwargs["outcomes"].append(
                BatchOutcome(
                    status="error",
                    input_path=Path("/data/b.mat"),
                    session="b",
                    epoc="CueA",
                    channels=("A_465",),
                    reason="Analysis failed: synthetic failure",
                )
            )
            return [exported, failed_export]

        with (
            mock.patch(
                "photon_cruncher.gui_aurora.server.run_batch_custom",
                side_effect=batch_runner,
            ) as runner,
            mock.patch(
                "photon_cruncher.gui_aurora.server.service.open_session",
                return_value=session,
            ) as opened,
            mock.patch(
                "photon_cruncher.gui_aurora.server.service.quality_summary",
                return_value={"warnings": []},
            ),
        ):
            payload = _batch_export_request(
                {
                    "paths": ["/data/a.mat", "/data/b.mat"],
                    "epoc_selections": [
                        {
                            "label": "Cue (prefer A/1_)",
                            "members": ["CueA", "CueC"],
                            "mode": "prefer_left",
                        }
                    ],
                    "channels": ["A_465"],
                    "settings": {
                        "baseline_start": -3,
                        "baseline_end": -1,
                        "use_isosbestic": False,
                        "polynomial_degree": 3,
                    },
                    "output_dir": "/exports",
                    "export_csv": True,
                    "export_figure": False,
                }
            )

        kwargs = runner.call_args.kwargs
        self.assertEqual(len(kwargs["input_paths"]), 2)
        self.assertEqual(
            kwargs["epoc_selections"],
            [("Cue (prefer A/1_)", ("CueA", "CueC"), "prefer_left")],
        )
        self.assertTrue(kwargs["per_session_subdir"])
        settings = kwargs["settings_factory"]("A_465")
        self.assertEqual(settings.baseline_per, (-3.0, -1.0))
        self.assertFalse(settings.use_isosbestic)
        self.assertEqual(settings.polynomial_degree, 3)
        self.assertEqual(payload["input_count"], 2)
        self.assertEqual(len(payload["exports"]), 1)
        self.assertEqual(payload["exports"][0]["channel"], "A_465")
        self.assertEqual(payload["exports"][0]["quality"], {"warnings": []})
        self.assertEqual(
            payload["exports"][0]["csv"],
            "/exports/a/a_CueA_A_465_heatmap.csv",
        )
        self.assertEqual(payload["errors"][0]["session"], "b")
        self.assertEqual(payload["errors"][0]["channels"], ["A_465"])
        self.assertIn("synthetic failure", payload["errors"][0]["reason"])
        opened.assert_not_called()

    def test_filtered_analysis_keeps_full_plot_payloads(self) -> None:
        full_processed = object()
        filtered_processed = object()
        result = SimpleNamespace(
            session=object(),
            epoc=object(),
            channel_key="A_465",
            processed=full_processed,
            settings=object(),
            stream_store=("x405A", "x465A"),
        )
        cached = SimpleNamespace(
            path="/synthetic/session.mat",
            summary={"channels": ["A_465"]},
        )

        def plot_payload(item):
            return {
                "channel": item.channel_key,
                "filtered": item.processed is filtered_processed,
            }

        with (
            mock.patch.object(STORE, "open", return_value=cached),
            mock.patch.object(STORE, "get_analysis", return_value=[result]),
            mock.patch(
                "photon_cruncher.gui_aurora.server.service.filter_trials",
                return_value=filtered_processed,
            ),
            mock.patch(
                "photon_cruncher.gui_aurora.server.service.result_plot_payload",
                side_effect=plot_payload,
            ),
        ):
            payload = _analyze_request(
                {
                    "path": cached.path,
                    "epoc": "Cue",
                    "trial_numbers": [2],
                }
            )

        self.assertEqual(
            payload["all_results"],
            [{"channel": "A_465", "filtered": False}],
        )
        self.assertEqual(payload["results"], [{"channel": "A_465", "filtered": True}])

    def test_empty_trial_selection_keeps_full_payload_without_fake_filter(self) -> None:
        result = SimpleNamespace(channel_key="A_465", processed=object())
        cached = SimpleNamespace(path="/synthetic/session.mat", summary={})
        with (
            mock.patch.object(STORE, "open", return_value=cached),
            mock.patch.object(STORE, "get_analysis", return_value=[result]),
            mock.patch(
                "photon_cruncher.gui_aurora.server.service.result_plot_payload",
                return_value={"channel": "A_465"},
            ),
        ):
            payload = _analyze_request(
                {
                    "path": cached.path,
                    "epoc": "Cue",
                    "trial_numbers": [],
                }
            )
        self.assertEqual(payload["results"], [])
        self.assertEqual(payload["all_results"], [{"channel": "A_465"}])

    def test_plot_matrix_request_returns_compact_float32_rows(self) -> None:
        matrix = np.arange(12, dtype=float).reshape(3, 4)
        result = SimpleNamespace(
            channel_key="A_465",
            processed=SimpleNamespace(zall=matrix, zall_smooth=matrix + 0.5),
            settings=SimpleNamespace(plot_smooth=True),
        )
        with mock.patch(
            "photon_cruncher.gui_aurora.server._cached_analysis",
            return_value=(SimpleNamespace(), [result], "Cue"),
        ):
            raw, headers = _plot_matrix_request(
                {"path": "/synthetic.mat", "epoc": "Cue", "channel": "A_465"}
            )

        decoded = np.frombuffer(raw, dtype="<f4").reshape(3, 4)
        np.testing.assert_allclose(decoded, matrix + 0.5)
        self.assertEqual(headers["X-Aurora-Rows"], "3")
        self.assertEqual(headers["X-Aurora-Columns"], "4")


if __name__ == "__main__":
    unittest.main()
