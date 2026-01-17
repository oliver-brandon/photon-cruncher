# Photometry App

Python 3.11+ desktop app for MATLAB-faithful fiber photometry analysis. The
pipeline mirrors lab MATLAB preprocessing, supports single-file and batch
processing, and exports all plotted data as CSV.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e photometry_app
```

## Run

```bash
photometry-app
```

## Data Expectations

The app expects MATLAB `.mat` files with a top-level `data` struct produced by
TDTbin2mat, with streams/epocs schema described in the project prompt.

## Notes

* The preprocessing pipeline follows the MATLAB script exactly, including
  downsampling, regression, baseline logic, and smoothing.
* Export outputs include heatmap, time vector, PSTH mean/SEM, and settings JSON
  per session + epoc + channel.
