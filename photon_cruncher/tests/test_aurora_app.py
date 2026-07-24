from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

import numpy as np

from photon_cruncher.gui_aurora.server import serve_in_background
from photon_cruncher.gui_aurora.session_store import STORE
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
                self.assertTrue(exported["exports"])
                csv_path = Path(exported["exports"][0]["csv"])
                self.assertTrue(csv_path.exists())
                text = csv_path.read_text(encoding="utf-8").splitlines()
                self.assertTrue(text[0].startswith("TIME,"))
                self.assertTrue(text[1].startswith("MEAN,"))

            health = _get(port, "/api/health")
            self.assertEqual(health["backend"], "photon_cruncher.service")
            self.assertEqual(health["current_session"], opened["path"])
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_shell_and_bridge_import(self) -> None:
        from photon_cruncher.gui_aurora.shell import AuroraBridge, AuroraShellWindow, run_shell

        self.assertTrue(callable(run_shell))
        self.assertTrue(AuroraBridge)
        self.assertTrue(AuroraShellWindow)


if __name__ == "__main__":
    unittest.main()
