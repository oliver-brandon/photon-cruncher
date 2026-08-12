# Photon Cruncher

Python 3.11+ desktop app for MATLAB-faithful fiber photometry analysis. On the
`dev` branch the desktop surface is **Photon Cruncher Aurora** (hybrid
Qt WebEngine UI + shared analysis service). The pipeline mirrors lab MATLAB
preprocessing, supports MAT exports and raw TDT blocks, and exports CSV/figures.

> **Release status:** the newest public lab release is
> [v1.1.4](https://github.com/oliver-brandon/photon-cruncher/releases/tag/v1.1.4)
> from `main`. Aurora is implemented on `dev` but has not yet been tagged
> or published as a stable GitHub release. Dev-only Velopack prereleases use
> separate Aurora channels and do not update the v1 app. See [Project Status](docs/project-status.md)
> for the verified handoff and release checklist.

## Dev Branch (Aurora)

* Desktop GUI: **Aurora only** (`photon-cruncher` / `python -m photon_cruncher.aurora_main`)
* Version source: `photon_cruncher/version.py`
* Current version: `photon-cruncher-cli --version`
* The UI label and bundle names are derived automatically from that version
* Automatic updates: Velopack prereleases on isolated Windows/macOS dev channels
* Shared analysis facade: `photon_cruncher.service`
* Live sessions only (MAT/TDT open → analyze → export)

```bash
.build-venv/bin/python -m photon_cruncher.aurora_main
# or
photon-cruncher
```

## Downloads And Release Status

Most users should use GitHub Releases. No Python install is required. The
currently available v1.1.4 assets are `Photon-Cruncher-v1.1.4-Windows.zip` and
`Photon-Cruncher-v1.1.4-macOS.zip`.

Aurora v2 dev installers appear as GitHub **prereleases** only after the
`Publish Aurora dev updates` workflow succeeds. They are intentionally separate
from the stable v1.1.4 downloads. Developers can also run Aurora from source,
but source launches are not managed by the automatic updater.

### Windows

1. Open **Releases** on the GitHub repo.
2. Open the Aurora dev prerelease and download
   `Photon-Cruncher-Aurora-v<version>-Windows.exe`.
3. Double-click the installer and follow its prompts.
4. Launch **Photon Cruncher Aurora** from the shortcut it creates.

If Windows SmartScreen warns about an unknown publisher, choose **More info** →
**Run anyway** for builds you trust from the lab GitHub release page.

### macOS

1. Open **Releases** on the GitHub repo.
2. Open the Aurora dev prerelease and download
   `Photon-Cruncher-Aurora-v<version>-macOS.pkg`.
3. Open the installer and choose **Applications** or your user Applications folder.
4. Launch **Photon Cruncher Aurora**.

The Aurora dev `.pkg` is required to be Developer ID signed and notarized by
the release workflow. Do not distribute a macOS workflow artifact if its
signing/notarization job failed.

## Build from source

```bash
# macOS
scripts/build_macos_app.sh
# → dist/Photon Cruncher Aurora v<version>.app
# → dist/Photon-Cruncher-Aurora-v<version>-macOS.zip

# Windows (PowerShell)
.\scripts\build_windows_app.ps1
# → dist/Photon Cruncher Aurora v<version>/
# → dist/Photon-Cruncher-Aurora-v<version>-Windows.zip
```

GitHub Actions (`.github/workflows/build-desktop-apps.yml`) builds the same Aurora
PyInstaller bundles, then packages and publishes them with Velopack. Installed
apps and shortcuts use the friendly name **Photon Cruncher Aurora**; the internal
dev package ID and platform-specific channels remain stable across updates. For
local Velopack packaging, use `scripts/package_windows_update.ps1` or
`scripts/package_macos_update.sh`; the macOS command requires Developer ID and
notary credentials.

## Update the App

Aurora dev installations check their own OS/architecture-specific prerelease
channel after launch and every six hours while open. When a newer version is
available, a small **Update x.y.z** indicator appears in the lower-right corner.
Click it to review the new version and release notes, then choose **Install and
restart** or **Later**. You can also choose **Help → Check for Updates…** at any
time. An unavailable network is nonfatal and does not interrupt analysis.

Recordings and exports live outside the app bundle, and saved processing
settings remain in the user's app settings. Updates never consume stable or
cross-platform packages: Windows x64 and macOS arm64 dev builds each have their
own feed.

### Update on Windows

1. Click the update indicator or choose **Help → Check for Updates…**.
2. Review the release notes and choose **Install and restart**.
3. If a download fails, leave the app open and choose **Try again** later. The
   current installation is not changed by an incomplete download.

If the updater itself cannot be used, download the newest versioned Windows
`.exe` installer from the Aurora dev prerelease and run it again. Windows builds
are not yet Authenticode signed, so SmartScreen may still appear.

### Update on macOS

1. Click the update indicator or choose **Help → Check for Updates…**.
2. Review the release notes and choose **Install and restart**.
3. macOS may request an administrator password when updating an app in the
   system Applications folder. Choose **Later** if you do not want to restart.

If the updater itself cannot be used, run the newest versioned macOS `.pkg`
installer from the Aurora dev prerelease. A correctly published build is Developer ID signed and
notarized, so it should identify the developer instead of showing an
unverified-developer warning.

### Publishing an Aurora dev update

1. Change only `__version__` in `photon_cruncher/version.py`.
2. Update the brief Markdown notes in `packaging/velopack/release-notes.md`.
3. Commit and push the change to `dev`.
4. Run **Actions → Publish Aurora dev updates → Run workflow** from `dev`, or
   push the matching `aurora-dev-v<version>` tag.
5. Confirm the prerelease contains a Windows installer, a signed macOS `.pkg`,
   full/delta `.nupkg` files, and both `releases.aurora-dev-*.json` feeds.

The macOS job requires these GitHub Actions secrets:

- `MACOS_DEVELOPER_ID_APPLICATION_P12_BASE64`
- `MACOS_DEVELOPER_ID_INSTALLER_P12_BASE64`
- `MACOS_CERTIFICATE_PASSWORD`
- `MACOS_KEYCHAIN_PASSWORD`
- `MACOS_DEVELOPER_ID_APPLICATION`
- `MACOS_DEVELOPER_ID_INSTALLER`
- `APPLE_ID`
- `APPLE_APP_PASSWORD`
- `APPLE_TEAM_ID`

The two identity secrets should contain the certificate names without the Team
ID suffix, such as `Developer ID Application: Your Name` and
`Developer ID Installer: Your Name`. The workflow validates, signs, notarizes,
and assesses the installer before publishing either platform.

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

## Aurora GUI (Developer Surface)

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
- Align exposes explicit channel controls, reactive processing updates, and separate CSV/figure exports
- Named analysis presets can be saved, imported, exported, and applied in Align or Trial Explorer; edited settings are marked as **Custom**
- Trial Explorer shows original trial numbers, onset times, classified outcomes, and selected-trial plots/exports
- Displayed plots include file, epoc, channel, labeled axes, and integer trial-aligned heatmap ticks
- Batch Export runs as a responsive background job with live progress, real cancellation between analysis steps, and detailed exported/skipped/failed results
- Result callouts report incomplete-trial loss, artifact removal, unstable baselines, extreme/non-finite z-scores, and signal-only processing
- Processing and export-folder settings persist between launches
- A lower-right update indicator shows the dev version and release notes
- **Help → Check for Updates…** runs an immediate manual update check
- **Help → Export Diagnostic Report…** saves app/runtime, cache, updater, and recent-error details without raw photometry samples

### Browser mode (optional)

```bash
.build-venv/bin/python -m photon_cruncher.aurora_main --browser
```

Default URL: `http://127.0.0.1:8766/`

Browser mode can import files directly from the browser: **Open MAT files**
uploads selected `.mat` files, while **Open TDT tanks** and the Batch Export
pickers upload a selected folder and preserve its relative layout. Uploaded
data is kept in a temporary server folder for the current session and removed
when the session is closed or the server exits.

API (same backend as lab/CLI):
- `GET /api/health`
- `POST /api/open` or `/api/inspect` with `{"path": "..."}`
- `POST /api/analyze` with `{"path": "...", "epoc": "Cue", "channels": ["A_465"]}`
- `POST /api/plot-matrix` returns the requested displayed channel as compact float32 data
- `POST /api/export` with path, epoc, output_dir, and export flags
- `POST /api/inspect-paths` with a list of batch source paths
- `POST /api/upload?upload_id=...&relative_path=...&final=0|1` with the raw file
  bytes; set `final=1` on the last file to receive discovered MAT/TDT paths
- `POST /api/batch-export` with source paths, epoc selections, channels, and export flags
- `POST /api/batch-jobs`, then `GET /api/batch-jobs/<id>` for responsive batch progress
- `POST /api/batch-jobs/<id>/cancel` to stop after the current analysis step
- `GET /api/diagnostics` for a data-free troubleshooting report

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
progress, and can be cancelled without waiting for every remaining file.

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
