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

## Interpretation

- Normal cue/reward epocs should remain comfortably interactive on this machine.
- Very dense `Tick` exports are still the useful stress case because they create
  thousands of trial rows.
- CSV and figure export are no longer obvious multi-second bottlenecks once the
  renderer is warm.
- Batch processing currently handles source files sequentially, so a large batch
  still scales roughly with the number and size of recordings.
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

1. Profile a representative multi-file batch from the Aurora API or CLI.
2. Add stage-level debug timing only if the aggregate harness cannot identify
   the bottleneck.
3. Consider bounded per-source batch parallelism only if processing dominates
   and memory remains acceptable.
4. Keep CSV as the default lab interchange format; add a binary cache only as an
   optional acceleration path, never as a replacement for current exports.
