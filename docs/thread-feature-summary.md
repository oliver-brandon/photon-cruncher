# Photon Cruncher Development Summary

This document summarizes the features, fixes, packaging work, and workflow
improvements developed during this Photon Cruncher thread. It covers the
original desktop application through the current Aurora v2 development branch.

## Application Foundation

- Built a desktop fiber-photometry application around the lab's original
  MATLAB-faithful analysis workflow.
- Added loading and analysis of TDT-generated MATLAB `.mat` files.
- Added direct loading of raw TDT blocks and TDT tanks containing multiple
  blocks.
- Added defensive TDT stream and epoc handling so both dictionary-like and
  attribute-based TDT objects work.
- Added paired MAT/TDT test fixtures from the same recordings to check that
  both input formats produce equivalent results.
- Added missing-epoc handling so one incompatible file does not silently break
  a larger export.

## Processing Pipeline

- Preserved the core photometry workflow: stream extraction, optional
  downsampling, smoothing, 405 control fitting, corrected signal calculation,
  baseline normalization, per-trial z-scoring, mean, and SEM.
- Standardized `TRANGE end` to mean seconds after the alignment epoc. For
  example, `TRANGE start = -2` and `TRANGE end = 5` always produce a window
  from 2 seconds before to 5 seconds after the epoc.
- Fixed incomplete edge trials so trials without the full requested window are
  excluded instead of being clipped or padded with misleading values.
- Added reporting of dropped edge trials to the user.
- Kept control and signal trial rows synchronized while trials are dropped,
  intersected, or artifact-filtered.
- Made smoothing match MATLAB `smoothdata(..., 'movmean', N)` endpoint behavior,
  removing the artificial sharp drop that could appear near the end of traces.
- Added configurable per-channel smoothing and processing controls.
- Added optional artifact thresholds, baseline correction, raw versus smoothed
  plotting/export, downsampling, baseline windows, and baseline adjustment.
- Added pipeline-equivalence and regression tests for high-risk scientific
  behavior.

## Align and Visualize

- Added interactive epoc-aligned mean +/- SEM and z-score heatmap plots.
- Added selectable analyzed channels and a separate displayed-channel picker.
- Fixed the displayed channel reverting to the default after processing
  settings or smoothing were changed.
- Fixed an epoc-picker bug that caused Align and Visualize to repeatedly plot
  the same or wrong epoc.
- Made the plot update immediately when the selected epoc or relevant
  processing setting changes.
- Added source file and epoc names to displayed and saved figures.
- Fixed heatmap y-axis ticks so they align with actual trials and show only
  whole-numbered trial labels.
- Added original trial numbers to exported and plotted trial identities instead
  of renumbering filtered rows sequentially.
- Moved single-file CSV and figure export destinations to native folder
  choosers.
- Removed the obsolete artifact 405 and artifact 465 text boxes from the older
  interface.

## Trial Explorer

- Added a dedicated Trial Explorer for inspecting one file and one epoc at a
  time.
- Added a checklist of surviving original trial numbers with All, None, and
  Invert selection controls.
- Made mean +/- SEM and heatmap plots update as trial selections change.
- Added independent file, epoc/source, channel, smoothing, and processing
  controls for Trial Explorer.
- Added selected-trial CSV and figure exports for the currently displayed
  channel.
- Added clear handling for an empty trial selection instead of exporting empty
  results.
- Preserved original trial labels through edge filtering, artifact filtering,
  smoothing, downsampling, subsetting, plotting, and export.
- Defined single-trial SEM as zero so a one-trial plot remains clean and
  meaningful.

## Classified Trials

- Added in-memory classified trial sources to Trial Explorer without modifying
  the original MAT or TDT data.
- Detects relevant epoc structures rather than relying on file names.
- Uses explicit `cRew*`, `cNoRew*`, `iRew*`, and `iNoRew*` outcome epocs when
  available.
- Otherwise derives lever-aligned trial types from matching `CL*`, `IL*`, and
  `Pe*` epoc families.
- Classifies trials as correct rewarded, correct not rewarded, incorrect
  rewarded, incorrect not rewarded, or unclassified.
- Uses a 20 ms reward-matching tolerance and ignores exact 0.0-second startup
  events in derived sources.
- Warns when explicit outcomes disagree with available lever, correct,
  incorrect, or pellet epocs.
- Shows trial number, timestamp, and outcome type in the Trial Explorer list.
- Added quick selection by trial type and included classification labels in
  selected-trial exports.

## Batch Processing and Export

- Added batch processing for multiple MAT files, TDT blocks, and complete TDT
  tanks.
- Added mixed-source batch discovery and multi-source session inspection.
- Added epoc suffix-selection policies for recordings with related epoc
  families such as `1_`/`2_` or `A`/`C` conventions.
- Added explicit channel selection for batch analysis.
- Added checkboxes to export CSV files, figures, or both.
- Added figure-format selection for PNG, PDF, and TIFF.
- Kept the Batch Export tab focused on batch work by removing duplicate
  single-file export buttons.
- Added structured skipped-file and error reporting so partial batch results are
  understandable.
- Improved batch CSV/export and pipeline performance for larger workloads.

## Persistent Settings

- Added default processing settings for first launch.
- Persisted user changes between sessions, including epoc windows, baseline
  settings, smoothing, downsampling, plotting choices, artifact settings, and
  related analysis preferences.
- Kept Trial Explorer controls independent while retaining the same shared
  scientific processing semantics.
- Prevented newly added controls from forcing horizontal scrolling in the
  processing and smoothing areas.

## Command-Line and Agentic Access

- Added the supported `photon-cruncher-cli` headless entry point alongside the
  desktop launcher.
- Added `inspect`, `analyze`, and `validate-config` commands.
- Added JSON configuration files for reusable inputs, channels, epocs,
  classified sources, trial filters, processing settings, and export settings.
- Added CLI overrides for trial numbers, trial types, smoothing, TRANGE,
  baseline, artifact thresholds, channels, and export options.
- Added JSON summaries containing exported paths, skipped analyses, dropped
  edge trials, artifact removals, trial counts, warnings, and app version.
- Added stable exit codes for success, no exported analyses, invalid requests,
  and loading/processing failures.
- Refactored figure generation into shared code so CLI and GUI figures use the
  same layout, titles, heatmap ticks, mean, and SEM behavior.
- Bundled a console CLI executable beside the desktop app on macOS and Windows.
- Added a separate local Codex skill that can inspect data, create or validate a
  config, and run requested signal/figure extraction through the CLI. The skill
  is user-level tooling and is not part of the application repository.

## Aurora v2 Desktop Interface

- Replaced the development branch's older PySide interface with Photon Cruncher
  Aurora, a hybrid web interface in a native Qt desktop shell.
- Removed synthetic prototype behavior; Aurora works with live MAT and TDT
  sessions through the real processing backend.
- Added a shared `service.py` facade used by Aurora, the CLI, and analysis/export
  workflows so scientific logic is not duplicated in the interface.
- Restored feature parity for Align, Trial Explorer, classified sources, batch
  export, processing controls, smoothing, settings persistence, and exports.
- Added native MAT/TDT open dialogs in the desktop shell.
- Added multi-select MAT import and multi-tank TDT import.
- Added browser-native MAT/TDT folder uploads using relative paths, avoiding a
  pasted-path-only workflow in optional browser mode.
- Added responsive layouts for long file/epoc names and compact controls.
- Added Aurora-specific desktop icons and a restrained animated starfield visual
  treatment.
- Added a shared local API for open, inspect, analyze, export, batch export, and
  health operations.
- Added macOS bundle signing checks and platform-specific Aurora packaging.

## Desktop Distribution

- Added a portable macOS `.app` bundle that can be moved without hard-coded
  project paths or Terminal-based launching.
- Added a Windows desktop executable and downloadable ZIP for nontechnical lab
  users.
- Added PyInstaller specifications and platform build scripts.
- Added GitHub Actions builds for macOS and Windows, including manual workflow
  dispatch and tag-triggered release builds.
- Added versioned application names and metadata so downloaded builds can be
  distinguished before launch.
- Added a separate `Dev` application identity for pre-release testing before
  stable features are merged to `main`.
- Added tagged stable releases through v1.1.4; the current development line is
  Aurora v2.0/package version 2.0.0.

## Documentation and Update Experience

- Expanded the README with nontechnical download, install, launch, and update
  steps for macOS and Windows.
- Documented the macOS Gatekeeper Control-click/Open workaround for unverified
  apps.
- Documented the Windows SmartScreen More info/Run anyway workflow.
- Documented how users replace an older app with a newly downloaded release.
- Documented GitHub Actions, manual workflow runs, release artifacts, TDT/MAT
  expectations, Trial Explorer, classified trials, batch export, Aurora, and
  command-line automation.
- Added an MIT license with the project owner's copyright.
- Added architecture notes for Aurora and the shared service boundary.

## Repository and Developer Workflow

- Established `main` as the stable lab-facing release branch and `dev` as the
  feature-testing branch.
- Added branch-specific development naming and synchronized version metadata
  across the package, app bundles, build scripts, workflow, and README.
- Added local-only `AGENTS.md` maintenance guidance and ignored it in Git.
- Added ignore rules for local test data, build outputs, virtual environments,
  Python bytecode, `.DS_Store`, and the local `scripts/analyze_photometry.py`
  helper.
- Removed accidentally tracked `.pyc` files and normalized `.gitignore`.
- Added focused loader, classifier, pipeline, service, CLI, Aurora API, shell,
  browser-import, GUI, and packaging-oriented tests.

## Release Milestones

| Release | Main additions |
| --- | --- |
| v0.1.x | MATLAB-faithful app foundation, TDT support, batch processing, and desktop builds |
| v1.0.0 | Lab-ready macOS/Windows distribution, update documentation, and stable release workflow |
| v1.0.1-v1.0.4 dev | Edge-trial exclusion, corrected TRANGE semantics, persistent settings, and development identity |
| v1.1.0 | Trial Explorer and classified lever-trial outcomes |
| v1.1.1 | Align epoc-selection fix and immediate plot updates |
| v1.1.2 | Batch CSV/figure choices and PNG/PDF/TIFF figure formats |
| v1.1.3 | Figure source/epoc titles and integer-aligned heatmap ticks |
| v1.1.4 | MATLAB-compatible smoothing endpoints and accumulated batch/export fixes |
| CLI access point | Headless inspection, analysis, configuration, JSON summaries, and bundled executables |
| Aurora v2.0 dev | Modern native desktop shell, browser-native imports, restored feature parity, and shared service architecture |
