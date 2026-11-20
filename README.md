# Photon Cruncher Aurora

Photon Cruncher Aurora is a desktop application for fiber photometry analysis.
It reads MATLAB exports and raw TDT blocks, aligns signals to events, lets you
inspect trials, and exports plots and data with analysis provenance.

## Availability

This is the Aurora interface for Photon Cruncher's stable channel. Download the
[latest stable release](https://github.com/oliver-brandon/photon-cruncher/releases/latest)
for the lab. Aurora dev prereleases use a separate update channel.

## Scientific comparisons

Version 1.2.1 corrected the 405 control regression. It predicts the signal
from the 405 control before subtraction; older stable versions fit the inverse
relationship. This can change z-scores and figures. Process comparison datasets
with the same version and settings, preserve older exports, and use a fresh
output folder when reprocessing. Existing exports without provenance sidecars
cannot be identified by the overwrite guard. See
[maintenance validation](docs/maintenance-1.2.1.md).

Every result export includes an `_analysis.json` sidecar with source, settings,
version, trial selection and quality findings. Inspect QC findings before drawing
conclusions.

## Install and update

**If your stable app has Help → Check for Updates…** (installed v1.2.0 or later),
choose it, then select **Install and restart** when Aurora is offered.

**If you don’t see Check for Updates…**, or you launch Photon Cruncher from an
extracted ZIP such as v1.1.4, use the installer once to get automatic updates:

1. Quit Photon Cruncher and open the [latest stable release](https://github.com/oliver-brandon/photon-cruncher/releases/latest).
2. Under **Assets**, download the file ending in **\`-Windows.exe\`** for Windows x64
   or **\`-macOS.pkg\`** for an Apple Silicon Mac. Run it and follow the installer prompts.
3. Open **Photon Cruncher** from the Windows Start menu or the Mac Applications
   folder. The window title is **Photon Cruncher Aurora**. Use **Help → Check for Updates…**
   to confirm you opened the installed copy. Replace any shortcut that still opens the old ZIP copy.

The installer does not require moving your recordings or exports. If you are
upgrading from before v1.2.1, read [Scientific comparisons](#scientific-comparisons)
before comparing new results with older exports.

Windows installers are not Authenticode signed and SmartScreen may show a warning.
macOS stable installers are Developer ID signed and notarized.

## Developer source launch

Use Python 3.11 or newer and create an isolated environment:

```bash
python3 -m venv .build-venv
.build-venv/bin/python -m pip install -e ./photon_cruncher
./dev-aurora
```

On Windows, create the environment with `py -3.11 -m venv .build-venv`,
install using `.build-venv\Scripts\python.exe -m pip install -e ./photon_cruncher`,
and launch with `.\dev-aurora.ps1`. Source launches do not receive in-place
updates. Ubuntu source runs are for development.

## Building and releasing

Build platform bundles with `scripts/build_macos_app.sh` or
`scripts/build_windows_app.ps1`. Stable releases use a `v<version>` tag from
`main`, package ID `com.photoncruncher.app`, and OS-specific `stable-*`
channels. Verify regression jobs for both platforms, signing, notarization,
installers, full/delta packages and feeds before announcing a release.
See [project status](docs/project-status.md) for the current verification
boundary.

## Data Expectations

The app accepts either:

* MATLAB `.mat` files with a top-level `data` struct produced by TDTbin2mat.
* TDT block folders that can be read by `tdt.read_block`.

Streams should include the expected photometry stores such as `x405A`, `x465A`,
`x560A`, `x405C`, `x465C`, or `x560C`. Epocs are read from the TDT `epocs`
collection or the equivalent MATLAB export schema.

## Command-Line Access Point

`photon-cruncher-cli` supports scripted analysis and agentic workflows.

```bash
photon-cruncher-cli inspect local-test-data --json
```

```bash
photon-cruncher-cli analyze local-test-data \
  --output-dir exports/agentic-run \
  --all-epocs \
  --epoc-policy prefer-left \
  --channel A_465 \
  --channel-smooth A_465=10 \
  --use-isosbestic \
  --polynomial-degree 1 \
  --export both \
  --figure-format png
```

The CLI uses the paired 405 isosbestic fit by default with polynomial degree
`1`. The fit models the selected signal as a polynomial function of its paired
405 control, then subtracts that fitted control contribution. Use
`--polynomial-degree N` to change the fit degree, or `--no-isosbestic` to skip
the fit and process the selected signal channel directly, including recordings
that do not contain a 405 stream. Reusable JSON configs accept the corresponding
processing fields: `"use_isosbestic": true` and `"polynomial_degree": 1`.

Use `--channel-smooth CHANNEL=FACTOR` for channel-specific smoothing. Use
`--all-epocs` to analyze every available epoc, optionally with
`--epoc-policy prefer-left` (A/1_) or `--epoc-policy prefer-right` (C/2_).
The symmetric `--plot-smoothed` / `--plot-raw`,
`--baseline-correction` / `--no-baseline-correction`, artifact reset, and
`--default-smoothing` flags can override either state from a JSON config.

```bash
photon-cruncher-cli validate-config analysis-config.json
photon-cruncher-cli analyze --config analysis-config.json
```

Packaged downloads include the CLI beside the desktop app. CLI output is JSON.

Analysis summaries distinguish `skipped` selections (such as no matching trials)
from `errors` with a load, analysis, or export stage. Exit codes are `0` when at
least one analysis succeeds, `1` for no matching analyses, `2` for invalid
arguments/configuration, and `3` when runtime failures leave no successful
analyses. Inspect `errors` even after exit code `0` to catch partial failures.

Batch exports from both the GUI and CLI give same-named recordings separate
folders with a short source identifier, including when flat output is requested.
An existing analysis manifest belonging to another source blocks replacement;
choose a fresh destination in that case. Rerunning the same source in its own
destination still replaces its previous export.

Baseline windows must contain at least two samples after downsampling and inside
the extracted TRANGE. Invalid windows are reported before files are exported.

## Aurora Desktop GUI

Codename **Aurora**. Live analysis only via `photon_cruncher.service` (no
synthetic demo feed). Aurora is supported as a desktop application, not as a
website or normal-browser application.

### Desktop app

Opens a real desktop window (PySide6 + Qt WebEngine) wrapping the Aurora web UI:

```bash
# macOS / Linux
./dev-aurora

# Windows PowerShell
.\dev-aurora.ps1
```

Both launchers run the canonical `photon_cruncher.aurora_main` entry point
directly from the working tree using `.build-venv`. Use them for the fast local
edit-and-test loop; release packaging remains a separate process.

In the shell:
- **File → Open MAT / TDT** uses native dialogs
- **Data → Clear imports** (or **File → Clear All Imports**) removes every loaded MAT/TDT session and resets analysis and batch results without deleting exports, presets, or saved settings
- Analysis runs through the local API → `photon_cruncher.service`
- Align exposes explicit channel controls, reactive processing updates, and separate CSV/figure exports
- Named analysis presets can be saved, imported, exported, and applied in Align or Trial Explorer; edited settings are marked as **Custom**
- Trial Explorer shows original trial numbers, onset times, classified outcomes, and selected-trial plots/exports
- Displayed plots include file, epoc, channel, labeled axes, and integer trial-aligned heatmap ticks
- Batch Export runs as a responsive background job with live progress, real cancellation between analysis steps, and detailed exported/skipped/failed results
- Result callouts report incomplete-trial loss, artifact removal, unstable baselines, extreme/non-finite z-scores, and signal-only processing
- Processing and export-folder settings persist between launches
- A lower-right update indicator shows an available update and release notes
- **Help → Check for Updates…** runs an immediate manual update check
- **Help → Export Diagnostic Report…** saves app/runtime, cache, updater, and recent-error details without raw photometry samples

Architecture: `docs/architecture-aurora.md`.
Current performance measurements: `docs/backend-performance.md`.

Current branch/release state, verification evidence, known risks, and the next
recommended work are maintained in `docs/project-status.md`.

## Trial Explorer



Use the **Trial Explorer** tab when you want to inspect or export only certain
trials from one file. Choose a file, choose an epoc or classified trial source,
set the processing window and smoothing, then click **Load Trials**. The trial
list can be checked or unchecked by hand, and the plot updates to show only the
selected trials.

Use the **Analysis preset** controls to save a named processing recipe, exchange
it as JSON, or apply the same recipe in Align and Trial Explorer. **Default**
restores the app defaults; **Custom** means at least one visible setting has
changed since the selected preset was applied.

## Batch Export

Use **Add files**, **Add folder**, or **Add TDT tank** to build a multi-recording
batch. Select the epocs and channels to export, then choose exact suffixes or
prefer the `A / 1_` or `C / 2_` member when paired epocs are available. Each
recording is written to its own output subfolder. CSV is enabled by default;
figures can be added in PNG, PDF, or TIFF format. The batch runs in the
background, loads each recording once for all selected epocs, reports live
progress, and can be cancelled without waiting for every remaining file. After
the export finishes, return to **Data** and choose **Clear imports** to remove
the completed batch before importing a fresh one.

For recordings with compatible behavior epocs, Photon Cruncher can add
in-memory classified trial sources in Trial Explorer. These sources do not
change the original `.mat` or TDT data. They label lever-aligned trials as
correct rewarded, correct not rewarded, incorrect rewarded, or incorrect not
rewarded so you can quickly select trials by outcome type. Selected trial CSV
exports include those trial labels in the row names.

## Notes

* The preprocessing pipeline preserves the lab workflow's analysis windows,
  downsampling, baseline logic, and smoothing. Isosbestic regression explicitly
  fits signal from the paired 405 control before subtraction.
* Export outputs include heatmap CSVs with the time vector in the first row,
  followed by per-trial z-score rows.
* Every GUI, CLI, and batch result also includes an `_analysis.json` provenance
  sidecar with the Photon Cruncher version, source, epoc/channel, processing
  settings, trial labels/onsets, exclusions, QC findings, and written files.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).
