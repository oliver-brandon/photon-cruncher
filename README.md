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

* The preprocessing pipeline follows the lab's MATLAB script exactly, including
  downsampling, regression, baseline logic, and smoothing.
* Export outputs include heatmap CSVs with the time vector in the first row,
  followed by per-trial z-score rows.
