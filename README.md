# Photon Cruncher

Python 3.11+ desktop app for MATLAB-faithful fiber photometry analysis. On the
`dev` branch the desktop surface is **Photon Cruncher Aurora** (hybrid
Qt WebEngine UI + shared analysis service). The pipeline mirrors lab MATLAB
preprocessing, supports MAT exports and raw TDT blocks, and exports CSV/figures.

## Dev branch (Aurora v2.0)

* Desktop GUI: **Aurora only** (`photon-cruncher` / `python -m photon_cruncher.aurora_main`)
* UI rail label: `Aurora v2.0` (window title has no version suffix)
* Package / CLI version: `2.0.0`
* Shared analysis facade: `photon_cruncher.service`
* Live sessions only (MAT/TDT open → analyze → export)

```bash
.build-venv/bin/python -m photon_cruncher.aurora_main
# or
photon-cruncher
```

## Download (prebuilt)

Most users should use GitHub Releases. No Python install required.

### Windows

1. Open **Releases** on the GitHub repo.
2. Download `Photon-Cruncher-Aurora-v2.0-Windows.zip`.
3. Extract the zip.
4. Open the `Photon Cruncher Aurora v2.0` folder.
5. Double-click `Photon Cruncher Aurora v2.0.exe`.

Keep the whole extracted folder together.

If Windows SmartScreen warns about an unknown publisher, choose **More info** →
**Run anyway** for builds you trust from the lab GitHub release page.

### macOS

1. Open **Releases** on the GitHub repo.
2. Download `Photon-Cruncher-Aurora-v2.0-macOS.zip`.
3. Expand the zip.
4. Drag `Photon Cruncher Aurora v2.0.app` to **Applications** (or anywhere).
5. Double-click the app.

If macOS blocks an unsigned build: Control-click → **Open** → **Open**, or use
**System Settings → Privacy & Security → Open Anyway**.

## Build from source

```bash
# macOS
scripts/build_macos_app.sh
# → dist/Photon Cruncher Aurora v2.0.app
# → dist/Photon-Cruncher-Aurora-v2.0-macOS.zip

# Windows (PowerShell)
.\scripts\build_windows_app.ps1
# → dist/Photon Cruncher Aurora v2.0/
# → dist/Photon-Cruncher-Aurora-v2.0-Windows.zip
```

GitHub Actions (`.github/workflows/build-desktop-apps.yml`) builds the same Aurora
bundles on `v*` tags or manual workflow dispatch.

## Update the App

Download the newest release zip and replace the previous Aurora app/folder.
Data files and exports live outside the app bundle.

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
  --epoc aRw_ \
  --channel A_465 \
  --export both \
  --figure-format png
```

```bash
photon-cruncher-cli validate-config analysis-config.json
photon-cruncher-cli analyze --config analysis-config.json
```

Packaged downloads include the CLI beside the desktop app. CLI output is JSON.

## Aurora GUI (developer v2 surface)

Codename **Aurora**. Separate from the lab PySide GUI. Live analysis only via
`photon_cruncher.service` (no synthetic demo feed).

### Native shell (default)

Opens a real desktop window (PySide6 + Qt WebEngine) wrapping the Aurora web UI:

```bash
.build-venv/bin/python -m photon_cruncher.aurora_main
# or: photon-cruncher-aurora
```

In the shell:
- **File → Open MAT / TDT** uses native dialogs
- Analysis runs through the local API → `photon_cruncher.service`
- Align / Trials / Export are wired to real results

### Browser mode (optional)

```bash
.build-venv/bin/python -m photon_cruncher.aurora_main --browser
```

Default URL: `http://127.0.0.1:8766/`

API (same backend as lab/CLI):
- `GET /api/health`
- `POST /api/open` or `/api/inspect` with `{"path": "..."}`
- `POST /api/analyze` with `{"path": "...", "epoc": "Cue", "channels": ["A_465"]}`
- `POST /api/export` with path, epoc, output_dir, and export flags

Architecture: `docs/architecture-aurora.md`.

## Trial Explorer



Use the **Trial Explorer** tab when you want to inspect or export only certain
trials from one file. Choose a file, choose an epoc or classified trial source,
set the processing window and smoothing, then click **Load Trials**. The trial
list can be checked or unchecked by hand, and the plot updates to show only the
selected trials.

For recordings with compatible behavior epocs, Photon Cruncher can add
in-memory classified trial sources in Trial Explorer. These sources do not
change the original `.mat` or TDT data. They label lever-aligned trials as
correct rewarded, correct not rewarded, incorrect rewarded, or incorrect not
rewarded so you can quickly select trials by outcome type. Selected trial CSV
exports include those trial labels in the row names.

## Notes

* The preprocessing pipeline follows the lab's MATLAB script exactly, including
  downsampling, regression, baseline logic, and smoothing.
* Export outputs include heatmap CSVs with the time vector in the first row,
  followed by per-trial z-score rows.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).
