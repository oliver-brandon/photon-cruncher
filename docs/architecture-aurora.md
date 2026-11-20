# Aurora Architecture

**Photon Cruncher Aurora** is the desktop GUI on this stable branch.

## Principle

```text
        ┌──────── shared backend ────────┐
        │  service.py                    │
        │  io / processing / analysis /  │
        │  export / model / cli           │
        └───────────────┬────────────────┘
                        │
              ┌─────────▼──────────┐
              │ Aurora desktop     │
              │ aurora_main.py     │
              │ gui_aurora/shell   │
              └────────────────────┘
```

- **One science core.** Fixes to loader/pipeline/export/classifier land in shared modules.
- **No analysis math in GUI code.** The UI calls `photon_cruncher.service` (or CLI helpers that call the service).
- **Live sessions only.** Open MAT/TDT → analyze → export. No synthetic demo feed.

## Surfaces

| Surface | Entry | Branding |
| --- | --- | --- |
| Desktop | `python -m photon_cruncher.aurora_main` / `photon-cruncher` | Window: `Photon Cruncher Aurora`; rail from `aurora_brand_label()` |
| CLI | `photon-cruncher-cli` | version from `photon_cruncher.version` |

Aurora is an app-only supported product surface. The desktop shell starts a
loopback HTTP server on an ephemeral port and embeds the HTML/CSS/JavaScript UI
inside Qt WebEngine. That local server is an implementation detail, not a
normal-browser user mode.

For external-browser visual debugging only, developers can run:

```bash
.build-venv/bin/python scripts/dev_aurora_browser.py
```

This preview is not packaged, documented as a user workflow, or supported as a
separate product surface.

## Version Metadata

`photon_cruncher/version.py` is the canonical source for the full semantic
version, display version, product name, bundle name, archive stem, and macOS
bundle identifier. Package metadata, PyInstaller specs, build scripts, the API,
and the interface derive their values from it. Run:

```bash
.build-venv/bin/python scripts/version_metadata.py --check
```

Generated `.egg-info` metadata is ignored and should not be committed.

## Automatic Updates

`photon_cruncher/updates.py` is the UI-independent update coordinator. The
Aurora shell owns only the native status indicator, dialog, and background task
wiring. Velopack lifecycle hooks run before packaged desktop startup, and update
checks/downloads never run on the Qt UI thread.

- Package ID: `com.photoncruncher.app`
- Channels: `stable-<os>-<architecture>`
- Source: public stable GitHub releases for this repository
- Version acceptance: newer versions only; no downgrade/channel switching
- Failure behavior: offline checks are silent during automatic polling, failed
  downloads leave the installed app unchanged, and manual checks explain errors

The stable package identity and channel are maintained for installed v1.2.x
clients. A live installed-app update and restart on each supported platform is
still a separate verification step. Aurora prereleases on `dev` use their own
package ID and channels.

## Shared service API

Module: `photon_cruncher/service.py`

- `open_session(path)`
- `list_channels(session)`
- `resolve_epoc(session, name)`
- `analyze(session, epoc, …)`
- `annotate_trials` / `filter_trials`
- `export_result`
- `session_summary` / `result_plot_payload` / `quality_summary`

Aurora local API includes:

- session and inspection: `/api/open`, `/api/inspect-paths`, `/api/health`
- analysis summaries: `/api/analyze`
- displayed heatmap data: compact float32 `/api/plot-matrix`
- export: `/api/export` and legacy synchronous `/api/batch-export`
- responsive batch jobs: `/api/batch-jobs`, job status, and cancellation
- support: `/api/diagnostics` and `/api/evict`
- developer browser preview only: `/api/upload` for temporary MAT/TDT transfer

The frontend requests JSON summaries for all analyzed channels, then fetches the
full matrix only for the displayed channel. Stale Align and Trial Explorer
requests are aborted and ignored. The in-process session/analysis cache is LRU
bounded by session count and estimated NumPy bytes; a result larger than the
configured cache budget is used for the current request but not retained.

Multi-source Batch Export delegates to `analysis.runner.run_batch_custom`.
Align, Trial Explorer, single-result export, and batch settings all resolve
through the shared `photon_cruncher.service` processing and export contracts.
Only one background batch job runs at a time. It loads each source once, reports
progress, and checks for cancellation between sources, epocs, and channels.

## Scientific UX Contracts

- Named processing presets are persisted locally and can be exchanged as JSON.
  Align and Trial Explorer show `Custom` as soon as a visible setting diverges.
- Align processing edits are explicit: the last analyzed plots remain visible,
  but exports and Batch are disabled until **Apply + analyze** succeeds. Batch
  shows the captured last-applied settings rather than silently reading pending
  form values.
- Heatmaps use a symmetric zero-centered diverging z-score scale with a visible
  colorbar. Users can keep automatic per-result limits or lock a shared limit
  while comparing Align and Trial Explorer plots.
- Every CSV or figure result has a neighboring `_analysis.json` manifest with
  source identity, app version, settings, trial provenance, exclusions, QC, and
  output paths.
- Result summaries surface incomplete-edge loss, artifact removal, missing 405
  control, unstable baseline variance, non-finite z-scores, and raw absolute
  z-scores above 20 as a visible heuristic warning.
- **Help -> Export Diagnostic Report...** records runtime, updater, bounded-cache,
  and recent error state, but never raw samples or trial matrices.

## Packaging

The platform build scripts produce local bundles; the stable publishing workflow
packages Windows and macOS installers and update feeds from `main` and matching
`v*` tags. Both platform builds must succeed. macOS packaging requires Developer
ID signing and notarization. Windows installers are not Authenticode signed.
See `docs/project-status.md` for release status and remaining checks.

## Verification

```bash
env -u PYTHONPATH -u PYTHONHOME .build-venv/bin/python -m unittest \
  photon_cruncher.tests.test_loader \
  photon_cruncher.tests.test_service \
  photon_cruncher.tests.test_pipeline_equivalence \
  photon_cruncher.tests.test_gui_aurora \
  photon_cruncher.tests.test_aurora_jobs \
  photon_cruncher.tests.test_aurora_shell \
  photon_cruncher.tests.test_aurora_app \
  photon_cruncher.tests.test_updates \
  photon_cruncher.tests.test_version_metadata
```
