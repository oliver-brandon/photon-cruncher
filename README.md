# Photon Cruncher

Python 3.11+ desktop app for MATLAB-faithful fiber photometry analysis. The
pipeline mirrors lab MATLAB preprocessing, supports single-file and batch
processing, and exports all plotted data as CSV.

## Setup

### Conda (Recommended)

```bash
conda create -n photometry-app python=3.11
conda activate photometry-app
pip install -e photon_cruncher
```

### venv

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e photon_cruncher
```

## Run

```bash
photon-cruncher
```

## Data Expectations

The app expects MATLAB `.mat` files with a top-level `data` struct produced by
TDTbin2mat, with streams/epocs schema described in the project prompt.

## Notes

* The preprocessing pipeline follows the MATLAB script exactly, including
  downsampling, regression, baseline logic, and smoothing.
* Export outputs include heatmap CSVs with the time vector in the first row,
  followed by per-trial z-score rows.
