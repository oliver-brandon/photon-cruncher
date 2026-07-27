from __future__ import annotations

import unittest
from pathlib import Path
from urllib.request import urlopen

from PySide6 import QtGui

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
        self.assertIn('id="exportDir"', html)
        self.assertIn('id="chooseExportDir"', html)
        self.assertIn('id="smoothFactor"', html)
        self.assertIn('id="batchEpocSelectors"', html)
        self.assertIn('id="batchChannelSelectors"', html)
        self.assertIn('id="batchAddFiles"', html)
        self.assertIn('id="batchAddFolder"', html)
        self.assertIn('id="batchAddTank"', html)
        self.assertIn('id="batchEpocPolicy"', html)
        self.assertIn('id="alignChannelSelectors"', html)
        self.assertIn('id="trialChannelSelectors"', html)
        self.assertIn('id="trialEpoc"', html)
        self.assertIn('id="trialLoad"', html)
        self.assertIn('id="alignExportCsv"', html)
        self.assertIn('id="alignExportFig"', html)
        self.assertIn('value="-3"', html)
        self.assertIn('value="-1"', html)
        self.assertNotIn('id="alignExport"', html)
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
        self.assertIn("filteredResultsByChannel", js)
        self.assertIn("channel_settings", js)
        self.assertIn("exportBatchSelection", js)
        self.assertIn("/api/batch-export", js)
        self.assertIn("/api/inspect-paths", js)
        self.assertIn("batchEpocSelections", js)
        self.assertIn("batchEpocs", js)
        self.assertIn("runTrialAnalyze", js)
        self.assertIn("trialSettingsPayload", js)
        self.assertIn("analysisChannels", js)
        self.assertIn("savedProcessingSettings", js)
        self.assertIn("saveProcessingSettings", js)
        self.assertGreaterEqual(js.count("channels: trialExportChannels()"), 2)
        self.assertNotIn("meanSemRows", js)

    def test_select_controls_are_contained(self) -> None:
        css = (STATIC_DIR / "css" / "aurora.css").read_text(encoding="utf-8")
        self.assertIn("max-width: 100%", css)
        self.assertIn(".plot-tools select", css)
        self.assertIn("text-overflow: ellipsis", css)

    def test_aurora_icon_has_transparent_corners(self) -> None:
        icon = (
            Path(__file__).resolve().parents[1]
            / "assets"
            / "icons"
            / "png"
            / "photon-cruncher-aurora-1024.png"
        )
        image = QtGui.QImage(str(icon))
        self.assertFalse(image.isNull())
        self.assertTrue(image.hasAlphaChannel())
        corners = (
            (0, 0),
            (image.width() - 1, 0),
            (0, image.height() - 1),
            (image.width() - 1, image.height() - 1),
        )
        self.assertEqual([image.pixelColor(*point).alpha() for point in corners], [0] * 4)

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
