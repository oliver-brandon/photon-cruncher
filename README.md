<<<<<<< ours
# Photon Cruncher
=======
# Photometry App
>>>>>>> theirs

Python 3.11+ desktop app for MATLAB-faithful fiber photometry analysis. The
pipeline mirrors lab MATLAB preprocessing, supports single-file and batch
processing, and exports all plotted data as CSV.

## Setup

<<<<<<< ours
### Conda (Recommended)

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
=======
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e photometry_app
>>>>>>> theirs
```

## Run

```bash
<<<<<<< ours
photon-cruncher
```

## macOS Dock Icon (Optional)

To reliably set the Dock icon at runtime, install the optional macOS extra:

```bash
pip install -e "photon_cruncher[macos]"
=======
photometry-app
>>>>>>> theirs
```

## Data Expectations

The app expects MATLAB `.mat` files with a top-level `data` struct produced by
TDTbin2mat, with streams/epocs schema described in the project prompt.

## Notes

* The preprocessing pipeline follows the MATLAB script exactly, including
  downsampling, regression, baseline logic, and smoothing.
<<<<<<< ours
* Export outputs include heatmap CSVs with the time vector in the first row,
  followed by per-trial z-score rows.
=======
* Export outputs include heatmap, time vector, PSTH mean/SEM, and settings JSON
  per session + epoc + channel.
>>>>>>> theirs
