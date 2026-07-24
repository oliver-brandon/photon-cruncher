# Dual-GUI Architecture: Lab + Aurora

**Codename:** Aurora is the developer / v2 GUI surface.
**Lab app:** current PySide GUI remains the familiar day-to-day tool.

## Principle

```text
                 ┌──────── shared backend ────────┐
                 │  service.py                    │
                 │  io / processing / analysis /  │
                 │  export / model / cli           │
                 └───────┬────────────┬───────────┘
                         │            │
              ┌──────────▼───┐   ┌────▼────────────┐
              │ Lab GUI      │   │ Aurora (dev)    │
              │ main.py      │   │ aurora_main.py  │
              │ gui/         │   │ gui_aurora/     │
              └──────────────┘   └─────────────────┘
```

- **One science core.** Fixes to loader/pipeline/export/classifier land in shared modules and benefit both surfaces.
- **Two faces.** Lab UX stays stable. Aurora can move fast visually.
- **No analysis math in GUI code.** GUIs call `photon_cruncher.service` (or thin wrappers like `analysis.runner` / CLI helpers that themselves call the service).

## Surfaces

| Surface | Entry | Branding | Audience |
| --- | --- | --- | --- |
| Lab desktop | `python -m photon_cruncher.main` / `photon-cruncher` | `Photon Cruncher` / Dev title on `dev` branch | Lab users |
| Aurora | `python -m photon_cruncher.aurora_main` / `photon-cruncher-aurora` | `Photon Cruncher Aurora` | Developer / v2 |
| CLI | `photon-cruncher-cli` | version only | Automation / Hermes |

## Shared service API

Module: `photon_cruncher/service.py`

Primary calls:
- `open_session(path)`
- `list_channels(session)`
- `resolve_epoc(session, name)`
- `analyze(session, epoc, *, channel_keys, settings_factory, settings_overrides, source)`
- `annotate_trials` / `filter_trials`
- `export_result`
- `session_summary` / `result_plot_payload` (JSON-friendly for Aurora)

`analysis.runner.run_session*` delegates to `service.analyze`.
Lab GUI preview / trial explorer call `service.analyze`.
CLI analyze path uses `service.analyze`.
Aurora local API (`/api/inspect`, `/api/analyze`) uses the same service.

## Branch / release rules

- `main` — lab-facing stable packaging; lab GUI default.
- `dev` — developer builds; Aurora is the experimental UI default for exploration, lab GUI still present.
- Backend PRs should avoid mixing large Aurora-only UI churn when the goal is a lab hotfix.
- Prefer PR labels: `backend`, `gui-lab`, `gui-aurora`.

## Packaging

- Lab build scripts continue to launch `photon_cruncher.main`.
- Aurora default entry is the **native shell** (`gui_aurora/shell.py` via
  `aurora_main`): PySide6 + Qt WebEngine window hosting the web UI, plus a
  localhost service backend.
- `--browser` still available for pure web debugging.
- Future packaging can ship Aurora as `Photon Cruncher Aurora` without changing
  the lab default app.

## What must stay identical

- Pipeline math and defaults (`processing/pipeline.py`)
- Edge-trial drop policy and control/signal alignment
- Export CSV schema (TIME / MEAN / TRIAL_### rows)
- Loader contracts for MAT + TDT

## Verification

```bash
env -u PYTHONPATH -u PYTHONHOME .build-venv/bin/python -m unittest \
  photon_cruncher.tests.test_loader \
  photon_cruncher.tests.test_service \
  photon_cruncher.tests.test_pipeline_equivalence \
  photon_cruncher.tests.test_gui_aurora
```

## Building Aurora (macOS)

```bash
scripts/build_macos_aurora_app.sh
```

Produces `dist/Photon Cruncher Aurora v1.1.4.app`. Lab packaging scripts are unchanged.
