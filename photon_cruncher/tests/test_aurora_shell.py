from __future__ import annotations

import json
import unittest
from pathlib import Path
from urllib.request import urlopen

from photon_cruncher.gui_aurora.server import find_free_port, serve_in_background, static_files
from photon_cruncher.gui_aurora import STATIC_DIR
from photon_cruncher.product import aurora_app_title


class AuroraShellSpikeTests(unittest.TestCase):
    def test_shell_module_imports(self) -> None:
        from photon_cruncher.gui_aurora import shell

        self.assertTrue(callable(shell.run_shell))
        self.assertTrue(callable(shell.AuroraShellWindow))

    def test_free_port_and_background_server_tuple(self) -> None:
        port = find_free_port("127.0.0.1")
        self.assertIsInstance(port, int)
        self.assertGreater(port, 0)
        httpd, _thread, bound = serve_in_background(host="127.0.0.1", port=None)
        try:
            self.assertGreater(bound, 0)
            with urlopen(f"http://127.0.0.1:{bound}/api/health", timeout=2) as resp:
                health = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(health["ok"])
            self.assertEqual(health["backend"], "photon_cruncher.service")
            self.assertIn("Aurora", health["title"])
            self.assertEqual(health["title"], "Photon Cruncher Aurora")
            self.assertEqual(health.get("brand"), "Aurora v2.0")
            self.assertEqual(health.get("ui_version"), "2.0")
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_static_bundle_still_present(self) -> None:
        names = {path.name for path in static_files()}
        self.assertIn("index.html", names)
        self.assertTrue((STATIC_DIR / "js" / "app.js").is_file())
        app_js = (STATIC_DIR / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIn("onShellMessage", app_js)
        self.assertNotIn("AuroraDemo", app_js)
        self.assertNotIn("demo.js", {path.name for path in static_files()})

    def test_title(self) -> None:
        self.assertIn("Aurora", aurora_app_title())


if __name__ == "__main__":
    unittest.main()
