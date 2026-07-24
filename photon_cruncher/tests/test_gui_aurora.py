from __future__ import annotations

import unittest
from urllib.request import urlopen

from photon_cruncher.gui_aurora import STATIC_DIR
from photon_cruncher.gui_aurora.server import serve_in_background, static_files


class AuroraPrototypeTests(unittest.TestCase):
    def test_bundle(self) -> None:
        names = {p.name for p in static_files()}
        for needed in ("index.html", "aurora.css", "app.js", "plots.js"):
            self.assertIn(needed, names)
        self.assertNotIn("demo.js", names)
        self.assertNotIn("fx.js", names)

    def test_index_identity(self) -> None:
        html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        self.assertIn("Aurora v2.0", html)
        self.assertIn("brandSub", html)
        self.assertIn("nav-item", html)
        self.assertIn("page-align", html)
        self.assertIn("photon_cruncher.service", html)
        self.assertIn("openSessionBtn", html)
        self.assertNotIn("demo.js", html)
        self.assertNotIn("Demo_Mouse", html)
        self.assertNotIn("synthetic", html.lower())

    def test_app_js_is_live_only(self) -> None:
        js = (STATIC_DIR / "js" / "app.js").read_text(encoding="utf-8")
        self.assertNotIn("AuroraDemo", js)
        self.assertNotIn("launchDemoBatch", js)
        self.assertNotIn("demo feed", js)
        self.assertIn("photon_cruncher.service", js)
        self.assertIn("/api/open", js)
        self.assertIn("/api/analyze", js)
        self.assertIn("/api/export", js)

    def test_serves(self) -> None:
        httpd, _thread, _port = serve_in_background(host="127.0.0.1", port=8768)
        try:
            with urlopen("http://127.0.0.1:8768/", timeout=2) as resp:
                body = resp.read().decode("utf-8")
                self.assertEqual(resp.status, 200)
            self.assertIn("Aurora", body)
            self.assertIn("rail", body)
            self.assertNotIn("Demo_Mouse", body)
            with urlopen("http://127.0.0.1:8768/api/health", timeout=2) as resp:
                health = resp.read().decode("utf-8")
            self.assertIn("photon_cruncher.service", health)
            self.assertIn("Aurora", health)
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
