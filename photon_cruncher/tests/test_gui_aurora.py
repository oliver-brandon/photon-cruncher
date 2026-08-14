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
        self.assertNotRegex(html, r"Aurora v\d")
        self.assertIn("brandSub", html)
        self.assertNotIn("Shared backend", html)
        self.assertNotIn('class="safety"', html)
        self.assertIn("nav-item", html)
        self.assertIn("page-align", html)
        self.assertIn("openSessionBtn", html)
        self.assertIn('id="matFileInput"', html)
        self.assertIn('id="tdtFolderInput"', html)
        self.assertIn('id="batchMatFileInput"', html)
        self.assertIn('id="batchFolderInput"', html)
        self.assertIn('id="batchTankInput"', html)
        self.assertIn('id="presetFileInput"', html)
        self.assertIn('id="exportDir"', html)
        self.assertIn('id="chooseExportDir"', html)
        self.assertIn('id="smoothFactor"', html)
        self.assertIn('id="useIsosbestic"', html)
        self.assertIn('id="polynomialDegree"', html)
        self.assertIn('id="trialUseIsosbestic"', html)
        self.assertIn('id="trialPolynomialDegree"', html)
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
        self.assertIn('id="alignPreset"', html)
        self.assertIn('id="trialPreset"', html)
        self.assertIn('id="alignPresetImport"', html)
        self.assertIn('id="trialPresetExport"', html)
        self.assertIn('id="trialCalloutText"', html)
        self.assertIn('id="batchResults"', html)
        self.assertIn('id="alignExportCsv"', html)
        self.assertIn('id="alignExportFig"', html)
        self.assertIn('id="alignRunStatus"', html)
        self.assertIn('class="align-action-bar"', html)
        self.assertIn('id="alignHeatScaleMode"', html)
        self.assertIn('id="qcKept"', html)
        self.assertIn('id="trialHeatScaleMode"', html)
        self.assertIn('id="batchConfigSummary"', html)
        self.assertIn('id="batchEditConfig"', html)
        self.assertIn('id="dataContinueAlign"', html)
        self.assertIn('role="status" aria-live="polite"', html)
        self.assertIn('role="img" aria-label="Event-aligned mean response plot"', html)
        self.assertNotIn('id="alignPulse"', html)
        self.assertLess(html.index('id="alignApply"'), html.index('class="split align-layout"'))
        self.assertNotIn("fonts.googleapis.com", html)
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
        self.assertIn("/api/batch-jobs", js)
        self.assertIn("/api/plot-matrix", js)
        self.assertIn("/api/inspect-paths", js)
        self.assertIn("/api/upload?", js)
        self.assertIn("uploadBrowserFiles", js)
        self.assertIn("webkitRelativePath", js)
        self.assertNotIn("Browser mode cannot read local paths", js)
        self.assertNotIn("Batch source dialogs require the desktop app", js)
        self.assertIn("batchEpocSelections", js)
        self.assertIn("appendBatchOutcomes(result)", js)
        self.assertIn("failed ${errors.length}", js)
        self.assertIn("batchEpocs", js)
        self.assertIn("runTrialAnalyze", js)
        self.assertIn("markAlignDirty", js)
        self.assertIn("setAlignRunState", js)
        self.assertIn("captureAppliedConfiguration", js)
        self.assertIn("renderBatchConfiguration", js)
        self.assertIn("setupHeatScaleControls", js)
        self.assertNotIn("scheduleAlignAnalyze", js)
        self.assertIn("scheduleTrialAnalyze", js)
        self.assertIn("alignRequestSequence", js)
        self.assertIn("trialRequestSequence", js)
        self.assertIn("AbortController", js)
        self.assertIn("compact: true", js)
        self.assertIn("trialSettingsPayload", js)
        self.assertIn("analysisChannels", js)
        self.assertIn("savedProcessingSettings", js)
        self.assertIn("saveProcessingSettings", js)
        self.assertIn("aurora.analysisPresets", js)
        self.assertIn("saveAnalysisPresetFile", js)
        self.assertIn("use_isosbestic", js)
        self.assertIn("polynomial_degree", js)
        self.assertIn("syncIsosbesticControls", js)
        self.assertGreaterEqual(js.count("channels: trialExportChannels()"), 2)
        self.assertNotIn("meanSemRows", js)

    def test_import_rows_are_safe_and_isolated_from_trial_controls(self) -> None:
        js = (STATIC_DIR / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIn('row.className = "import-row"', js)
        self.assertIn("label.textContent = sourceLabel(source);", js)
        self.assertIn("sourceCell.textContent = sourceLabel(source);", js)
        self.assertIn('sourceCell.title = source.path || "";', js)
        self.assertIn("chip.textContent = channel;", js)
        self.assertIn("chip.textContent = epoc.label;", js)
        self.assertIn("labelText.textContent = label || \"trial\";", js)
        self.assertIn("result.trial_times", js)
        self.assertIn("trialTime.textContent", js)
        self.assertIn("checkbox.checked = checked;", js)
        self.assertIn("function syncSessionIsosbesticAvailability(session)", js)
        self.assertIn("details.every((detail) => !detail.iso_stream)", js)
        self.assertIn("toggle.disabled = fullySignalOnly;", js)
        self.assertIn("settings.use_isosbestic = false;", js)
        self.assertNotIn('<td title="${source.path}">', js)
        self.assertNotIn("row.innerHTML", js)
        self.assertNotIn("`${c}</span>`", js)
        self.assertNotIn("`${e}</span>`", js)
        self.assertEqual(js.count('document.querySelectorAll("#trialStream .trial-row")'), 4)
        self.assertNotIn('document.querySelectorAll(".trial-row")', js)

    def test_trial_and_plot_parity_controls_are_wired(self) -> None:
        js = (STATIC_DIR / "js" / "app.js").read_text(encoding="utf-8")
        plots = (STATIC_DIR / "js" / "plots.js").read_text(encoding="utf-8")
        shell = (STATIC_DIR.parent / "shell.py").read_text(encoding="utf-8")

        self.assertIn('fillSelect($("alignEpoc"), epocNames', js)
        self.assertIn('fillSelect($("trialEpoc"), trialEpocs', js)
        self.assertIn("state.trialFilteredResultsByChannel = {};", js)
        self.assertGreaterEqual(js.count("trialNumbers: result.trial_numbers || []"), 2)
        self.assertIn("const outputDir = await chooseExportDestination();", js)
        self.assertIn("appendBatchOutcomes", js)
        self.assertIn('$("batchResults")', js)
        self.assertIn('ctx.fillText("Z-score"', plots)
        self.assertIn('ctx.fillText("Trial"', plots)
        self.assertIn("ticksIncludingZero", plots)
        self.assertIn("yb.min = Math.min(yb.min, 0)", plots)
        self.assertIn("Zero-centered blue-dark-red scale", plots)
        self.assertIn("[20, 27, 42]", plots)
        self.assertIn('ctx.strokeStyle = "rgba(3,7,15,0.92)"', plots)
        self.assertIn("ctx.lineTo(plot.l + plot.w, zy)", plots)
        self.assertIn('ctx.fillText("0 z"', plots)
        self.assertIn('mode: opts.scaleMode === "locked" ? "locked" : "auto"', plots)
        self.assertIn("Math.round(raw)", plots)
        self.assertIn('(\"Trial Explorer\", \"trials\")', shell)
        self.assertIn('(\"Batch Export\", \"batch\")', shell)

    def test_starfield_animation_avoids_animated_filters(self) -> None:
        css = (STATIC_DIR / "css" / "aurora.css").read_text(encoding="utf-8")
        near_keyframes = css.split("@keyframes star-twinkle-near", 1)[1].split(
            "@keyframes dust-drift", 1
        )[0]
        self.assertNotIn("filter:", near_keyframes)
        self.assertIn("from { opacity: 0.7; }", near_keyframes)
        self.assertIn("to { opacity: 1; }", near_keyframes)

    def test_select_controls_are_contained(self) -> None:
        css = (STATIC_DIR / "css" / "aurora.css").read_text(encoding="utf-8")
        self.assertIn("max-width: 100%", css)
        self.assertIn(".plot-tools select", css)
        self.assertIn("text-overflow: ellipsis", css)

    def test_supported_minimum_width_keeps_navigation_and_plot_layout(self) -> None:
        css = (STATIC_DIR / "css" / "aurora.css").read_text(encoding="utf-8")
        html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        self.assertIn('class="mobile-nav"', html)
        responsive = css.split("@media (max-width: 1180px)", 1)[1].split(
            "@media (min-width: 1181px)", 1
        )[0]
        self.assertIn(".mobile-nav", responsive)
        self.assertNotIn(".plot-grid, .stat-grid", responsive)
        self.assertIn("@media (max-width: 900px)", css)
        self.assertIn(".align-layout .align-plot-card", css)
        self.assertNotIn("max-height: calc(100vh - 180px)", css)

    def test_plot_panels_share_height_and_desktop_rail_stays_put(self) -> None:
        css = (STATIC_DIR / "css" / "aurora.css").read_text(encoding="utf-8")
        plot_canvas = css.split(".plot-grid canvas {", 1)[1].split("}", 1)[0]
        self.assertIn("height: clamp(280px, 28vw, 340px)", plot_canvas)
        self.assertNotIn("height: auto", plot_canvas)
        rail = css.split(".rail {", 1)[1].split("}", 1)[0]
        self.assertIn("position: fixed", rail)
        self.assertIn("inset: 0 auto 0 0", rail)
        self.assertIn("z-index: 6", rail)
        self.assertIn("width: 232px", rail)
        self.assertIn("height: 100vh", rail)
        self.assertIn(".main { grid-column: 1; }", css)

    def test_analysis_changes_are_explicit_and_batch_configuration_is_visible(self) -> None:
        js = (STATIC_DIR / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIn('markAlignDirty("Processing changes not applied")', js)
        self.assertIn('state.alignRunState === "current"', js)
        self.assertIn("!!state.appliedConfiguration", js)
        self.assertIn("processingSummary(state.appliedConfiguration)", js)
        self.assertIn("apply the analysis configuration in Align before batch export", js)

    def test_align_apply_action_stays_accessible_while_settings_scroll(self) -> None:
        css = (STATIC_DIR / "css" / "aurora.css").read_text(encoding="utf-8")
        action_bar = css.split(".align-action-bar {", 1)[1].split("}", 1)[0]
        self.assertIn("position: sticky", action_bar)
        self.assertIn("top: 67px", action_bar)
        self.assertIn(".align-action-bar { top: 124px; }", css)

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
