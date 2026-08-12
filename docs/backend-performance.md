# Aurora Backend Performance

Last measured: 2026-08-11

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
  local-test-data/mat/1996_FR3-3_NA.mat \
  local-test-data/mat/2143_Rev1_JZL18.mat \
  local-test-data/mat/2149_Rev1_JZL18.mat \
  --epoc Tick --figure --repeat 3
```

Add `--transport` to compare the legacy all-channel JSON payload with Aurora's
compact summary plus one displayed float32 heatmap matrix. Transport measurement
intentionally materializes the legacy payload, so use a dense fixture only when
the machine has enough free memory.

Environment for the measurements below:

- Photon Cruncher `2.0.0`
- Python `3.11.15`
- Darwin `27.0.0`, arm64
- Explicit `Tick` epoc
- Median of three warm-filesystem runs per stage

## Current Measurements

| Fixture | Kept trials x samples | Load | Process 3 channels | CSV | Figure |
| --- | ---: | ---: | ---: | ---: | ---: |
| `1996_FR1-4_NA.mat` | 3534 x 712 | 0.261 s | 0.488 s | 0.299 s | 0.262 s |
| `1996_FR3-3_NA.mat` | 2288 x 712 | 0.170 s | 0.305 s | 0.194 s | 0.231 s |
| `2143_Rev1_JZL18.mat` | 614 x 712 | 0.048 s | 0.089 s | 0.051 s | 0.161 s |
| `2149_Rev1_JZL18.mat` | 470 x 712 | 0.036 s | 0.065 s | 0.041 s | 0.160 s |

These values are local reference measurements, not cross-platform guarantees.
Rerun the command after pipeline, exporter, NumPy, SciPy, pandas, Matplotlib, or
hardware changes rather than carrying the numbers forward unchanged.

## Plot Transport Stress Check

One warm-filesystem run of the densest fixture used the `Tick` epoc, three
channels, and a `3534 x 712` displayed matrix:

| Transport stage | Time | Payload |
| --- | ---: | ---: |
| Legacy JSON with all three heatmaps | 2.618 s | 141.444 MiB |
| Compact JSON summaries for all channels | 0.015 s | 0.174 MiB |
| Displayed-channel float32 matrix | 0.001 s | 9.599 MiB |

The current UI transfers about 9.8 MiB for that view instead of 141.4 MiB,
roughly a 93% reduction, and does not decode matrices for hidden channels.
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
- Environment overrides: `AURORA_MAX_CACHED_SESSIONS` and
  `AURORA_ANALYSIS_CACHE_MB`.

## Interpretation

- Normal cue/reward epocs should remain comfortably interactive on this machine.
- Very dense `Tick` exports are still the useful stress case because they create
  thousands of trial rows.
- CSV and figure export are no longer obvious multi-second bottlenecks once the
  renderer is warm.
- Batch processing handles source files sequentially in a background worker, so
  a large batch remains responsive but still scales roughly with recording count.
- Parallel batch work should only be added after profiling an actual lab batch;
  process startup, memory duplication, and disk contention can erase the gain.

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
