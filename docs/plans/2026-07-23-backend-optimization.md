# Backend Optimization Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.
> **Mode:** Planning only — do not implement until Brandon approves scope and phase order.

**Goal:** Make Photon Cruncher’s analysis backend faster and leaner on real lab sessions (especially high-trial FR data and multi-file batch export) without changing MATLAB-faithful numeric results.

**Architecture:** Keep the public pipeline contract (`process_channel` → `ProcessedSignal` → `export_channel` / figures) stable. Optimize inside existing modules first, then collapse duplicated orchestration (CLI / runner / GUI) and add batch-level parallelism only after single-job hot paths are fixed and behavior is pinned by tests.

**Tech stack:** NumPy, pandas (export only where still useful), SciPy `loadmat`, optional `tdt`, PySide workers already in GUI, stdlib `concurrent.futures` for batch.

**Constraint (non-negotiable):** Baseline, smoothing endpoints, regression, downsampling, edge-trial drops, and control/signal alignment must remain bit-close to current MATLAB-faithful behavior. Every numeric change needs an equivalence test on synthetic + local fixture data.

---

## Current backend map

| Layer | Path | Role |
| --- | --- | --- |
| Model | `photon_cruncher/model.py` | `Stream`, `Epoc`, `PhotometrySession` |
| IO | `photon_cruncher/io/loader.py` | `.mat` + TDT load/discovery |
| Pipeline | `photon_cruncher/processing/pipeline.py` | trial extract → artifact → downsample → regress → z-score → smooth |
| Orchestration | `photon_cruncher/analysis/runner.py` | session/batch runners |
| Classification | `photon_cruncher/analysis/trial_classifier.py` | cRew/CL-IL-Pe sources |
| Export | `photon_cruncher/export/exporter.py` | heatmap CSV + summary figures |
| CLI | `photon_cruncher/cli.py` | headless inspect/analyze |
| GUI glue | `photon_cruncher/gui/main_window.py` | QThreadPool workers calling pipeline/batch |

```text
load_session(path)
  -> available_channels(session)
  -> process_channel(... per channel x epoc ...)
  -> annotate / subset trials
  -> export_channel / save_result_figure
```

---

## Benchmark baseline (dev machine, local fixtures)

Fixture: `local-test-data/mat/1996_FR1-4_NA.mat` (~55 MB, 5 streams × ~29 MB float64 each)

| Stage | Workload | Time |
| --- | --- | --- |
| `load_session` | full MAT | **0.27 s** |
| `process_channel` × 3 channels | Tick epoc, ~3534 kept trials | **0.68 s** total |
| `export_channel` (current) | one channel, shape `(3534, 712)` → ~33 MB CSV | **1.13 s** |
| `save_result_figure` PNG dpi=300 | same | **0.25–0.64 s** |
| Stage breakdown inside process (A_465 / Tick) | | |
| trial extract (both) | | ~3 ms |
| artifact scan | | ~33 ms |
| downsample both | | ~46 ms |
| `polyfit` + residual | | **65 ms** |
| z-score Python loop | | 32 ms → vectorized **4 ms** |
| smooth loop | | ~15 ms |
| baseline correct | | ~3 ms |

**Interpretation**

1. For large trial counts, **CSV export is the #1 backend cost** — often slower than processing itself.
2. Pipeline compute is already decent; biggest internal wins are **vectorized z-score**, cheaper regression, and removing dead work — not a rewrite.
3. Typical cue/reward epocs (hundreds of trials) will feel snappy; FR “Tick”-scale matrices and multi-epoc × multi-channel × multi-file batch are where users wait.
4. Batch has structural waste: sequential sessions, duplicated analysis entry points, and a **second full `load_session` per file** just to compute skipped-epoc messages in the GUI.

Smaller fixtures for reference:

| File | Load | Process 3 ch | CSV 1 ch |
| --- | --- | --- | --- |
| `1996_FR3-3_NA.mat` (2288 trials) | 0.17 s | 0.43 s | 0.72 s |
| `2143_Rev1_JZL18.mat` (614 trials) | 0.05 s | 0.12 s | 0.19 s |
| `2149_Rev1_JZL18.mat` (470 trials) | 0.04 s | 0.09 s | 0.15 s |

---

## Optimization principles

1. **Measure first, keep a tiny bench harness** under `scripts/` (not committed fixtures).
2. **Numeric equivalence before speed claims** — `np.testing.assert_allclose` on `zall`, `zall_smooth`, `ts`, trial numbers.
3. **Optimize the shared backend**, not GUI-only shortcuts. CLI + batch + GUI should all benefit.
4. **No new heavy deps** unless a phase clearly needs them (e.g. avoid numba unless vectorized NumPy is insufficient).
5. **Preserve APIs** used by GUI/CLI; add helpers rather than breaking `process_channel` signatures.
6. **Memory matters in batch** — close figures, avoid holding all session arrays longer than needed, stream CSV writes.

---

## Phased plan

### Phase 0 — Safety net and bench harness (do first)

**Objective:** Lock current behavior so optimizations cannot silently drift from MATLAB-faithful outputs.

**Files:**
- Create: `photon_cruncher/tests/test_pipeline_equivalence.py`
- Create: `scripts/bench_backend.py` (gitignored local use OK; or keep checked in without data deps)
- Modify: `photon_cruncher/tests/test_loader.py` only if shared fixtures help

**Tasks:**
1. Add synthetic golden-path test: fixed RNG streams + known onsets → freeze `ts`, `zall`, `zall_smooth`, means, dropped edge trials.
2. Add optional local-fixture test (skip if `local-test-data/` missing) comparing pre/post arrays for one channel/epoc.
3. Add `scripts/bench_backend.py` printing load / process / export timings for a path list.
4. Record baseline numbers in the PR description before changing code.

**Acceptance:**
- `env -u PYTHONPATH -u PYTHONHOME .build-venv/bin/python -m unittest photon_cruncher.tests.test_loader photon_cruncher.tests.test_pipeline_equivalence`
- Bench script runs against `local-test-data/mat/*.mat` without crashing.

**Risk:** Low.

---

### Phase 1 — Export path (highest ROI, low risk)

**Objective:** Cut heatmap CSV write time ~3–5× on large trial matrices.

**Why:** Current `export_channel` builds `list[list]` via per-row `.tolist()` then `pd.DataFrame(rows).to_csv(...)`. On `(3534, 712)` this is **1.13 s**; a NumPy-first write is ~**0.30 s**.

**Files:**
- Modify: `photon_cruncher/export/exporter.py`
- Test: `photon_cruncher/tests/test_loader.py` (existing CSV shape/label tests) + new exact content test

**Implementation sketch:**

```python
def export_channel(...):
    ...
    z_data = processed.zall_smooth if export_smoothed else processed.zall
    labels = _trial_row_labels(processed, z_data.shape[0])  # TIME/MEAN/TRIAL_xxx
    mean_trace = z_data.mean(axis=0) if z_data.shape[0] else np.full_like(processed.ts, np.nan)
    matrix = np.vstack([processed.ts, mean_trace, z_data])
    _write_labeled_csv(heatmap_path, labels, matrix)
```

Write strategy (pick one after microbench):
1. Preferred: open text file; for each row write label + `np.savetxt` line (`fmt` stable).
2. Avoid row-wise Python float formatting over 2.5M cells.
3. Keep row labels identical: `TRIAL_007`, `TRIAL_007_correct_rewarded`, etc.
4. Do **not** change column count, headerless layout, or TIME/MEAN first rows.

Also in this phase:
- `save_result_figure`: explicitly `figure.clf();` + `plt.close(figure)` or `figure.clear()` + drop refs after `savefig` to bound batch memory.
- Optional: parameterize DPI (default 300 for lab figures; allow 150 for bulk batch previews later — only if UI/CLI exposed carefully).

**Acceptance:**
- Existing export tests pass.
- New test: labels + numeric values match old writer within formatting tolerance.
- Bench: `1996_FR1-4_NA` A_465 CSV **≤ 0.40 s** (target), no API break.

**Risk:** Float formatting differences in CSV (`1.0` vs `1.000000`). Pin `fmt` and compare parsed floats, not raw text, unless lab scripts depend on exact strings (verify against a known export if available).

---

### Phase 2 — Vectorize pipeline hot loops (medium ROI, fidelity-sensitive)

**Objective:** Reduce per-channel process time on large trial counts without changing formulas.

**Files:**
- Modify: `photon_cruncher/processing/pipeline.py`
- Test: equivalence suite from Phase 0

**2a. Remove dead work**
- Delete unused `mean_signal1/2`, `std_signal1/2`, `dc_signal1/2`, and unused `ts1` if only `ts2` is returned.
- Confirm nothing external depended on side effects (none today).

**2b. Vectorize z-score**

Replace per-trial loop:

```python
base = y_df_all[:, baseline_mask]
zb = base.mean(axis=1, keepdims=True)
zsd = base.std(axis=1, ddof=1, keepdims=True)
zall = (y_df_all - zb) / zsd
```

Bench already shows 32 ms → 4 ms with exact match.

**2c. Vectorize baseline shift**

Current row loop is equivalent to subtracting the value at the first `ts > base_adjust` index from each row:

```python
vals = z_data[:, idx]
corrected = z_data - vals[:, None]
```

**2d. Artifact mask without Python `any` loops**

After trials are rectangular (post-trim), operate on 2D arrays:

```python
arr = np.vstack(trials)
good = (arr.max(axis=1) <= artifact) & (arr.min(axis=1) >= -artifact)
```

Keep list-based path until trim if lengths differ; or trim first when safe.

**2e. Downsample**

After trim to equal length, stack once and reshape:

```python
arr = np.stack(trials, axis=0)  # or vstack already equal
bins = arr.shape[1] // factor
arr = arr[:, : bins * factor].reshape(arr.shape[0], bins, factor).mean(axis=2)
```

**2f. Smoothing**
- Keep endpoint-shrinking moving mean behavior (recently matched to MATLAB).
- Vectorize carefully; do **not** switch to zero-padded `uniform_filter1d` without equivalence tests.
- Reasonable approach: retain `_moving_mean` but apply via a small validated 2D helper; prioritize correctness over another 10 ms.

**2g. Regression**
- `np.polyfit` on 3534×712 flattened points costs ~65 ms.
- Try `np.linalg.lstsq` on the same design matrix; accept only if slope/intercept match closely enough that final `zall` matches within tight rtol/atol (e.g. `1e-10` relative on synthetic, looser only if float order differs).
- If equivalence is fragile, leave `polyfit` alone — it is not the dominant batch cost once export is fixed.

**Acceptance:**
- All equivalence tests pass at tight tolerances.
- Process 3 channels on FR1 Tick **≤ ~0.45 s** (about 30%+ better) without export changes counted.

**Risk:** Medium — smoothing/regression fidelity. Mitigate with frozen golden arrays.

---

### Phase 3 — Orchestration efficiency (batch / multi-channel)

**Objective:** Stop redoing work across channels, epocs, and GUI post-steps.

**Files:**
- Modify: `photon_cruncher/analysis/runner.py`
- Modify: `photon_cruncher/cli.py` (thin wrapper over runner)
- Modify: `photon_cruncher/gui/main_window.py` (call shared helpers; remove double load)
- Maybe create: `photon_cruncher/analysis/service.py` if runner gets crowded

**3a. Single analysis service API**

Unify the three copies of “for each channel: build settings → process → annotate”:
- GUI `_preview_signals` / trial explorer task
- `cli.analyze_session_epoc`
- `runner.run_session_with_settings`

Target shape:

```python
def analyze_epoc(
    session,
    epoc,
    *,
    channel_keys=None,
    settings_factory=default_settings_for_channel,
    trial_source=None,
    trial_filter=None,
) -> list[AnalysisResult]:
    ...
```

CLI/GUI become adapters. Less drift, one place to optimize.

**3b. Fix GUI batch double-load**

In `main_window._run_batch`, after `run_batch_custom`, the code **reloads every session** to build skipped-epoc messages. Fold skip reporting into `run_batch_custom` return value instead.

**3c. Shared control-stream extraction (optional, same epoc)**

`A_465` and `A_560` both extract `x405A` trials independently. For multi-channel runs on one epoc:
- extract control/signal trial matrices once per stream name
- reuse for channels sharing iso/stream + identical `trange` / artifacts / downsample

Only worth it when processing cost dominates; after Phase 2 maybe ~10–20% on multi-channel. Implement behind a helper used by `analyze_epoc`, not by rewriting `process_channel` call sites ad hoc.

**3d. Batch progress + cancellation hooks**

Add optional `progress_callback(done, total, message)` and cooperative cancel flag to `run_batch_custom` so GUI can show real progress without parsing logs.

**Acceptance:**
- GUI batch no longer calls `load_session` twice per path.
- CLI and runner share one analyze function.
- Behavior tests for batch export paths still pass.

**Risk:** Low–medium (refactor). Stay behavior-preserving; no numeric changes required.

---

### Phase 4 — Parallel batch sessions (high ROI for multi-file, more complexity)

**Objective:** Use multiple cores when exporting many independent sessions.

**Files:**
- Modify: `photon_cruncher/analysis/runner.py`
- Modify: CLI flags / GUI optional checkbox later
- Test: batch tests with monkeypatched loaders

**Design:**
- Process **one session per worker** (`ProcessPoolExecutor` or `ThreadPoolExecutor`).
- Prefer threads first if GIL release from NumPy/IO dominates and pickling sessions is costly; measure both.
- Processes need picklable top-level worker: `(path, epoc_selections, channel_keys, settings_dict, export_opts) -> summary`.
- Preserve deterministic summary ordering (sort by input path / epoc / channel).
- Default `max_workers` = `min(4, os.cpu_count() or 1)`; allow override.
- Keep sequential fallback for `max_workers=1` (easier debugging).

**Do not parallelize inside a single `process_channel` first** — trial matrices are already vectorized NumPy; process-level parallelism wins more for 20-file batches.

**Acceptance:**
- 4-file synthetic batch wall time improves materially vs sequential on multi-core.
- No file clobbering when `per_session_subdir=True`.
- Failures in one file don’t kill entire batch (collect errors like CLI `skipped`).

**Risk:** Medium (PyInstaller + multiprocessing freeze support on macOS/Windows). Validate packaged app if GUI exposes it.

---

### Phase 5 — Loader / memory (only if still needed)

**Objective:** Faster loads and lower RAM for long recordings / big tanks.

**Files:**
- `photon_cruncher/io/loader.py`
- model optional `dtype` policy

**Candidates:**
1. **MAT load:** profile `scipy.io.loadmat` vs `mat73` only if v7.3 files appear; current v5-style loads are already 0.04–0.27 s.
2. **Avoid deep `_object_to_dict` on huge TDT info** if metadata conversion shows up in profiles.
3. **Lazy streams:** don’t flatten unused stores when channel filter is known up front (batch/CLI know channels early; GUI inspect needs all names — load names/fs first if TDT allows).
4. **dtype:** keep float64 for processing fidelity; consider float32 only for display caches, not core math, unless explicitly approved.
5. **Session cache keyed by resolved path + mtime** for GUI re-entry / batch dry runs — careful with memory; LRU of 1–2 sessions max.

**Acceptance:** Prove a before/after with bench on real TDT blocks before merging.

**Risk:** Medium for TDT edge cases; low for metadata-only tweaks.

---

### Phase 6 — Secondary cleanups (quality, not raw speed)

1. Drop unused export args noise if truly unused (`dropped_trials`, `metadata` currently unused in `export_channel` body — either use them in a sidecar JSON or stop passing dead params).
2. Classifier micro-opts only if profiling says so (`_has_match` can binary-search sorted `pe_times`); trial counts are tiny vs photometry matrices.
3. Add backend-facing logging at DEBUG: trials kept, matrix shape, stage ms.
4. Document performance tips in README: prefer specific epocs over Tick-scale event streams; batch subdirs; channel filters.

---

## Suggested implementation order

| Order | Phase | Effort | Expected user-visible win |
| --- | --- | --- | --- |
| 1 | Phase 0 tests + bench | S | Safety |
| 2 | Phase 1 CSV + figure close | S | Large export / batch CSV much faster |
| 3 | Phase 2 vectorize + dead code | M | Faster Align/Trial/CLI on big epocs |
| 4 | Phase 3 unify + fix double load | M | Cleaner code, faster batch messaging, fewer bugs |
| 5 | Phase 4 parallel batch | M–L | Multi-file lab export scales with cores |
| 6 | Phase 5 loader/memory | S–M | Only if profiling still shows IO pain |

**Recommended MVP to ship first:** Phases 0–2. That targets the measured hotspots with minimal architectural churn.

---

## Out of scope (for this backend plan)

- GUI v2 prototype visual redesign (`gui_prototype/`)
- Changing default analysis windows or MATLAB algorithm definitions
- GPU acceleration
- Rewriting exports to Parquet/HDF5 (nice future option; would break lab CSV workflows)
- Plotting style changes beyond resource cleanup / optional DPI

---

## Verification checklist (every phase)

```bash
# unit + equivalence
env -u PYTHONPATH -u PYTHONHOME .build-venv/bin/python -m unittest \
  photon_cruncher.tests.test_loader \
  photon_cruncher.tests.test_pipeline_equivalence

# compile surface
env -u PYTHONPATH -u PYTHONHOME .build-venv/bin/python -m py_compile \
  photon_cruncher/processing/pipeline.py \
  photon_cruncher/export/exporter.py \
  photon_cruncher/analysis/runner.py \
  photon_cruncher/cli.py \
  photon_cruncher/gui/main_window.py

# local bench (requires fixtures)
env -u PYTHONPATH -u PYTHONHOME .build-venv/bin/python scripts/bench_backend.py \
  local-test-data/mat/1996_FR1-4_NA.mat

git diff --check
```

Numeric gate for pipeline changes:
- synthetic golden: exact or `rtol=0, atol=0` if pure reorder-safe; else `rtol=1e-12, atol=1e-12`
- local fixture: `rtol=1e-9, atol=1e-9` on `zall` / `zall_smooth` unless a documented float-path change requires slightly looser bounds

---

## Concrete first tasks (bite-sized, when execution starts)

### Task 1: Golden synthetic process snapshot
**Files:** create `photon_cruncher/tests/test_pipeline_equivalence.py`  
**Step:** Build fixed session (fs=100, short streams, 5 onsets), run `process_channel`, assert shapes + hash/allclose against stored arrays in the test file.

### Task 2: Bench script
**Files:** create `scripts/bench_backend.py`  
**Step:** Time load, per-channel process, CSV export, optional figure; print markdown-friendly table.

### Task 3: Fast labeled CSV writer
**Files:** `export/exporter.py`  
**Step:** Implement `_write_labeled_numeric_csv`; swap `export_channel`; parse-back test.

### Task 4: Vectorized z-score + baseline
**Files:** `processing/pipeline.py`  
**Step:** Replace loops; run equivalence tests; bench FR1.

### Task 5: Stacked downsample + artifact masks
**Files:** `processing/pipeline.py`  
**Step:** Rectangularize after edge drop/trim; keep dropped trial numbering identical.

### Task 6: Runner/CLI/GUI analyze unification + batch skip info
**Files:** `runner.py`, `cli.py`, `main_window.py`  
**Step:** One `analyze_epoc`; batch returns skip list; GUI stops reloading.

### Task 7: Optional process-pool batch
**Files:** `runner.py`, thin CLI flag `--jobs N`  
**Step:** Parallel per input path; order-stable summary.

---

## Success metrics

After MVP (Phases 0–2) on `1996_FR1-4_NA.mat` / Tick / A_465:

| Metric | Now | Target |
| --- | --- | --- |
| CSV export | ~1.13 s | ≤ 0.35 s |
| Single-channel process | ~0.22 s | ≤ 0.15 s |
| 3-channel process | ~0.68 s | ≤ 0.45 s |
| Numeric drift | n/a | within equivalence gates |
| Public APIs | stable | stable |

After Phase 4, a 8-session batch should approach near-linear speedup up to ~4 workers for process+export dominated workloads (IO may cap gains).

---

## Decision points for Brandon

1. **MVP only (0–2) vs full plan including parallel batch?**  
2. **CSV text exact-match required** for downstream MATLAB `readtable` workflows, or float-parse equivalence enough?  
3. **Expose `--jobs` / GUI “parallel batch”** or keep parallelism internal/default off until packaging tested?  
4. Any appetite later for **binary cache format** (e.g. `.npz`/`parquet`) alongside CSV for huge Tick-scale exports?

---

## Notes from code review (non-perf but related)

- `export_channel` accepts `dropped_trials` and `metadata` but does not write them — either emit a small JSON sidecar in an export cleanup or drop the dead parameters.
- GUI, CLI, and runner each reimplement channel loops; this is the main maintainability tax.
- `process_channel` still computes mean/std/dc signals that are discarded — pure waste, easy win in Phase 2a.
- Figure export uses raw `Figure` without pyplot; still close explicitly in batch loops for RAM.

Inspected branch: `dev` @ `65b100a` (plus local uncommitted GUI prototype work unrelated to backend).
