# Photon Cruncher

Python 3.11+ desktop app for MATLAB-faithful fiber photometry analysis. The
pipeline mirrors lab MATLAB preprocessing, supports single-file and batch
processing, reads MATLAB exports or raw TDT block folders, and exports plotted
data as CSV.

## Download for Lab Users

Most students should use the prebuilt app downloads from GitHub. They do not
need Python, Conda, Terminal, Automator, or the project source folder.

### Windows

1. Open the GitHub repository page.
2. Click **Releases** on the right side of the page.
3. Open the newest release.
4. Download `Photon-Cruncher-Windows.zip`.
5. Right-click the zip file and choose **Extract All...**.
6. Open the extracted `Photon Cruncher` folder.
7. Double-click `Photon Cruncher.exe`.

Keep the extracted `Photon Cruncher` folder together. The `.exe` depends on the
files beside it in that folder, but the whole folder can be moved anywhere on
the computer, including the Desktop, Downloads, Documents, or a lab software
folder.

If Windows SmartScreen warns that the app is from an unknown publisher, choose
**More info** and then **Run anyway** if you trust the downloaded file. This can
happen because the app is not currently signed with a Windows code-signing
certificate.

### macOS

1. Open the GitHub repository page.
2. Click **Releases** on the right side of the page.
3. Open the newest release.
4. Download `Photon-Cruncher-macOS.zip`.
5. Double-click the zip file to expand it.
6. Drag `Photon Cruncher.app` to **Applications** or any other folder.
7. Double-click `Photon Cruncher.app`.

The macOS app bundle contains its own Python runtime, dependencies, and icons,
so it can be moved without depending on the original project folder path.

## Build Release Downloads

Maintainers can create downloadable app zips with GitHub Actions.

### Automatic Release Build

Create and push a version tag:

```bash
git tag v0.1.0
git push origin v0.1.0
```

GitHub Actions will build:

* `Photon-Cruncher-Windows.zip`
* `Photon-Cruncher-macOS.zip`

Those files are attached to the GitHub release for that tag.

### Manual Build From GitHub

1. Open the repository on GitHub.
2. Go to **Actions**.
3. Choose **Build desktop apps**.
4. Click **Run workflow**.
5. Wait for the Windows and macOS jobs to finish.
6. Download the build artifacts from the workflow run.

Manual workflow artifacts are useful for testing. Tagged releases are better for
students because the downloads are shown on the repository's **Releases** page.

## Build Locally

These steps are for maintainers and developers.

### macOS App

Run this on macOS:

```bash
scripts/build_macos_app.sh
```

The app is written to:

```text
dist/Photon Cruncher.app
```

You can move `Photon Cruncher.app` anywhere on the same Mac, including
`/Applications`.

### Windows App

Run this in PowerShell on Windows:

```powershell
.\scripts\build_windows_app.ps1
```

The build creates:

```text
dist\Photon Cruncher\Photon Cruncher.exe
dist\Photon-Cruncher-Windows.zip
```

Share the zip file with Windows users. After unzipping, users can move the
entire `Photon Cruncher` folder anywhere and launch the app by double-clicking
`Photon Cruncher.exe`.

## Developer Setup

### Conda

```bash
conda create -n photon-cruncher python=3.11
conda activate photon-cruncher
pip install -e photon_cruncher
```

### venv

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e photon_cruncher
```

On Windows PowerShell, activate the venv with:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -e photon_cruncher
```

## Run From Source

```bash
photon-cruncher
```

## Data Expectations

The app accepts either:

* MATLAB `.mat` files with a top-level `data` struct produced by TDTbin2mat.
* TDT block folders that can be read by `tdt.read_block`.

Streams should include the expected photometry stores such as `x405A`, `x465A`,
`x560A`, `x405C`, `x465C`, or `x560C`. Epocs are read from the TDT `epocs`
collection or the equivalent MATLAB export schema.

For batch processing, use **Add Files** for `.mat` files, **Add TDT Tank** for a
TDT tank folder containing one or more block folders, or **Add Folder** for a
mixed folder containing `.mat` files and TDT blocks.

## Notes

* The preprocessing pipeline follows the MATLAB script exactly, including
  downsampling, regression, baseline logic, and smoothing.
* Export outputs include heatmap CSVs with the time vector in the first row,
  followed by per-trial z-score rows.
