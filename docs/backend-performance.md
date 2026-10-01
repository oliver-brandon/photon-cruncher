# Aurora Backend Performance

Last measured: 2026-10-01 (local maintenance changes on dev)

This document replaces the pre-Aurora optimization plan. It records the current
backend layout, reproducible benchmark method, and measured performance without
referencing the deleted PySide GUI.

## Current Path

```text
MAT / TDT input
  -> photon_cruncher.io.loader
  -> photon_cruncher.service
  -> photon_cruncher.processing.pipeline
  -> photon_cruncher.export.exporter
  -> Aurora API, CLI, or batch runner
```

- Aurora frontend: `photon_cruncher/gui_aurora/static/`
- Aurora HTTP/API boundary: `photon_cruncher/gui_aurora/server.py`
- Native desktop shell: `photon_cruncher/gui_aurora/shell.py`
- Shared analysis facade: `photon_cruncher/service.py`
- Batch orchestration: `photon_cruncher/analysis/runner.py`
- Benchmark harness: `scripts/bench_backend.py`

No analysis loop should be added to the GUI. Performance work should improve the
shared service, pipeline, loader, runner, or exporter so Aurora and the CLI stay
numerically consistent.

## Method

The harness reports the median of repeated calls for loading, processing all
available channels, exporting the first channel to CSV, and optionally saving a
figure. Figure timing includes a warm-up export so Matplotlib font-cache setup is
not mistaken for steady-state rendering cost.

```bash
MPLCONFIGDIR=/tmp/photon-cruncher-mpl-bench \
  .build-venv/bin/python scripts/bench_backend.py \
  local-test-data/mat/1996_FR1-4_NA.mat \
  local-test-data/mat/2143_Rev1_JZL18.mat \
  local-test-data/mat/2149_Rev1_JZL18.mat \
  --epoc CL2_ --figure --transport --repeat 3

MPLCONFIGDIR=/tmp/photon-cruncher-mpl-bench \
  .build-venv/bin/python scripts/bench_backend.py \
  local-test-data/mat/1996_FR3-3_NA.mat \
  --epoc CL1_ --figure --repeat 3
```

An explicitly requested epoc must exist. The harness now rejects missing epocs
instead of silently choosing a different one. `Cam1`, `Cam2`, and `Tick` are
ignored by the loader and cannot be used for current benchmarks.

Add `--transport` to compare the legacy all-channel JSON payload with Aurora's
compact summary plus one displayed float32 heatmap matrix. Transport measurement
intentionally materializes the legacy payload, so use a dense fixture only when
the machine has enough free memory.

Environment for the measurements below:

- Photon Cruncher `2.0.5` with the October maintenance changes
- Python `3.11.15`
- Darwin `27.2.0`, arm64
- Explicit behavioral epocs (`CL2_`, or `CL1_` for `1996_FR3-3_NA`)
- Median of three warm-filesystem runs per stage

## Current Measurements

| Fixture | Epoc | Kept trials x samples | Load | Process 3 channels | CSV | Figure |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `1996_FR1-4_NA.mat` | `CL2_` | 67 x 712 | 0.265 s | 0.010 s | 0.006 s | 0.134 s |
| `1996_FR3-3_NA.mat` | `CL1_` | 23 x 712 | 0.169 s | 0.003 s | 0.002 s | 0.147 s |
| `2143_Rev1_JZL18.mat` | `CL2_` | 28 x 712 | 0.045 s | 0.004 s | 0.003 s | 0.130 s |
| `2149_Rev1_JZL18.mat` | `CL2_` | 7 x 712 | 0.037 s | 0.001 s | 0.001 s | 0.124 s |

These values are local reference measurements, not cross-platform guarantees.
Rerun the command after pipeline, exporter, NumPy, SciPy, pandas, Matplotlib, or
hardware changes rather than carrying the numbers forward unchanged.

## Plot Transport

The `1996_FR1-4_NA.mat` / `CL2_` benchmark used three channels and a
`67 x 712` displayed matrix:

| Transport stage | Time | Payload |
| --- | ---: | ---: |
| Legacy JSON with all three heatmaps | 0.055 s | 2.799 MiB |
| Compact JSON summaries for all channels | 0.003 s | 0.124 MiB |
| Displayed-channel float32 matrix | <0.001 s | 0.182 MiB |

The current UI transfers about 0.306 MiB for that view instead of 2.799 MiB,
roughly an 89% reduction, and does not decode matrices for hidden channels.
Changing the display channel fetches that channel lazily. Align and Trial
Explorer abort stale summary/matrix requests so older responses cannot replace
newer settings. The float32 matrix remains one flat browser buffer with row
views, avoiding a second full float64 copy during plotting; switching channels
releases the previous display buffer.

## Runtime Bounds

- Session storage retains at most eight sources by default.
- Analysis cache retention defaults to 256 MiB of estimated NumPy arrays.
- An individual result larger than the cache budget is returned but not cached.
- Batch Export has one background worker, loads each source once per run, and
  checks cancellation between analysis steps.
- Completed batch records retain paths and QC metadata, not raw sessions or
  processed matrices. Evicted sessions can therefore be released during a batch.
- Saved heatmaps use at most 12 whole-row tick labels. This avoids creating
  hundreds of text artists for large trial counts.
- Environment overrides: `AURORA_MAX_CACHED_SESSIONS` and
  `AURORA_ANALYSIS_CACHE_MB`.

## Interpretation

- Normal cue/reward epocs should remain comfortably interactive on this machine.
- Use synthetic dense behavioral epocs for stress tests; ignored camera/clock
  epocs are not available for analysis.
- CSV and figure export are no longer obvious multi-second bottlenecks once the
  renderer is warm.
- Batch processing handles source files sequentially in a background worker, so
  a large batch remains responsive but still scales roughly with recording count.
- Parallel batch work should only be added after profiling an actual lab batch;
  process startup, memory duplication, and disk contention can erase the gain.

A one-off 670-trial figure comparison during the review took 0.509 s with
335 labels versus 0.170 s with 12 labels. This isolates the label-count cost;
it is not a multi-run speedup guarantee.

## Performance Guardrails

- Preserve the frozen pipeline-equivalence fixture and tight numeric tolerances.
- Keep incomplete edge-trial removal, original trial numbers, and control/signal
  row alignment unchanged.
- Measure loader, processing, CSV, and figure stages separately.
- Warm Matplotlib before recording figure results.
- Use an explicit epoc and report kept matrix dimensions.
- Compare medians over repeated runs, not a single cold result.
- Recheck memory use before introducing process-level parallelism.

## Next Performance Work

1. Profile a representative multi-file lab batch from the Aurora API or CLI.
2. Add stage-level debug timing only if the aggregate harness cannot identify
   the bottleneck.
3. Consider bounded per-source batch parallelism only if processing dominates
   and memory remains acceptable.
4. Keep compact binary matrices as display transport only; CSV and manifest
   files remain the durable scientific export formats.
