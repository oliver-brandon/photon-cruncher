# Aurora Architecture (dev branch)

**Photon Cruncher Aurora** is the only desktop GUI on the `dev` branch.

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

## Surfaces (dev)

| Surface | Entry | Branding |
| --- | --- | --- |
| Desktop | `python -m photon_cruncher.aurora_main` / `photon-cruncher` | Window: `Photon Cruncher Aurora` · UI rail: `Aurora v2.0` |
| CLI | `photon-cruncher-cli` | package version `2.0.0` |

## Shared service API

Module: `photon_cruncher/service.py`

- `open_session(path)`
- `list_channels(session)`
- `resolve_epoc(session, name)`
- `analyze(session, epoc, …)`
- `annotate_trials` / `filter_trials`
- `export_result`
- `session_summary` / `result_plot_payload`

Aurora local API: `/api/open`, `/api/analyze`, `/api/export`, `/api/health`.

## Packaging

```bash
scripts/build_macos_app.sh
scripts/build_windows_app.ps1
```

Artifacts:
- `dist/Photon Cruncher Aurora v2.0.app`
- `dist/Photon-Cruncher-Aurora-v2.0-macOS.zip`
- `dist/Photon Cruncher Aurora v2.0/` (+ zip on Windows)

GitHub Actions workflow builds those same Aurora bundles on `v*` tags / manual dispatch.

## Branch notes

- `dev` — Aurora desktop + shared backend + CLI.
- `main` — lab-facing stable history; this branch no longer carries the old PySide lab GUI.

## Verification

```bash
env -u PYTHONPATH -u PYTHONHOME .build-venv/bin/python -m unittest \
  photon_cruncher.tests.test_loader \
  photon_cruncher.tests.test_service \
  photon_cruncher.tests.test_pipeline_equivalence \
  photon_cruncher.tests.test_gui_aurora \
  photon_cruncher.tests.test_aurora_shell \
  photon_cruncher.tests.test_aurora_app
```
