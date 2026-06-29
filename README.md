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
4. Download the newest Windows zip, such as
   `Photon-Cruncher-Dev-v1.1.3-Windows.zip`.
5. Right-click the zip file and choose **Extract All...**.
6. Open the extracted `Photon Cruncher Dev v1.1.3` folder.
7. Double-click `Photon Cruncher Dev v1.1.3.exe`.

Keep the extracted `Photon Cruncher Dev v1.1.3` folder together. The `.exe`
depends on the files beside it in that folder, but the whole folder can be
moved anywhere on the computer, including the Desktop, Downloads, Documents, or
a lab software folder.

If Windows SmartScreen warns that the app is from an unknown publisher, choose
**More info** and then **Run anyway** if you trust the downloaded file. This can
happen because the app is not currently signed with a Windows code-signing
certificate.

### macOS

1. Open the GitHub repository page.
2. Click **Releases** on the right side of the page.
3. Open the newest release.
4. Download the newest macOS zip, such as
   `Photon-Cruncher-Dev-v1.1.3-macOS.zip`.
5. Double-click the zip file to expand it.
6. Drag `Photon Cruncher Dev v1.1.3.app` to **Applications** or any other folder.
7. Double-click `Photon Cruncher Dev v1.1.3.app`.

The macOS app bundle contains its own Python runtime, dependencies, and icons,
so it can be moved without depending on the original project folder path.

If macOS says the app cannot be opened because Apple cannot verify it, this is
expected for an unsigned lab build. Open it once using this path:

1. Control-click or right-click `Photon Cruncher Dev v1.1.3.app`.
2. Choose **Open**.
3. In the warning dialog, choose **Open** again.

If macOS blocks the app without showing an **Open** button, go to **System
Settings** > **Privacy & Security**, scroll to the security message about
`Photon Cruncher Dev v1.1.3.app`, and choose **Open Anyway**. Only do this for
app files downloaded from the lab's GitHub release page.

## Update the App

The app does not update itself automatically. When a new version is posted on
GitHub, download the new zip and replace the old app copy. Your data files and
exported results are not stored inside the app, so replacing the app should not
delete your recordings or exports.

### Update on Windows

1. Quit `Photon Cruncher` if it is open.
2. Open the GitHub repository page.
3. Click **Releases** on the right side of the page.
4. Open the newest release.
5. Download the newest Windows zip, such as
   `Photon-Cruncher-Dev-v1.1.3-Windows.zip`.
6. Right-click the zip file and choose **Extract All...**.
7. Open the extracted folder.
8. You should see a folder with the version in its name, such as
   `Photon Cruncher Dev v1.1.3`.
9. Go to the place where your old `Photon Cruncher` folder lives.
10. Rename the old folder to `Photon Cruncher old`.
11. Move the new versioned `Photon Cruncher Dev v1.1.3` folder into that same
    place.
12. Double-click `Photon Cruncher Dev v1.1.3.exe` inside the new folder.
13. After the new version opens correctly, delete `Photon Cruncher old`.

Keep the whole `Photon Cruncher` folder together. Do not move only
`Photon Cruncher Dev v1.1.3.exe` by itself, because the `.exe` needs the files
beside it.

If Windows says files with the same name already exist, choose **Replace** only
if you are replacing the entire old `Photon Cruncher` folder with the newly
extracted one. The rename-first method above is safer because it keeps the old
copy available until you confirm the new one opens.

### Update on macOS

1. Quit `Photon Cruncher` if it is open.
2. Open the GitHub repository page.
3. Click **Releases** on the right side of the page.
4. Open the newest release.
5. Download the newest macOS zip, such as
   `Photon-Cruncher-Dev-v1.1.3-macOS.zip`.
6. Double-click the zip file to expand it.
7. You should see a versioned app, such as `Photon Cruncher Dev v1.1.3.app`.
8. Go to the place where your old `Photon Cruncher.app` lives, usually
   **Applications**.
9. Rename the old app to `Photon Cruncher old.app`.
10. Drag the new `Photon Cruncher Dev v1.1.3.app` into that same place.
11. Double-click the new `Photon Cruncher Dev v1.1.3.app`.
12. After the new version opens correctly, delete `Photon Cruncher old.app`.

If macOS asks whether to replace the existing app, you can choose **Replace**,
but the rename-first method above is safer because it keeps the old copy
available until you confirm the new one opens.

If macOS shows the Apple verification warning again after an update, repeat the
same first-open steps: Control-click or right-click the new versioned app,
choose **Open**, then choose **Open** again.

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

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).
