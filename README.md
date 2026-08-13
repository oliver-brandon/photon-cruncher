# Photon Cruncher

Python 3.11+ desktop app for MATLAB-faithful fiber photometry analysis. The
pipeline mirrors lab MATLAB preprocessing, supports single-file and batch
processing, reads MATLAB exports or raw TDT block folders, lets users inspect
and export selected trials, and exports plotted data as CSV.

## Download for Lab Users

Most students should use the prebuilt app downloads from GitHub. They do not
need Python, Conda, Terminal, Automator, or the project source folder.

### Windows

1. Open the GitHub repository page.
2. Click **Releases** on the right side of the page.
3. Open the newest release.
4. Download the Windows installer, such as
   `Photon-Cruncher-v1.2.0-Windows.exe`.
5. Double-click the installer and follow its prompts.
6. Launch **Photon Cruncher** from the shortcut it creates.

If Windows SmartScreen warns that the app is from an unknown publisher, choose
**More info** and then **Run anyway** if you trust the downloaded file. This can
still happen because the Windows installer is not Authenticode signed with a
certificate.

### macOS

1. Open the GitHub repository page.
2. Click **Releases** on the right side of the page.
3. Open the newest release.
4. Download the macOS installer, such as
   `Photon-Cruncher-v1.2.0-macOS.pkg`.
5. Open the installer and follow its prompts.
6. Launch **Photon Cruncher** from Applications.

The release workflow requires the macOS app and installer to be Developer ID
signed and notarized. It fails instead of publishing an unsigned macOS build.

## Update the App

Installed v1.2.0 and newer apps check their own Windows or macOS stable channel
after launch and every six hours while open. When an update is available, an
**Update x.y.z** button appears in the lower-right corner. Click it to review
the release notes, then choose **Install and restart** or **Later**. You can
also choose **Help → Check for Updates…** at any time. A network failure does
not interrupt analysis.

The old v1.1.4 zip build is not managed by Velopack and cannot receive v1.2.0
automatically. Install v1.2.0 once using the new installer; later releases can
then update in place. Recordings and exports stay outside the app installation
and are not deleted by an update.

### Update on Windows

1. Click the update button or choose **Help → Check for Updates…**.
2. Review the release notes and choose **Install and restart**.
3. If a download fails, choose **Try again** later. The current installation is
   not changed by an incomplete download.

If the updater itself cannot be used, download the newest versioned Windows
`.exe` installer from the stable GitHub release and run it again.

### Update on macOS

1. Click the update button or choose **Help → Check for Updates…**.
2. Review the release notes and choose **Install and restart**.
3. macOS may request an administrator password when updating an app installed
   for all users. Choose **Later** if you do not want to restart.

If the updater itself cannot be used, run the newest versioned macOS `.pkg`
installer from the stable GitHub release.

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

## Building and Publishing Stable Updates

The existing platform build scripts still create local PyInstaller bundles and
zip files:

```bash
# macOS
scripts/build_macos_app.sh

# Windows PowerShell
.\scripts\build_windows_app.ps1
```

Source launches and these portable zip files are not managed by the automatic
updater. The `Publish stable desktop updates` GitHub Actions workflow packages
the bundles as Velopack installers and publishes separate `stable-win-x64` and
`stable-osx-arm64` feeds.

To publish a stable update:

1. Change only `__version__` in `photon_cruncher/version.py`.
2. Update `packaging/velopack/release-notes.md`.
3. Commit and push the change to `main`.
4. Run **Actions → Publish stable desktop updates → Run workflow** from `main`,
   or push the matching `v<version>` tag.
5. Confirm the release contains the readable Windows `.exe` installer, the
   signed macOS `.pkg`, full packages, both stable JSON feeds, and delta
   packages when a prior Velopack release exists.

The macOS job requires the Developer ID certificate, keychain, Apple ID, and
notarization secrets already used by the Aurora updater workflow. It validates,
signs, notarizes, and assesses the installer before either platform is
published. Windows packages are update-enabled but remain unsigned unless an
Authenticode certificate is added separately.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).
